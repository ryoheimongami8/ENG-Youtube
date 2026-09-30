"""GPU stages. Each runs in its own child process (`python -m engyt stage <name> <workdir>`)
so VRAM is freed on exit. Each stage processes all chunks, saving one JSON per chunk."""
from __future__ import annotations

import difflib
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .util import (SR, load_cached, norm_word, read_json, read_wav_slice, sha, write_json)

PROMPT_VERSION_KEY = "prompt_version"

SYSTEM_PROMPT = """You are an editor for English-learning material built from speech-recognition (ASR) output.
Given one raw ASR transcript segment, do the following:
1. Correct obvious recognition errors (wrong words, homophones, proper nouns, missing punctuation and casing). Make the MINIMUM edits needed. Never add, drop, reorder or paraphrase content. Keep every filler word and repetition that was actually spoken.
2. Split the corrected text into natural sentences.
3. Translate each sentence into natural Japanese.
Do not output timestamps. Output only JSON: {"sentences":[{"en":"...","ja":"..."}]}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"en": {"type": "string"}, "ja": {"type": "string"}},
                "required": ["en", "ja"],
            },
        }
    },
    "required": ["sentences"],
}


def edit_ratio(a: str, b: str) -> float:
    aw, bw = norm_seq(a), norm_seq(b)
    if not aw and not bw:
        return 0.0
    return 1.0 - difflib.SequenceMatcher(None, aw, bw).ratio()


def norm_seq(s: str) -> list[str]:
    return [w for w in (norm_word(x) for x in s.split()) if w]


# ------------------------------------------------------------------ keys
def asr_key(cfg, meta, ch) -> str:
    return sha("asr", cfg["asr"], meta["id"], ch["start"], ch["end"])


def fix_key(cfg, meta, ch, raw_key) -> str:
    return sha("fix", raw_key, cfg["llm"]["repo"], cfg["llm"]["file"], cfg["llm"]["prompt_version"], SYSTEM_PROMPT, meta["title"])


def align_key(cfg, fixk) -> str:
    return sha("align", fixk, cfg["align"])


# ------------------------------------------------------------------ ASR
def run_asr(cfg, wd: Path) -> None:
    import torch
    from qwen_asr import Qwen3ASRModel

    meta, chunks = read_json(wd / "meta.json"), read_json(wd / "chunks.json")["chunks"]
    todo = [c for c in chunks if not load_cached(wd / "asr" / f"c{c['id']:04d}.json", asr_key(cfg, meta, c))]
    if not todo:
        return
    a = cfg["asr"]
    model = Qwen3ASRModel.from_pretrained(
        a["model"], dtype=torch.bfloat16, device_map="cuda:0",
        max_inference_batch_size=a["batch_size"], max_new_tokens=a["max_new_tokens"],
    )
    B = a["batch_size"]
    for i in range(0, len(todo), B):
        batch = todo[i : i + B]
        audios = [read_wav_slice(wd / "audio16k.wav", c["start"], c["end"]) for c in batch]
        res = model.transcribe(audio=audios, language=[a["language"]] * len(batch))
        for c, r in zip(batch, res):
            write_json(wd / "asr" / f"c{c['id']:04d}.json",
                       {"key": asr_key(cfg, meta, c), "chunk": c["id"], "start": c["start"], "end": c["end"], "text": r.text.strip(), "language": r.language})
        print(f"asr {min(i + B, len(todo))}/{len(todo)}", flush=True)


# ------------------------------------------------------------------ LLM fix + translate
def _start_server(cfg, log: Path):
    from huggingface_hub import hf_hub_download

    l = cfg["llm"]
    gguf = hf_hub_download(l["repo"], l["file"], local_dir=Path(cfg["paths"]["models_dir"]) / "llm")
    f = open(log, "ab")
    proc = subprocess.Popen(
        [l["server_exe"], "-m", str(gguf), "-c", str(l["ctx"]), "-ngl", "99", "--host", "127.0.0.1",
         "--port", str(l["port"]), "--jinja", "-fa", "on"],
        stdout=f, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{l['port']}"
    for _ in range(600):
        if proc.poll() is not None:
            raise RuntimeError("llama-server exited early (see logs/llama.log)")
        try:
            if httpx.get(base + "/health", timeout=2).status_code == 200:
                return proc, base
        except httpx.HTTPError:
            pass
        time.sleep(1)
    proc.kill()
    raise RuntimeError("llama-server start timeout")


def _ask(base, cfg, title, raw_text) -> list[dict] | None:
    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Video title (context only): {title}\n\nRaw ASR segment:\n{raw_text}"},
        ],
        "temperature": 0.2,
        "max_tokens": 2048,
        "response_format": {"type": "json_schema", "json_schema": {"name": "lesson", "schema": SCHEMA}},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = httpx.post(base + "/v1/chat/completions", json=body, timeout=300)
    r.raise_for_status()
    import json as _j

    sents = _j.loads(r.json()["choices"][0]["message"]["content"])["sentences"]
    sents = [{"en": s["en"].strip(), "ja": s["ja"].strip()} for s in sents if s["en"].strip()]
    return sents or None


def run_fix(cfg, wd: Path) -> None:
    meta, chunks = read_json(wd / "meta.json"), read_json(wd / "chunks.json")["chunks"]
    jobs = []
    for c in chunks:
        raw = read_json(wd / "asr" / f"c{c['id']:04d}.json")
        k = fix_key(cfg, meta, c, raw["key"])
        if not load_cached(wd / "fix" / f"c{c['id']:04d}.json", k):
            jobs.append((c, raw, k))
    if not jobs:
        return
    proc, base = _start_server(cfg, wd / "logs" / "llama.log")
    try:
        for n, (c, raw, k) in enumerate(jobs, 1):
            sents, err = None, None
            if raw["text"].strip():
                for _ in range(cfg["llm"]["retries"]):
                    try:
                        s = _ask(base, cfg, meta["title"], raw["text"])
                        # reject rewrites: corrected text must stay close to raw
                        if s and edit_ratio(raw["text"], " ".join(x["en"] for x in s)) <= 0.5:
                            sents = s
                            break
                        err = "rewrite_or_empty"
                    except Exception as e:  # noqa: BLE001
                        err = f"{type(e).__name__}: {e}"[:200]
            if sents is None and raw["text"].strip():  # keep the chunk, flag it
                sents = [{"en": raw["text"].strip(), "ja": "", "llm_failed": True}]
            sents = sents or []
            ratio = edit_ratio(raw["text"], " ".join(x["en"] for x in sents))
            write_json(wd / "fix" / f"c{c['id']:04d}.json",
                       {"key": k, "chunk": c["id"], "edit_ratio": ratio, "error": err if sents and sents[0].get("llm_failed") else None, "sentences": sents})
            print(f"fix {n}/{len(jobs)}", flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


# ------------------------------------------------------------------ forced alignment
def split_word_ranges(sent_texts: list[str], items: list) -> list[tuple[int, int]]:
    """Map aligned word items to sentences by cumulative normalized-character count.
    Returns [(first_word_idx, last_word_idx_exclusive)] per sentence."""
    ranges, wi = [], 0
    for t in sent_texts:
        need = sum(len(norm_word(w)) for w in t.split())
        start, got = wi, 0
        while wi < len(items) and got < need:
            got += len(norm_word(items[wi].text))
            wi += 1
        ranges.append((start, wi))
    return ranges


def run_align(cfg, wd: Path) -> None:
    import torch
    from qwen_asr import Qwen3ForcedAligner

    meta, chunks = read_json(wd / "meta.json"), read_json(wd / "chunks.json")["chunks"]
    jobs = []
    for c in chunks:
        fx = read_json(wd / "fix" / f"c{c['id']:04d}.json")
        k = align_key(cfg, fx["key"])
        if not load_cached(wd / "align" / f"c{c['id']:04d}.json", k):
            jobs.append((c, fx, k))
    if not jobs:
        return
    model = Qwen3ForcedAligner.from_pretrained(cfg["align"]["model"], dtype=torch.bfloat16, device_map="cuda:0")
    for n, (c, fx, k) in enumerate(jobs, 1):
        texts = [s["en"] for s in fx["sentences"]]
        out_sents, err = [], None
        if texts:
            audio = read_wav_slice(wd / "audio16k.wav", c["start"], c["end"])
            try:
                items = model.align(audio=audio, text=" ".join(texts), language=cfg["align"]["language"])[0]
                items = list(items)
            except Exception as e:  # noqa: BLE001
                items, err = [], f"{type(e).__name__}: {e}"[:200]
            ranges = split_word_ranges(texts, items)
            for s, (a, b) in zip(fx["sentences"], ranges):
                words = [{"w": it.text, "start": round(c["start"] + it.start_time, 3), "end": round(c["start"] + it.end_time, 3)} for it in items[a:b]]
                out_sents.append({**s, "words": words, "word_range": [a, b]})
        write_json(wd / "align" / f"c{c['id']:04d}.json", {"key": k, "chunk": c["id"], "error": err, "sentences": out_sents})
        print(f"align {n}/{len(jobs)}", flush=True)


STAGES = {"asr": run_asr, "fix": run_fix, "align": run_align}

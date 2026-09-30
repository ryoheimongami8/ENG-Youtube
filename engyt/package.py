"""Assemble lesson.json (flagging suspicious sentences) and zip it with the mp3."""
from __future__ import annotations

import zipfile
from pathlib import Path

from .util import read_json, write_json

VERSION = 1


def flag_sentence(s: dict, chunk_ratio: float, chunk_err: str | None, rv: dict) -> list[str]:
    fl = []
    w = s["words"]
    if not w or chunk_err:
        fl.append("unaligned")
    else:
        n_expected = len(s["en"].split())
        if abs(len(w) - n_expected) > max(1, n_expected * 0.2):
            fl.append("word_count_mismatch")
        prev_end = None
        # aligner resolution is 80ms, so isolated zero-length words are normal; many are not
        durs = [x["end"] - x["start"] for x in w]
        if any(d > rv["max_word_sec"] for d in durs) or (len(w) >= 4 and sum(d <= 0 for d in durs) > len(w) * 0.3):
            fl.append("odd_word_length")
        for x in w:
            if x["end"] < x["start"] or (prev_end is not None and x["start"] < prev_end - 0.01):
                fl.append("time_reversal")
                break
            prev_end = x["end"]
    if chunk_ratio > rv["max_edit_ratio"]:
        fl.append("large_edit")
    if not s.get("ja") or s.get("llm_failed"):
        fl.append("translation_missing")
    return fl


def build_lesson(cfg, wd: Path) -> dict:
    meta = read_json(wd / "meta.json")
    chunks = read_json(wd / "chunks.json")
    rv = cfg["review"]
    sentences = []
    for c in chunks["chunks"]:
        fx = read_json(wd / "fix" / f"c{c['id']:04d}.json")
        al = read_json(wd / "align" / f"c{c['id']:04d}.json")
        for s in al["sentences"]:
            fl = flag_sentence(s, fx["edit_ratio"], al["error"], rv)
            words = s["words"]
            start = words[0]["start"] if words else c["start"]
            end = words[-1]["end"] if words else c["end"]
            item = {"i": len(sentences), "chunk": c["id"], "start": start, "end": end, "en": s["en"], "ja": s.get("ja", ""), "words": words}
            if fl:
                item["flag"] = sorted(set(fl))
            sentences.append(item)
    # keep sentence times monotonic even when a flagged sentence has no words
    for a, b in zip(sentences, sentences[1:]):
        if b["start"] < a["start"]:
            b["start"] = a["start"]
        if a["end"] > b["start"] and "flag" not in a:
            a["end"] = b["start"]
    return {"version": VERSION, "id": meta["id"], "title": meta["title"], "source_url": meta["url"],
            "duration": chunks["duration"], "sentences": sentences}


def validate_mp3(cfg, wd: Path, duration: float) -> float:
    import subprocess

    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wd / "audio.mp3")],
                       capture_output=True, text=True)
    d = float(r.stdout.strip())
    if abs(d - duration) > cfg["review"]["mp3_tolerance_sec"]:
        raise RuntimeError(f"mp3 duration {d:.2f}s vs wav {duration:.2f}s exceeds tolerance")
    return d


def make_zip(cfg, wd: Path) -> tuple[Path, dict]:
    lesson = build_lesson(cfg, wd)
    validate_mp3(cfg, wd, lesson["duration"])
    write_json(wd / "lesson.json", lesson)
    out = Path(cfg["paths"]["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    zp = out / f"{lesson['id']}.zip"
    tmp = zp.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(wd / "lesson.json", "lesson.json")
        z.write(wd / "audio.mp3", "audio.mp3", compress_type=zipfile.ZIP_STORED)  # mp3 doesn't compress
    tmp.replace(zp)
    return zp, lesson

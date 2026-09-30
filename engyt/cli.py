"""CLI. stdout of `run` / `resume` is one final JSON line only; details go to work/<id>/logs."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .util import load_config, run_logged


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _stage(name: str, wd: Path) -> None:
    run_logged([sys.executable, "-m", "engyt", "stage", name, str(wd)], wd / "logs" / f"{name}.log")


def run_pipeline(cfg, url: str) -> dict:
    from .chunking import make_chunks
    from .download import download_audio
    from .package import make_zip

    wd, meta = download_audio(cfg, url, Path(cfg["paths"]["work_dir"]))
    make_chunks(cfg, wd)
    for st in ("asr", "fix", "align"):
        try:
            _stage(st, wd)
        except subprocess.CalledProcessError:
            return {"ok": False, "failed_stage": st, "log": str(wd / "logs" / f"{st}.log"), "workdir": str(wd)}
    zp, lesson = make_zip(cfg, wd)
    flagged = sum(1 for s in lesson["sentences"] if "flag" in s)
    return {"ok": True, "zip": str(zp), "title": meta["title"], "duration": round(lesson["duration"], 1),
            "sentences": len(lesson["sentences"]), "review_needed": flagged, "workdir": str(wd)}


def cmd_setup(cfg) -> dict:
    from huggingface_hub import hf_hub_download, snapshot_download

    m = Path(cfg["paths"]["models_dir"])
    snapshot_download(cfg["asr"]["model"])
    snapshot_download(cfg["align"]["model"])
    hf_hub_download(cfg["llm"]["repo"], cfg["llm"]["file"], local_dir=m / "llm")
    return {"ok": True}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engyt")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("run", "resume"):  # same behaviour: every step is cached & resumable
        sub.add_parser(n).add_argument("url")
    sub.add_parser("setup")
    sp = sub.add_parser("stage")
    sp.add_argument("name")
    sp.add_argument("workdir")
    a = ap.parse_args(argv)
    cfg = load_config()

    if a.cmd == "stage":
        from .stages import STAGES

        STAGES[a.name](cfg, Path(a.workdir))
        return 0
    try:
        res = cmd_setup(cfg) if a.cmd == "setup" else run_pipeline(cfg, a.url)
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    _emit(res)
    return 0 if res.get("ok") else 1

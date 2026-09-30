"""yt-dlp audio fetch + ffmpeg conversion (16k mono wav for models, mp3 for the lesson)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .util import SR, read_json, run_logged, write_json


def _ytdlp(cfg, extra: list[str]) -> list[str]:
    return [sys.executable, "-m", "yt_dlp", "--no-playlist", "--js-runtimes", cfg["download"]["js_runtime"], *extra]


def fetch_meta(cfg, url: str, log: Path) -> dict:
    cmd = _ytdlp(cfg, ["--skip-download", "--dump-single-json", url])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(r.stderr)
    if r.returncode != 0:
        raise RuntimeError("yt-dlp metadata failed (see log)")
    j = json.loads(r.stdout)
    return {"id": j["id"], "title": j.get("title", j["id"]), "duration": j.get("duration"), "url": url}


def download_audio(cfg, url: str, work_root: Path) -> tuple[Path, dict]:
    """Returns (workdir, meta). Skips work already done."""
    tmp_log = work_root / "_probe.log"
    meta = fetch_meta(cfg, url, tmp_log)
    wd = work_root / meta["id"]
    logs = wd / "logs"
    wd.mkdir(parents=True, exist_ok=True)
    write_json(wd / "meta.json", meta)

    src = next(iter(wd.glob("source.*")), None)
    if src is None or src.suffix in (".part", ".ytdl"):
        run_logged(_ytdlp(cfg, ["-f", "bestaudio/best", "-o", str(wd / "source.%(ext)s"), url]), logs / "download.log")
        src = next(p for p in wd.glob("source.*") if p.suffix not in (".part", ".ytdl"))

    wav = wd / "audio16k.wav"
    if not wav.exists():
        tmp = wd / "audio16k.tmp.wav"
        run_logged(["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(tmp)], logs / "ffmpeg.log")
        tmp.replace(wav)
    mp3 = wd / "audio.mp3"
    if not mp3.exists():
        tmp = wd / "audio.tmp.mp3"
        run_logged(["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "44100", "-b:a", cfg["download"]["mp3_bitrate"], str(tmp)], logs / "ffmpeg.log")
        tmp.replace(mp3)
    return wd, meta

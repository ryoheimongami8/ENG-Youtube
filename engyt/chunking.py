"""Split audio at silences into chunks of roughly target_sec (never above max_sec)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .util import read_json, write_json


def wav_duration(wav: Path) -> float:
    import soundfile as sf

    info = sf.info(str(wav))
    return info.frames / info.samplerate


def detect_silences(wav: Path, db: float, min_sec: float) -> list[tuple[float, float]]:
    r = subprocess.run(
        ["ffmpeg", "-i", str(wav), "-af", f"silencedetect=noise={db}dB:d={min_sec}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(starts, ends))


def plan_chunks(duration: float, silences: list[tuple[float, float]], target: float, max_sec: float, min_sec: float):
    """Cut points are silence midpoints. Greedy: cut at the silence closest to target within (min, max]."""
    mids = [(s + e) / 2 for s, e in silences]
    bounds = [0.0]
    while duration - bounds[-1] > max_sec:
        lo, hi = bounds[-1] + min_sec, bounds[-1] + max_sec
        cands = [m for m in mids if lo <= m <= hi]
        cut = min(cands, key=lambda m: abs(m - bounds[-1] - target)) if cands else hi
        bounds.append(cut)
    bounds.append(duration)
    if len(bounds) > 2 and bounds[-1] - bounds[-2] < min_sec:  # merge tiny tail if it fits
        if bounds[-1] - bounds[-3] <= max_sec * 1.2:
            del bounds[-2]
    return [{"id": i, "start": round(a, 3), "end": round(b, 3)} for i, (a, b) in enumerate(zip(bounds, bounds[1:]))]


def make_chunks(cfg, wd: Path) -> list[dict]:
    p = wd / "chunks.json"
    if p.exists():
        return read_json(p)["chunks"]
    c = cfg["chunking"]
    wav = wd / "audio16k.wav"
    dur = wav_duration(wav)
    sil = detect_silences(wav, c["silence_db"], c["silence_min_sec"])
    chunks = plan_chunks(dur, sil, c["target_sec"], c["max_sec"], c["min_sec"])
    write_json(p, {"duration": dur, "chunks": chunks})
    return chunks

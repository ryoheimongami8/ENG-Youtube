"""Shared helpers: config, atomic JSON, hashing, ffmpeg wrapper, audio adapter."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SR = 16000


def load_config() -> dict:
    with open(ROOT / "config.toml", "rb") as f:
        cfg = tomllib.load(f)
    for k in ("work_dir", "out_dir", "models_dir"):
        cfg["paths"][k] = str((ROOT / cfg["paths"][k]).resolve())
    return cfg


def sha(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode())
    return h.hexdigest()[:16]


def write_json(path: Path, obj) -> None:
    """Write to temp file then atomically replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_cached(path: Path, key: str):
    """Return cached JSON if it exists and its key matches, else None."""
    if not path.exists():
        return None
    try:
        obj = read_json(path)
    except Exception:
        return None
    return obj if obj.get("key") == key else None


def run_logged(cmd: list[str], log: Path, **kw) -> None:
    """Run a command, appending all output to a log file. Raises on failure."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as f:
        f.write(("\n$ " + " ".join(map(str, cmd)) + "\n").encode())
        f.flush()
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True, **kw)


# --- audio adapter: avoids torchcodec (broken with FFmpeg 8 on this machine) ---
def read_wav_slice(wav: Path, start: float, end: float) -> tuple[np.ndarray, int]:
    """Return (mono float32 waveform, 16000) for [start, end) seconds."""
    import soundfile as sf

    with sf.SoundFile(str(wav)) as f:
        assert f.samplerate == SR, f"expected {SR}Hz wav"
        f.seek(int(start * SR))
        data = f.read(int((end - start) * SR), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, SR


def norm_word(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())

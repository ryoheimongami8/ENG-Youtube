from types import SimpleNamespace as NS

from engyt.chunking import plan_chunks
from engyt.package import flag_sentence
from engyt.stages import edit_ratio, split_word_ranges

RV = {"max_word_sec": 3.0, "max_edit_ratio": 0.3}


def test_plan_chunks_covers_duration_and_caps():
    ch = plan_chunks(200.0, [(29, 31), (58, 60), (95, 96)], 30, 60, 8)
    assert ch[0]["start"] == 0 and ch[-1]["end"] == 200.0
    assert all(a["end"] == b["start"] for a, b in zip(ch, ch[1:]))
    assert all(c["end"] - c["start"] <= 72 for c in ch)


def test_split_word_ranges_by_chars():
    items = [NS(text=w) for w in ["Hello", "world", "It's", "me"]]
    assert split_word_ranges(["Hello world.", "It's me."], items) == [(0, 2), (2, 4)]


def test_edit_ratio():
    assert edit_ratio("a b c", "a b c") == 0
    assert edit_ratio("a b c d", "a x c d") > 0


def _s(words, ja="x"):
    return {"en": " ".join(w["w"] for w in words), "ja": ja, "words": words}


def test_flags():
    ok = [{"w": "a", "start": 0, "end": 0.2}, {"w": "b", "start": 0.2, "end": 0.4}]
    assert flag_sentence(_s(ok), 0, None, RV) == []
    assert "unaligned" in flag_sentence(_s([]), 0, None, RV)
    assert "translation_missing" in flag_sentence(_s(ok, ja=""), 0, None, RV)
    assert "large_edit" in flag_sentence(_s(ok), 0.5, None, RV)
    rev = [{"w": "a", "start": 1, "end": 1.2}, {"w": "b", "start": 0.5, "end": 0.7}]
    assert "time_reversal" in flag_sentence(_s(rev), 0, None, RV)
    long = [{"w": "a", "start": 0, "end": 5}, {"w": "b", "start": 5, "end": 5.2}]
    assert "odd_word_length" in flag_sentence(_s(long), 0, None, RV)

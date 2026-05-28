"""Pure WebVTT parser, slicer, and search. No I/O, no Graph calls."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Iterable

_TS_RE = re.compile(r"(\d+):(\d+):(\d+)[.,](\d+)\s*-->\s*(\d+):(\d+):(\d+)[.,](\d+)")
_SPEAKER_RE = re.compile(r"<v\s+([^>]+?)>(.*?)(?:</v>|$)", re.DOTALL)


@dataclass
class Cue:
    start_sec: float
    end_sec: float
    speaker: str
    text: str

    def as_line(self) -> str:
        ts = _fmt_ts(self.start_sec)
        if self.speaker:
            return f"[{ts}] {self.speaker}: {self.text}"
        return f"[{ts}] {self.text}"


def _fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _parse_ts(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_vtt(vtt_text: str) -> list[Cue]:
    cues: list[Cue] = []
    blocks = re.split(r"\n\s*\n", vtt_text.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        ts_line_idx = next((i for i, ln in enumerate(lines) if _TS_RE.search(ln)), None)
        if ts_line_idx is None:
            continue
        m = _TS_RE.search(lines[ts_line_idx])
        start = _parse_ts(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _parse_ts(m.group(5), m.group(6), m.group(7), m.group(8))
        body = "\n".join(lines[ts_line_idx + 1:]).strip()
        sp_match = _SPEAKER_RE.search(body)
        if sp_match:
            speaker = sp_match.group(1).strip()
            text = sp_match.group(2).strip()
        else:
            speaker = ""
            text = body
        cues.append(Cue(start, end, speaker, text))
    return cues


def cues_to_text(cues: Iterable[Cue]) -> str:
    return "\n".join(c.as_line() for c in cues)


def build_header(cues: list[Cue], preview_seconds: int = 90) -> dict:
    if not cues:
        return {"duration_sec": 0, "cue_count": 0, "speakers": {}, "preview": ""}
    total = cues[-1].end_sec - cues[0].start_sec
    speakers: dict[str, dict] = {}
    for c in cues:
        s = speakers.setdefault(c.speaker or "(unknown)", {"talk_sec": 0.0, "cue_count": 0})
        s["talk_sec"] += c.end_sec - c.start_sec
        s["cue_count"] += 1
    for v in speakers.values():
        v["talk_pct"] = round(100 * v["talk_sec"] / total, 1) if total else 0.0
    preview = cues_to_text(c for c in cues if c.start_sec < preview_seconds)
    return {
        "duration_sec": int(total),
        "cue_count": len(cues),
        "speakers": speakers,
        "preview": preview,
    }


def slice_range(cues: list[Cue], start_sec: float, end_sec: float) -> list[Cue]:
    return [c for c in cues if c.end_sec > start_sec and c.start_sec < end_sec]


def filter_speaker(cues: list[Cue], name: str) -> list[Cue]:
    needle = name.strip().lower()
    return [c for c in cues if needle in c.speaker.lower()]


def search_cues(cues: list[Cue], query: str, context_sec: float = 30.0, max_results: int = 5) -> list[dict]:
    needle = query.strip().lower()
    if not needle:
        return []
    hits = []
    for i, c in enumerate(cues):
        if needle in c.text.lower():
            ctx = slice_range(cues, c.start_sec - context_sec, c.end_sec + context_sec)
            hits.append({
                "match_index": i,
                "match": c.as_line(),
                "context": [x.as_line() for x in ctx],
            })
            if len(hits) >= max_results:
                break
    return hits

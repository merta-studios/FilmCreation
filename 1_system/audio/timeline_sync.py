"""Wandelt ElevenLabs Zeichen-Timestamps in Wort-/Satz-Timestamps & Frame-Zahlen um."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WordTiming:
    word: str
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int
    segment_id: int = 0


@dataclass
class SegmentTiming:
    segment_id: int
    role: str
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int
    duration_frames: int
    words: list[WordTiming] = field(default_factory=list)
    pause_after_seconds: float = 0.0


def _words_from_alignment(alignment: dict, segment_id: int, fps: int,
                          offset_seconds: float) -> list[WordTiming]:
    """Splittet Zeichen-Alignment in Woerter mit exakten Zeiten."""
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    if not (len(chars) == len(starts) == len(ends)):
        raise ValueError("Alignment-Arrays haben verschiedene Längen")
    if any(float(a) < 0 or float(b) < float(a) for a, b in zip(starts, ends)):
        raise ValueError("Ungültige Alignment-Zeiten")
    if any(float(starts[i]) < float(starts[i-1]) for i in range(1, len(starts))):
        raise ValueError("Alignment ist nicht chronologisch")
    words: list[WordTiming] = []
    cur_chars: list[str] = []
    cur_start: Optional[float] = None
    cur_end: Optional[float] = None

    def flush():
        nonlocal cur_chars, cur_start, cur_end
        if cur_chars and cur_start is not None and cur_end is not None:
            word = "".join(cur_chars).strip()
            if word:
                s = offset_seconds + cur_start
                e = offset_seconds + cur_end
                words.append(WordTiming(
                    word=word, start_seconds=round(s, 3), end_seconds=round(e, 3),
                    start_frame=int(round(s * fps)), end_frame=int(round(e * fps)),
                    segment_id=segment_id))
        cur_chars = []
        cur_start = None
        cur_end = None

    for i, ch in enumerate(chars):
        s = float(starts[i]) if i < len(starts) else 0.0
        e = float(ends[i]) if i < len(ends) else s
        if ch.isspace():
            flush()
            continue
        if cur_start is None:
            cur_start = s
        cur_end = e
        cur_chars.append(ch)
    flush()
    return words


def build_timeline(segment_results: list[dict], fps: int = 24,
                   pause_after: Optional[dict] = None) -> dict:
    """Baut die aufgeloeste Timeline: Segmente, Woerter, Frames, Cues.

    segment_results: Liste mit segment_id, role, audio_path, alignment, duration.
    pause_after: optionales Dict segment_id -> Pausen Sekunden (Atempausen).
    """
    if fps <= 0:
        raise ValueError("fps muss positiv sein")
    pause_after = pause_after or {}
    segments: list[SegmentTiming] = []
    offset = 0.0
    all_words: list[WordTiming] = []
    for res in sorted(segment_results, key=lambda r: r["segment_id"]):
        sid = int(res["segment_id"])
        alignment = res.get("alignment", {})
        duration = float(res.get("duration", 0.0))
        if duration <= 0 and alignment.get("character_end_times_seconds"):
            duration = float(alignment["character_end_times_seconds"][-1])
        words = _words_from_alignment(alignment, sid, fps, offset)
        start_f = int(round(offset * fps))
        end_f = int(round((offset + duration) * fps))
        pause = float(pause_after.get(sid, 0.0))
        seg = SegmentTiming(segment_id=sid, role=res.get("role", "ERZAEHLER"),
                            start_seconds=round(offset, 3),
                            end_seconds=round(offset + duration, 3),
                            start_frame=start_f, end_frame=end_f,
                            duration_frames=max(1, end_f - start_f),
                            words=words, pause_after_seconds=pause)
        segments.append(seg)
        all_words.extend(words)
        offset += duration + pause
    total_frames = int(round(offset * fps))
    cues: list[dict] = []
    for w in all_words:
        cues.append({"word": w.word, "segment_id": w.segment_id,
                     "start_seconds": w.start_seconds, "end_seconds": w.end_seconds,
                     "start_frame": w.start_frame, "end_frame": w.end_frame})
    return {
        "fps": fps,
        "total_seconds": round(offset, 3),
        "total_frames": total_frames,
        "segments": [
            {"segment_id": s.segment_id, "role": s.role,
             "start_seconds": s.start_seconds, "end_seconds": s.end_seconds,
             "start_frame": s.start_frame, "end_frame": s.end_frame,
             "duration_frames": s.duration_frames,
             "pause_after_seconds": s.pause_after_seconds,
             "audio_path": next((r.get("audio_path") for r in segment_results
                                 if int(r["segment_id"]) == s.segment_id), ""),
             "words": [{"word": w.word, "start_seconds": w.start_seconds,
                        "end_seconds": w.end_seconds, "start_frame": w.start_frame,
                        "end_frame": w.end_frame} for w in s.words]}
            for s in segments
        ],
        "word_cues": cues,
    }


def find_word_frame(timeline: dict, segment_id: int, word_index: int) -> int:
    """Gibt den Start-Frame des n-ten Wortes eines Segments zurueck."""
    for seg in timeline.get("segments", []):
        if int(seg["segment_id"]) == int(segment_id):
            words = seg.get("words", [])
            if 0 <= word_index < len(words):
                return int(words[word_index]["start_frame"])
            raise IndexError(f"Segment {segment_id} hat nur {len(words)} Woerter.")
    raise KeyError(f"Segment {segment_id} nicht in Timeline.")


def find_word_by_text(timeline: dict, segment_id: int, word: str,
                      occurrence: int = 0) -> int:
    """Findet den Start-Frame des ersten Vorkommens von `word` im Segment."""
    target = word.lower().strip(".,!?;:\"'()")
    count = 0
    for seg in timeline.get("segments", []):
        if int(seg["segment_id"]) == int(segment_id):
            for w in seg.get("words", []):
                if w["word"].lower().strip(".,!?;:\"'()") == target:
                    if count == occurrence:
                        return int(w["start_frame"])
                    count += 1
            raise ValueError(f"Wort '{word}' nicht in Segment {segment_id} gefunden.")
    raise KeyError(f"Segment {segment_id} nicht in Timeline.")

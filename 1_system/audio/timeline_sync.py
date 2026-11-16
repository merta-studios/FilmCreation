"""Wortgenaue Timeline: ElevenLabs-Zeichen-Timestamps -> Woerter, Saetze, Frames, Shots.

Dieses Modul ist absichtlich frei von Blender-, Netzwerk- und FFmpeg-Abhaengigkeiten,
damit es ueberall (Tests, GitHub Actions, Kaggle) identisch rechnet.

Fachliche Regeln
----------------
* 24 fps ist fix. Jede Sekunde entspricht exakt 24 Frames; gerundet wird kaufmaennisch.
* Ein Segment ist ein zusammenhaengender Sprechblock einer Stimme. Sprechpausen
  (`pause_after`) werden zwischen die Segmente gelegt und gehoeren zum vorherigen
  Segment-Zeitfenster (so bleiben Shots lueckenlos).
* Ein Shot ist ein visueller Block. Mehrere Shots duerfen ein Segment teilen
  (Wort-genaue Schnitte). Shots sind immer lueckenlos und ueberdecken den Film
  vom ersten bis zum letzten Frame.
* Alle Zeiten werden aus den echten `character_start_times_seconds` /
  `character_end_times_seconds` der ElevenLabs-Antwort berechnet - nie geschaetzt.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

FPS_DEFAULT = 24
MIN_SHOT_FRAMES = 24          # 1,0 s: kuerzere Shots wirken im Feed wie ein Blitzer
SENTENCE_GAP_SECONDS = 0.30   # ab dieser Luecke beginnt ein neuer Satz (Untertitel)
PUNCTUATION_STRIP = ".,!?;:\"'\u201e\u201c\u2018\u2019()[]{}-\u2013\u2014\u2026"

_WORD_RE = re.compile(r"[^\s]+", re.UNICODE)


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #
@dataclass
class WordTiming:
    word: str
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int
    segment_id: int = 0
    index_in_segment: int = 0
    sentence_index: int = 0

    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "segment_id": self.segment_id,
            "index_in_segment": self.index_in_segment,
            "sentence_index": self.sentence_index,
        }


@dataclass
class SentenceTiming:
    segment_id: int
    sentence_index: int
    text: str
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int
    words: list[WordTiming] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "sentence_index": self.sentence_index,
            "text": self.text,
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "word_count": len(self.words),
        }


@dataclass
class SegmentTiming:
    segment_id: int
    role: str
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int
    duration_frames: int
    text: str = ""
    voice_id: str = ""
    audio_path: str = ""
    words: list[WordTiming] = field(default_factory=list)
    sentences: list[SentenceTiming] = field(default_factory=list)
    pause_after_seconds: float = 0.0


# --------------------------------------------------------------------------- #
# Hilfsfunktionen
# --------------------------------------------------------------------------- #
def seconds_to_frames(seconds: float, fps: int = FPS_DEFAULT) -> int:
    """Kaufmaennische Rundung Sekunden -> Frame (nie negativ)."""
    if fps <= 0:
        raise ValueError("fps muss positiv sein")
    return max(0, int(round(float(seconds) * fps)))


def clean_word(word: str) -> str:
    return word.strip().strip(PUNCTUATION_STRIP).casefold()


def _validate_alignment(alignment: dict) -> tuple[list[str], list[float], list[float]]:
    chars = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not (isinstance(chars, list) and isinstance(starts, list) and isinstance(ends, list)):
        raise ValueError("Alignment unvollstaendig (characters/start/end fehlen)")
    if not (len(chars) == len(starts) == len(ends)):
        raise ValueError("Alignment-Arrays haben verschiedene Laengen")
    if not chars:
        raise ValueError("Alignment ist leer - der Text wurde nicht gesprochen")
    try:
        starts_f = [float(x) for x in starts]
        ends_f = [float(x) for x in ends]
    except (TypeError, ValueError) as exc:
        raise ValueError("Alignment-Zeiten sind keine Zahlen") from exc
    if any(s < 0 for s in starts_f) or any(e < 0 for e in ends_f):
        raise ValueError("Alignment enthaelt negative Zeiten")
    if any(e < s for s, e in zip(starts_f, ends_f)):
        raise ValueError("Alignment enthaelt Zeiten mit Ende vor Start")
    if any(starts_f[i] < starts_f[i - 1] for i in range(1, len(starts_f))):
        raise ValueError("Alignment ist nicht chronologisch")
    return [str(c) for c in chars], starts_f, ends_f


# --------------------------------------------------------------------------- #
# Alignment -> Woerter
# --------------------------------------------------------------------------- #
def words_from_alignment(alignment: dict, segment_id: int, fps: int = FPS_DEFAULT,
                         offset_seconds: float = 0.0) -> list[WordTiming]:
    """Zerlegt ein Zeichen-Alignment in Woerter mit exakten Zeiten und Frames."""
    chars, starts, ends = _validate_alignment(alignment)
    words: list[WordTiming] = []
    buffer: list[str] = []
    word_start: Optional[float] = None
    word_end: Optional[float] = None

    def flush() -> None:
        nonlocal buffer, word_start, word_end
        text = "".join(buffer).strip()
        if text and word_start is not None and word_end is not None:
            start = offset_seconds + word_start
            end = offset_seconds + word_end
            words.append(WordTiming(
                word=text,
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                start_frame=seconds_to_frames(start, fps),
                end_frame=seconds_to_frames(end, fps),
                segment_id=segment_id,
                index_in_segment=len(words),
            ))
        buffer = []
        word_start = None
        word_end = None

    for ch, start, end in zip(chars, starts, ends):
        if ch.isspace():
            flush()
            continue
        if word_start is None:
            word_start = start
        word_end = end
        buffer.append(ch)
    flush()
    if not words:
        raise ValueError(f"Segment {segment_id}: keine Woerter aus Alignment lesbar")
    # Monotonie absichern: ein Wort darf nie vor dem vorherigen enden.
    for i in range(1, len(words)):
        if words[i].start_frame < words[i - 1].end_frame:
            words[i].start_frame = words[i - 1].end_frame
        if words[i].end_frame <= words[i].start_frame:
            words[i].end_frame = words[i].start_frame + 1
    return words


def group_sentences(words: list[WordTiming], fps: int = FPS_DEFAULT) -> list[SentenceTiming]:
    """Gruppiert Woerter zu Saetzen (Interpunktion oder Sprechpause)."""
    if not words:
        return []
    sentences: list[SentenceTiming] = []
    current: list[WordTiming] = []

    def close() -> None:
        nonlocal current
        if not current:
            return
        text = " ".join(w.word for w in current)
        sentences.append(SentenceTiming(
            segment_id=current[0].segment_id,
            sentence_index=len(sentences),
            text=text,
            start_seconds=current[0].start_seconds,
            end_seconds=current[-1].end_seconds,
            start_frame=current[0].start_frame,
            end_frame=current[-1].end_frame,
            words=list(current),
        ))
        for w in current:
            w.sentence_index = len(sentences) - 1
        current = []

    for word in words:
        if current:
            gap = word.start_seconds - current[-1].end_seconds
            if gap >= SENTENCE_GAP_SECONDS:
                close()
        current.append(word)
        if word.word.rstrip().endswith((".", "!", "?", "\u2026", ":")):
            close()
    close()
    return sentences


# --------------------------------------------------------------------------- #
# Segmente -> Timeline
# --------------------------------------------------------------------------- #
def build_timeline(segment_results: Iterable[dict], fps: int = FPS_DEFAULT,
                   pause_after: Optional[dict] = None,
                   width: int = 1080, height: int = 1920,
                   film_title: str = "") -> dict:
    """Baut die aufgeloeste Timeline (Segmente, Woerter, Saetze, Cues, Frames).

    `segment_results` ist eine Liste von Dicts mit:
      segment_id, role (Sprecher), text, alignment, duration (optional),
      audio_path (optional), voice_id (optional), pause_after (optional).
    """
    if fps <= 0:
        raise ValueError("fps muss positiv sein")
    if width <= 0 or height <= 0:
        raise ValueError("Aufloesung muss positiv sein")
    if width * 16 != height * 9:
        raise ValueError(f"Aufloesung {width}x{height} ist nicht 9:16")

    pause_after = {int(k): float(v) for k, v in (pause_after or {}).items()}
    results = sorted(segment_results, key=lambda r: int(r["segment_id"]))
    if not results:
        raise ValueError("Keine Segmente vorhanden")
    ids = [int(r["segment_id"]) for r in results]
    if len(set(ids)) != len(ids):
        raise ValueError("Segment-IDs sind nicht eindeutig")

    segments: list[SegmentTiming] = []
    offset = 0.0
    for res in results:
        sid = int(res["segment_id"])
        alignment = res.get("alignment") or {}
        words = words_from_alignment(alignment, sid, fps, offset)
        audio_duration = float(res.get("duration") or 0.0)
        if audio_duration <= 0:
            audio_duration = float(alignment["character_end_times_seconds"][-1])
        if audio_duration <= 0:
            raise ValueError(f"Segment {sid}: Dauer ist 0")
        pause = float(res.get("pause_after", pause_after.get(sid, 0.0)))
        if pause < 0:
            raise ValueError(f"Segment {sid}: negative Pause")
        start_f = seconds_to_frames(offset, fps)
        end_f = seconds_to_frames(offset + audio_duration, fps)
        if end_f <= start_f:
            raise ValueError(f"Segment {sid} ist kuerzer als ein Frame")
        sentences = group_sentences(words, fps)
        segments.append(SegmentTiming(
            segment_id=sid,
            role=str(res.get("role") or "ERZAEHLER"),
            start_seconds=round(offset, 3),
            end_seconds=round(offset + audio_duration, 3),
            start_frame=start_f,
            end_frame=end_f,
            duration_frames=end_f - start_f,
            text=str(res.get("text") or ""),
            voice_id=str(res.get("voice_id") or ""),
            audio_path=str(res.get("audio_path") or ""),
            words=words,
            sentences=sentences,
            pause_after_seconds=pause,
        ))
        offset += audio_duration + pause

    total_frames = seconds_to_frames(offset, fps)
    word_cues = [w.to_dict() for seg in segments for w in seg.words]
    return {
        "fps": fps,
        "width": width,
        "height": height,
        "aspect": "9:16",
        "film_title": film_title,
        "total_seconds": round(offset, 3),
        "total_frames": total_frames,
        "total_words": len(word_cues),
        "segments": [
            {
                "segment_id": seg.segment_id,
                "role": seg.role,
                "voice_id": seg.voice_id,
                "text": seg.text,
                "start_seconds": seg.start_seconds,
                "end_seconds": seg.end_seconds,
                "start_frame": seg.start_frame,
                "end_frame": seg.end_frame,
                "duration_frames": seg.duration_frames,
                "pause_after_seconds": seg.pause_after_seconds,
                "audio_path": seg.audio_path,
                "words": [w.to_dict() for w in seg.words],
                "sentences": [s.to_dict() for s in seg.sentences],
            }
            for seg in segments
        ],
        "word_cues": word_cues,
    }


# --------------------------------------------------------------------------- #
# Shots auf die Timeline legen
# --------------------------------------------------------------------------- #
def _segment_of(timeline: dict, segment_id: int) -> dict:
    for seg in timeline.get("segments", []):
        if int(seg["segment_id"]) == int(segment_id):
            return seg
    raise KeyError(f"Segment {segment_id} nicht in Timeline")


def resolve_shots(timeline: dict, shots_spec: list[dict],
                  min_frames: int = MIN_SHOT_FRAMES) -> list[dict]:
    """Verteilt Shots lueckenlos und wortgenau auf die Segment-Zeitfenster.

    `shots_spec`: Liste von Dicts mit mindestens `id` und `segment_id`.
    Optional je Shot: `start_word` und `end_word` (Text des ersten/letzten Worts,
    case-insensitiv, Interpunktion wird ignoriert) sowie `occurrence` (0-basiert).
    Ohne Wortmarken wird ein Segment gleichmaessig nach Wortaenzahl aufgeteilt.
    """
    if not shots_spec:
        raise ValueError("Keine Shots definiert")
    ids = [int(s["id"]) for s in shots_spec]
    if len(set(ids)) != len(ids):
        raise ValueError("Shot-IDs sind nicht eindeutig")

    by_segment: dict[int, list[dict]] = {}
    for shot in shots_spec:
        by_segment.setdefault(int(shot["segment_id"]), []).append(shot)
    for seg_id in by_segment:
        _segment_of(timeline, seg_id)  # wirft, wenn unbekannt

    unassigned_segments = [int(s["segment_id"]) for s in timeline["segments"]
                           if int(s["segment_id"]) not in by_segment]
    if unassigned_segments:
        raise ValueError(f"Segmente ohne Shot: {unassigned_segments}")

    resolved: dict[int, dict] = {}
    for seg_id, seg_shots in by_segment.items():
        segment = _segment_of(timeline, seg_id)
        words = segment["words"]
        seg_start, seg_end = int(segment["start_frame"]), int(segment["end_frame"])
        seg_shots.sort(key=lambda s: int(s["id"]))
        n = len(seg_shots)
        cuts: list[int] = []
        if n == 1:
            cuts = [0, len(words)]
        else:
            explicit = [(s.get("start_word"), s.get("end_word")) for s in seg_shots]
            if any(w for pair in explicit for w in pair):
                cuts = [0]
                for idx in range(1, n):
                    marker = explicit[idx][0]
                    if not marker:
                        raise ValueError(
                            f"Segment {seg_id}: Shot {seg_shots[idx]['id']} braucht start_word, "
                            "wenn andere Shots Wortmarken nutzen")
                    pos = _word_index(words, marker, int(seg_shots[idx].get("occurrence", 0)))
                    cuts.append(max(cuts[-1] + 1, pos))
                cuts.append(len(words))
            else:
                total_weight = sum(max(1, w["end_frame"] - w["start_frame"]) for w in words)
                target = total_weight / n
                cuts = [0]
                acc = 0
                next_target = target
                for i, w in enumerate(words):
                    acc += max(1, w["end_frame"] - w["start_frame"])
                    if acc >= next_target and len(cuts) < n:
                        cuts.append(min(len(words) - 1, i + 1))
                        next_target += target
                cuts.append(len(words))
                # Duplikate/Ordnung reparieren
                cuts = sorted(set(cuts))
                while len(cuts) < n + 1:
                    cuts.insert(-1, cuts[-1])
        if len(cuts) != n + 1:
            raise ValueError(f"Segment {seg_id}: Shot-Aufteilung fehlgeschlagen")

        for i, shot in enumerate(seg_shots):
            w_from, w_to = cuts[i], cuts[i + 1]
            if w_from >= len(words):
                raise ValueError(f"Shot {shot['id']}: start_word liegt hinter dem Segmentende")
            start_f = seg_start if i == 0 else int(words[w_from]["start_frame"])
            end_f = seg_end if i == n - 1 else int(words[min(w_to, len(words) - 1)]["start_frame"])
            if end_f <= start_f:
                end_f = start_f + 1
            resolved[int(shot["id"])] = {
                "id": int(shot["id"]),
                "segment_id": seg_id,
                "title": str(shot.get("title") or f"Shot {shot['id']}"),
                "start_frame": start_f,
                "end_frame": end_f,
                "frames": end_f - start_f,
                "start_seconds": round(start_f / timeline["fps"], 3),
                "end_seconds": round(end_f / timeline["fps"], 3),
                "first_word": words[w_from]["word"] if w_from < len(words) else "",
                "last_word": words[min(w_to, len(words)) - 1]["word"] if words else "",
                "word_start_index": w_from,
                "word_end_index": min(w_to, len(words)),
                "spec": shot,
            }

    shots = [resolved[int(s["id"])] for s in sorted(shots_spec, key=lambda s: int(s["id"]))]
    shots.sort(key=lambda s: s["start_frame"])
    if shots[0]["start_frame"] != 0:
        raise ValueError("Der erste Shot beginnt nicht bei Frame 0")
    fps_value = float(timeline.get("fps", 24))
    for a, b in zip(shots, shots[1:]):
        if a["end_frame"] < b["start_frame"]:
            # Sprechpause zwischen zwei Segmenten: der laufende Shot haelt durch,
            # damit im Film keine schwarze Luecke entsteht.
            a["end_frame"] = b["start_frame"]
            a["frames"] = a["end_frame"] - a["start_frame"]
            a["end_seconds"] = round(a["end_frame"] / fps_value, 3)
            a["holds_through_pause"] = True
        elif a["end_frame"] > b["start_frame"]:
            raise ValueError(
                f"Shots {a['id']} und {b['id']} ueberlappen sich "
                f"({a['end_frame']} > {b['start_frame']})")
    if shots[-1]["end_frame"] < timeline["total_frames"]:
        shots[-1]["end_frame"] = int(timeline["total_frames"])
        shots[-1]["frames"] = shots[-1]["end_frame"] - shots[-1]["start_frame"]
        shots[-1]["end_seconds"] = round(shots[-1]["end_frame"] / fps_value, 3)
        shots[-1]["holds_to_end"] = True
    if shots[-1]["end_frame"] != timeline["total_frames"]:
        raise ValueError("Der letzte Shot endet nicht am Filmende")
    too_short = [s["id"] for s in shots if s["frames"] < min_frames]
    if too_short:
        raise ValueError(f"Shots kuerzer als {min_frames} Frames: {too_short}")
    return shots


def _word_index(words: list[dict], marker: str, occurrence: int = 0) -> int:
    target = clean_word(marker)
    seen = 0
    for i, w in enumerate(words):
        if clean_word(w["word"]) == target:
            if seen == occurrence:
                return i
            seen += 1
    raise ValueError(f"Wortmarke '{marker}' nicht im Segment gefunden")


def attach_shots(timeline: dict, shots: list[dict]) -> dict:
    """Schreibt die Shots in die Timeline (ohne das Spec-Dict zu duplizieren)."""
    timeline = dict(timeline)
    timeline["shots"] = [
        {k: v for k, v in shot.items() if k != "spec"} for shot in shots
    ]
    return timeline


# --------------------------------------------------------------------------- #
# Abfragen
# --------------------------------------------------------------------------- #
def find_word_frame(timeline: dict, segment_id: int, word: str,
                    occurrence: int = 0) -> int:
    """Startframe des n-ten Vorkommens von `word` im Segment."""
    segment = _segment_of(timeline, segment_id)
    idx = _word_index(segment["words"], word, occurrence)
    return int(segment["words"][idx]["start_frame"])


def frame_to_seconds(timeline: dict, frame: int) -> float:
    return round(int(frame) / timeline["fps"], 3)


def shot_at_frame(timeline: dict, frame: int) -> Optional[dict]:
    for shot in timeline.get("shots", []):
        if int(shot["start_frame"]) <= frame < int(shot["end_frame"]):
            return shot
    return None


def word_at_time(timeline: dict, seconds: float) -> Optional[dict]:
    for cue in timeline.get("word_cues", []):
        if cue["start_seconds"] <= seconds < cue["end_seconds"]:
            return cue
    return None


def timeline_stats(timeline: dict) -> dict:
    """Kurzstatistik fuer Logs, Job-Summary und Filmbericht."""
    segments = timeline["segments"]
    shots = timeline.get("shots", [])
    return {
        "fps": timeline["fps"],
        "resolution": f"{timeline['width']}x{timeline['height']}",
        "total_seconds": timeline["total_seconds"],
        "total_frames": timeline["total_frames"],
        "segments": len(segments),
        "shots": len(shots),
        "words": sum(len(s["words"]) for s in segments),
        "sentences": sum(len(s["sentences"]) for s in segments),
        "speakers": sorted({s["role"] for s in segments}),
        "min_segment_seconds": min(s["end_seconds"] - s["start_seconds"] for s in segments),
        "max_segment_seconds": max(s["end_seconds"] - s["start_seconds"] for s in segments),
    }


def validate_timeline(timeline: dict) -> list[str]:
    """Prueft eine bereits aufgeloeste Timeline auf innere Konsistenz."""
    errors: list[str] = []
    for key in ("fps", "width", "height", "segments", "total_frames", "word_cues"):
        if key not in timeline:
            errors.append(f"Timeline ohne '{key}'")
    if errors:
        return errors
    if timeline["fps"] != FPS_DEFAULT:
        errors.append(f"fps ist {timeline['fps']}, es muss 24 sein")
    if timeline["width"] * 16 != timeline["height"] * 9:
        errors.append("Timeline-Aufloesung ist nicht 9:16")
    if timeline["total_seconds"] < 20:
        errors.append("Film ist kuerzer als 20 s")
    if timeline["total_seconds"] > 180:
        errors.append("Film ist laenger als 180 s")
    prev_end = 0
    for seg in timeline["segments"]:
        if seg["start_frame"] < prev_end:
            errors.append(f"Segment {seg['segment_id']} ueberlappt das vorherige")
        prev_end = seg["end_frame"]
        if seg["end_frame"] - seg["start_frame"] < 6:
            errors.append(f"Segment {seg['segment_id']} ist kuerzer als 6 Frames")
        if not seg["words"]:
            errors.append(f"Segment {seg['segment_id']} hat keine Wort-Timestamps")
    frames = [c["start_frame"] for c in timeline["word_cues"]]
    if frames != sorted(frames):
        errors.append("Wort-Cues sind nicht chronologisch")
    return errors


# --------------------------------------------------------------------------- #
# Datei-Ein-/Ausgabe
# --------------------------------------------------------------------------- #
def write_timeline(timeline: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_timeline(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_timeline(data)
    if errors:
        raise ValueError("Ungueltige Timeline:\n- " + "\n- ".join(errors))
    return data


def count_speech_characters(text: str) -> int:
    """Zeichen, die ElevenLabs abrechnet (ohne reine Whitespace-Zeilen)."""
    return sum(len(line.strip()) for line in str(text).splitlines())


if __name__ == "__main__":  # pragma: no cover - kleines Werkzeug
    import argparse

    parser = argparse.ArgumentParser(description="Timeline pruefen/anzeigen")
    parser.add_argument("timeline", type=Path)
    args = parser.parse_args()
    data = load_timeline(args.timeline)
    stats = timeline_stats(data)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"Pause gesamt: {data['total_seconds'] - sum(s['end_seconds'] - s['start_seconds'] for s in data['segments']):.2f} s")
    print(f"Mathe-Check: {math.floor(data['total_frames'])} Frames = {data['total_frames'] / data['fps']:.2f} s")

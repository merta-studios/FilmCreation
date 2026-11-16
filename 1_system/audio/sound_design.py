"""Sound Design: Musik, Foley/Ambient-SFX, Auto-Ducking, LUFS-Mastering, TikTok-Untertitel.

Bausteine
---------
* :func:`generate_music` - lizenzfreie, prozedural komponierte Musik pro Stimmung
  (melancholisch, hoffnungsvoll, angespannt, regen, warm, traurig). Kein fremdes
  Material, keine Lizenzfragen, exakt so lang wie der Film.
* :func:`generate_procedural_sfx` - Foley und Atmosphaere (Regen, Wind, Schritte,
  Stadt, Uhr, Herzschlag, Tuer, Schulglocke, Rollstuhl, Donner, Voegel, Verkehr,
  Papier, Stift, Atem, Kinderlachen-Fern).
* :func:`mix_master_audio` - baut eine fertige Master-Spur: Sprache wortgenau an
  ihren Zeitpunkten, Musik mit Sidechain-Ducking unter der Stimme, SFX an ihren
  Cues, Loudness-Normalisierung auf -14 LUFS (TikTok/YouTube-Standard), Limiter.
* :func:`build_tiktok_subtitles` - wortgenaue `.ass`-Untertitel mit aktivem
  Wort-Highlight, 2-4 Woerter pro Einblendung, in der TikTok-Safe-Zone.
* :func:`build_sfx_events` - liest SFX + Trigger aus den Shots und legt sie auf
  die Timeline.

Alles laeuft ohne Blender. FFmpeg wird ueber :func:`ffmpeg_binary` gefunden
(ffmpeg im PATH oder das mitgelieferte ``imageio-ffmpeg``).
"""
from __future__ import annotations

import importlib
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

FPS = 24
TARGET_LUFS = -14.0
TRUE_PEAK = -1.5
SAFE_ZONE_BOTTOM_PX = 380
CAPTION_Y = 1920 - SAFE_ZONE_BOTTOM_PX

#: Musikstimmungen: Akkorde (MIDI-Noten), Tempo, Instrumentierung
MUSIC_MOODS: dict[str, dict] = {
    "melancholisch": dict(bpm=62, chords=[[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]],
                          pad_gain=0.30, arp_gain=0.16, bass_gain=0.22, brightness=0.4),
    "traurig": dict(bpm=54, chords=[[45, 48, 52], [41, 45, 48], [43, 47, 50], [40, 43, 47]],
                    pad_gain=0.34, arp_gain=0.10, bass_gain=0.20, brightness=0.3),
    "hoffnungsvoll": dict(bpm=76, chords=[[48, 52, 55], [53, 57, 60], [55, 59, 62], [48, 52, 55]],
                          pad_gain=0.26, arp_gain=0.22, bass_gain=0.18, brightness=0.75),
    "angspannt": dict(bpm=96, chords=[[50, 53, 57], [49, 52, 56], [46, 50, 53], [45, 48, 52]],
                      pad_gain=0.22, arp_gain=0.20, bass_gain=0.26, brightness=0.5),
    "angespannt": dict(bpm=96, chords=[[50, 53, 57], [49, 52, 56], [46, 50, 53], [45, 48, 52]],
                       pad_gain=0.22, arp_gain=0.20, bass_gain=0.26, brightness=0.5),
    "regen": dict(bpm=58, chords=[[52, 55, 59], [48, 52, 55], [50, 54, 57], [45, 48, 52]],
                  pad_gain=0.28, arp_gain=0.12, bass_gain=0.20, brightness=0.35),
    "warm": dict(bpm=70, chords=[[48, 52, 55], [50, 54, 57], [53, 57, 60], [48, 52, 55]],
                 pad_gain=0.30, arp_gain=0.18, bass_gain=0.20, brightness=0.65),
    "episch_leise": dict(bpm=66, chords=[[45, 52, 57], [43, 50, 55], [41, 48, 53], [43, 50, 55]],
                         pad_gain=0.32, arp_gain=0.18, bass_gain=0.24, brightness=0.6),
}

SFX_KINDS = (
    "rain", "wind", "steps", "clock_tick", "heartbeat", "city_ambience", "door_creak",
    "school_bell", "paper", "wheelchair", "thunder", "birds", "traffic", "breathing",
    "pen_scratch", "chalk", "crowd_distant", "church_bell", "window_rain", "bus_stop",
)


# --------------------------------------------------------------------------- #
# FFmpeg-Helfer
# --------------------------------------------------------------------------- #
def ffmpeg_binary() -> str:
    binary = shutil.which("ffmpeg")
    if binary:
        return binary
    try:
        module = importlib.import_module("imageio_ffmpeg")
        return module.get_ffmpeg_exe()
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FFmpeg fehlt: apt-get install ffmpeg oder pip install imageio-ffmpeg") from exc


def ffprobe_binary() -> Optional[str]:
    binary = shutil.which("ffprobe")
    if binary:
        return binary
    candidate = Path(ffmpeg_binary()).with_name("ffprobe")
    return str(candidate) if candidate.is_file() else None


def run_ffmpeg(args: Sequence[str], timeout: int = 900) -> None:
    command = [ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error", *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg fehlgeschlagen ({' '.join(args[:6])} ...):\n"
                           f"{result.stderr[-2500:]}")


def probe_duration(path: Path) -> float:
    binary = ffprobe_binary()
    if binary:
        result = subprocess.run([binary, "-v", "error", "-show_entries", "format=duration",
                                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                                capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0
    # Fallback: WAV-Header lesen
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except (wave.Error, OSError):
        return 0.0


def _write_wav(path: Path, samples: Sequence[float], rate: int = 32000,
               channels: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        if channels == 2:
            frames = bytearray()
            for value in samples:
                clipped = int(max(-1.0, min(1.0, value)) * 32767)
                data = struct.pack("<h", clipped)
                frames.extend(data)
                frames.extend(data)
            handle.writeframes(bytes(frames))
        else:
            handle.writeframes(b"".join(
                struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767)) for value in samples))
    return path


# --------------------------------------------------------------------------- #
# SFX
# --------------------------------------------------------------------------- #
def generate_procedural_sfx(kind: str, duration_seconds: float, output_path: Path,
                           sample_rate: int = 32000, seed: Optional[int] = None) -> Path:
    """Erzeugt ein lizenzfreies SFX/Ambient als WAV (mono)."""
    if kind not in SFX_KINDS:
        raise ValueError(f"Unbekannter SFX-Typ '{kind}'. Erlaubt: {', '.join(SFX_KINDS)}")
    if duration_seconds <= 0:
        raise ValueError("SFX-Dauer muss positiv sein")
    rng = random.Random(seed if seed is not None else abs(hash(kind)) % 100_000)
    n = int(duration_seconds * sample_rate)
    samples = [0.0] * n

    def add_noise(amplitude: float, lowpass: int = 8) -> None:
        buffer = [0.0] * lowpass
        index = 0
        for i in range(n):
            buffer[index] = rng.uniform(-1.0, 1.0)
            index = (index + 1) % lowpass
            samples[i] += (sum(buffer) / lowpass) * amplitude

    if kind in ("rain", "window_rain"):
        add_noise(0.42 if kind == "rain" else 0.22, 4)
        for i in range(n):
            t = i / sample_rate
            samples[i] += math.sin(2 * math.pi * 90 * t) * 0.02
            # einzelne Tropfen
            if kind == "window_rain" and rng.random() < 0.0009:
                length = int(0.04 * sample_rate)
                for j in range(min(length, n - i)):
                    samples[i + j] += math.sin(2 * math.pi * 1800 * j / sample_rate) * 0.12 * (1 - j / length)
    elif kind == "wind":
        for i in range(n):
            t = i / sample_rate
            base = 55 + 25 * math.sin(t * 0.4) + 12 * math.sin(t * 0.11)
            samples[i] = math.sin(2 * math.pi * base * t) * 0.18
        add_noise(0.10, 12)
    elif kind in ("steps", "wheelchair"):
        interval = 0.52 if kind == "steps" else 0.75
        for i in range(n):
            phase = (i / sample_rate) % interval
            if phase < 0.09:
                envelope = 1 - phase / 0.09
                frequency = 120 if kind == "steps" else 70
                samples[i] += math.sin(2 * math.pi * frequency * i / sample_rate) * 0.35 * envelope
                if kind == "wheelchair":
                    samples[i] += rng.uniform(-0.1, 0.1) * envelope
    elif kind == "clock_tick":
        for i in range(n):
            phase = (i / sample_rate) % 1.0
            if phase < 0.02:
                samples[i] = math.sin(2 * math.pi * 2400 * i / sample_rate) * 0.5 * (1 - phase / 0.02)
    elif kind == "heartbeat":
        beat = 0.88
        for i in range(n):
            phase = (i / sample_rate) % beat
            for start, strength in ((0.0, 1.0), (0.16, 0.65)):
                if start <= phase < start + 0.16:
                    envelope = math.sin((phase - start) / 0.16 * math.pi)
                    samples[i] += math.sin(2 * math.pi * 52 * i / sample_rate) * 0.55 * envelope * strength
    elif kind in ("city_ambience", "traffic", "crowd_distant"):
        add_noise(0.10, 16)
        for i in range(n):
            t = i / sample_rate
            hum = (math.sin(2 * math.pi * 52 * t) * 0.05
                   + math.sin(2 * math.pi * 78 * t) * 0.03)
            samples[i] += hum * (0.6 + 0.4 * math.sin(t * 0.7))
            if kind in ("traffic", "city_ambience") and rng.random() < 0.00002:
                length = int(0.7 * sample_rate)
                for j in range(min(length, n - i)):
                    envelope = math.sin(math.pi * j / length)
                    samples[i + j] += math.sin(2 * math.pi * (200 + 40 * math.sin(j * 0.001)) *
                                               j / sample_rate) * 0.09 * envelope
    elif kind == "door_creak":
        for i in range(min(n, int(0.9 * sample_rate))):
            t = i / sample_rate
            frequency = 220 + 180 * math.sin(t * 9) * math.exp(-t * 0.7)
            samples[i] = math.sin(2 * math.pi * frequency * t) * 0.22 * math.exp(-t * 1.2)
    elif kind in ("school_bell", "church_bell"):
        base = 880 if kind == "school_bell" else 220
        for i in range(n):
            t = i / sample_rate
            envelope = math.exp(-t * (2.2 if kind == "school_bell" else 0.8))
            samples[i] = (math.sin(2 * math.pi * base * t) * 0.30
                          + math.sin(2 * math.pi * base * 2.01 * t) * 0.18
                          + math.sin(2 * math.pi * base * 3.02 * t) * 0.10) * envelope
    elif kind == "paper":
        add_noise(0.16, 3)
        for i in range(n):
            t = i / sample_rate
            samples[i] *= max(0.0, 1 - t / max(0.1, duration_seconds))
    elif kind == "thunder":
        for i in range(n):
            t = i / sample_rate
            envelope = math.exp(-t * 1.1) * (1 - math.exp(-t * 12))
            samples[i] = (rng.uniform(-1, 1) * 0.45 + math.sin(2 * math.pi * 38 * t) * 0.3) * envelope
    elif kind == "birds":
        add_noise(0.02, 20)
        for _ in range(max(2, int(duration_seconds * 2))):
            start = rng.randint(0, max(1, n - sample_rate // 4))
            length = rng.randint(sample_rate // 12, sample_rate // 5)
            frequency = rng.uniform(1800, 3600)
            for j in range(length):
                if start + j >= n:
                    break
                envelope = math.sin(math.pi * j / length)
                samples[start + j] += math.sin(2 * math.pi * frequency * j / sample_rate) * 0.12 * envelope
    elif kind == "breathing":
        for i in range(n):
            t = i / sample_rate
            envelope = max(0.0, math.sin(t * 2 * math.pi / 4.0))
            samples[i] = rng.uniform(-1, 1) * 0.05 * envelope
    elif kind in ("pen_scratch", "chalk"):
        for i in range(n):
            t = i / sample_rate
            envelope = 0.5 + 0.5 * math.sin(t * 6)
            samples[i] = rng.uniform(-1, 1) * (0.06 if kind == "pen_scratch" else 0.09) * envelope
    else:  # bus_stop
        add_noise(0.08, 10)

    # sanftes Ein-/Ausblenden gegen Knackser
    fade = min(int(0.05 * sample_rate), n // 8)
    for i in range(fade):
        factor = i / max(1, fade)
        samples[i] *= factor
        samples[n - 1 - i] *= factor
    return _write_wav(Path(output_path), samples, sample_rate)


# --------------------------------------------------------------------------- #
# Musik
# --------------------------------------------------------------------------- #
def _midi_to_hz(note: float) -> float:
    return 440.0 * (2 ** ((note - 69) / 12.0))


def generate_music(mood: str, duration_seconds: float, output_path: Path,
                   sample_rate: int = 32000, seed: int = 4) -> Path:
    """Komponiert eine lizenzfreie Musikspur passend zur Stimmung."""
    key = (mood or "melancholisch").strip().lower()
    spec = MUSIC_MOODS.get(key) or MUSIC_MOODS["melancholisch"]
    duration_seconds = max(2.0, float(duration_seconds))
    bpm = spec["bpm"]
    beat = 60.0 / bpm
    bar = beat * 4
    n = int(duration_seconds * sample_rate)
    pad = [0.0] * n
    arp = [0.0] * n
    bass = [0.0] * n
    rng = random.Random(seed)
    chords = spec["chords"]
    bars = int(math.ceil(duration_seconds / bar))

    for bar_index in range(bars):
        chord = chords[bar_index % len(chords)]
        start = int(bar_index * bar * sample_rate)
        end = min(n, int((bar_index + 1) * bar * sample_rate))
        if start >= n:
            break
        # Pad: weiche, langsame Akkordflaeche mit Vibrato
        for note in chord:
            frequency = _midi_to_hz(note)
            phase = rng.random() * math.tau
            for i in range(start, end):
                t = (i - start) / sample_rate
                envelope = min(1.0, t / 0.9) * math.exp(-t * 0.22)
                vibrato = 1.0 + 0.0015 * math.sin(2 * math.pi * 0.7 * t)
                pad[i] += (math.sin(2 * math.pi * frequency * vibrato * t + phase) * 0.5
                           + math.sin(2 * math.pi * frequency * 2 * t + phase) * 0.12) * envelope
        # Bass: Grundton, leicht gepulst
        root = chord[0] - 12
        for i in range(start, end):
            t = (i - start) / sample_rate
            envelope = min(1.0, t / 0.25) * math.exp(-t * 0.5)
            bass[i] += math.sin(2 * math.pi * _midi_to_hz(root) * t) * envelope
        # Arpeggio: Achtelnoten, Stimmung bestimmt Helligkeit
        steps = 8
        for step in range(steps):
            note = chord[step % len(chord)] + (12 if spec["brightness"] > 0.6 and step % 4 == 3 else 0)
            step_start = start + int(step * (bar / steps) * sample_rate)
            length = int(min(bar / steps, 0.6) * sample_rate)
            for i in range(max(0, step_start), min(n, step_start + length)):
                t = (i - step_start) / sample_rate
                envelope = math.exp(-t * 3.2) * min(1.0, t / 0.02)
                arp[i] += math.sin(2 * math.pi * _midi_to_hz(note) * t) * envelope

    mix = [pad[i] * spec["pad_gain"] + arp[i] * spec["arp_gain"] * spec["brightness"]
           + bass[i] * spec["bass_gain"] for i in range(n)]
    # einfache Tiefpass-/Raumfahne
    smoothed = [0.0] * n
    previous = 0.0
    for i in range(n):
        previous = previous * 0.86 + mix[i] * 0.14
        smoothed[i] = previous
    for delay in (0.23, 0.37):
        offset = int(delay * sample_rate)
        for i in range(n - offset):
            smoothed[i + offset] += smoothed[i] * 0.18
    # Gesamtpegel vorsichtig anheben, harte Begrenzung
    peak = max(1e-6, max(abs(value) for value in smoothed))
    gain = 0.72 / peak
    fade_in = int(min(2.0, duration_seconds * 0.2) * sample_rate)
    fade_out = int(min(3.0, duration_seconds * 0.25) * sample_rate)
    for i in range(n):
        value = smoothed[i] * gain
        if i < fade_in:
            value *= i / max(1, fade_in)
        if i > n - fade_out:
            value *= max(0.0, (n - i) / max(1, fade_out))
        smoothed[i] = max(-1.0, min(1.0, value))
    return _write_wav(Path(output_path), smoothed, sample_rate)


# --------------------------------------------------------------------------- #
# Untertitel (ASS)
# --------------------------------------------------------------------------- #
def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def group_words_for_captions(words: list[dict], max_words: int = 3,
                             max_chars: int = 22,
                             max_gap: float = 0.55) -> list[list[dict]]:
    """Teilt Woerter in kurze TikTok-Untertitelgruppen (2-4 Woerter)."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if current:
            gap = word["start_seconds"] - current[-1]["end_seconds"]
            length = sum(len(w["word"]) + 1 for w in current) + len(word["word"])
            sentence_end = current[-1]["word"].rstrip().endswith((".", "!", "?", "\u2026"))
            if gap > max_gap or length > max_chars or sentence_end or len(current) >= max_words:
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


@dataclass
class SubtitleStyle:
    font: str = "Inter"
    font_size: int = 62
    primary: str = "FFFFFF"      # ASS ist BGR
    highlight: str = "00D7FF"    # warmes Gelb (#FFD700 als BGR)
    outline: str = "101010"
    outline_width: int = 5
    shadow: int = 2
    margin_v: int = SAFE_ZONE_BOTTOM_PX
    bold: int = -1
    alignment: int = 2


def build_tiktok_subtitles(timeline: dict, output_path: Path,
                           style: Optional[SubtitleStyle] = None,
                           width: Optional[int] = None,
                           height: Optional[int] = None) -> Path:
    """Erzeugt wortgenaue TikTok-Untertitel mit aktivem Wort-Highlight."""
    style = style or SubtitleStyle()
    width = int(width or timeline.get("width", 1080))
    height = int(height or timeline.get("height", 1920))
    if width * 16 != height * 9:
        raise ValueError("Untertitel brauchen ein 9:16-Format")
    words: list[dict] = list(timeline.get("word_cues") or [])
    if not words:
        for segment in timeline.get("segments", []):
            words.extend(segment.get("words", []))
    if not words:
        raise ValueError("Timeline enthaelt keine Wort-Timestamps - keine Untertitel moeglich")
    words = sorted(words, key=lambda w: w["start_seconds"])

    header = f"""[Script Info]
; Von 1_system/audio/sound_design.py erzeugt - wortgenaue TikTok-Untertitel
Title: {_ass_escape(str(timeline.get('film_title', 'Film')))}
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{style.font},{style.font_size},&H00{style.primary},&H00{style.highlight},&H00{style.outline},&H80000000,{style.bold},0,0,0,100,100,0.6,0,1,{style.outline_width},{style.shadow},{style.alignment},60,60,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    cursor = 0.0
    for group in group_words_for_captions(words):
        texts = [w["word"] for w in group]
        # Zeilenumbruch, wenn die Gruppe zu lang fuer eine Zeile ist
        if sum(len(t) + 1 for t in texts) > 18 and len(texts) > 2:
            split = (len(texts) + 1) // 2
            line_break_at = split
        else:
            line_break_at = None
        for index, active in enumerate(group):
            start = max(active["start_seconds"], cursor)
            end = group[index + 1]["start_seconds"] if index + 1 < len(group) else active["end_seconds"] + 0.10
            end = max(start + 0.06, min(end, active["end_seconds"] + 0.35))
            visible = []
            for j, word in enumerate(group):
                if line_break_at is not None and j == line_break_at:
                    visible.append("\\N")
                if j == index:
                    visible.append(f"{{\\c&H{style.highlight}&}}{_ass_escape(word['word'])}{{\\c&H{style.primary}&}}")
                else:
                    visible.append(_ass_escape(word["word"]))
            text = " ".join(part for part in visible if part != "\\N")
            text = text.replace(" \\N", "\\N")
            fade = f"{{\\fad(60,60)}}"
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,{style.margin_v},,"
                f"{fade}{text}\n")
            cursor = end
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# SFX-Events aus den Shots
# --------------------------------------------------------------------------- #
@dataclass
class SfxEvent:
    kind: str
    start_seconds: float
    duration: float
    gain_db: float = -14.0
    loop: bool = True
    source: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "start_seconds": round(self.start_seconds, 3),
                "duration": round(self.duration, 3), "gain_db": self.gain_db,
                "loop": self.loop, "source": self.source}


def build_sfx_events(timeline: dict, shots_spec: Sequence[dict],
                    config: Optional[dict] = None) -> list[SfxEvent]:
    """Liest ``sfx`` und Wort-Trigger aus den Shots und legt sie auf die Zeitachse."""
    config = config or {}
    default_gain = float(config.get("sfx_gain_db", -14.0))
    shots_in_timeline = {int(s["id"]): s for s in timeline.get("shots", [])}
    events: list[SfxEvent] = []
    for spec in sorted(shots_spec, key=lambda s: int(s["id"])):
        shot = shots_in_timeline.get(int(spec["id"]))
        if shot is None:
            continue
        start = float(shot["start_seconds"])
        frames = int(shot["frames"])
        length = frames / float(timeline.get("fps", FPS))
        for entry in spec.get("sfx") or []:
            if isinstance(entry, str):
                entry = {"kind": entry}
            kind = str(entry.get("kind", "")).strip()
            if not kind:
                continue
            relative_start = float(entry.get("at_seconds", 0.0))
            duration = float(entry.get("duration", max(0.4, length - relative_start)))
            events.append(SfxEvent(kind=kind, start_seconds=start + relative_start,
                                   duration=min(duration, max(0.2, length - relative_start)),
                                   gain_db=float(entry.get("gain_db", default_gain)),
                                   loop=bool(entry.get("loop", True)),
                                   source=f"shot:{spec['id']}"))
        for trigger in spec.get("triggers") or []:
            if str(trigger.get("action")) != "sfx":
                continue
            segment = next((s for s in timeline.get("segments", [])
                            if int(s["segment_id"]) == int(shot["segment_id"])), None)
            if segment is None:
                continue
            word = str(trigger.get("on_word", ""))
            from importlib import import_module

            timeline_sync = import_module("1_system.audio.timeline_sync")
            target = timeline_sync.clean_word(word)
            frame = None
            for index, cue in enumerate(segment.get("words", [])):
                if timeline_sync.clean_word(cue["word"]) == target:
                    frame = int(cue["start_frame"])
                    break
            if frame is None:
                continue
            events.append(SfxEvent(kind=str(trigger.get("value", "city_ambience")),
                                   start_seconds=frame / float(timeline.get("fps", FPS)),
                                   duration=float(trigger.get("duration", 1.2)),
                                   gain_db=float(trigger.get("gain_db", default_gain)),
                                   loop=False, source=f"trigger:{spec['id']}"))
    return events


# --------------------------------------------------------------------------- #
# Mastering
# --------------------------------------------------------------------------- #
def mix_master_audio(timeline: dict, output_path: Path, work_dir: Path,
                    music_mood: Optional[str] = None, music_gain_db: float = -20.0,
                    music_path: Optional[Path] = None,
                    sfx_events: Optional[Sequence[SfxEvent]] = None,
                    loudness_target: float = TARGET_LUFS,
                    auto_ducking: bool = True,
                    keep_stems: bool = False) -> dict:
    """Mischt Sprache + Musik + SFX zu einer fertigen Master-Spur (48 kHz stereo)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    total = float(timeline["total_seconds"])
    segments = [s for s in timeline.get("segments", []) if s.get("audio_path")]
    if not segments:
        raise ValueError("Keine Sprachdateien in der Timeline (audio_path fehlt)")
    inputs: list[str] = []
    filters: list[str] = []
    voice_labels: list[str] = []
    input_count = 0

    for index, segment in enumerate(segments):
        audio = Path(segment["audio_path"])
        if not audio.is_file():
            raise FileNotFoundError(f"Sprachdatei fehlt: {audio}")
        inputs.extend(["-i", str(audio)])
        input_count += 1
        delay_ms = int(round(float(segment["start_seconds"]) * 1000))
        filters.append(
            f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms},volume=1.0[v{index}]")
        voice_labels.append(f"[v{index}]")
    voice = (f"{''.join(voice_labels)}amix=inputs={len(voice_labels)}:"
             f"duration=longest:dropout_transition=0:normalize=0,"
             f"apad,atrim=duration={total:.3f},asetpts=PTS-STARTPTS[voice]")
    filters.append(voice)

    # Musik
    mood = music_mood or "melancholisch"
    if music_path is None:
        music_path = generate_music(mood, total + 1.0, work_dir / "musik.wav")
    music_path = Path(music_path)
    music_index = input_count
    inputs.extend(["-stream_loop", "-1", "-i", str(music_path)])
    input_count += 1
    filters.append(
        f"[{music_index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=duration={total:.3f},asetpts=PTS-STARTPTS,volume={music_gain_db}dB[mustrack]")
    if auto_ducking:
        filters.append("[voice]asplit=2[voice_mix][voice_sc]")
        filters.append("[mustrack][voice_sc]sidechaincompress=threshold=0.035:ratio=9:"
                       "attack=25:release=420:makeup=1[music_out]")
    else:
        filters.append("[voice]anull[voice_mix]")
        filters.append("[mustrack]anull[music_out]")

    # SFX
    sfx_inputs: list[int] = []
    for event in sfx_events or []:
        sfx_file = work_dir / "sfx" / f"{event.kind}_{event.start_seconds:.2f}.wav".replace(" ", "_")
        if not sfx_file.is_file():
            generate_procedural_sfx(event.kind, max(event.duration, 0.3), sfx_file)
        index = input_count
        inputs.extend(["-i", str(sfx_file)])
        input_count += 1
        delay_ms = int(round(event.start_seconds * 1000))
        filters.append(
            f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={event.gain_db}dB,atrim=duration={max(0.2, event.duration):.3f},"
            f"adelay={delay_ms}|{delay_ms}[s{index}]")
        sfx_inputs.append(index)

    mix_labels = "[voice_mix][music_out]" + "".join(f"[s{index}]" for index in sfx_inputs)
    mix_count = 2 + len(sfx_inputs)
    filters.append(f"{mix_labels}amix=inputs={mix_count}:duration=longest:"
                   f"dropout_transition=0:normalize=0,apad,atrim=duration={total:.3f}[mixed]")
    filters.append(f"[mixed]loudnorm=I={loudness_target}:TP={TRUE_PEAK}:LRA=11,"
                   "alimiter=limit=0.94,aresample=48000[master]")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([*inputs, "-filter_complex", ";".join(filters), "-map", "[master]",
                "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(output_path)],
               timeout=1800)
    return {
        "path": str(output_path),
        "duration": probe_duration(output_path),
        "music": str(music_path),
        "mood": mood,
        "music_gain_db": music_gain_db,
        "voice_segments": len(segments),
        "sfx_events": len(sfx_events or []),
        "loudness_target": loudness_target,
    }


def write_audio_report(report: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - kleines Werkzeug
    import argparse

    parser = argparse.ArgumentParser(description="SFX/Musik/Untertitel erzeugen")
    parser.add_argument("--sfx", nargs="*", default=None, help="z. B. rain wind clock_tick")
    parser.add_argument("--music", default=None, help=f"Stimmung: {', '.join(MUSIC_MOODS)}")
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--out", type=Path, default=Path("render_output/probe"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.sfx:
        for kind in args.sfx:
            path = generate_procedural_sfx(kind, args.duration, args.out / f"{kind}.wav")
            print(f"SFX {kind}: {path} ({probe_duration(path):.2f} s)")
    if args.music:
        path = generate_music(args.music, args.duration, args.out / f"musik_{args.music}.wav")
        print(f"Musik {args.music}: {path} ({probe_duration(path):.2f} s)")

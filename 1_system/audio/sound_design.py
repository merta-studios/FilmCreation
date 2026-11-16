"""Sound Design: Musik-Ducking, prozedurale SFX, LUFS-Normalisierung, TikTok-Untertitel (.ass)."""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

FPS = 24
SAFE_ZONE_BOTTOM_PX = 320  # TikTok-UI-Zone unten (Caption/Buttons) – Untertitel darueber


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Befehl fehlgeschlagen: {' '.join(cmd)}\n{r.stderr[:800]}")


def _ffprobe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def generate_procedural_sfx(kind: str, duration_seconds: float, output_path: Path,
                            sample_rate: int = 44100) -> Path:
    """Erzeugt lizenzfreie Ambient-/Foley-SFX prozedural als WAV (Regen, Wind, Schritte, Uhr, Herz)."""
    import random
    random.seed(42)
    n = int(duration_seconds * sample_rate)
    samples = [0.0] * n
    if kind == "rain":
        for i in range(n):
            samples[i] = (random.uniform(-1, 1) * 0.35
                          + math.sin(2 * math.pi * 120 * i / sample_rate) * 0.05)
    elif kind == "wind":
        for i in range(n):
            t = i / sample_rate
            samples[i] = math.sin(2 * math.pi * (80 + 40 * math.sin(t * 0.7)) * t) * 0.25
    elif kind == "steps":
        step_every = int(0.55 * sample_rate)
        for i in range(n):
            if (i % step_every) < int(0.08 * sample_rate):
                samples[i] = random.uniform(-0.6, 0.6) * (1 - (i % step_every) / (0.08 * sample_rate))
    elif kind == "clock_tick":
        for i in range(n):
            if (i % sample_rate) < int(0.03 * sample_rate):
                samples[i] = 0.7 * math.sin(2 * math.pi * 2000 * i / sample_rate)
    elif kind == "heartbeat":
        beat = int(0.9 * sample_rate)
        for i in range(n):
            phase = i % beat
            if phase < int(0.15 * sample_rate):
                samples[i] = 0.8 * math.sin(2 * math.pi * 55 * i / sample_rate)
    elif kind == "city_ambience":
        for i in range(n):
            t = i / sample_rate
            samples[i] = (math.sin(2 * math.pi * 50 * t) * 0.12
                          + random.uniform(-0.08, 0.08))
    else:
        raise ValueError(f"Unbekannter SFX-Typ: {kind}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = b"".join(int(max(-1.0, min(1.0, s)) * 32767).to_bytes(2, "little", signed=True)
                          for s in samples)
        wf.writeframes(frames)
    return output_path


def duck_music_under_voice(voice_path: Path, music_path: Path, output_path: Path,
                           duck_db: float = -12.0, music_volume: float = 0.35) -> Path:
    """Mischt Musik unter Sprache mit Sidechain-Ducking + LUFS-Normalisierung."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(voice_path), "-i", str(music_path),
          "-filter_complex",
          f"[0:a]asplit=2[voice][side];[1:a]volume={music_volume}[mus];"
          f"[mus][side]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=500[ducked];"
          f"[voice][ducked]amix=inputs=2:duration=longest:dropout_transition=0,"
          f"loudnorm=I=-14:TP=-1.5:LRA=11[a]",
          "-map", "[a]", "-c:a", "aac", "-b:a", "192k", str(output_path)])
    return output_path


def normalize_lufs(input_path: Path, output_path: Path, target_i: float = -14.0) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(input_path),
          "-af", f"loudnorm=I={target_i}:TP=-1.5:LRA=11",
          "-c:a", "aac", "-b:a", "192k", str(output_path)])
    return output_path


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_tiktok_subtitles(timeline: dict, output_path: Path,
                           words_per_line: int = 3, font_size: int = 84) -> Path:
    """Erzeugt wortgenaue TikTok-Untertitel (.ass) mit aktivem Wort-Highlight.

    - Kurze Wortgruppen (2-4 Woerter), aktive Woerter gelb hervorgehoben.
    - Platzierung oberhalb der unteren TikTok-UI-Zone (Safe-Zone).
    - Schalter subtitles: true/false entscheidet, ob die Datei eingebrannt wird.
    """
    cues = timeline.get("word_cues", [])
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for cue in cues:
        cur.append(cue)
        if len(cur) >= words_per_line:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: TikTok,Arial,{font_size},&H0000FFFF,&H00FFFFFF,&H00000000,"
        f"&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,{SAFE_ZONE_BOTTOM_PX},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    def safe(word):
        return str(word).replace(chr(92), '').replace('{', '(').replace('}', ')').replace('\n', ' ')
    for group in groups:
        # Each word has its own event: pauses are not incorrectly assigned to
        # neighbouring words as they would be with duration-only karaoke tags.
        for index, word in enumerate(group):
            start, end = float(word['start_seconds']), float(word['end_seconds'])
            if end <= start:
                continue
            parts = []
            for j, other in enumerate(group):
                colour = '&H00FFFF&' if index == j else '&HFFFFFF&'
                parts.append('{\\c' + colour + '}' + safe(other['word']))
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},TikTok,,0,0,0,,{' '.join(parts)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def burn_subtitles(video_path: Path, ass_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(video_path),
          "-vf", f"ass={ass_path}",
          "-c:v", "libx264", "-preset", "medium", "-crf", "18",
          "-c:a", "copy", str(output_path)])
    return output_path

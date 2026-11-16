"""Master-Audio bauen: Sprache + Musik + SFX + Untertitel aus der Timeline.

Das ist der Ton-Schritt zwischen Sprachaufnahme und Schnitt:

* liest ``timeline_resolved.json`` (Sprachdateien, Wortzeiten, Shots),
* erzeugt die SFX-Ereignisse aus den Shot-Definitionen (``sfx`` + Wort-Trigger),
* waehlt die Musikstimmung aus ``film_config.yaml``,
* mischt alles auf -14 LUFS und schreibt ``master_audio.wav``,
* baut bei ``subtitles: true`` gleich die TikTok-Untertitel (``captions.ass``).

Beispiel::

    python -m 1_system.tools.mix_audio \
        --timeline render_session/timeline_resolved.json \
        --out render_session/master_audio.wav
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

film_loader = importlib.import_module("1_system.tools.film_loader")
timeline_sync = importlib.import_module("1_system.audio.timeline_sync")
sound_design = importlib.import_module("1_system.audio.sound_design")
font_manager = importlib.import_module("1_system.tools.font_manager")


def _ass_color(value: str) -> str:
    """``#FFD700`` -> ``00D7FF`` (ASS nutzt BGR ohne Raute)."""
    text = str(value).strip().lstrip("#")
    if len(text) != 6:
        return "00D7FF"
    red, green, blue = text[0:2], text[2:4], text[4:6]
    return f"{blue}{green}{red}".upper()


def mix(film, timeline: dict, output: Path, work_dir: Path,
        subtitle_path: Optional[Path] = None, keep_stems: bool = False) -> dict:
    """Mischt die Tonspur und (optional) die Untertitel fuer den fertigen Film."""
    config = film.config or {}
    music = config.get("musik") or {}
    mood = str(music.get("mood") or "melancholisch")
    music_gain = float(music.get("gain_db", -20.0))
    auto_ducking = bool(music.get("auto_ducking", True))
    loudness_target = float(config.get("master_lufs", sound_design.TARGET_LUFS))
    sfx_gain = float(config.get("sfx_gain_db", -14.0))
    events = sound_design.build_sfx_events(timeline, film.shots, {"sfx_gain_db": sfx_gain})
    report = sound_design.mix_master_audio(
        timeline, output, work_dir, music_mood=mood, music_gain_db=music_gain,
        sfx_events=events, loudness_target=loudness_target,
        auto_ducking=auto_ducking, keep_stems=keep_stems)
    report["sfx_kinds"] = sorted({event.kind for event in events})
    report["music_mood"] = mood

    if subtitle_path is not None and film.subtitles:
        style_cfg = config.get("untertitel_stil") or {}
        safe_cfg = config.get("safe_zone") or {}
        font_key = str(style_cfg.get("font", "inter"))
        font_name = font_manager.font_family_for_ass(font_key, allow_download=True)
        style = sound_design.SubtitleStyle(
            font=font_name,
            font_size=int(style_cfg.get("size", 62)),
            highlight=_ass_color(style_cfg.get("highlight", "#FFD700")),
            margin_v=int(safe_cfg.get("bottom_px", sound_design.SAFE_ZONE_BOTTOM_PX)),
        )
        ass = sound_design.build_tiktok_subtitles(timeline, Path(subtitle_path),
                                                  style=style)
        report["subtitles"] = str(ass)
    return report


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sprache, Musik und SFX mischen")
    parser.add_argument("--film-dir", type=Path, default=film_loader.FILM_DIR_DEFAULT)
    parser.add_argument("--timeline", type=Path,
                        default=Path("render_session/timeline_resolved.json"))
    parser.add_argument("--out", type=Path, default=Path("render_session/master_audio.wav"))
    parser.add_argument("--work-dir", type=Path, default=Path("render_session/audio_work"))
    parser.add_argument("--captions", type=Path,
                        default=Path("render_session/captions.ass"))
    parser.add_argument("--report", type=Path,
                        default=Path("render_session/audio_report.json"))
    parser.add_argument("--keep-stems", action="store_true")
    args = parser.parse_args(argv)

    film = film_loader.load_film(args.film_dir)
    if not args.timeline.is_file():
        raise SystemExit(f"Timeline fehlt: {args.timeline} - zuerst "
                         "1_system/audio/generate_timeline.py laufen lassen")
    timeline = timeline_sync.load_timeline(args.timeline)
    report = mix(film, timeline, args.out, args.work_dir,
                 args.captions if film.subtitles else None, args.keep_stems)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"Master-Audio: {args.out} ({report['duration']:.2f} s, "
          f"{report['sfx_events']} SFX, Musik '{report['mood']}')")
    if report.get("subtitles"):
        print(f"Untertitel:   {report['subtitles']}")
    summary_path = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## Ton\n\n")
            stream.write(f"* Master: `{args.out.name}` - {report['duration']:.2f} s, "
                         f"{report['loudness_target']} LUFS\n")
            stream.write(f"* Musik: {report['mood']} ({report['music_gain_db']} dB)\n")
            stream.write(f"* SFX: {report['sfx_events']} Ereignisse "
                         f"({', '.join(report['sfx_kinds']) or 'keine'})\n")
            if report.get("subtitles"):
                stream.write(f"* Untertitel: `{Path(report['subtitles']).name}`\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

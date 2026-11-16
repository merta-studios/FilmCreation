"""Kompletter Filmlauf auf dem eigenen Rechner: Audio, Shots, Schnitt.

Voraussetzungen: ``bpy`` (Blender 4.2) importierbar und ``ffmpeg`` vorhanden
(imageio-ffmpeg genuegt). Ohne ``bpy`` bricht das Skript *vor* dem ersten
Credits-Verbrauch ab.

Beispiele::

    # schneller Testlauf, vier Shots, 540x960
    python -m 1_system.tools.render_local --quality preview --shots 1-4
    # vollstaendig, Audio aus einem frueheren Lauf weiterverwenden
    python -m 1_system.tools.render_local --reuse-audio
"""
from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

film_loader = importlib.import_module("1_system.tools.film_loader")
validate_film = importlib.import_module("1_system.tools.validate_film")
generate_timeline = importlib.import_module("1_system.audio.generate_timeline")
timeline_sync = importlib.import_module("1_system.audio.timeline_sync")
mix_audio = importlib.import_module("1_system.tools.mix_audio")
check_shots = importlib.import_module("1_system.tools.check_shots")
assemble_final = importlib.import_module("1_system.tools.assemble_final")

QUALITIES = {"preview", "high", "max"}


def _run(module: str, *args: str) -> None:
    command = [sys.executable, "-m", module, *args]
    print("$", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Film lokal rendern")
    parser.add_argument("--film-dir", type=Path, default=film_loader.FILM_DIR_DEFAULT)
    parser.add_argument("--out-dir", type=Path, default=Path("render_output"))
    parser.add_argument("--session-dir", type=Path, default=Path("render_session"))
    parser.add_argument("--shots", default="all", help="'all', '1,3' oder '2-5'")
    parser.add_argument("--quality", choices=sorted(QUALITIES), default="preview")
    parser.add_argument("--device", default="GPU", choices=("GPU", "CPU"))
    parser.add_argument("--reuse-audio", action="store_true",
                        help="vorhandene Timeline/Master-Audio nicht neu erzeugen")
    parser.add_argument("--skip-credit-check", action="store_true",
                        help="nur wenn bereits bezahltes Audio existiert")
    parser.add_argument("--no-subtitles", action="store_true",
                        help="Untertitel beim Schnitt ignorieren")
    args = parser.parse_args(argv)

    # 1. Ohne bpy gibt es keinen Render - also gar nicht erst Credits ausgeben.
    try:
        import bpy  # noqa: F401
    except ImportError:
        raise SystemExit("bpy fehlt. Blender 4.2 installieren (pip install bpy==4.2.0) "
                         "oder scene_builder ueber 'blender -b -P' starten. "
                         "Es wurden keine Credits verbraucht.")
    assemble_final.ffmpeg_binary()

    # 2. Vertrag pruefen.
    report = validate_film.validate_report(args.film_dir)
    for warning in report.warnings:
        print(f"HINWEIS: {warning}")
    if not report.ok:
        for error in report.errors:
            print(f"FEHLER: {error}", file=sys.stderr)
        return 1

    timeline_path = args.session_dir / "timeline_resolved.json"
    audio_path = args.session_dir / "master_audio.wav"
    captions_path = args.session_dir / "captions.ass"

    # 3. Sprache + Wortzeiten.
    if not (args.reuse_audio and timeline_path.is_file()):
        timeline = generate_timeline.generate(
            film_dir=args.film_dir, out_dir=args.session_dir,
            skip_credit_check=args.skip_credit_check)
    else:
        timeline = timeline_sync.load_timeline(timeline_path)
        print(f"Audio wiederverwendet: {timeline_path}")

    # 4. Musik, SFX, Untertitel.
    if not (args.reuse_audio and audio_path.is_file()):
        film = film_loader.load_film(args.film_dir)
        mix_audio.mix(film, timeline, audio_path, args.session_dir / "audio_work",
                      captions_path if film.subtitles else None)

    # 5. Shots rendern (wiederaufsetzbar, Manifest im Ausgabeordner).
    shots_dir = args.out_dir / "shots"
    _run("1_system.blender_engine.scene_builder",
         "--film-dir", str(args.film_dir),
         "--timeline", str(timeline_path),
         "--shots", args.shots,
         "--quality", args.quality,
         "--device", args.device,
         "--out-dir", str(shots_dir))

    # 6. Vollstaendigkeit pruefen, bevor geschnitten wird.
    manifest_path = shots_dir / "render_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = check_shots.check(timeline, manifest, shots_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        for problem in result["problems"]:
            print(f"FEHLER: {problem}", file=sys.stderr)
        print("Es wird nicht geschnitten, solange Shots fehlen.", file=sys.stderr)
        return 1

    # 7. Schnitt.
    film = film_loader.load_film(args.film_dir)
    subtitles = False if args.no_subtitles else bool(film.subtitles)
    final = args.out_dir / "final_film.mp4"
    info = assemble_final.assemble(
        timeline, manifest, audio_path, final,
        subtitles=subtitles, config=film.config,
        subtitles_path=captions_path if subtitles else None,
        storyboard=args.out_dir / "storyboard.png",
        report=args.out_dir / "film_info.md",
        shots_dir=shots_dir)
    print(f"Fertig: {final}")
    for key in ("duration", "frames", "size_bytes"):
        if key in info:
            print(f"  {key}: {info[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

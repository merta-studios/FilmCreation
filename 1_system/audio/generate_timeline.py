"""Sprachaufnahme + Timeline fuer den aktuellen Film (Schritt 1 der Pipeline).

Ablauf
------
1. Film laden (``2_aktueller_film/``) und Pflichtfelder pruefen.
2. Guthaben aller ElevenLabs-Keys pruefen - reicht es nicht, bricht alles ab,
   BEVOR Credits verbraucht werden.
3. Jedes Segment sprechen lassen (mit ``previous_text``/``next_text`` fuer
   natuerlichen Fluss), Audio speichern, Wort-Timestamps einsammeln.
4. Segmente, Pausen, Woerter und Shots zu ``timeline_resolved.json`` verrechnen.
5. Bericht schreiben (Zeichen, Guthaben, Sprecher, Shots, Dauer).

Der Exitcode ist 0 nur bei vollstaendigem Erfolg - die Workflows haengen daran.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

film_loader = importlib.import_module("1_system.tools.film_loader")
timeline_sync = importlib.import_module("1_system.audio.timeline_sync")
pool_module = importlib.import_module("1_system.audio.elevenlabs_pool")

CREDIT_BUFFER = 1.15          # 15 % Puffer auf die exakte Zeichenzahl
MAX_SEGMENT_CHARS = 2500      # ElevenLabs-Limit pro Request (multilingual v2)


class TimelineError(RuntimeError):
    """Fachlicher Fehler mit klarer Handlungsanweisung."""


def emotion_settings(emotion: Optional[str], base: dict) -> dict:
    """Passt Voice-Settings an die Emotion eines Segments an (dezent, nicht kitschig)."""
    settings = dict(base or {})
    mapping = {
        "fluestern": dict(stability=0.62, style=0.15, similarity_boost=0.75),
        "traurig": dict(stability=0.55, style=0.35),
        "zittern": dict(stability=0.42, style=0.45),
        "hoffnungsvoll": dict(stability=0.45, style=0.3),
        "ruhig": dict(stability=0.55, style=0.15),
        "kindlich": dict(stability=0.5, style=0.45),
        "streng": dict(stability=0.4, style=0.4),
        "sachlich": dict(stability=0.6, style=0.1),
    }
    settings.update(mapping.get(str(emotion or "").strip().lower(), {}))
    return settings


def validate_script(script: dict, voices: dict) -> list[dict]:
    """Prueft die Sprechdatei und gibt normalisierte Segmente zurueck."""
    raw_segments = script.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise TimelineError("script_and_voices.yaml: 'segments' fehlt oder ist leer")
    speaker_entries = {"haupt_erzaehler": (voices.get("haupt_erzaehler") or {})}
    for key, value in (voices.get("nebenstimmen") or {}).items():
        speaker_entries[str(key)] = value or {}
    segments: list[dict] = []
    seen_ids: set[int] = set()
    total_chars = 0
    for index, raw in enumerate(raw_segments, start=1):
        if not isinstance(raw, dict):
            raise TimelineError(f"Segment {index} ist kein Mapping")
        segment_id = int(raw.get("id", index))
        if segment_id in seen_ids:
            raise TimelineError(f"Segment-ID {segment_id} doppelt vergeben")
        seen_ids.add(segment_id)
        text = str(raw.get("text") or "").strip()
        if len(text) < 2:
            raise TimelineError(f"Segment {segment_id} hat keinen Sprechtext")
        if len(text) > MAX_SEGMENT_CHARS:
            raise TimelineError(f"Segment {segment_id} ist mit {len(text)} Zeichen zu lang "
                                f"(max. {MAX_SEGMENT_CHARS}). Bitte in kuerzere Segmente teilen.")
        speaker = str(raw.get("speaker") or "haupt_erzaehler")
        if speaker not in speaker_entries:
            raise TimelineError(
                f"Segment {segment_id}: Sprecher '{speaker}' fehlt in "
                f"3_regeln/empfohlene_elevenlabs_stimmen.yaml")
        voice = (speaker_entries[speaker] or {}).get("voice_id")
        if not voice:
            raise TimelineError(
                f"Sprecher '{speaker}' hat keine voice_id. Bitte in "
                f"3_regeln/empfohlene_elevenlabs_stimmen.yaml eintragen.")
        pause = float(raw.get("pause_after", 0.0) or 0.0)
        if pause < 0 or pause > 6:
            raise TimelineError(f"Segment {segment_id}: Pause {pause}s ist unplausibel (0-6 s)")
        settings = emotion_settings(raw.get("emotion"), (speaker_entries[speaker] or {}).get("settings") or {})
        segments.append({
            "segment_id": segment_id, "speaker": speaker, "text": text,
            "voice_id": str(voice), "pause_after": pause,
            "voice_settings": settings,
            "model_id": (speaker_entries[speaker] or {}).get("model_id"),
            "emotion": raw.get("emotion"),
        })
        total_chars += len(text)
    if len(segments) < 2:
        raise TimelineError("Ein Film braucht mindestens 2 Sprachsegmente")
    if total_chars < 140:
        raise TimelineError(f"Nur {total_chars} Zeichen - das ist zu kurz fuer 60-120 s")
    if total_chars > 3200:
        print(f"Warnung: {total_chars} Zeichen sind lang - pruefe die Filmlaenge "
              "(Ziel: 140-290 Woerter / 1.800-2.200 Zeichen).", file=sys.stderr)
    return segments


def synthesize(film, segments: list[dict], out_dir: Path,
               api_pool=None, skip_credit_check: bool = False) -> tuple[list[dict], dict]:
    """Spricht alle Segmente und liefert Timeline-Rohdaten + Bericht."""
    out_dir = Path(out_dir)
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    first_voice = segments[0]["voice_id"]
    api_pool = api_pool or pool_module.ElevenLabsPool(
        voice_settings={"stability": 0.45, "similarity_boost": 0.8, "style": 0.25,
                        "use_speaker_boost": True})
    if not api_pool.keys:
        raise TimelineError("Keine ElevenLabs-Keys gesetzt (ELEVENLABS_API_KEYS oder "
                            "ELEVENLABS_API_KEY_1..10)")
    total_chars = sum(len(s["text"]) for s in segments)
    needed = int(round(total_chars * CREDIT_BUFFER))

    credit_report = None
    if not skip_credit_check:
        credit_report = api_pool.check_credits(needed, first_voice)
        print(credit_report.summary())
        if not credit_report.ok:
            raise TimelineError(
                "Guthaben reicht nicht (oder Keys/Stimme fehlen). Start abgebrochen, "
                "BEVOR Credits verbraucht wurden.\n" + credit_report.summary())

    results: list[dict] = []
    started = time.time()
    for index, segment in enumerate(segments):
        previous_text = segments[index - 1]["text"] if index > 0 else ""
        next_text = segments[index + 1]["text"] if index + 1 < len(segments) else ""
        audio_path = audio_dir / f"seg_{segment['segment_id']:03d}.mp3"
        api_pool.model_id = segment.get("model_id") or api_pool.model_id
        synthesised = api_pool.synthesize_segment(
            segment["text"], segment["voice_id"], audio_path,
            previous_text=previous_text, next_text=next_text,
            voice_settings=segment["voice_settings"])
        duration = synthesised.duration_seconds
        if duration <= 0:
            raise TimelineError(f"Segment {segment['segment_id']}: Dauer 0 - Audio defekt")
        results.append({
            "segment_id": segment["segment_id"],
            "role": segment["speaker"],
            "text": segment["text"],
            "audio_path": str(audio_path),
            "voice_id": segment["voice_id"],
            "duration": duration,
            "alignment": synthesised.alignment,
            "pause_after": segment["pause_after"],
        })
        print(f"  Segment {segment['segment_id']:>2}: {duration:6.2f} s, "
              f"{len(segment['text'])} Zeichen -> {audio_path.name}")

    report = {
        "characters": total_chars,
        "credits_needed_with_buffer": needed,
        "credits": credit_report.to_dict() if credit_report else None,
        "segments": len(segments),
        "speakers": sorted({s["speaker"] for s in segments}),
        "synthesis_seconds": round(time.time() - started, 2),
        "remaining_keys": api_pool.remaining_snapshot(),
        "audio_files": [r["audio_path"] for r in results],
    }
    return results, report


def resolve(film, results: list[dict]) -> dict:
    """Baut die Timeline inkl. Shots (wortgenau, lueckenlos, 24 fps)."""
    timeline = timeline_sync.build_timeline(
        results, fps=24, width=1080, height=1920,
        pause_after={r["segment_id"]: r.get("pause_after", 0.0) for r in results},
        film_title=film.title)
    shots = timeline_sync.resolve_shots(timeline, film.shots)
    timeline = timeline_sync.attach_shots(timeline, shots)
    errors = timeline_sync.validate_timeline(timeline)
    if errors:
        raise TimelineError("Timeline ungueltig:\n- " + "\n- ".join(errors))
    return timeline


def write_film_info(film, timeline: dict, report: dict, path: Path) -> Path:
    stats = timeline_sync.timeline_stats(timeline)
    lines = [
        f"# {film.title}",
        "",
        f"* Format: **9:16** {stats['resolution']} @ {stats['fps']} fps",
        f"* Untertitel: **{'an' if film.subtitles else 'aus'}**",
        f"* Dauer: **{stats['total_seconds']:.1f} s** ({stats['total_frames']} Frames)",
        f"* Segmente: {stats['segments']} | Shots: {stats['shots']} | "
        f"Woerter: {stats['words']} | Saetze: {stats['sentences']}",
        f"* Sprecher: {', '.join(stats['speakers'])}",
        f"* Musik: {(film.config.get('musik') or {}).get('mood', 'melancholisch')}",
        "",
        "## Shots",
        "",
        "| Shot | Segment | Start | Dauer | Titel |",
        "|---|---|---|---|---|",
    ]
    for shot in timeline.get("shots", []):
        lines.append(f"| {shot['id']} | {shot['segment_id']} | "
                     f"{shot['start_seconds']:.2f} s | {shot['frames'] / 24:.2f} s | "
                     f"{shot.get('title', '')} |")
    lines += ["", "## Sprechtext", ""]
    for segment in timeline["segments"]:
        lines.append(f"**[{segment['role']}]** ({segment['start_seconds']:.2f}-"
                     f"{segment['end_seconds']:.2f} s): {segment['text']}")
        lines.append("")
    lines += ["## Kosten dieses Laufs", "",
              f"* Zeichen: {report['characters']} (Bedarf inkl. Puffer: "
              f"{report['credits_needed_with_buffer']})",
              f"* Sprachdateien: {len(report['audio_files'])}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def generate(film_dir: Path = film_loader.FILM_DIR_DEFAULT, out_dir: Path = Path("render_session"),
             pool=None, skip_credit_check: bool = False, dry_run: bool = False) -> dict:
    """Kompletter Schritt 1 (als Python-Funktion, damit Tests ihn aufrufen koennen)."""
    film = film_loader.load_film(film_dir)
    if film.subtitles is None:
        raise TimelineError("film_config.yaml: 'subtitles' muss ausdruecklich true oder false sein")
    if (film.width, film.height, film.fps) != (1080, 1920, 24):
        raise TimelineError(f"Format muss 1080x1920 @ 24 fps sein, ist "
                            f"{film.width}x{film.height} @ {film.fps}")
    segments = validate_script(film.script, film.voices)
    total_chars = sum(len(s["text"]) for s in segments)
    print(f"Film: {film.title} | {len(segments)} Segmente | {total_chars} Zeichen | "
          f"Untertitel: {'an' if film.subtitles else 'aus'}")
    if dry_run:
        return {"dry_run": True, "segments": len(segments), "characters": total_chars,
                "needed": int(round(total_chars * CREDIT_BUFFER))}
    results, report = synthesize(film, segments, out_dir, pool, skip_credit_check)
    timeline = resolve(film, results)
    timeline_path = timeline_sync.write_timeline(timeline, Path(out_dir) / "timeline_resolved.json")
    write_film_info(film, timeline, report, Path(out_dir) / "film_info.md")
    (Path(out_dir) / "speech_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = timeline_sync.timeline_stats(timeline)
    print(f"Timeline: {stats['shots']} Shots, {stats['total_seconds']:.2f} s, "
          f"{stats['total_frames']} Frames -> {timeline_path}")
    if not 60 <= stats["total_seconds"] <= 130:
        print(f"Warnung: Filmdauer {stats['total_seconds']:.1f} s liegt ausserhalb "
              "der Zielspanne 60-120 s.", file=sys.stderr)
    return {"timeline": timeline, "timeline_path": str(timeline_path), "stats": stats,
            "report": report, "film": film.title, "subtitles": film.subtitles}


def credits_only(film_dir: Path, out_json: Optional[Path] = None) -> int:
    """Prueft Guthaben und Stimme, ohne einen einzigen Credit zu verbrauchen."""
    film = film_loader.load_film(film_dir)
    segments = validate_script(film.script, film.voices)
    total = sum(len(segment["text"]) for segment in segments)
    needed = int(round(total * CREDIT_BUFFER))
    pool = pool_module.ElevenLabsPool()
    if not pool.keys:
        print("FEHLER: Keine ElevenLabs-Keys gesetzt (ELEVENLABS_API_KEYS oder "
              "ELEVENLABS_API_KEY_1..10).", file=sys.stderr)
        return 2
    report = pool.check_credits(needed, segments[0]["voice_id"])
    print(report.summary())
    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({"characters": total, "needed": needed,
                                        **report.to_dict()}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## Guthaben-Check\n\n")
            stream.write(report.summary_markdown() + "\n")
    return 0 if report.ok else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sprachaufnahme + Timeline erzeugen")
    parser.add_argument("--film-dir", type=Path, default=film_loader.FILM_DIR_DEFAULT)
    parser.add_argument("--out-dir", type=Path, default=Path("render_session"))
    parser.add_argument("--dry-run", action="store_true",
                        help="nur Zeichen zaehlen und pruefen, nichts sprechen")
    parser.add_argument("--credits-only", action="store_true",
                        help="nur Guthaben/Stimme pruefen (verbraucht keine Credits)")
    parser.add_argument("--json-out", type=Path, default=None,
                        help="Ergebnis zusaetzlich als JSON schreiben")
    parser.add_argument("--skip-credit-check", action="store_true")
    args = parser.parse_args(argv)
    if args.credits_only:
        try:
            return credits_only(args.film_dir, args.json_out)
        except (TimelineError, film_loader.FilmLoadError) as exc:
            print(f"FEHLER: {exc}", file=sys.stderr)
            return 2
    try:
        result = generate(args.film_dir, args.out_dir, None, args.skip_credit_check,
                          args.dry_run)
    except (TimelineError, film_loader.FilmLoadError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and not args.dry_run:
        stats = result["stats"]
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## Sprachaufnahme\n\n")
            stream.write(f"* Film: **{result['film']}**\n")
            stream.write(f"* Dauer: {stats['total_seconds']:.1f} s, {stats['shots']} Shots\n")
            stream.write(f"* Zeichen: {result['report']['characters']}\n")
            stream.write(f"* Untertitel: {'an' if result['subtitles'] else 'aus'}\n")
    payload = {k: v for k, v in result.items() if k not in ("timeline", "report")}
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate the supported declarative film subset without executing film Python."""
from __future__ import annotations
import argparse
import ast
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[2]
CAMERAS = {'crane_reveal', 'slow_push_in', 'pull_out', 'orbit_arc', 'tracking_follow', 'over_shoulder_drift', 'spline'}


def literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in statement.targets):
            return ast.literal_eval(statement.value)
    raise ValueError(f'{path.name}: {name} fehlt oder ist nicht deklarativ')


def validate_film(directory: Path) -> list[str]:
    errors = []
    try:
        cfg = yaml.safe_load((directory / 'film_config.yaml').read_text(encoding='utf-8'))
        script = yaml.safe_load((directory / 'script_and_voices.yaml').read_text(encoding='utf-8'))
        chars = literal_assignment(directory / 'characters.py', 'CHARACTERS')
        shots = literal_assignment(directory / 'shots.py', 'SHOTS')
        if not isinstance(cfg, dict) or not isinstance(script, dict) or not isinstance(chars, list) or not isinstance(shots, list):
            raise ValueError('Falsche Datenstruktur')
    except (OSError, ValueError, SyntaxError, yaml.YAMLError) as e:
        return [f'Filmdateien ungültig: {e}']
    if (cfg.get('width'), cfg.get('height'), cfg.get('fps')) != (1080, 1920, 24):
        errors.append('Format muss 1080×1920 bei 24 fps sein.')
    if type(cfg.get('subtitles')) is not bool:
        errors.append('subtitles muss explizit true oder false sein.')
    if len(chars) < 3 or sum(isinstance(c, dict) and c.get('role') == 'main' for c in chars) != 1 or sum(isinstance(c, dict) and c.get('role') == 'supporting' for c in chars) < 2:
        errors.append('Eine Hauptfigur und mindestens zwei Nebenfiguren erforderlich.')
    segments = script.get('segments')
    if not isinstance(segments, list) or not segments:
        errors.append('Sprechsegmente fehlen.')
        segments = []
    by_id = {}
    for segment in segments:
        if not isinstance(segment, dict) or type(segment.get('id')) is not int or not isinstance(segment.get('text'), str) or not segment['text'].strip():
            errors.append('Segment benötigt ganzzahlige id und nichtleeren Text.')
            continue
        if segment['id'] in by_id:
            errors.append(f'Doppelte Segment-ID {segment["id"]}.')
        by_id[segment['id']] = segment
    if not shots:
        errors.append('Shots fehlen.')
    seen = set()
    for shot in shots:
        if not isinstance(shot, dict):
            errors.append('Ungültiger Shot.')
            continue
        if shot.get('id') in seen or type(shot.get('id')) is not int:
            errors.append('Shot-IDs müssen eindeutig und ganzzahlig sein.')
        seen.add(shot.get('id'))
        if shot.get('camera') not in CAMERAS:
            errors.append(f'Shot {shot.get("id")}: Kamera ungültig oder statisch.')
        segment = by_id.get(shot.get('segment_id'))
        cue = shot.get('trigger_on_word')
        if not segment:
            errors.append(f'Shot {shot.get("id")}: Segment fehlt.')
        elif not isinstance(cue, str) or cue.casefold() not in [w.strip('.,!?;:„“"()').casefold() for w in segment['text'].split()]:
            errors.append(f'Shot {shot.get("id")}: Wort-Cue nicht im Segment.')
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--film-dir', type=Path, default=ROOT / '2_aktueller_film')
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args()
    errors = validate_film(args.film_dir)
    for error in errors:
        print('FEHLER:', error, file=sys.stderr)
    if errors:
        return 1
    print('Deklarative Grundprüfung bestanden; kein Nachweis für Renderfähigkeit, Geometrie oder Bildqualität.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

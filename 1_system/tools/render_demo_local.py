"""Run the current built-in demo locally with real ElevenLabs audio and Blender."""
from __future__ import annotations
import argparse
import importlib
import os
from pathlib import Path
import subprocess
import sys
import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('render_output'))
    parser.add_argument('--preview', action='store_true', help='540x960, 8 Samples (finales Master bleibt 1080x1920)')
    args = parser.parse_args()
    validator = importlib.import_module('1_system.tools.validate_film')
    errors = validator.validate_film(Path('2_aktueller_film'))
    if errors:
        raise ValueError('\n'.join(errors))
    # This builder implements only the 4 built-in demo shots, not arbitrary
    # films or Roblox assets. Refuse unsupported data instead of silently
    # rendering the wrong scene.
    shots = validator.literal_assignment(Path('2_aktueller_film/shots.py'), 'SHOTS')
    if [(s['id'], s['segment_id']) for s in shots] != [(1,1),(2,2),(3,3),(4,4)]:
        raise ValueError('Dieser lokale Renderer unterstützt nur die vier Demo-Shots 1–4.')
    cfg = yaml.safe_load(Path('2_aktueller_film/film_config.yaml').read_text(encoding='utf8'))
    script = yaml.safe_load(Path('2_aktueller_film/script_and_voices.yaml').read_text(encoding='utf8'))
    if [s['id'] for s in script['segments']] != [1,2,3,4]:
        raise ValueError('Der Demo-Renderer erwartet genau vier aufsteigende Segmente.')
    voices = yaml.safe_load(Path('3_regeln/empfohlene_elevenlabs_stimmen.yaml').read_text(encoding='utf8'))
    # Check dependencies before consuming paid TTS credits.
    try:
        subprocess.run([sys.executable, '-c', 'import bpy'], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        raise RuntimeError('Blender bpy konnte nicht geladen werden; keine Credits verbraucht.') from e
    assembler = importlib.import_module('1_system.tools.assemble_final')
    assembler.ffmpeg_binary()
    tl = importlib.import_module('1_system.audio.generate_timeline').generate(script, voices, args.output)
    outshots = args.output / 'shots'
    outshots.mkdir(parents=True, exist_ok=True)
    starts = [s['start_frame'] for s in tl['segments']] + [tl['total_frames']]
    paths = []
    for i, (start, end) in enumerate(zip(starts, starts[1:]), 1):
        output = outshots / f'shot_{i:03d}.mp4'
        frames = end-start
        if frames < 2:
            raise ValueError(f'Segment {i} ist zu kurz')
        subprocess.run([sys.executable, '-m', '1_system.blender_engine.scene_builder',
                        '--shot', str(i), '--frames', str(frames), '--output', str(output),
                        '--width', '540' if args.preview else '1080',
                        '--height', '960' if args.preview else '1920',
                        '--samples', '8' if args.preview else '64'], check=True)
        if not output.exists():
            raise RuntimeError(f'Blender hat den Shot nicht erzeugt: {output}')
        paths.append(output)
    audios = [args.output / 'audio' / f'seg_{i:03d}.mp3' for i in range(1,5)]
    assembler.assemble(tl, paths, audios, args.output/'final_film.mp4',
                       subtitles=cfg['subtitles'], storyboard=args.output/'storyboard.png')
    print('Fertig:', args.output/'final_film.mp4')

if __name__ == '__main__':
    main()

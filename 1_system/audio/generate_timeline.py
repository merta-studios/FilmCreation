"""Generate ElevenLabs audio and resolved timing for the current film."""
from __future__ import annotations
import argparse
import importlib
import json
import math
from pathlib import Path
import yaml

poolmod = importlib.import_module('1_system.audio.elevenlabs_pool')
timeline = importlib.import_module('1_system.audio.timeline_sync')


def generate(script, voice_config, output, pool=None):
    segments = script['segments']
    if not segments:
        raise ValueError('Keine Sprechsegmente')
    voice_id = voice_config.get('haupt_erzaehler', {}).get('voice_id')
    if not voice_id and any(not s.get('voice_id') for s in segments):
        raise ValueError('Voice-ID in 3_regeln/empfohlene_elevenlabs_stimmen.yaml eintragen')
    pool = pool or poolmod.ElevenLabsPool()
    needed = sum(len(s['text']) for s in segments)
    report = pool.check_credits(estimated_chars=needed)
    print(report.summary())
    if not report.ok:
        raise RuntimeError('Credits nicht ausreichend oder ein Key ungültig')
    output = Path(output)
    audio_dir = output / 'audio'
    audio_dir.mkdir(parents=True, exist_ok=True)
    results = []
    pauses = {}
    for i, segment in enumerate(segments):
        sid = int(segment['id'])
        path = audio_dir / f'seg_{sid:03d}.mp3'
        result = pool.synthesize_segment(segment['text'], segment.get('voice_id') or voice_id, path,
            previous_text=segments[i-1]['text'] if i else '',
            next_text=segments[i+1]['text'] if i+1 < len(segments) else '')
        if not result.audio_bytes or not result.alignment.get('characters') or result.duration_seconds <= 0:
            raise ValueError(f'Segment {sid}: leeres Audio oder Alignment')
        results.append({'segment_id': sid, 'role': segment.get('role', 'ERZAEHLER'),
                        'audio_path': str(path), 'alignment': result.alignment, 'duration': result.duration_seconds})
        pauses[sid] = float(segment.get('pause_after', 0))
    resolved = timeline.build_timeline(results, fps=24, pause_after=pauses)
    (output / 'timeline_resolved.json').write_text(json.dumps(resolved, ensure_ascii=False, indent=2), encoding='utf8')
    return resolved


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--script', type=Path, default=Path('2_aktueller_film/script_and_voices.yaml'))
    p.add_argument('--voices', type=Path, default=Path('3_regeln/empfohlene_elevenlabs_stimmen.yaml'))
    p.add_argument('--output', type=Path, default=Path('audio_output'))
    args = p.parse_args()
    generate(yaml.safe_load(args.script.read_text(encoding='utf8')), yaml.safe_load(args.voices.read_text(encoding='utf8')), args.output)

if __name__ == '__main__':
    main()

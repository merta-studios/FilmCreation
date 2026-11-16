import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

assemble = importlib.import_module('1_system.tools.assemble_final')
generate = importlib.import_module('1_system.audio.generate_timeline')


def test_audio_pipeline_checks_and_neighbours(tmp_path):
    class Pool:
        def __init__(self): self.calls = []
        def check_credits(self, estimated_chars):
            assert estimated_chars == 6
            return SimpleNamespace(ok=True, summary=lambda: 'ok')
        def synthesize_segment(self, text, voice, path, previous_text, next_text):
            self.calls.append((previous_text, next_text))
            path.write_bytes(b'audio')
            return SimpleNamespace(audio_bytes=b'audio', duration_seconds=.3, alignment={'characters': list(text), 'character_start_times_seconds':[0,.1,.2], 'character_end_times_seconds':[.1,.2,.3]})
    pool = Pool()
    tl = generate.generate({'segments': [{'id': 1, 'text': 'abc', 'pause_after': .2}, {'id': 2, 'text': 'def'}]}, {'haupt_erzaehler': {'voice_id': 'v'}}, tmp_path, pool)
    assert pool.calls == [('', 'def'), ('abc', '')]
    assert tl['segments'][1]['start_frame'] == 12
    assert json.loads((tmp_path / 'timeline_resolved.json').read_text()) == tl


def test_mastering_rejects_bad_inputs(tmp_path):
    with pytest.raises(ValueError):
        assemble.assemble({'fps':24, 'segments': [], 'total_frames':24}, [], [], tmp_path/'out.mp4')
    with pytest.raises(FileNotFoundError):
        assemble.assemble({'fps':24, 'segments': [{'start_frame': 0}], 'total_frames':24}, ['missing'], ['missing'], tmp_path/'out.mp4')


def test_real_ffmpeg_mastering(tmp_path):
    ffmpeg = assemble.ffmpeg_binary()
    clips, sounds = [], []
    for i in range(2):
        clip, audio = tmp_path/f'{i}.mp4', tmp_path/f'{i}.wav'
        assemble.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f','lavfi','-i',f'color=c={"red" if i == 0 else "blue"}:s=90x160:r=24:d=1', '-c:v','libx264','-pix_fmt','yuv420p',str(clip)])
        assemble.run([ffmpeg, '-y', '-hide_banner', '-loglevel', 'error', '-f','lavfi','-i','sine=frequency=440:duration=0.7',str(audio)])
        clips.append(clip); sounds.append(audio)
    tl = {'fps':24,'segments':[{'start_frame':0},{'start_frame':24}], 'total_frames':48,'word_cues':[]}
    tl['word_cues'] = [{'word': 'Hallo', 'start_seconds': 0.1, 'end_seconds': 0.5}]
    result = assemble.assemble(tl, clips, sounds, tmp_path/'final.mp4', width=90, height=160, storyboard=tmp_path/'board.png')
    subtitled = assemble.assemble(tl, clips, sounds, tmp_path/'subtitled.mp4', subtitles=True, width=90, height=160)
    assert subtitled.stat().st_size > 1000
    assert result.read_bytes() != subtitled.read_bytes()
    assert result.stat().st_size > 1000
    assert (tmp_path/'board.png').is_file()
    import subprocess
    raw = subprocess.check_output([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(result), '-map', '0:v:0', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    assert len(raw) == 48 * 90 * 160 * 3

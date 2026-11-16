import importlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

timeline = importlib.import_module('1_system.audio.timeline_sync')
sound = importlib.import_module('1_system.audio.sound_design')
validation = importlib.import_module('1_system.tools.validate_film')
parser = importlib.import_module('1_system.roblox_api.rbxm_parser')
pool = importlib.import_module('1_system.audio.elevenlabs_pool')


def alignment(text):
    return {'characters': list(text), 'character_start_times_seconds': [i / 10 for i in range(len(text))], 'character_end_times_seconds': [(i+1) / 10 for i in range(len(text))]}


def test_timeline_and_word_cues():
    t = timeline.build_timeline([{'segment_id': 1, 'alignment': alignment('Hallo Welt!'), 'duration': 1.1}, {'segment_id': 2, 'alignment': alignment('Ja.'), 'duration': .3}], fps=24, pause_after={1: .5})
    assert [w['word'] for w in t['word_cues']] == ['Hallo', 'Welt!', 'Ja.']
    assert timeline.find_word_by_text(t, 1, 'Welt') == 14
    assert t['segments'][1]['start_seconds'] == 1.6
    assert t['total_frames'] == 46


def test_timeline_rejects_bad_alignment():
    a = alignment('ab'); a['character_end_times_seconds'].pop()
    with pytest.raises(ValueError):
        timeline.build_timeline([{'segment_id': 1, 'alignment': a}])


def test_subtitles_and_sfx(tmp_path):
    t = timeline.build_timeline([{'segment_id': 1, 'alignment': alignment('Hallo Welt!'), 'duration': 1.1}])
    path = sound.build_tiktok_subtitles(t, tmp_path / 'x.ass')
    content = path.read_text()
    assert 'PlayResX: 1080' in content and 'PlayResY: 1920' in content
    assert 'Hallo' in content and '\\k' in content
    assert sound.generate_procedural_sfx('rain', .1, tmp_path / 'rain.wav').read_bytes()[:4] == b'RIFF'


def test_credit_report_fails_closed_and_no_double_count():
    a = pool.KeyStatus('abcd****yz', True, characters_remaining=100)
    b = pool.KeyStatus('efgh****yz', True, characters_remaining=100)
    report = pool.CreditReport([a, b], estimated_chars=150)
    assert report.total_remaining == 100 and not report.ok
    assert 'abcd****yz' in report.summary()
    assert not pool.CreditReport([a, pool.KeyStatus('bad****', False)], estimated_chars=10).ok


def test_keys_dedupe(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEYS', 'a,b\na')
    monkeypatch.setenv('ELEVENLABS_API_KEY_1', 'b')
    monkeypatch.setenv('ELEVENLABS_API_KEY_2', 'c')
    assert pool.collect_api_keys() == ['a', 'b', 'c']


def test_demo_validate_and_static_camera(tmp_path):
    import shutil
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / '2_aktueller_film', tmp_path / 'film')
    f = tmp_path / 'film'
    assert not validation.validate_film(f)
    p = f / 'shots.py'; p.write_text(p.read_text().replace('crane_reveal', 'static'))
    assert any('statisch' in s for s in validation.validate_film(f))


def test_rbxmx_and_reject_binary(tmp_path):
    p = tmp_path / 'x.rbxmx'
    p.write_text('''<roblox><Item class="Part"><Properties><string name="Name">Wall</string><Vector3 name="Size"><X>1</X><Y>2</Y><Z>3</Z></Vector3></Properties><Item class="Attachment"><Properties><string name="Name">HatAttachment</string></Properties></Item></Item></roblox>''')
    model = parser.RbxmParser().parse_file(p)
    assert model.parts[0].size == (1,2,3) and model.parts[0].attachments[0]['name'] == 'HatAttachment'
    p.write_bytes(b'<roblox!\x89\xff')
    with pytest.raises(NotImplementedError): parser.RbxmParser().parse_file(p)


def test_subscription_masks_secrets_and_formats_reset(monkeypatch):
    secret = 'sk_test_very_secret_value'
    monkeypatch.setattr(pool.requests, 'get', lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {'character_count': 4, 'character_limit': 50, 'next_character_count_reset_unix': 1735689600}))
    result = pool.ElevenLabsPool([secret]).check_credits(20)
    assert result.ok and result.total_remaining == 46
    assert '2025-01-01' in result.summary()
    assert secret not in result.summary()


def test_tts_rotates_on_limit(monkeypatch, tmp_path):
    import base64
    requests = []
    def post(url, headers, json, timeout):
        requests.append(headers['xi-api-key'])
        if headers['xi-api-key'] == 'first':
            return SimpleNamespace(status_code=429)
        return SimpleNamespace(status_code=200, json=lambda: {'audio_base64': base64.b64encode(b'audio').decode(), 'alignment': alignment('Hi')})
    monkeypatch.setattr(pool.requests, 'post', post)
    monkeypatch.setattr(pool.time, 'sleep', lambda _: None)
    result = pool.ElevenLabsPool(['first', 'second']).synthesize_segment('Hi', 'voice', tmp_path / 'x.mp3')
    assert requests == ['first', 'second'] and (tmp_path / 'x.mp3').read_bytes() == b'audio'
    assert result.duration_seconds == .2

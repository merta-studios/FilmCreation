"""Pipeline-Tests: Sprachsynthese -> Timeline -> Master-Audio -> fertiger Film."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

assemble = importlib.import_module("1_system.tools.assemble_final")
generate = importlib.import_module("1_system.audio.generate_timeline")
sound = importlib.import_module("1_system.audio.sound_design")
film_loader = importlib.import_module("1_system.tools.film_loader")
timeline_sync = importlib.import_module("1_system.audio.timeline_sync")


def slow_alignment(text: str, seconds_per_char: float = 0.055) -> dict:
    """Gleichmaessiges Alignment - so lang, dass die Timeline 60-120 s ergibt."""
    return {
        "characters": list(text),
        "character_start_times_seconds": [index * seconds_per_char for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) * seconds_per_char for index in range(len(text))],
    }


class FakePool:
    """Ersetzt ElevenLabsPool: schreibt Platzhalter-Audio und liefert Alignment."""

    def __init__(self):
        self.keys = ["fake-key"]
        self.model_id = "eleven_multilingual_v2"
        self.calls: list[tuple[str, str, str]] = []

    def check_credits(self, estimated_chars, required_voice_id=None):
        return SimpleNamespace(ok=True, summary=lambda: "ok", to_dict=lambda: {"ok": True})

    def synthesize_segment(self, text, voice_id, path, previous_text="", next_text="",
                           voice_settings=None, max_attempts=6):
        self.calls.append((previous_text, next_text, voice_id))
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-audio")
        alignment = slow_alignment(text)
        return SimpleNamespace(
            audio_bytes=b"fake-audio", alignment=alignment,
            duration_seconds=alignment["character_end_times_seconds"][-1],
            key_used="fake****ey", account="fake", characters=len(text))

    def remaining_snapshot(self):
        return {"fake****ey": 10_000}


def test_script_validation_synthesis_and_resolution(tmp_path):
    film = film_loader.load_film()
    voices = {"haupt_erzaehler": {"voice_id": "v-erzaehler", "settings": {}},
              "nebenstimmen": {}}
    for segment in film.script["segments"]:
        speaker = segment.get("speaker")
        if speaker and speaker != "haupt_erzaehler" and speaker not in voices["nebenstimmen"]:
            voices["nebenstimmen"][speaker] = {"voice_id": f"v-{speaker}", "settings": {}}

    segments = generate.validate_script(film.script, voices)
    assert len(segments) >= 3
    assert sum(len(segment["text"]) for segment in segments) >= 140

    pool = FakePool()
    results, report = generate.synthesize(film, segments, tmp_path, pool,
                                          skip_credit_check=True)
    assert len(results) == len(segments)
    assert report["characters"] == sum(len(segment["text"]) for segment in segments)
    # Nachbar-Kontext fuer ElevenLabs-Stabilitaet
    assert pool.calls[0][0] == "" and pool.calls[0][1] == segments[1]["text"]
    assert pool.calls[-1][2] == "" or pool.calls[-1][1] == ""

    resolved = generate.resolve(film, results)
    assert timeline_sync.validate_timeline(resolved) == []
    assert len(resolved["shots"]) == len(film.shots)
    assert resolved["width"] == 1080 and resolved["height"] == 1920
    assert 60 <= resolved["total_seconds"] <= 130
    # Wortgenaue Trigger: der erste Shot beginnt bei Frame 0
    assert resolved["shots"][0]["start_frame"] == 0
    assert resolved["shots"][-1]["end_frame"] == resolved["total_frames"]

    path = timeline_sync.write_timeline(resolved, tmp_path / "timeline_resolved.json")
    assert json.loads(path.read_text(encoding="utf-8"))["fps"] == 24


def test_sfx_events_follow_words(tmp_path):
    film = film_loader.load_film()
    voices = {"haupt_erzaehler": {"voice_id": "v"}, "nebenstimmen": {}}
    for segment in film.script["segments"]:
        speaker = segment.get("speaker")
        if speaker and speaker != "haupt_erzaehler":
            voices["nebenstimmen"].setdefault(speaker, {"voice_id": f"v-{speaker}"})
    segments = generate.validate_script(film.script, voices)
    results, _ = generate.synthesize(film, segments, tmp_path, FakePool(),
                                     skip_credit_check=True)
    resolved = generate.resolve(film, results)
    events = sound.build_sfx_events(resolved, film.shots, {"sfx_gain_db": -16})
    assert events, "der Demo-Film definiert SFX in den Shots"
    assert all(event.duration > 0 for event in events)
    assert all(0 <= event.start_seconds < resolved["total_seconds"] + 1 for event in events)


def test_mastering_rejects_bad_inputs(tmp_path):
    timeline = {"fps": 24, "segments": [], "total_frames": 24, "total_seconds": 1.0}
    with pytest.raises(ValueError):
        sound.mix_master_audio(timeline, tmp_path / "master.wav", tmp_path / "work")
    with pytest.raises(assemble.AssemblyError):
        assemble.collect_clips({"shots": []}, {**timeline, "width": 1080, "height": 1920})
    with pytest.raises(assemble.AssemblyError):
        assemble.assemble({**timeline, "width": 1080, "height": 1920}, {"shots": []},
                          tmp_path / "missing.wav", tmp_path / "out.mp4")


def test_music_and_sfx_generation(tmp_path):
    music = sound.generate_music("hoffnungsvoll", 2.0, tmp_path / "music.wav")
    assert music.is_file() and music.stat().st_size > 10_000
    sfx = sound.generate_procedural_sfx("door_creak", 0.4, tmp_path / "door.wav")
    assert sfx.is_file()
    assert sound.probe_duration(music) == pytest.approx(2.0, abs=0.2)


def test_real_ffmpeg_master_and_assembly(tmp_path):
    ffmpeg = assemble.ffmpeg_binary()
    # Zwei winzige Quell-Shots (2 s und 1 s) und eine Sprachspur
    clips = []
    for index, seconds in enumerate((2.0, 1.0)):
        clip = tmp_path / f"shot_{index}.mp4"
        assemble.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                      "-f", "lavfi", "-i",
                      f"color=c={'#334455' if index == 0 else '#664433'}:s=540x960:r=24:d={seconds}",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)])
        clips.append(clip)
    voice = tmp_path / "voice.wav"
    assemble.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                  "-i", "sine=frequency=300:duration=3", str(voice)])

    timeline = {
        "fps": 24, "width": 1080, "height": 1920, "total_frames": 72,
        "total_seconds": 3.0, "film_title": "Testfilm",
        "segments": [{"segment_id": 1, "start_seconds": 0.0, "start_frame": 0,
                      "end_frame": 72, "audio_path": str(voice), "words": []}],
        "word_cues": [{"word": "Hallo", "start_seconds": 0.1, "end_seconds": 0.5,
                       "start_frame": 2, "end_frame": 12}],
    }
    manifest = {"shots": [
        {"id": 1, "path": str(clips[0]), "start_frame": 0, "frames": 48},
        {"id": 2, "path": str(clips[1]), "start_frame": 48, "frames": 24},
    ]}
    collected = assemble.collect_clips(manifest, timeline)
    assert [clip.frames for clip in collected] == [48, 24]

    master = sound.mix_master_audio(timeline, tmp_path / "master.wav", tmp_path / "work",
                                    music_mood="hoffnungsvoll")
    audio = Path(master["path"])
    assert audio.is_file() and audio.stat().st_size > 10_000

    result = assemble.assemble(timeline, manifest, audio, tmp_path / "final.mp4",
                               subtitles=False, storyboard=tmp_path / "board.png",
                               report=tmp_path / "report.md")
    plain = Path(result["output"])
    assert plain.is_file() and plain.stat().st_size > 10_000
    assert Path(result["storyboard"]).is_file()
    assert Path(result["report"]).is_file()

    subtitled = Path(assemble.assemble(timeline, manifest, audio,
                                       tmp_path / "final_subs.mp4",
                                       subtitles=True)["output"])
    assert subtitled.is_file() and subtitled.stat().st_size > 10_000
    assert subtitled.read_bytes() != plain.read_bytes()

    info = subprocess.run([ffmpeg, "-hide_banner", "-i", str(plain)],
                          capture_output=True, text=True).stderr
    assert "1080x1920" in info and "24 fps" in info


def test_credit_check_without_configured_voices_does_not_claim_render_ready(monkeypatch, capsys):
    film = film_loader.load_film()
    film.voices.clear()
    monkeypatch.setattr(generate.film_loader, 'load_film', lambda _: film)
    checks = []

    class CreditPool:
        keys = ['fake']

        def check_credits(self, amount, voice):
            checks.append((amount, voice))
            return SimpleNamespace(ok=True, summary=lambda: 'Guthaben ok')

    monkeypatch.setattr(generate.pool_module, 'ElevenLabsPool', CreditPool)
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    assert generate.credits_only(Path('.')) == 1
    assert checks and checks[0][0] > 0 and checks[0][1] is None
    assert 'Stimmen nicht konfiguriert' in capsys.readouterr().err
    with pytest.raises(generate.TimelineError):
        generate.validate_script(film.script, film.voices)


def test_list_shots_without_audio_timeline(tmp_path, capsys):
    scene_builder = importlib.import_module('1_system.blender_engine.scene_builder')
    assert scene_builder.main(['--list-shots', '--timeline', str(tmp_path / 'missing.json')]) == 0
    assert 'Shot  1' in capsys.readouterr().out


def test_custom_model_passes_position_and_rotation_once():
    primitives = importlib.import_module('1_system.blender_engine.primitives_and_map')
    calls = []
    world = SimpleNamespace(custom_models={'tower': lambda world, **kw: calls.append(kw)})
    assert primitives.build_spec([{'type': 'custom_model', 'model': 'tower',
                                   'name': 'clock', 'pos': (1, 2, 3),
                                   'rotation': (0, 0, 1), 'params': {'height': 7}}], world) == ['clock']
    assert calls == [{'pos': (1, 2, 3), 'rotation': (0, 0, 1), 'height': 7}]

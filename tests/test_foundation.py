"""Grundlagen-Tests: Timeline, Untertitel, Guthaben, Validierung, RBXM."""
from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

timeline = importlib.import_module("1_system.audio.timeline_sync")
sound = importlib.import_module("1_system.audio.sound_design")
validation = importlib.import_module("1_system.tools.validate_film")
parser = importlib.import_module("1_system.roblox_api.rbxm_parser")
pool = importlib.import_module("1_system.audio.elevenlabs_pool")


def alignment(text: str) -> dict:
    return {
        "characters": list(text),
        "character_start_times_seconds": [index / 10 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) / 10 for index in range(len(text))],
    }


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #
def test_timeline_and_word_cues():
    built = timeline.build_timeline(
        [
            {"segment_id": 1, "alignment": alignment("Hallo Welt!"), "duration": 1.1},
            {"segment_id": 2, "alignment": alignment("Ja."), "duration": 0.3},
        ],
        fps=24, pause_after={1: 0.5},
    )
    assert [cue["word"] for cue in built["word_cues"]] == ["Hallo", "Welt!", "Ja."]
    welt = next(cue for cue in built["word_cues"] if cue["word"] == "Welt!")
    assert timeline.find_word_frame(built, 1, "Welt") == welt["start_frame"]
    assert welt["start_seconds"] == pytest.approx(0.6, abs=0.05)
    assert built["segments"][1]["start_seconds"] == pytest.approx(1.6)
    assert built["total_frames"] == 46
    assert built["words" if False else "total_words"] == 3
    stats = timeline.timeline_stats(built)
    assert stats["resolution"] == "1080x1920" and stats["segments"] == 2


def test_timeline_rejects_bad_alignment():
    broken = alignment("ab")
    broken["character_end_times_seconds"].pop()
    with pytest.raises(ValueError):
        timeline.build_timeline([{"segment_id": 1, "alignment": broken}])


def test_timeline_rejects_non_vertical_format():
    with pytest.raises(ValueError):
        timeline.build_timeline([{"segment_id": 1, "alignment": alignment("Hi")}],
                                width=1920, height=1080)


def test_subtitles_and_sfx(tmp_path):
    built = timeline.build_timeline(
        [{"segment_id": 1, "alignment": alignment("Hallo Welt!"), "duration": 1.1}])
    path = sound.build_tiktok_subtitles(built, tmp_path / "x.ass")
    content = path.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content and "PlayResY: 1920" in content
    assert "Hallo" in content and "Welt!" in content
    # Karaoke-Hervorhebung: aktuelles Wort in Gold
    assert "\\c&H00D7FF&" in content
    rain = sound.generate_procedural_sfx("rain", 0.1, tmp_path / "rain.wav")
    assert rain.read_bytes()[:4] == b"RIFF"


# --------------------------------------------------------------------------- #
# Guthaben
# --------------------------------------------------------------------------- #
def test_credit_report_sums_accounts_and_dedupes():
    same_account = [
        pool.KeyStatus("abcd****yz", True, account="A", characters_remaining=100),
        pool.KeyStatus("efgh****yz", True, account="A", characters_remaining=100),
    ]
    assert pool.CreditReport(same_account, estimated_chars=150).total_remaining == 100
    two_accounts = [
        pool.KeyStatus("abcd****yz", True, account="A", characters_remaining=100),
        pool.KeyStatus("ijkl****yz", True, account="B", characters_remaining=100),
    ]
    report = pool.CreditReport(two_accounts, estimated_chars=150)
    assert report.total_remaining == 200 and report.ok
    assert "abcd****yz" in report.summary()
    dead = pool.CreditReport([pool.KeyStatus("bad****", False, error="401")], 10)
    assert not dead.ok and "HARTER STOPP" in dead.summary()
    too_little = pool.CreditReport(two_accounts, estimated_chars=10_000)
    assert not too_little.ok


def test_keys_dedupe(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEYS", "a,b\na")
    monkeypatch.setenv("ELEVENLABS_API_KEY_1", "b")
    monkeypatch.setenv("ELEVENLABS_API_KEY_2", "c")
    assert pool.collect_api_keys() == ["a", "b", "c"]


class FakeSession:
    """Ersetzt requests.Session und protokolliert die verwendeten Keys."""

    def __init__(self, post_plan=None, subscription=None):
        self.used_keys: list[str] = []
        self.post_plan = post_plan or {}
        self.subscription = subscription or {
            "character_count": 4, "character_limit": 50,
            "next_character_count_reset_unix": 1735689600, "tier": "free"}

    def get(self, url, headers=None, timeout=None):
        return SimpleNamespace(status_code=200, json=lambda: dict(self.subscription), text="")

    def post(self, url, params=None, headers=None, json=None, timeout=None):
        key = (headers or {}).get("xi-api-key", "")
        self.used_keys.append(key)
        plan = self.post_plan.get(key)
        if plan is None:
            return SimpleNamespace(status_code=200, json=lambda: {}, text="")
        status, payload = plan
        return SimpleNamespace(status_code=status,
                               json=lambda: payload, text=str(payload)[:200])


def test_subscription_masks_secrets_and_formats_reset():
    secret = "sk_test_very_secret_value"
    client = pool.ElevenLabsPool([secret], session=FakeSession())
    report = client.check_credits(20)
    assert report.ok and report.total_remaining == 46
    assert "2025-01-01" in report.summary()
    assert secret not in report.summary()
    assert "****" in report.summary()


def test_tts_rotates_on_limit(tmp_path):
    import base64

    audio = b"a" * 4000
    payload = {"audio_base64": base64.b64encode(audio).decode(),
               "alignment": alignment("Hi")}
    session = FakeSession(post_plan={"first": (429, {"detail": {"status": "rate_limit_exceeded",
                                                               "message": "slow down"}}),
                                     "second": (200, payload)})
    client = pool.ElevenLabsPool(["first", "second"], session=session)
    result = client.synthesize_segment("Hi", "voice", tmp_path / "x.mp3")
    assert session.used_keys == ["first", "second"]
    assert (tmp_path / "x.mp3").read_bytes() == audio
    assert result.duration_seconds == pytest.approx(0.2)
    assert result.characters == 2 and result.word_count == 1


def test_tts_without_alignment_fails(tmp_path):
    session = FakeSession(post_plan={"k": (200, {"audio_base64": "QUJD",
                                                 "alignment": {}})})
    client = pool.ElevenLabsPool(["k"], session=session)
    with pytest.raises(pool.ElevenLabsError):
        client.synthesize_segment("Hi", "voice", tmp_path / "x.mp3")


# --------------------------------------------------------------------------- #
# Film-Validierung
# --------------------------------------------------------------------------- #
def test_demo_validates_and_rejects_static_camera(tmp_path):
    film_dir = tmp_path / "film"
    shutil.copytree(ROOT / "2_aktueller_film", film_dir)
    report = validation.validate_report(film_dir, allow_unconfigured=True)
    assert report.errors == [], report.errors
    assert report.info["Format"] == "1080x1920 @ 24 fps"
    shots_file = film_dir / "shots.py"
    shots_file.write_text(shots_file.read_text(encoding="utf-8").replace(
        "crane_reveal", "static"), encoding="utf-8")
    broken = validation.validate_report(film_dir, allow_unconfigured=True)
    assert any("statisch" in error for error in broken.errors)


def test_validation_needs_explicit_subtitles_flag(tmp_path):
    film_dir = tmp_path / "film"
    shutil.copytree(ROOT / "2_aktueller_film", film_dir)
    config = film_dir / "film_config.yaml"
    config.write_text(
        "\n".join(line for line in config.read_text(encoding="utf-8").splitlines()
                  if not line.strip().startswith("subtitles")),
        encoding="utf-8")
    report = validation.validate_report(film_dir, allow_unconfigured=True)
    assert any("subtitles" in error for error in report.errors)


# --------------------------------------------------------------------------- #
# RBXM
# --------------------------------------------------------------------------- #
def test_rbxmx_and_reject_binary(tmp_path):
    path = tmp_path / "x.rbxmx"
    path.write_text(
        '<roblox><Item class="Part"><Properties><string name="Name">Wall</string>'
        '<Vector3 name="size"><X>1</X><Y>2</Y><Z>3</Z></Vector3></Properties>'
        '<Item class="Attachment"><Properties><string name="Name">HatAttachment</string>'
        "</Properties></Item></Item></roblox>",
        encoding="utf-8")
    model = parser.RbxmParser().parse_file(path)
    assert tuple(model.parts[0].size) == (1, 2, 3)
    assert model.parts[0].attachments[0]["name"] == "HatAttachment"
    with pytest.raises(ValueError):
        parser.RbxmParser().parse_bytes(b"<roblox!\x89\xff\r\n\x1a\n")

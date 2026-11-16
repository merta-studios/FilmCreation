"""Tests fuer die Kaggle-Bruecke: CLI-Huelle, Dataset, Kernel-Template, Status."""
from __future__ import annotations

import importlib
import json
import os
import py_compile
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

client_mod = importlib.import_module("1_system.kaggle_bridge.kaggle_client")
dataset = importlib.import_module("1_system.kaggle_bridge.dataset_sync")
builder = importlib.import_module("1_system.kaggle_bridge.kernel_builder")
parallel = importlib.import_module("1_system.kaggle_bridge.parallel_render")


FAKE_CLI = """#!/usr/bin/env python3
import json, sys
from pathlib import Path
args = sys.argv[1:]
state_file = Path(__file__).with_name("state.json")
state = json.loads(state_file.read_text()) if state_file.is_file() else {"polls": 0}
if args[:2] == ["kernels", "status"]:
    state["polls"] = state.get("polls", 0) + 1
    state_file.write_text(json.dumps(state))
    status = "RUNNING" if state["polls"] < 2 else "COMPLETE"
    print(f'{args[2]} has status "KernelWorkerStatus.{status}"')
    sys.exit(0)
if args[:2] == ["kernels", "push"]:
    print("Kernel version 3 successfully pushed")
    sys.exit(0)
if args[:2] == ["kernels", "output"]:
    target = Path(args[args.index("-p") + 1])
    shots = target / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    (shots / "shot_001.mp4").write_bytes(b"0" * 200)
    (shots / "render_manifest.json").write_text(json.dumps(
        {"fps": 24, "width": 1080, "height": 1920, "film": "Test",
         "shots": [{"id": 1, "path": "/kaggle/working/shots/shot_001.mp4",
                    "start_frame": 0, "frames": 24}]}))
    sys.exit(0)
if args[:2] == ["datasets", "files"]:
    print("name size")
    sys.exit(0)
if args[:1] == ["quota"]:
    print("Your remaining GPU quota is 12.5 hours")
    sys.exit(0)
print("unknown command: " + " ".join(args))
sys.exit(1)
"""


@pytest.fixture()
def fake_cli(tmp_path):
    script = tmp_path / "kaggle"
    script.write_text(FAKE_CLI, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_status_parsing_and_wait(fake_cli, tmp_path):
    client = client_mod.KaggleClient(username="u", key="secret-key", cli=str(fake_cli),
                                     config_dir=tmp_path / "config")
    assert client.ensure_credentials().is_file()
    assert oct((tmp_path / "config" / "kaggle.json").stat().st_mode)[-3:] == "600"
    state = client.kernel_status("u/kernel")
    assert "RUNNING" in state.status and not state.finished
    final = client.wait_for_kernel("u/kernel", timeout_minutes=1, poll_seconds=0)
    assert final.ok and final.finished


def test_download_output(fake_cli, tmp_path):
    client = client_mod.KaggleClient(username="u", key="k", cli=str(fake_cli),
                                     config_dir=tmp_path / "config")
    target = client.download_output("u/kernel", tmp_path / "download")
    assert (target / "shots" / "shot_001.mp4").is_file()


def test_quota_parsing(fake_cli, tmp_path):
    client = client_mod.KaggleClient(username="u", key="k", cli=str(fake_cli),
                                     config_dir=tmp_path / "config")
    assert client.quota()["hours"] == pytest.approx(12.5)


def test_missing_credentials_is_explicit():
    client = client_mod.KaggleClient(username="", key="", cli="/nonexistent/kaggle")
    report = client.verify()
    assert report["auth_ok"] is False
    assert any("KAGGLE_USERNAME" in error for error in report["errors"])


def test_dataset_folder_and_slug(tmp_path):
    session = tmp_path / "session"
    (session / "audio").mkdir(parents=True)
    (session / "timeline_resolved.json").write_text('{"fps": 24}', encoding="utf-8")
    (session / "film_info.md").write_text("info", encoding="utf-8")
    (session / "audio" / "seg_001.mp3").write_bytes(b"audio")
    (session / "roblox_assets").mkdir()
    (session / "roblox_assets" / "mesh_123.mesh").write_bytes(b"mesh")
    slug = dataset.prepared_slug("Max-Mustermann", "12345")
    assert slug.startswith("max-mustermann/") and slug.endswith("-12345")
    assert dataset.dataset_slug("Max-Mustermann", "Render Session!!") == "max-mustermann/render-session"
    folder = dataset.build_dataset_folder(session, tmp_path / "ds", slug, include_audio=True)
    assert (folder / "dataset-metadata.json").is_file()
    assert (folder / "timeline_resolved.json").is_file()
    assert (folder / "audio" / "seg_001.mp3").is_file()
    assert (folder / "roblox_assets" / "mesh_123.mesh").is_file()
    staged = dataset.stage_session(folder, tmp_path / "staged")
    assert (staged / "timeline_resolved.json").is_file()


def test_dataset_without_timeline_fails(tmp_path):
    (tmp_path / "session").mkdir()
    with pytest.raises(FileNotFoundError):
        dataset.build_dataset_folder(tmp_path / "session", tmp_path / "ds", "u/x")


def test_kernel_build_compiles_and_metadata(tmp_path):
    folder = builder.build_kernel(
        tmp_path / "kernel", "someone/render-1",
        "https://github.com/merta-studios/FilmCreation.git", "deadbeef",
        "someone/session-1", shots="1-3", samples=48, quality="preview",
        callback={"repo": "merta-studios/FilmCreation", "workflow": "2-finish-film.yml",
                  "ref": "main", "token": "tok", "inputs": {}})
    py_compile.compile(str(folder / "main.py"), doraise=True,
                       cfile=str(tmp_path / "main.pyc"))
    source = (folder / "main.py").read_text(encoding="utf-8")
    assert "%%" not in source
    assert 'CUDA_VISIBLE_DEVICES' in source
    metadata = json.loads((folder / "kernel-metadata.json").read_text(encoding="utf-8"))
    assert metadata["machine_shape"] == "NvidiaTeslaT4"
    assert metadata["enable_gpu"] is True and metadata["enable_internet"] is True
    assert metadata["is_private"] is True
    assert metadata["dataset_sources"] == ["someone/session-1"]
    assert metadata["kernel_type"] == "script"
    assert "bpy==4.2.0" in source


def test_kernel_slug_sanitising():
    slug = builder.kernel_slug_for("Some-User", "gha 1234/5")
    assert slug.startswith("some-user/filmcreation-render-")
    assert slug == slug.lower()
    assert " " not in slug and "/" in slug


def test_merge_manifests(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    for folder, shot_id in ((first, 1), (second, 2)):
        folder.mkdir()
        (folder / f"shot_{shot_id:03d}.mp4").write_bytes(b"x" * 50)
        (folder / "render_manifest.json").write_text(json.dumps({
            "fps": 24, "width": 1080, "height": 1920,
            "shots": [{"id": shot_id, "path": str(folder / f"shot_{shot_id:03d}.mp4"),
                       "start_frame": 0, "frames": 24}]}), encoding="utf-8")
    merged = parallel.merge_manifests([first, second], tmp_path / "render_manifest.json")
    assert [shot["id"] for shot in merged["shots"]] == [1, 2]
    assert all(Path(shot["path"]).is_file() for shot in merged["shots"])
    flattened = parallel.flatten_shots(first, tmp_path / "flat")
    assert [path.name for path in flattened] == ["shot_001.mp4"]


def test_start_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv("KAGGLE_USERNAME", "tester")
    monkeypatch.setenv("KAGGLE_KEY", "key")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    session = tmp_path / "render_session"
    session.mkdir()
    (session / "timeline_resolved.json").write_text('{"fps": 24, "shots": []}', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    status = parallel.start(session, shots="all", out_dir=tmp_path / "out",
                            dry_run=True, publish=False)
    assert status["ok"] and status["dry_run"]
    assert (tmp_path / "out" / "kaggle_status.json").is_file()
    assert (tmp_path / "kaggle_kernel" / "main.py").is_file()


def test_start_without_username_reports_error(tmp_path, monkeypatch):
    monkeypatch.delenv("KAGGLE_USERNAME", raising=False)
    monkeypatch.delenv("KAGGLE_KEY", raising=False)
    session = tmp_path / "render_session"
    session.mkdir()
    (session / "timeline_resolved.json").write_text('{"fps": 24}', encoding="utf-8")
    status = parallel.start(session, out_dir=tmp_path / "out", dry_run=True)
    assert not status["ok"] and "KAGGLE_USERNAME" in status["error"]


def test_api_token_is_passed_as_token_not_written_as_legacy_key(tmp_path, monkeypatch):
    monkeypatch.setenv('KAGGLE_USERNAME', 'example')
    monkeypatch.setenv('KAGGLE_KEY', 'KGAT_fake_token')
    client = client_mod.KaggleClient(config_dir=tmp_path)
    assert client.ensure_credentials() is None
    assert not (tmp_path / 'kaggle.json').exists()
    env = client._env()
    assert env['KAGGLE_API_TOKEN'] == 'KGAT_fake_token'
    assert 'KAGGLE_USERNAME' not in env and 'KAGGLE_KEY' not in env


def test_kernel_never_serializes_callback_secret(tmp_path):
    marker = 'distinct-callback-secret-should-not-be-written'
    folder = builder.build_kernel(tmp_path / 'kernel', 'u/render',
                                  'https://github.com/a/b.git', 'abc', 'u/dataset',
                                  callback={'repo': 'a/b', 'token': marker})
    assert all(marker not in file.read_text() for file in folder.iterdir() if file.is_file())

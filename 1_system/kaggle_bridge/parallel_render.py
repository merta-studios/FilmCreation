"""Paralleler Render auf Kaggle: Dataset -> Kernel -> Status -> Shots zurueck.

Dieses Modul ist der einzige Einstiegspunkt fuer die Workflows. Es kapselt die
Reihenfolge, die Fallbacks und die Fehlertexte, damit ``1-start-render.yml`` und
``check-kaggle-fallback.yml`` nur noch zwei Befehle aufrufen muessen.

Typischer Lauf (GitHub Actions)::

    python -m 1_system.kaggle_bridge.parallel_render start \
        --session-dir render_session --shots all --samples 96

Danach liegen die Shots entweder lokal in ``render_output/shots`` (Direktrender
auf dem Runner, wenn Kaggle nicht verfuegbar ist) oder als Download aus dem
Kernel. Der Befehl schreibt immer ``render_output/kaggle_status.json``.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):  # pragma: no cover - direkter Aufruf
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from importlib import import_module  # noqa: E402

kaggle_client = import_module("1_system.kaggle_bridge.kaggle_client")
dataset_sync = import_module("1_system.kaggle_bridge.dataset_sync")
kernel_builder = import_module("1_system.kaggle_bridge.kernel_builder")

DEFAULT_REPO_URL = "https://github.com/merta-studios/FilmCreation.git"
STATUS_FILE = "kaggle_status.json"


def _log(message: str) -> None:
    print(f"[parallel] {message}", flush=True)


def write_status(path: Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def merge_manifests(shot_dirs: list[Path], target: Path) -> dict:
    """Fuehrt mehrere ``render_manifest.json`` zu einem Manifest zusammen."""
    entries: dict[int, dict] = {}
    meta = {"fps": 24, "width": 1080, "height": 1920, "film": ""}
    for directory in shot_dirs:
        for manifest in sorted(Path(directory).rglob("render_manifest*.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            meta["fps"] = data.get("fps", meta["fps"])
            meta["width"] = data.get("width", meta["width"])
            meta["height"] = data.get("height", meta["height"])
            meta["film"] = data.get("film") or meta["film"]
            for entry in data.get("shots", []):
                source = Path(entry.get("path", ""))
                if not source.is_absolute():
                    for candidate in (manifest.parent / source.name,
                                      Path(directory) / source.name,
                                      Path(directory) / "shots" / source.name):
                        if candidate.is_file():
                            source = candidate
                            break
                if not source.is_file():
                    continue
                entry = dict(entry)
                entry["path"] = str(source)
                entries[int(entry["id"])] = entry
    merged = {**meta, "shots": [entries[key] for key in sorted(entries)]}
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def flatten_shots(source_dir: Path, target_dir: Path) -> list[Path]:
    """Kopiert alle Shot-Dateien flach nach ``target_dir`` (Manifest-Pfade bleiben gueltig)."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for pattern in ("shot_*.mp4", "shot_*.png"):
        for file in sorted(Path(source_dir).rglob(pattern)):
            destination = target_dir / file.name
            if not destination.is_file() or destination.stat().st_size < file.stat().st_size:
                shutil.copy2(file, destination)
            copied.append(destination)
    return copied


def start(session_dir: Path = Path("render_session"), shots: str = "all",
          samples: int = 96, quality: str = "", workers: int = 2,
          out_dir: Path = Path("render_output"), kernel_slug: Optional[str] = None,
          repo_url: str = DEFAULT_REPO_URL, publish: bool = True,
          poll_seconds: int = 60, timeout_minutes: int = 320,
          callback_token: str = "", dry_run: bool = False) -> dict:
    """Kompletter Kaggle-Lauf. Gibt einen Status-Dict zurueck (auch bei Fehlern)."""
    client = kaggle_client.KaggleClient(dry_run=dry_run)
    run_id = os.environ.get("GITHUB_RUN_ID") or time.strftime("%Y%m%d%H%M%S")
    commit = os.environ.get("GITHUB_SHA", "")
    status: dict = {"ok": False, "run_id": run_id, "commit": commit,
                    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not client.username:
        status["error"] = "KAGGLE_USERNAME fehlt"
        write_status(Path(out_dir) / STATUS_FILE, status)
        return status

    try:
        dataset_slug = dataset_sync.prepared_slug(client.username, run_id)
        folder = dataset_sync.build_dataset_folder(session_dir, Path("kaggle_session"),
                                                   dataset_slug)
        status["dataset"] = dataset_slug
        if publish:
            verified = client.ensure_credentials() if not dry_run else None
            dataset_slug = dataset_sync.publish(client, folder, f"Session {run_id}")
            status["dataset_published"] = True
            if verified:
                status["kaggle_config"] = str(verified)
        _log(f"Dataset: {dataset_slug}")

        slug = kernel_slug or kernel_builder.kernel_slug_for(client.username, run_id)
        kernel_dir = kernel_builder.build_kernel(
            Path("kaggle_kernel"), slug, repo_url, commit, dataset_slug,
            shots=shots, samples=samples, quality=quality, workers=workers,
            username=client.username)
        status["kernel"] = slug
        status["kernel_dir"] = str(kernel_dir)
        if dry_run:
            status.update({"ok": True, "dry_run": True})
            write_status(Path(out_dir) / STATUS_FILE, status)
            return status

        published = client.push_kernel(kernel_dir)
        status["kernel_pushed"] = published
        _log(f"Kernel gestartet: {published}")

        state = client.wait_for_kernel(slug, timeout_minutes=timeout_minutes,
                                       poll_seconds=poll_seconds,
                                       on_poll=lambda s: _log(f"{slug}: {s.status}"))
        status["kernel_status"] = state.status
        if not state.ok:
            status["error"] = f"Kernel-Status {state.status}"
            write_status(Path(out_dir) / STATUS_FILE, status)
            return status

        download_dir = Path(out_dir) / "kaggle_output"
        if download_dir.exists():
            shutil.rmtree(download_dir)
        client.download_output(slug, download_dir)
        shots_dir = Path(out_dir) / "shots"
        copied = flatten_shots(download_dir, shots_dir)
        merged = merge_manifests([download_dir, shots_dir],
                                 Path(out_dir) / "render_manifest.json")
        status.update({
            "ok": bool(copied),
            "shots_downloaded": len(copied),
            "shots_manifest": len(merged.get("shots", [])),
            "output_dir": str(shots_dir),
        })
        if not copied:
            status["error"] = "Download enthielt keine Shot-Dateien"
        _log(f"{len(copied)} Shots heruntergeladen -> {shots_dir}")
    except (kaggle_client.KaggleError, FileNotFoundError, ValueError) as exc:
        status["error"] = str(exc)
        hint = getattr(exc, "hint", "")
        if hint:
            status["hint"] = hint
        _log(f"Fehler: {exc}")
        if hint:
            _log(f"Hinweis: {hint}")
    status["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_status(Path(out_dir) / STATUS_FILE, status)
    return status


def download(kernel_slug: str, out_dir: Path = Path("render_output")) -> dict:
    """Nur die Ergebnisse eines fertigen Kernels holen (fuer Workflow 2)."""
    client = kaggle_client.KaggleClient()
    out_dir = Path(out_dir)
    download_dir = out_dir / "kaggle_output"
    if download_dir.exists():
        shutil.rmtree(download_dir)
    try:
        client.download_output(kernel_slug, download_dir)
    except kaggle_client.KaggleError as exc:
        return {"ok": False, "kernel": kernel_slug, "error": str(exc),
                "hint": getattr(exc, "hint", "")}
    shots_dir = out_dir / "shots"
    copied = flatten_shots(download_dir, shots_dir)
    merged = merge_manifests([download_dir, shots_dir], out_dir / "render_manifest.json")
    return {"ok": bool(copied), "kernel": kernel_slug, "shots_downloaded": len(copied),
            "shots_manifest": len(merged.get("shots", [])), "output_dir": str(shots_dir)}


def check(kernel_slug: str, out_dir: Path = Path("render_output")) -> dict:
    """Nur Status abfragen (fuer den 15-Minuten-Cron)."""
    client = kaggle_client.KaggleClient()
    try:
        state = client.kernel_status(kernel_slug)
    except kaggle_client.KaggleError as exc:
        return {"ok": False, "kernel": kernel_slug, "error": str(exc),
                "hint": getattr(exc, "hint", "")}
    return {"ok": state.ok, "kernel": kernel_slug, "status": state.status,
            "finished": state.finished}


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Kaggle-Render starten oder pruefen")
    sub = parser.add_subparsers(dest="command", required=True)

    start_parser = sub.add_parser("start", help="Dataset + Kernel starten und Shots holen")
    start_parser.add_argument("--session-dir", type=Path, default=Path("render_session"))
    start_parser.add_argument("--out-dir", type=Path, default=Path("render_output"))
    start_parser.add_argument("--shots", default="all")
    start_parser.add_argument("--samples", type=int, default=96)
    start_parser.add_argument("--quality", default="")
    start_parser.add_argument("--workers", type=int, default=2)
    start_parser.add_argument("--kernel-slug", default=None)
    start_parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    start_parser.add_argument("--no-publish", action="store_true")
    start_parser.add_argument("--poll-seconds", type=int, default=60)
    start_parser.add_argument("--timeout-minutes", type=int, default=320)
    start_parser.add_argument("--callback-token", default="", help="veraltet; wird nicht an Kaggle uebertragen")
    start_parser.add_argument("--dry-run", action="store_true")

    check_parser = sub.add_parser("check", help="Status eines Kernels abfragen")
    check_parser.add_argument("--kernel", required=True)
    check_parser.add_argument("--out-dir", type=Path, default=Path("render_output"))

    download_parser = sub.add_parser("download", help="Shots eines Kernels herunterladen")
    download_parser.add_argument("--kernel", required=True)
    download_parser.add_argument("--out-dir", type=Path, default=Path("render_output"))

    args = parser.parse_args(argv)
    if args.command == "start":
        status = start(args.session_dir, args.shots, args.samples, args.quality,
                       args.workers, args.out_dir, args.kernel_slug, args.repo_url,
                       not args.no_publish, args.poll_seconds, args.timeout_minutes,
                       args.callback_token, args.dry_run)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status.get("ok") else 1
    if args.command == "download":
        status = download(args.kernel, args.out_dir)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status.get("ok") else 1
    status = check(args.kernel, args.out_dir)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

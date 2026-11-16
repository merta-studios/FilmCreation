"""Render-Session als Kaggle-Dataset bereitstellen (Transport GitHub -> Kaggle).

Der GitHub-Runner erzeugt in Schritt 1 die Timeline (``timeline_resolved.json``)
und die Sprachdateien. Kaggle-Kernel haben keinen Zugriff auf GitHub-Artefakte,
darum wird die Session als **privates Kaggle-Dataset** veroeffentlicht und im
Kernel unter ``/kaggle/input/<slug>/`` gemountet.

Ablauf
------
1. :func:`build_dataset_folder` kopiert Timeline, Film-Info und optional Audio in
   einen Ordner mit ``dataset-metadata.json``.
2. :func:`publish` legt das Dataset an (oder erzeugt eine neue Version).
3. Im Kernel kopiert :func:`stage_session` die Dateien in den Arbeitsordner.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):  # pragma: no cover - direkter Aufruf
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from importlib import import_module  # noqa: E402

kaggle_client = import_module("1_system.kaggle_bridge.kaggle_client")

#: Dateien, die der Kernel wirklich braucht
SESSION_FILES = ("timeline_resolved.json", "film_info.md", "speech_report.json")
#: Zusaetzlich mitgenommene Ordner (Audio ist fuer den Schnitt relevant)
SESSION_DIRS = ("audio", "roblox_assets")


def dataset_slug(username: str, base: str = "filmcreation-session") -> str:
    """Bildet aus Benutzername und Basis einen gueltigen Kaggle-Slug."""
    cleaned = "".join(character if character.isalnum() or character in "-_" else "-"
                      for character in base.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return f"{username.strip().lower()}/{cleaned.strip('-')[:40] or 'session'}"


def build_dataset_folder(session_dir: Path, target_dir: Path, slug: str,
                         title: str = "FilmCreation Render-Session",
                         include_audio: bool = False) -> Path:
    """Legt den Dataset-Ordner an, den ``kaggle datasets create`` hochlaedt."""
    session_dir = Path(session_dir)
    target_dir = Path(target_dir)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    copied: list[str] = []
    for name in SESSION_FILES:
        source = session_dir / name
        if source.is_file():
            shutil.copy2(source, target_dir / name)
            copied.append(name)
    if "timeline_resolved.json" not in copied:
        raise FileNotFoundError(
            f"{session_dir}/timeline_resolved.json fehlt - zuerst "
            "1_system/audio/generate_timeline.py laufen lassen")
    for name in SESSION_DIRS:
        if name == "audio" and not include_audio:
            continue
        source = session_dir / name
        if source.is_dir():
            shutil.copytree(source, target_dir / name)
            copied.append(name)
    metadata = {
        "title": title[:50],
        "id": slug,
        "licenses": [{"name": "CC0-1.0"}],
        "description": ("Render-Session (Timeline, Film-Info, optional Audio) fuer "
                        "den FilmCreation-Kernel. Wird automatisch erzeugt."),
    }
    (target_dir / "dataset-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_dir


def publish(client: "kaggle_client.KaggleClient", folder: Path,
            message: str = "FilmCreation Update") -> str:
    """Legt das Dataset an oder versioniert es; gibt den Slug zurueck."""
    folder = Path(folder)
    slug = json.loads((folder / "dataset-metadata.json").read_text(encoding="utf-8"))["id"]
    if client.dataset_exists(slug):
        client.version_dataset(folder, message)
    else:
        client.create_dataset(folder)
    return slug


def stage_session(input_root: Path, target_dir: Path) -> Path:
    """Kopiert ein gemountetes Dataset in den Arbeitsordner (Kernel-Seite)."""
    input_root = Path(input_root)
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not input_root.is_dir():
        raise FileNotFoundError(f"Dataset-Mount fehlt: {input_root}")
    for entry in input_root.iterdir():
        if entry.name == "dataset-metadata.json":
            continue
        destination = target_dir / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination)
    if not (target_dir / "timeline_resolved.json").is_file():
        raise FileNotFoundError(
            "Im Dataset fehlt timeline_resolved.json - Dataset neu veroeffentlichen")
    return target_dir


def prepared_slug(username: str, run_id: Optional[str] = None,
                  base: str = "filmcreation-session") -> str:
    """Slug mit optionaler Run-ID, damit parallele Laeufe sich nicht ueberschreiben."""
    suffix = f"-{str(run_id).strip()}" if run_id else ""
    return dataset_slug(username, base + suffix)


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Render-Session als Kaggle-Dataset")
    parser.add_argument("--session-dir", type=Path, default=Path("render_session"))
    parser.add_argument("--out-dir", type=Path, default=Path("kaggle_session"))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--include-audio", action="store_true")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    client = kaggle_client.KaggleClient()
    if not client.username:
        raise SystemExit("KAGGLE_USERNAME fehlt")
    slug = prepared_slug(client.username, args.run_id)
    folder = build_dataset_folder(args.session_dir, args.out_dir, slug,
                                  include_audio=args.include_audio)
    print(f"Dataset-Ordner: {folder}")
    print(f"Slug:           {slug}")
    if args.publish:
        published = publish(client, folder, f"Session {args.run_id or 'manuell'}")
        print(f"Veroeffentlicht: {published}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

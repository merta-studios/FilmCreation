"""Kaggle-Kernel bauen: 2x T4 parallel rendern, Ergebnisse zurueckgeben.

Der Kernel ist ein **privates Kaggle-Script**, das genau drei Dinge tut:

1. das Repo im exakten Commit klonen (damit Systemcode und Film zusammenpassen),
2. die Render-Session aus dem gemounteten Dataset holen,
3. die Shots auf zwei Worker aufteilen - je eine T4 - und Blender rechnen lassen.

Danach liegen die MP4s plus ``render_manifest.json`` in ``/kaggle/working/shots``
und koennen mit ``kaggle kernels output`` heruntergeladen werden. Der GitHub-Runner
holt das Ergebnis durch Polling; es werden keine Callback-Tokens im Kernel gespeichert.

Die Datei ``main.py`` wird hier als Text erzeugt - so bleibt der komplette
Kernel-Ablauf im Repo versioniert und testbar (``py_compile`` in CI).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):  # pragma: no cover - direkter Aufruf
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

#: Offizielle Blender-Downloads (Fallback, wenn das bpy-Wheel nicht passt)
BLENDER_VERSION = "4.2.9"
BLENDER_TARBALL = (f"https://download.blender.org/release/Blender4.2/"
                   f"blender-{BLENDER_VERSION}-linux-x64.tar.xz")

KERNEL_TEMPLATE = r'''#!/usr/bin/env python3
"""FilmCreation-Renderkernel - automatisch erzeugt, nicht von Hand editieren.

Laeuft auf Kaggle mit 2x Nvidia T4. Der komplette Ablauf steht in
1_system/kaggle_bridge/kernel_builder.py (Template) und wird dort getestet.
"""
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_URL = "%%REPO_URL%%"
COMMIT = "%%COMMIT%%"
DATASET_SLUG = "%%DATASET_SLUG%%"
SHOT_SPEC = "%%SHOTS%%"
SAMPLES = %%SAMPLES%%
QUALITY = "%%QUALITY%%"
WORKERS = %%WORKERS%%
EXTRA_ARGS = %%EXTRA_ARGS%%

WORK = Path("/kaggle/working")
REPO = WORK / "repo"
SESSION = WORK / "session"
SHOTS_DIR = WORK / "shots"
LOGS = WORK / "logs"


def log(message):
    print(f"[filmcreation] {message}", flush=True)


def run(command, cwd=None, env=None, check=False):
    result = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env,
                            capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout[-4000:], flush=True)
    if result.stderr.strip():
        print(result.stderr[-4000:], flush=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"Befehl fehlgeschlagen ({result.returncode}): {' '.join(command[:3])}")
    return result


def clone_repo():
    if (REPO / "1_system").is_dir():
        log("Repo bereits vorhanden")
        return
    log(f"Klonen: {REPO_URL} @ {COMMIT}")
    run(["git", "clone", "--quiet", REPO_URL, str(REPO)], check=True)
    if COMMIT:
        run(["git", "-C", str(REPO), "fetch", "--quiet", "origin", COMMIT])
        run(["git", "-C", str(REPO), "checkout", "--quiet", COMMIT], check=True)
    log("Repo bereit")


def stage_dataset():
    slug_tail = DATASET_SLUG.split("/")[-1]
    candidates = [Path("/kaggle/input") / slug_tail,
                  Path("/kaggle/input") / DATASET_SLUG.replace("/", "-"),
                  Path("/kaggle/input") / DATASET_SLUG]
    for candidate in candidates:
        if (candidate / "timeline_resolved.json").is_file():
            SESSION.mkdir(parents=True, exist_ok=True)
            for entry in candidate.iterdir():
                if entry.name == "dataset-metadata.json":
                    continue
                target = SESSION / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(entry, target)
            log(f"Session aus {candidate} kopiert")
            return SESSION
    raise FileNotFoundError("Dataset mit timeline_resolved.json nicht gefunden")


def install_requirements():
    requirements = REPO / "1_system" / "requirements.txt"
    run([sys.executable, "-m", "pip", "install", "-q", "-r", str(requirements)])


def setup_renderer():
    """Liefert ('modul', None) fuer bpy oder ('blender', pfad) fuer den Blender-Build."""
    try:
        import bpy  # noqa: F401
        log(f"bpy vorhanden: {bpy.app.version_string}")
        return "modul", None
    except Exception:
        pass
    log("bpy fehlt - installiere bpy==4.2.0 (dauert 1-2 Minuten)")
    result = run([sys.executable, "-m", "pip", "install", "-q", "bpy==4.2.0"])
    probe = run([sys.executable, "-c", "import bpy; print(bpy.app.version_string)"])
    if result.returncode == 0 and probe.returncode == 0:
        return "modul", None
    log("bpy-Wheel passt nicht - lade offiziellen Blender-Build")
    archive = WORK / "blender.tar.xz"
    if not archive.is_file():
        urllib.request.urlretrieve("%%BLENDER_TARBALL%%", archive)
    target = WORK / "blender"
    if not (target / "blender").is_file():
        with tarfile.open(archive) as tar:
            tar.extractall(WORK)
        extracted = sorted(WORK.glob("blender-*"))[0]
        shutil.move(str(extracted), str(target))
    blender = target / "blender"
    run([str(blender), "-b", "--python-expr",
         "import subprocess,sys; subprocess.run([sys.executable,'-m','pip','install','-q',"
         "'PyYAML','requests','Pillow'],check=True)"], check=True)
    return "blender", blender


def shot_ids_from_timeline():
    data = json.loads((SESSION / "timeline_resolved.json").read_text(encoding="utf-8"))
    return [int(shot["id"]) for shot in data.get("shots", [])]


def split_shot_spec():
    if SHOT_SPEC in ("", "all", "alle"):
        return None
    ids = []
    for part in SHOT_SPEC.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = part.split("-", 1)
            ids.extend(range(int(low), int(high) + 1))
        else:
            ids.append(int(part))
    return sorted(dict.fromkeys(ids))


def worker_command(mode, blender, ids):
    shots = ",".join(str(shot) for shot in ids) if ids else "all"
    args = ["--film-dir", str(REPO / "2_aktueller_film"),
            "--timeline", str(SESSION / "timeline_resolved.json"),
            "--shots", shots,
            "--out-dir", str(SHOTS_DIR),
            "--samples", str(SAMPLES)]
    if QUALITY:
        args += ["--quality", QUALITY]
    args += EXTRA_ARGS
    if mode == "modul":
        return [sys.executable, "-m", "1_system.blender_engine.scene_builder", *args]
    script = REPO / "1_system" / "blender_engine" / "scene_builder.py"
    return [str(blender), "-b", "--factory-startup", "--python-exit-code", "1",
            "-P", str(script), "--", *args]


def merge_manifests():
    entries = {}
    meta = {"fps": 24, "width": 1080, "height": 1920, "film": ""}
    for manifest in sorted(SHOTS_DIR.glob("render_manifest*.json")):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        meta["fps"] = data.get("fps", meta["fps"])
        meta["width"] = data.get("width", meta["width"])
        meta["height"] = data.get("height", meta["height"])
        meta["film"] = data.get("film") or meta["film"]
        for entry in data.get("shots", []):
            path = Path(entry.get("path", ""))
            if not path.is_absolute():
                candidate = SHOTS_DIR / path.name
                path = candidate if candidate.is_file() else path
            if path.is_file():
                entry = dict(entry)
                entry["path"] = str(path)
                entries[int(entry["id"])] = entry
    merged = {**meta, "shots": [entries[key] for key in sorted(entries)]}
    target = SHOTS_DIR / "render_manifest.json"
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def main():
    started = time.time()
    WORK.mkdir(parents=True, exist_ok=True)
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    clone_repo()
    install_requirements()
    stage_dataset()
    mode, blender = setup_renderer()
    log(f"Renderer: {mode} (Blender-Fallback: {blender})")

    all_ids = shot_ids_from_timeline()
    wanted = split_shot_spec() or all_ids
    wanted = [shot for shot in wanted if shot in all_ids]
    log(f"{len(wanted)} Shots auf {WORKERS} Worker: {wanted}")

    buckets = [[] for _ in range(max(1, WORKERS))]
    for position, shot in enumerate(wanted):
        buckets[position % len(buckets)].append(shot)

    processes = []
    for index, ids in enumerate(buckets):
        if not ids:
            continue
        processes.append((index, ids))
    codes = {}
    children = []
    for index, ids in processes:
        env_index = index
        command = worker_command(mode, blender, ids)
        log(f"Start Worker {env_index} mit {ids}")
        env = dict(os.environ)
        env["CUDA_VISIBLE_DEVICES"] = str(env_index % 2)
        env["RENDER_DEVICE"] = "GPU"
        env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
        env["LC_ALL"] = "C.UTF-8"
        LOGS.mkdir(parents=True, exist_ok=True)
        log_path = LOGS / f"worker_{env_index}.log"
        handle = open(log_path, "w", encoding="utf-8")
        child = subprocess.Popen(command, cwd=str(REPO), env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True)
        children.append((env_index, child, handle, log_path))
    for env_index, child, handle, log_path in children:
        for line in child.stdout:
            handle.write(line)
            if line.strip():
                print(f"[w{env_index}] {line.rstrip()}", flush=True)
        codes[env_index] = child.wait()
        handle.close()

    merged = merge_manifests()
    rendered = [int(entry["id"]) for entry in merged.get("shots", [])]
    missing = [shot for shot in wanted if shot not in rendered]
    status = {
        "ok": not missing,
        "rendered": rendered,
        "missing": missing,
        "workers": {str(key): value for key, value in codes.items()},
        "kernel": "%%KERNEL_SLUG%%",
        "duration_seconds": round(time.time() - started, 1),
    }
    (WORK / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    log(f"Fertig: {len(rendered)} Shots, fehlend: {missing}")
    if missing:
        raise SystemExit(f"Shots fehlen: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def build_kernel(out_dir: Path, kernel_slug: str, repo_url: str, commit: str,
                 dataset_slug: str, shots: str = "all", samples: int = 96,
                 quality: str = "", workers: int = 2, extra_args: Optional[list[str]] = None,
                 callback: Optional[dict] = None, title: str = "FilmCreation Render",
                 username: Optional[str] = None) -> Path:
    """Schreibt ``main.py`` und ``kernel-metadata.json`` in ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if username and "/" not in kernel_slug:
        kernel_slug = f"{username.lower()}/{kernel_slug}"
    source = KERNEL_TEMPLATE
    replacements = {
        "%%REPO_URL%%": repo_url,
        "%%COMMIT%%": commit or "",
        "%%DATASET_SLUG%%": dataset_slug,
        "%%SHOTS%%": shots or "all",
        "%%SAMPLES%%": str(int(samples)),
        "%%QUALITY%%": quality or "",
        "%%WORKERS%%": str(max(1, int(workers))),
        "%%EXTRA_ARGS%%": json.dumps(list(extra_args or [])),
        "%%BLENDER_TARBALL%%": BLENDER_TARBALL,
        "%%KERNEL_SLUG%%": kernel_slug,
    }
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    if "%%" in source:
        remaining = [line for line in source.splitlines() if "%%" in line][:3]
        raise ValueError(f"Unersetzte Platzhalter im Kernel: {remaining}")
    (out_dir / "main.py").write_text(source, encoding="utf-8")

    metadata = {
        "id": kernel_slug,
        "title": title[:50],
        "code_file": "main.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        # Wichtig: nur so startet Kaggle die 2x-T4-Maschine statt einer P100
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [dataset_slug] if dataset_slug else [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    (out_dir / "kernel-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir


def kernel_slug_for(username: str, run_id: str, base: str = "filmcreation-render") -> str:
    """Slug mit Run-ID - Kaggle-Slugs erlauben nur Kleinbuchstaben, Ziffern und '-'."""
    suffix = "".join(character if character.isalnum() else "-"
                     for character in str(run_id)).strip("-").lower() or "run"
    cleaned = "".join(character if character.isalnum() else "-" for character in base.lower())
    return f"{username.lower()}/{cleaned}-{suffix[:20]}"


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Kaggle-Renderkernel bauen")
    parser.add_argument("--out-dir", type=Path, default=Path("kaggle_kernel"))
    parser.add_argument("--kernel-slug", default=None)
    parser.add_argument("--repo-url", default="https://github.com/merta-studios/FilmCreation.git")
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--dataset-slug", required=True)
    parser.add_argument("--shots", default="all")
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--quality", default="")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--callback-repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--callback-workflow", default="2-finish-film.yml")
    parser.add_argument("--callback-ref", default=os.environ.get("GITHUB_REF_NAME", "main"))
    parser.add_argument("--callback-token", default=os.environ.get("GH_CALLBACK_TOKEN", ""))
    args = parser.parse_args(argv)
    username = os.environ.get("KAGGLE_USERNAME", "")
    if not username:
        raise SystemExit("KAGGLE_USERNAME fehlt")
    slug = args.kernel_slug or kernel_slug_for(username, os.environ.get("GITHUB_RUN_ID", "local"))
    callback = {"repo": args.callback_repo, "workflow": args.callback_workflow,
                "ref": args.callback_ref, "token": args.callback_token,
                "inputs": {"run_id": os.environ.get("GITHUB_RUN_ID", ""),
                           "kaggle_kernel": slug}} if args.callback_repo else {}
    folder = build_kernel(args.out_dir, slug, args.repo_url, args.commit,
                          args.dataset_slug, args.shots, args.samples, args.quality,
                          args.workers, callback=callback, username=username)
    print(f"Kernel-Ordner: {folder} ({slug})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

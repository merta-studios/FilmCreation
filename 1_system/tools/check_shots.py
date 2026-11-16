"""Prueft, ob alle Shots gerendert sind - vor dem Schnitt und im CI.

Die Timeline sagt, wie viele Frames jeder Shot hat. Das Manifest sagt, was
wirklich auf der Platte liegt. Dieses Werkzeug vergleicht beides und meldet
fehlende Shots mit ID und Framezahl, damit man genau diese nachrendern kann.

Beispiel::

    python -m 1_system.tools.check_shots \
        --timeline render_session/timeline_resolved.json \
        --manifest render_output/render_manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def check(timeline: dict, manifest: dict, shots_dir: Optional[Path] = None) -> dict:
    """Vergleicht Timeline und Manifest; liefert ``missing`` und ``problems``."""
    problems: list[str] = []
    shots = timeline.get("shots") or []
    if not shots:
        problems.append("Timeline enthaelt keine Shots")
    by_id = {int(entry["id"]): entry for entry in manifest.get("shots") or []}
    if int(manifest.get("fps", timeline.get("fps", 24))) != int(timeline.get("fps", 24)):
        problems.append("Manifest und Timeline haben unterschiedliche fps")
    covered = 0
    missing: list[int] = []
    for shot in shots:
        shot_id = int(shot["id"])
        entry = by_id.get(shot_id)
        if entry is None:
            missing.append(shot_id)
            continue
        path = Path(entry.get("path", ""))
        if not path.is_file() and shots_dir is not None:
            candidate = Path(shots_dir) / path.name
            if candidate.is_file():
                path = candidate
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(shot_id)
            continue
        frames = int(entry.get("frames") or 0)
        expected = int(shot.get("frames") or 0)
        if frames and expected and frames != expected:
            problems.append(f"Shot {shot_id}: {frames} Frames im Manifest, "
                            f"{expected} in der Timeline")
        covered += frames
    total = int(timeline.get("total_frames") or 0)
    if covered and total and covered != total:
        problems.append(f"Shots decken {covered} von {total} Frames ab")
    return {
        "ok": not missing and not problems,
        "shots": len(shots),
        "rendered": len(shots) - len(missing),
        "missing": missing,
        "frames_covered": covered,
        "frames_total": total,
        "problems": problems,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fehlende Shots finden")
    parser.add_argument("--timeline", type=Path,
                        default=Path("render_session/timeline_resolved.json"))
    parser.add_argument("--manifest", type=Path,
                        default=Path("render_output/render_manifest.json"))
    parser.add_argument("--shots-dir", type=Path, default=Path("render_output/shots"))
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--allow-missing", action="store_true",
                        help="nur berichten, nicht mit Fehlercode beenden")
    args = parser.parse_args(argv)
    if not args.timeline.is_file():
        raise SystemExit(f"Timeline fehlt: {args.timeline}")
    timeline = json.loads(args.timeline.read_text(encoding="utf-8"))
    manifest = (json.loads(args.manifest.read_text(encoding="utf-8"))
                if args.manifest.is_file() else {"shots": []})
    result = check(timeline, manifest, args.shots_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    summary_path = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## Shots\n\n")
            stream.write(f"* Gerendert: {result['rendered']}/{result['shots']}\n")
            stream.write(f"* Frames: {result['frames_covered']}/{result['frames_total']}\n")
            if result["missing"]:
                stream.write(f"* Fehlend: {', '.join(str(s) for s in result['missing'])}\n")
            for problem in result["problems"]:
                stream.write(f"* Problem: {problem}\n")
    if not result["ok"] and not args.allow_missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

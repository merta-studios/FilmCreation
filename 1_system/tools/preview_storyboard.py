"""Storyboard-Vorschau: ein Standbild pro Shot als beschriftetes Raster.

Die Agenten-Regel lautet "erst schauen, dann bauen". Dieses Werkzeug macht aus
den Vorschau-Renders (``--preview-storyboard`` im Scene-Builder, 540x960,
8 Samples) ein einzelnes PNG mit Shot-Nummer, Segment, Dauer und Titel - genau
das Bild, das man im GitHub-Actions-Artifact und im Chat zeigt.

Beispiel::

    python -m 1_system.blender_engine.scene_builder --preview-storyboard --out-dir render_output/preview
    python -m 1_system.tools.preview_storyboard --shots-dir render_output/preview \
        --out render_output/preview_storyboard.png
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

timeline_sync = importlib.import_module("1_system.audio.timeline_sync")


def shot_number(path: Path) -> Optional[int]:
    match = re.search(r"shot_(\d+)", Path(path).name)
    return int(match.group(1)) if match else None


def collect_images(shots_dir: Path) -> list[tuple[int, Path]]:
    found: dict[int, Path] = {}
    for pattern in ("shot_*.png", "*.png", "shot_*.jpg"):
        for file in sorted(Path(shots_dir).glob(pattern)):
            number = shot_number(file)
            if number is not None and number not in found:
                found[number] = file
    return sorted(found.items())


def build_storyboard(shots_dir: Path, output: Path, columns: int = 4,
                     thumb_width: int = 300, timeline_path: Optional[Path] = None,
                     max_shots: int = 20) -> Path:
    """Baut das Raster; fehlende Shots werden als Luecke mit Hinweis gezeigt."""
    from PIL import Image, ImageDraw, ImageFont

    images = collect_images(shots_dir)[:max_shots]
    if not images:
        raise FileNotFoundError(f"Keine Shot-Standbilder in {shots_dir} gefunden")

    shots_meta: dict[int, dict] = {}
    if timeline_path and Path(timeline_path).is_file():
        timeline = timeline_sync.load_timeline(Path(timeline_path))
        shots_meta = {int(shot["id"]): shot for shot in timeline.get("shots", [])}

    rows = (len(images) + columns - 1) // columns
    cell_w = thumb_width
    cell_h = int(thumb_width * 16 / 9) + 74
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#0f1419")
    draw = ImageDraw.Draw(sheet)
    try:
        title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 17)
    except OSError:  # pragma: no cover - minimal system
        title_font = ImageFont.load_default()
        small_font = title_font

    for index, (number, file) in enumerate(images):
        column, row = index % columns, index // columns
        x, y = column * cell_w, row * cell_h
        try:
            with Image.open(file) as image:
                preview = image.convert("RGB")
                preview.thumbnail((cell_w - 12, cell_h - 86))
        except OSError:
            continue
        offset_x = x + (cell_w - preview.width) // 2
        sheet.paste(preview, (offset_x, y + 6))
        meta = shots_meta.get(number, {})
        title = f"Shot {number}"
        if meta:
            title += f"  {meta.get('frames', 0) / 24:.1f}s"
        draw.text((x + 8, y + cell_h - 76), title, fill="#e6edf3", font=title_font)
        subtitle = str(meta.get("title") or file.name)[:36]
        draw.text((x + 8, y + cell_h - 48), subtitle, fill="#8b949e", font=small_font)
        draw.rectangle([x + 1, y + 1, x + cell_w - 2, y + cell_h - 2],
                       outline="#30363d", width=2)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Standbilder zu einem Storyboard legen")
    parser.add_argument("--shots-dir", type=Path, default=Path("render_output/preview"))
    parser.add_argument("--out", type=Path, default=Path("render_output/preview_storyboard.png"))
    parser.add_argument("--timeline", type=Path,
                        default=Path("render_session/timeline_resolved.json"))
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--thumb-width", type=int, default=300)
    args = parser.parse_args(argv)
    path = build_storyboard(args.shots_dir, args.out, args.columns, args.thumb_width,
                            args.timeline)
    print(json.dumps({"storyboard": str(path),
                      "shots": len(collect_images(args.shots_dir))}, ensure_ascii=False))
    summary_path = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## Storyboard\n\n")
            stream.write(f"![Storyboard]({path.name})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

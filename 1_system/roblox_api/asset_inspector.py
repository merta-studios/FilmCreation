"""Asset-Pruefung: Vorschau, Lizenzcheck, Modell-Analyse und Anprobe-Render.

Der Inspector ist der Grund, warum im fertigen Film keine Ueberraschungen
auftauchen: Jedes Roblox-Asset (Haare, Hut, Requisite) wird vor der Verwendung

1. ueber die offizielle API beschrieben (Name, Typ, Creator) und **lizenzgeprueft**
   (:func:`1_system.roblox_api.open_cloud.check_license`),
2. als Thumbnail heruntergeladen und in einem **Kontaktabzug** (PNG-Raster)
   zusammengefasst, den man in GitHub direkt anschauen kann,
3. als Modell geladen (:mod:`1_system.roblox_api.rbxm_parser`) und mit Groesse,
   Teileanzahl und Skalierungsvorschlag vermessen,
4. optional in Blender **angezogen** und gerendert (Try-on, 540x960) - auf einem
   R15-Avatar am passenden Attachment (``HatAttachment``, ``HairAttachment`` ...).

Ergebnis ist ein ``report.md`` (menschenlesbar) plus ``report.json`` (maschinell),
damit die Agenten-Workflow ``inspect-assets`` genau das anzeigen kann.
"""
from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

open_cloud = importlib.import_module("1_system.roblox_api.open_cloud")
rbxm_parser = importlib.import_module("1_system.roblox_api.rbxm_parser")

#: Asset-Typ -> empfohlener Attachment-Slot fuer die Anprobe
SLOT_FOR_TYPE: dict[str, str] = {
    "Hat": "HatAttachment",
    "HairAccessory": "HairAttachment",
    "FaceAccessory": "FaceFrontAttachment",
    "NeckAccessory": "NeckAttachment",
    "ShoulderAccessory": "LeftCollarAttachment",
    "FrontAccessory": "FrontAttachment",
    "BackAccessory": "BackAttachment",
    "WaistAccessory": "WaistCenterAttachment",
}

TYPE_NAMES: dict[int, str] = {
    2: "T-Shirt", 8: "Hat", 11: "Shirt", 12: "Pants", 17: "Head", 18: "Face",
    19: "Gear", 24: "Animation", 27: "Torso", 28: "RightArm", 29: "LeftArm",
    30: "LeftLeg", 31: "RightLeg", 38: "Plugin", 40: "MeshPart", 41: "HairAccessory",
    42: "FaceAccessory", 43: "NeckAccessory", 44: "ShoulderAccessory",
    45: "FrontAccessory", 46: "BackAccessory", 47: "WaistAccessory", 61: "Emote",
    10: "Model",
}


@dataclass
class AssetReport:
    asset_id: int
    name: str = ""
    asset_type: str = ""
    creator: str = ""
    creator_id: int = 0
    license_ok: bool = False
    license_note: str = ""
    parts: int = 0
    size_studs: tuple = (0.0, 0.0, 0.0)
    suggested_scale: float = 1.0
    thumbnail: Optional[str] = None
    tryon: Optional[str] = None
    model_file: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        data = {
            "asset_id": self.asset_id, "name": self.name, "asset_type": self.asset_type,
            "creator": self.creator, "creator_id": self.creator_id,
            "license_ok": self.license_ok, "license_note": self.license_note,
            "parts": self.parts, "size_studs": [round(v, 2) for v in self.size_studs],
            "suggested_scale": round(self.suggested_scale, 3),
            "thumbnail": self.thumbnail, "tryon": self.tryon,
            "model_file": self.model_file, "warnings": self.warnings, "error": self.error,
        }
        return data


def _relative(path: Optional[Path]) -> Optional[str]:
    """Pfad relativ zum Repo (falls moeglich), sonst absolut - fuer Berichte."""
    if path is None:
        return None
    path = Path(path)
    try:
        return str(path.resolve().relative_to(_ROOT))
    except ValueError:
        return str(path)


def asset_type_name(asset_type) -> str:
    try:
        return TYPE_NAMES.get(int(asset_type), f"Typ {asset_type}")
    except (TypeError, ValueError):
        return str(asset_type)


def analyze_model(model: rbxm_parser.RbxmModel) -> tuple[tuple, float]:
    """Liefert (Groesse in Studs, Skalierungsvorschlag auf ~3 Studs Hoehe)."""
    bounds = model.bounds()
    size = tuple(bounds["max"][i] - bounds["min"][i] for i in range(3))
    largest = max(size) if size else 0.0
    scale = 3.0 / largest if largest > 0.01 else 1.0
    return size, max(0.05, min(scale, 20.0))


def inspect_asset(client, asset_id: int, out_dir: Path, *, try_on: bool = False,
                  slot: Optional[str] = None) -> AssetReport:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = AssetReport(asset_id=asset_id)
    try:
        info = client.asset_info(asset_id)
    except Exception as exc:  # noqa: BLE001 - API-Fehler sollen den Bericht nicht abbrechen
        report.error = str(exc)
        report.warnings.append("Metadaten konnten nicht geladen werden")
        return report
    report.name = info.name or f"Asset {asset_id}"
    report.asset_type = (asset_type_name(info.asset_type_id) if info.asset_type_id
                         else (info.asset_type or "Modell"))
    report.creator = info.creator
    report.creator_id = info.creator_id
    category = str(info.raw.get("category") or "")
    ok, note = open_cloud.check_license(info.name, info.creator_id, info.description,
                                        report.asset_type, category)
    report.license_ok, report.license_note = ok, note

    thumbnail_path = out_dir / f"thumb_{asset_id}.png"
    try:
        downloaded = client.download_thumbnail(asset_id, thumbnail_path)
        if downloaded:
            report.thumbnail = _relative(downloaded)
        else:
            report.warnings.append("kein Thumbnail verfuegbar")
    except Exception as exc:  # noqa: BLE001
        report.warnings.append(f"Thumbnail-Fehler: {exc}")

    # Modell laden (nicht bei jedem Asset-Typ sinnvoll)
    if report.asset_type not in ("T-Shirt", "Shirt", "Pants", "Face", "Emote", "Audio"):
        try:
            target = out_dir / f"model_{asset_id}"
            path = client.download_asset(asset_id, target)
            report.model_file = _relative(path)
            if path.suffix in (".rbxm", ".rbxmx"):
                model = rbxm_parser.RbxmParser().parse_file(path)
                report.parts = len(model.parts)
                report.size_studs, report.suggested_scale = analyze_model(model)
                if not model.parts:
                    report.warnings.append("Modell enthaelt keine Parts (evtl. Mesh/Union)")
                for mesh_entry in model.meshes:
                    mesh_id = rbxm_parser.RbxmParser.extract_asset_id(mesh_entry.get("mesh_id", ""))
                    if mesh_id and mesh_id != asset_id:
                        try:
                            client.download_asset(mesh_id, out_dir / f"mesh_{mesh_id}")
                        except Exception:  # noqa: BLE001 - Sub-Mesh ist optional
                            pass
            elif path.suffix == ".obj":
                geometry = rbxm_parser.parse_obj(path)
                report.parts = len(geometry["vertices"])
                report.warnings.append("3D-Thumbnail statt Originalmodell (OBJ)")
        except Exception as exc:  # noqa: BLE001
            report.warnings.append(f"Modell nicht ladbar: {exc}")
            obj_path = out_dir / f"thumb3d_{asset_id}.obj"
            try:
                if client.threed_thumbnail(asset_id, obj_path):
                    geometry = rbxm_parser.parse_obj(obj_path)
                    report.parts = len(geometry["vertices"])
                    report.warnings.append("3D-Thumbnail als Ersatzmodell gespeichert")
            except Exception as exc2:  # noqa: BLE001
                report.warnings.append(f"3D-Thumbnail-Fehler: {exc2}")

    if try_on:
        slot_name = slot or SLOT_FOR_TYPE.get(report.asset_type, "HatAttachment")
        tryon_path = out_dir / f"tryon_{asset_id}.png"
        try:
            render_tryon(asset_id, out_dir, tryon_path, slot=slot_name)
            report.tryon = _relative(tryon_path)
        except Exception as exc:  # noqa: BLE001
            report.warnings.append(f"Anprobe nicht moeglich: {exc}")
    return report


# --------------------------------------------------------------------------- #
# Kontaktabzug
# --------------------------------------------------------------------------- #
def build_contact_sheet(reports: Iterable[AssetReport], out_path: Path,
                        columns: int = 3, thumb: int = 360) -> Optional[Path]:
    """Baut ein PNG-Raster mit Thumbnails, Namen und Lizenzstatus."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # pragma: no cover
        return None
    reports = list(reports)
    if not reports:
        return None
    rows = (len(reports) + columns - 1) // columns
    cell_w, cell_h = thumb, thumb + 64
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#14181d")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 20)
        small = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:  # pragma: no cover
        font = ImageFont.load_default()
        small = font
    for index, report in enumerate(reports):
        column, row = index % columns, index // columns
        x, y = column * cell_w, row * cell_h
        draw.rectangle([x + 2, y + 2, x + cell_w - 2, y + cell_h - 2],
                       outline="#2b323b", width=2)
        if report.thumbnail and Path(report.thumbnail).is_file():
            try:
                image = Image.open(report.thumbnail).convert("RGBA")
                image.thumbnail((thumb - 16, thumb - 16))
                sheet.paste(image, (x + (cell_w - image.width) // 2,
                                    y + (thumb - image.height) // 2), image)
            except OSError:
                pass
        color = "#7ee787" if report.license_ok else "#ff7b72"
        draw.text((x + 12, y + thumb + 4), (report.name or f"#{report.asset_id}")[:28],
                  fill="#e6edf3", font=font)
        draw.text((x + 12, y + thumb + 30),
                  f"{report.asset_type} | {'OK' if report.license_ok else 'PRUEFEN'}",
                  fill=color, font=small)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


# --------------------------------------------------------------------------- #
# Anprobe in Blender
# --------------------------------------------------------------------------- #
def render_tryon(asset_id: int, out_dir: Path, out_png: Path,
                 slot: str = "HatAttachment") -> Path:
    """Rendert ein Asset am R15-Avatar (Vorderansicht, 540x960, EEVEE)."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Anprobe braucht Blender (bpy)") from exc
    rig = importlib.import_module("1_system.blender_engine.rig_r15")
    world_builder = importlib.import_module("1_system.blender_engine.primitives_and_map")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    collection = scene.collection
    character = rig.build_r15(name="TryOn", height_scale=1.0, collection=collection)
    rig.set_face(character, "hopeful")

    model_path = None
    out_dir = Path(out_dir)
    for candidate in (out_dir / f"model_{asset_id}.glb", out_dir / f"model_{asset_id}.gltf",
                      out_dir / f"model_{asset_id}.obj", out_dir / f"thumb3d_{asset_id}.obj",
                      out_dir / f"model_{asset_id}.rbxm", out_dir / f"model_{asset_id}.rbxmx",
                      out_dir / f"{asset_id}.rbxm", out_dir / f"{asset_id}.rbxmx"):
        if candidate.is_file():
            model_path = candidate
            break
    if model_path is None:
        raise FileNotFoundError(
            f"Kein importierbares Modell fuer Asset {asset_id} "
            "(unterstuetzt: .rbxm, .rbxmx, .glb, .gltf, .obj)")
    scale = 1.0
    if model_path.suffix.lower() in (".rbxm", ".rbxmx"):
        parsed = rbxm_parser.RbxmParser().parse_file(model_path)
        _, suggested = analyze_model(parsed)
        scale = min(1.5, suggested)
    builder = world_builder.WorldBuilder(collection=collection)
    obj = builder.import_model(f"anprobe_{asset_id}", model_path, pos=(0, 0, 0), scale=1.0)
    rig.attach_to_slot(character, slot, obj, scale=scale)

    # Kamera: frontal, Kopf im oberen Drittel
    camera_data = bpy.data.cameras.new("TryOnCam")
    camera = bpy.data.objects.new("TryOnCam", camera_data)
    camera_data.lens = 70.0
    collection.objects.link(camera)
    camera.location = (0.0, -15.0, 5.6)
    camera.rotation_euler = (1.5708, 0.0, 0.0)
    scene.camera = camera

    key = bpy.data.objects.new("Key", bpy.data.lights.new("Key", "AREA"))
    key.data.energy = 900.0
    key.data.size = 6.0
    key.location = (-5.0, -8.0, 9.0)
    key.rotation_euler = (0.9, 0.0, -0.5)
    collection.objects.link(key)
    fill = bpy.data.objects.new("Fill", bpy.data.lights.new("Fill", "AREA"))
    fill.data.energy = 300.0
    fill.data.size = 8.0
    fill.location = (6.0, -6.0, 6.0)
    fill.rotation_euler = (1.1, 0.0, 0.7)
    collection.objects.link(fill)

    world = bpy.data.worlds.new("TryOnWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.06, 0.08, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    scene.world = world

    for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = 32
    scene.render.resolution_x = 540
    scene.render.resolution_y = 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(Path(out_png).resolve())
    bpy.ops.render.render(write_still=True)
    return Path(out_png)


# --------------------------------------------------------------------------- #
# Bericht + CLI
# --------------------------------------------------------------------------- #
def write_report(reports: Iterable[AssetReport], out_dir: Path,
                 sheet: Optional[Path] = None) -> Path:
    reports = list(reports)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps([report.to_dict() for report in reports], ensure_ascii=False, indent=2),
        encoding="utf-8")
    lines = ["# Asset-Bericht", ""]
    if sheet is not None:
        lines += [f"![Kontaktabzug]({Path(sheet).name})", ""]
    lines += ["| ID | Name | Typ | Lizenz | Teile | Groesse (Studs) | Skalierung | Hinweise |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for report in reports:
        size = " x ".join(f"{v:.1f}" for v in report.size_studs)
        notes = "; ".join(report.warnings + ([report.error] if report.error else [])) or "-"
        lines.append(
            f"| {report.asset_id} | {report.name or '-'} | {report.asset_type or '-'} | "
            f"{'OK' if report.license_ok else 'PRUEFEN'} | {report.parts} | {size} | "
            f"{report.suggested_scale:.2f} | {notes} |")
    lines += ["", "## Lizenz-Begruendungen", ""]
    for report in reports:
        lines.append(f"- **{report.name or report.asset_id}**: {report.license_note or '-'}")
    lines += ["", "## Anproben", ""]
    tryons = [report for report in reports if report.tryon]
    if tryons:
        for report in tryons:
            lines.append(f"### {report.name}")
            lines.append(f"![Anprobe]({Path(report.tryon).name})")
            lines.append("")
    else:
        lines.append("Keine Anprobe gerendert (nur mit Blender und importierbarem Modell).")
    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def inspect_many(asset_ids: Iterable[int], out_dir: Path = Path("assets_cache/inspect"),
                 *, try_on: bool = False, client=None) -> tuple[list[AssetReport], Path, Optional[Path]]:
    client = client or open_cloud.RobloxClient()
    reports = [inspect_asset(client, int(asset_id), out_dir, try_on=try_on)
               for asset_id in asset_ids]
    sheet = build_contact_sheet(reports, Path(out_dir) / "kontaktabzug.png")
    report_path = write_report(reports, out_dir, sheet)
    return reports, report_path, sheet


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Roblox-Assets pruefen und anprobieren")
    parser.add_argument("--assets", default="", help="Komma-Liste von Asset-IDs")
    parser.add_argument("--search", default="", help="Creator-Store-Suche (z. B. 'street lamp')")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--out", type=Path, default=Path("assets_cache/inspect"))
    parser.add_argument("--tryon", action="store_true", help="Anprobe rendern (braucht Blender)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    client = open_cloud.RobloxClient()
    ids: list[int] = [int(part) for part in args.assets.replace(" ", "").split(",") if part]
    if args.search:
        for hit in client.search_creator_store(args.search, limit=args.limit):
            ids.append(int(hit.get("id") or hit.get("asset_id") or 0))
    if not ids:
        parser.error("--assets oder --search angeben")
    reports, report_path, sheet = inspect_many(ids, args.out, try_on=args.tryon, client=client)
    if args.json:
        print(json.dumps([report.to_dict() for report in reports], ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"{report.asset_id:>12} | {report.name[:30]:<30} | "
                  f"{'OK' if report.license_ok else 'PRUEFEN':<7} | {report.parts} Teile")
        print(f"Bericht: {report_path}")
        if sheet:
            print(f"Kontaktabzug: {sheet}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

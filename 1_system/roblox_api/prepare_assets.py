"""Roblox-Assets fuer Blender vorbereiten: herunterladen und als glTF speichern.

Blender kann ``.rbxm``/``.rbxmx`` nicht direkt oeffnen. Der saubere Weg:

1. Asset mit Open Cloud herunterladen (:mod:`open_cloud`),
2. Lizenz/Name pruefen (:func:`open_cloud.check_license`),
3. Teile in Blender aufbauen (:meth:`rbxm_parser.RbxmParser.import_into_blender`),
4. als **GLB** exportieren - das importiert
   :meth:`primitives_and_map.WorldBuilder.import_model` direkt.

Das Ergebnis traegt man in ``2_aktueller_film/characters.py`` ein::

    "accessories": [{"id": 12345, "path": "assets/models/12345.glb",
                     "slot": "HatAttachment", "scale": 1.0}]

Ohne Blender (z. B. im CI ohne bpy) wird nur heruntergeladen und ein Hinweis
geschrieben - mit ``--no-convert`` laesst sich das erzwingen.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

open_cloud = importlib.import_module("1_system.roblox_api.open_cloud")
rbxm_parser = importlib.import_module("1_system.roblox_api.rbxm_parser")
inspector = importlib.import_module("1_system.roblox_api.asset_inspector")


def convert_to_glb(model_path: Path, out_glb: Path, scale: float = 1.0) -> Path:
    """Baut ein RBXM/RBXMX in Blender auf und exportiert es als GLB."""
    try:
        import bpy  # type: ignore
    except ImportError as exc:  # pragma: no cover - braucht Blender
        raise RuntimeError("Konvertierung nach GLB braucht Blender (bpy)") from exc

    model_path = Path(model_path)
    model = rbxm_parser.RbxmParser().parse_file(model_path)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    collection = bpy.context.scene.collection
    parser = rbxm_parser.RbxmParser()
    parser.import_into_blender(model, collection=collection, scale=scale,
                               mesh_dir=model_path.parent)
    out_glb = Path(out_glb)
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(out_glb), export_format="GLB",
                              use_selection=True)
    return out_glb


def prepare_asset(client, asset_id: int, out_dir: Path = Path("assets/models"),
                  convert: bool = True, scale: Optional[float] = None) -> dict:
    """Laedt ein Asset, prueft die Lizenz und legt (wenn moeglich) ein GLB ab."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = client.asset_info(asset_id)
    ok, note = open_cloud.check_license(info.name, info.creator_id, info.description)
    result = {"asset_id": int(asset_id), "name": info.name, "creator": info.creator,
              "license_ok": ok, "license_note": note,
              "asset_type": inspector.asset_type_name(info.asset_type_id),
              "slot": inspector.SLOT_FOR_TYPE.get(
                  inspector.asset_type_name(info.asset_type_id), "HatAttachment")}
    raw = client.download_asset(asset_id, out_dir / f"{asset_id}")
    result["raw"] = str(raw)
    if raw.suffix not in (".rbxm", ".rbxmx"):
        result["error"] = f"unerwartetes Format {raw.suffix}"
        return result
    model = rbxm_parser.RbxmParser().parse_file(raw)
    for mesh_entry in model.meshes:
        mesh_id = rbxm_parser.RbxmParser.extract_asset_id(mesh_entry.get("mesh_id", ""))
        if mesh_id and mesh_id != int(asset_id):
            try:
                client.download_asset(mesh_id, out_dir / f"mesh_{mesh_id}")
            except Exception:  # noqa: BLE001 - Sub-Mesh ist optional
                pass
    size, suggested = inspector.analyze_model(model)
    result["parts"] = len(model.parts)
    result["size_studs"] = [round(value, 3) for value in size]
    result["scale"] = float(scale if scale is not None else suggested)
    if convert:
        try:
            glb = convert_to_glb(raw, out_dir / f"{asset_id}.glb", result["scale"])
            result["glb"] = str(glb)
        except Exception as exc:  # noqa: BLE001 - Blender darf optional sein
            result["warning"] = f"GLB-Konvertierung nicht moeglich: {exc}"
    return result


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Roblox-Assets fuer Blender vorbereiten")
    parser.add_argument("--assets", required=True, help="Komma-Liste von Asset-IDs")
    parser.add_argument("--out", type=Path, default=Path("assets/models"))
    parser.add_argument("--scale", type=float, default=None)
    parser.add_argument("--no-convert", action="store_true")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    ids: Iterable[int] = [int(part) for part in args.assets.replace(" ", "").split(",") if part]
    client = open_cloud.RobloxClient()
    results = [prepare_asset(client, asset_id, args.out, not args.no_convert, args.scale)
               for asset_id in ids]
    for result in results:
        flag = "OK" if result.get("license_ok") else "PRUEFEN"
        target = result.get("glb") or result.get("raw")
        print(f"{result['asset_id']:>12} | {result['name'][:28]:<28} | {flag:<7} | {target}")
        if result.get("warning"):
            print(f"             Hinweis: {result['warning']}")
        if not result.get("license_ok"):
            print(f"             Lizenz: {result.get('license_note')}")
    summary = args.json_out or (Path(args.out) / "assets.json")
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Bericht: {summary}")
    return 0 if all(result.get("license_ok", False) for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

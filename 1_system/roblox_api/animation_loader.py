"""Roblox-Animationen laden: Katalog-Emote -> Animation -> KeyframeSequence -> Blender.

Der Zwei-Schritt-Loader
-----------------------
1. Ein Katalog-Emote (AssetType 61) oder eine Animation-ID (AssetType 24) wird
   geladen. Der Inhalt ist meist ein ``Animation``-Objekt mit der Eigenschaft
   ``AnimationId`` (``rbxassetid://...``) - das ist die *echte* KeyframeSequence.
2. Diese zweite ID wird geladen und als ``KeyframeSequence`` gelesen: Keyframes
   mit ``Time`` und ineinander verschachtelten ``Pose``-Objekten (Name = R15-Teil,
   ``CFrame`` = Rotation im Elternraum).
3. Daraus wird ein Clip fuer :mod:`1_system.blender_engine.custom_animations` gebaut
   und kann wie jede eingebaute Animation verwendet werden.

Unterstuetzt werden XML (``.rbxmx``) und binaer (``.rbxm``). ``CurveAnimation``
(neueres Format mit FloatCurves) wird erkannt und - wenn die Kurven lesbar sind -
ebenfalls in Clips umgerechnet; sonst gibt es eine klare Warnung und der Aufrufer
faellt auf eine eingebaute Animation zurueck.
"""
from __future__ import annotations

import importlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

rbxm_parser = importlib.import_module("1_system.roblox_api.rbxm_parser")
rig_r15 = importlib.import_module("1_system.blender_engine.rig_r15")
animations = importlib.import_module("1_system.blender_engine.custom_animations")

FPS = 24
#: Roblox-R15-Posennamen, die direkt auf unsere Bones passen
POSE_TO_BONE = {name: name for name in rig_r15.BONE_NAMES}
#: Alte R6-Namen (werden auf R15-Bones gemappt, damit nichts verloren geht)
R6_TO_R15 = {
    "Torso": "UpperTorso", "Head": "Head", "Left Arm": "LeftUpperArm",
    "Right Arm": "RightUpperArm", "Left Leg": "LeftUpperLeg", "Right Leg": "RightUpperLeg",
}


@dataclass
class PoseFrame:
    time: float
    poses: dict[str, dict] = field(default_factory=dict)


@dataclass
class AnimationData:
    name: str = ""
    looped: bool = True
    priority: int = 0
    frames: list[PoseFrame] = field(default_factory=list)
    kind: str = "KeyframeSequence"
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max((f.time for f in self.frames), default=0.0)

    def summary(self) -> dict:
        return {"name": self.name, "kind": self.kind, "looped": self.looped,
                "frames": len(self.frames), "duration": round(self.duration_seconds, 3),
                "bones": sorted({bone for f in self.frames for bone in f.poses}),
                "warnings": self.warnings}


# --------------------------------------------------------------------------- #
# CFrame -> Euler
# --------------------------------------------------------------------------- #
def matrix_to_euler_deg(r: list[float]) -> tuple[float, float, float]:
    """3x3-Rotationsmatrix (zeilenweise) -> XYZ-Euler in Grad (Roblox-Konvention)."""
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = (r + [0.0] * 9)[:9]
    # Roblox nutzt rechtshaendige Matrizen; XYZ-Euler wie Blender
    sy = math.sqrt(m00 * m00 + m10 * m10)
    if sy > 1e-5:
        x = math.atan2(m21, m22)
        y = math.atan2(-m20, sy)
        z = math.atan2(m10, m00)
    else:
        x = math.atan2(-m12, m11)
        y = math.atan2(-m20, sy)
        z = 0.0
    return (round(math.degrees(x), 2), round(math.degrees(y), 2), round(math.degrees(z), 2))


def _pose_from_cframe(text_values: dict[str, float]) -> dict:
    position = (text_values.get("X", 0.0), text_values.get("Y", 0.0), text_values.get("Z", 0.0))
    rotation = [text_values.get(f"R{i}{j}", 1.0 if i == j else 0.0)
                for i in range(3) for j in range(3)]
    return {"position": position, "rotation": rotation}


# --------------------------------------------------------------------------- #
# XML-Parsing
# --------------------------------------------------------------------------- #
def _find_all(root, tag: str):
    return root.iter(tag)


def _prop(properties, name: str):
    if not properties:
        return None
    node = properties.find(f"./Properties/*[@name='{name}']")
    if node is not None:
        return node
    for child in properties:
        if child.get("name") == name:
            return child
    return None


def _walk_poses(item, frames: dict[str, dict]) -> None:
    """Sammelt Pose-Objekte (auch verschachtelt) eines Keyframes."""
    for child in item.findall("Item"):
        class_name = child.get("class", "")
        properties = child.find("Properties")
        if class_name == "Pose":
            name_node = _prop(properties, "Name")
            name = (name_node.text or "") if name_node is not None else ""
            cframe_node = _prop(properties, "CFrame")
            values: dict[str, float] = {}
            if cframe_node is not None:
                for axis in cframe_node:
                    try:
                        values[axis.tag] = float(axis.text)
                    except (TypeError, ValueError):
                        continue
            bone = POSE_TO_BONE.get(name) or R6_TO_R15.get(name)
            if bone is None:
                for key, mapped in POSE_TO_BONE.items():
                    if key.lower() == name.lower():
                        bone = mapped
                        break
            if bone is None:
                continue
            frames[bone] = _pose_from_cframe(values)
        _walk_poses(child, frames)


def parse_keyframe_sequence_xml(data: bytes) -> AnimationData:
    text = data.decode("utf-8", errors="replace")
    root = ET.fromstring(text)
    if root.tag != "roblox":
        raise ValueError("Kein Roblox-XML")
    data_out = AnimationData()
    for item in _find_all(root, "Item"):
        class_name = item.get("class", "")
        if class_name not in ("KeyframeSequence", "CurveAnimation"):
            continue
        data_out.kind = class_name
        properties = item.find("Properties")
        name_node = _prop(properties, "Name")
        data_out.name = (name_node.text or "") if name_node is not None else ""
        looped_node = _prop(properties, "Looped")
        data_out.looped = (looped_node.text or "true").lower() == "true" if looped_node is not None else True
        priority_node = _prop(properties, "Priority")
        if priority_node is not None and priority_node.text and priority_node.text.isdigit():
            data_out.priority = int(priority_node.text)
        if class_name == "KeyframeSequence":
            for keyframe in item.findall("Item"):
                if keyframe.get("class") != "Keyframe":
                    continue
                key_props = keyframe.find("Properties")
                time_node = _prop(key_props, "Time")
                try:
                    time_value = float(time_node.text) if time_node is not None else 0.0
                except (TypeError, ValueError):
                    time_value = 0.0
                poses: dict[str, dict] = {}
                _walk_poses(keyframe, poses)
                data_out.frames.append(PoseFrame(time=time_value, poses=poses))
        else:
            data_out.warnings.append(
                "CurveAnimation erkannt: FloatCurves liegen nur in binaeren Attributen "
                "vor; bitte Animation als KeyframeSequence laden oder eingebaute "
                "Animation nutzen")
    data_out.frames.sort(key=lambda f: f.time)
    return data_out


def parse_curve_animation_xml(data: bytes) -> AnimationData:
    """Best-effort-Parser fuer CurveAnimation (FloatCurve-Kinder mit Werten)."""
    text = data.decode("utf-8", errors="replace")
    root = ET.fromstring(text)
    data_out = AnimationData(kind="CurveAnimation", name="CurveAnimation")
    curves: dict[str, list[tuple[float, float]]] = {}
    for item in _find_all(root, "Item"):
        if item.get("class") != "FloatCurve":
            continue
        properties = item.find("Properties")
        name_node = _prop(properties, "Name")
        name = (name_node.text or "") if name_node is not None else ""
        keys_node = _prop(properties, "Keyframes") or _prop(properties, "Values")
        if keys_node is None or not name:
            continue
        values: list[tuple[float, float]] = []
        for key in keys_node:
            try:
                values.append((float(key.findtext("Time") or 0.0),
                               float(key.findtext("Value") or 0.0)))
            except (TypeError, ValueError):
                continue
        if values:
            curves[name] = values
    if not curves:
        data_out.warnings.append("CurveAnimation ohne lesbare FloatCurves")
        return data_out
    times = sorted({time for values in curves.values() for time, _ in values})
    for time in times:
        poses: dict[str, dict] = {}
        for name, values in curves.items():
            value = _interp(values, time)
            if value is None:
                continue
            bone, axis = _parse_curve_name(name)
            if bone is None:
                continue
            rotation = list(poses.get(bone, {}).get("rotation", [1, 0, 0, 0, 1, 0, 0, 0, 1]))
            poses.setdefault(bone, {"position": (0, 0, 0), "rotation": rotation})["rotation"][axis] = value
        data_out.frames.append(PoseFrame(time=time, poses=poses))
    return data_out


def _interp(values: list[tuple[float, float]], time: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    if time <= values[0][0]:
        return values[0][1]
    for (t0, v0), (t1, v1) in zip(values, values[1:]):
        if t0 <= time <= t1:
            if t1 == t0:
                return v1
            factor = (time - t0) / (t1 - t0)
            return v0 + (v1 - v0) * factor
    return values[-1][1]


def _parse_curve_name(name: str) -> tuple[Optional[str], int]:
    """``RightShoulder_Rot_X`` -> ("RightShoulder", 0)."""
    pattern = re.compile(r"(?P<part>[A-Za-z0-9 ]+?)_(?:Rot|Pos)_(?P<axis>[XYZ])$")
    match = pattern.search(name)
    if not match:
        return None, 0
    part = match.group("part").strip()
    bone = POSE_TO_BONE.get(part) or R6_TO_R15.get(part)
    axis = {"X": 0, "Y": 1, "Z": 2}[match.group("axis")]
    return bone, axis


# --------------------------------------------------------------------------- #
# Binaer-Parsing
# --------------------------------------------------------------------------- #
def parse_keyframe_sequence_binary(data: bytes) -> AnimationData:
    model = rbxm_parser.RbxmBinaryParser().parse(data)
    data_out = AnimationData()
    for instance in model.instances:
        if instance.class_name == "KeyframeSequence":
            data_out.name = instance.name
            data_out.looped = bool(instance.properties.get("Looped", True))
            for keyframe in instance.children:
                if keyframe.class_name != "Keyframe":
                    continue
                time_value = float(keyframe.properties.get("Time", 0.0) or 0.0)
                poses: dict[str, dict] = {}

                def walk(node):
                    for child in node.children:
                        if child.class_name == "Pose":
                            bone = POSE_TO_BONE.get(child.name) or R6_TO_R15.get(child.name)
                            cframe = child.properties.get("CFrame") or {}
                            if bone and isinstance(cframe, dict):
                                poses[bone] = {
                                    "position": cframe.get("position", (0, 0, 0)),
                                    "rotation": list(cframe.get("rotation", [1, 0, 0, 0, 1, 0, 0, 0, 1])),
                                }
                        walk(child)

                walk(keyframe)
                data_out.frames.append(PoseFrame(time=time_value, poses=poses))
    data_out.frames.sort(key=lambda f: f.time)
    return data_out


def parse_animation_bytes(data: bytes) -> AnimationData:
    """Erkennt XML/binaer und liest KeyframeSequence oder CurveAnimation."""
    if data[:8] == rbxm_parser.BINARY_MAGIC:
        return parse_keyframe_sequence_binary(data)
    stripped = data.lstrip()
    if stripped.startswith((b"<?xml", b"<roblox")):
        if b"CurveAnimation" in data:
            result = parse_curve_animation_xml(data)
            if result.frames:
                return result
        return parse_keyframe_sequence_xml(data)
    raise ValueError("Unbekanntes Animationsformat (weder RBXM noch RBXMX)")


# --------------------------------------------------------------------------- #
# Clip-Konvertierung
# --------------------------------------------------------------------------- #
def animation_to_clip(anim: AnimationData, name: Optional[str] = None,
                      duration_frames: Optional[int] = None) -> dict:
    """Wandelt eine KeyframeSequence in Clip-Daten (Grad-Keys, 24 fps) um."""
    if not anim.frames:
        raise ValueError("Animation enthaelt keine Keyframes")
    clip_name = name or anim.name or "roblox_animation"
    tracks: dict[str, dict[int, tuple[float, float, float]]] = {}
    for pose_frame in anim.frames:
        frame = max(0, int(round(pose_frame.time * FPS)))
        for bone, pose in pose_frame.poses.items():
            rotation = pose.get("rotation", [1, 0, 0, 0, 1, 0, 0, 0, 1])
            euler = matrix_to_euler_deg([float(v) for v in rotation])
            tracks.setdefault(bone, {})[frame] = euler
    last_frame = max((max(keys) for keys in tracks.values()), default=0)
    total = int(duration_frames or max(2, last_frame + 1))
    for bone, keys in tracks.items():
        if 0 not in keys:
            keys[0] = (0.0, 0.0, 0.0)
        if total not in keys:
            keys[total] = keys[max(keys)]
    return {
        "name": clip_name,
        "duration": total,
        "loop": bool(anim.looped),
        "rotation": {bone: dict(sorted(keys.items())) for bone, keys in tracks.items()},
        "faces": {},
        "description": f"Roblox-Animation '{anim.name}' ({anim.kind})",
    }


def register_clip(library, anim: AnimationData, name: Optional[str] = None,
                  duration_frames: Optional[int] = None) -> str:
    """Registriert eine geladene Roblox-Animation in einer AnimationLibrary."""
    spec = animation_to_clip(anim, name, duration_frames)
    if library.has(spec["name"]):
        return spec["name"]
    library.new(spec["name"], duration=spec["duration"], loop=spec["loop"],
                description=spec["description"])
    for bone, keys in spec["rotation"].items():
        library.key(bone, keys, clip=spec["name"])
    return spec["name"]


# --------------------------------------------------------------------------- #
# Zwei-Schritt-Loader
# --------------------------------------------------------------------------- #
class AnimationLoader:
    """Laedt Emotes/Animationen ueber die Roblox-API in den Clip-Speicher."""

    def __init__(self, client, cache_dir: Path = Path("assets_cache/animations")):
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def animation_id_from_asset(self, asset_id: int) -> tuple[int, Optional[AnimationData]]:
        """Schritt 1: Asset laden und - falls es ein Animation-Objekt ist - die ID finden."""
        cache = self.cache_dir / f"asset_{asset_id}.bin"
        if cache.is_file():
            data = cache.read_bytes()
        else:
            data, _ = self.client.asset_content(asset_id)
            cache.write_bytes(data)
        # Manche Assets enthalten direkt die KeyframeSequence
        try:
            direct = parse_animation_bytes(data)
            if direct.frames:
                return asset_id, direct
        except (ValueError, NotImplementedError, ET.ParseError):
            pass
        if data.lstrip().startswith((b"<?xml", b"<roblox")):
            text = data.decode("utf-8", errors="replace")
            match = re.search(r"rbxassetid://(\d+)", text)
            if match:
                return int(match.group(1)), None
            match = re.search(r"<Content name=\"AnimationId\">.*?(\d{4,})", text, re.S)
            if match:
                return int(match.group(1)), None
        raise ValueError(f"Asset {asset_id}: keine AnimationId und keine KeyframeSequence gefunden")

    def load(self, asset_id: int, name: Optional[str] = None) -> AnimationData:
        """Kompletter Zwei-Schritt-Loader mit Cache und klaren Fehlern."""
        meta_path = self.cache_dir / f"anim_{asset_id}.json"
        payload_path = self.cache_dir / f"anim_{asset_id}.rbxmx"
        if meta_path.is_file() and payload_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            parsed = parse_animation_bytes(payload_path.read_bytes())
            parsed.name = name or meta.get("name") or parsed.name
            return parsed
        second_id, direct = self.animation_id_from_asset(asset_id)
        if direct is None:
            data, _ = self.client.asset_content(second_id)
            payload_path.write_bytes(data)
            parsed = parse_animation_bytes(data)
        else:
            parsed = direct
            payload_path.write_bytes(self.cache_dir.joinpath(f"asset_{asset_id}.bin").read_bytes())
        if name:
            parsed.name = name
        meta_path.write_text(json.dumps(parsed.summary(), ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return parsed


def load_emote_ids(path: Path = Path("3_regeln/empfohlene_emotes_und_animationen.yaml")) -> dict:
    """Liest die kuratierten Emote-IDs aus den Regeln."""
    import yaml

    if not Path(path).is_file():
        return {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Roblox-Animation pruefen")
    parser.add_argument("--file", type=Path, default=None, help="lokale .rbxmx/.rbxm")
    parser.add_argument("--asset", type=int, default=None, help="Asset-ID (Emote/Animation)")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.file:
        anim = parse_animation_bytes(args.file.read_bytes())
    elif args.asset:
        open_cloud = importlib.import_module("1_system.roblox_api.open_cloud")
        loader = AnimationLoader(open_cloud.RobloxClient())
        anim = loader.load(args.asset)
    else:
        parser.error("--file oder --asset angeben")
    summary = anim.summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(animation_to_clip(anim)["rotation"].keys().__len__()), "Bones")
    if args.json:
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

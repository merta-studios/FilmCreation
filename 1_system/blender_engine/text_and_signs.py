"""Text auf Schildern, Waenden, Tafeln und schwebenden Stadt-Regel-Zaehlern.

Drei Bausteine, die im ganzen System benutzt werden
---------------------------------------------------
* :func:`make_sign` - echtes Schild: Brett + extrudierter Text + optionaler Rahmen,
  Neon-Glow, Kratzer. Fuer Ortsschilder, Ladenfronten, Briefkaesten, Schultafeln,
  Warnschilder und Notizzettel.
* :func:`make_3d_text` - freistehender 3D-Text in beliebiger Schriftgroesse.
* :func:`make_billboard_counter` - der schwebende Zaehler ueber einem Kopf
  (BillboardGui-Stil): immer zur Kamera gedreht, mit Hintergrundplatte und
  "Plopp"-Animation beim Zahlenwechsel.

Schriftarten kommen aus :mod:`1_system.tools.font_manager` (freie OFL/Apache-Schriften,
werden bei Bedarf heruntergeladen und gecacht). Faellt das Internet aus, wird die
Blender-Standardschrift benutzt, ohne den Render abzubrechen.
"""
from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path
from typing import Optional

try:
    import bpy  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

fonts = importlib.import_module("1_system.tools.font_manager")
textures = importlib.import_module("1_system.blender_engine.roblox_textures")


def require_bpy() -> None:
    if not HAS_BPY:
        raise RuntimeError("Text/Schilder brauchen Blender (bpy).")


def get_font(style: str = "inter", allow_download: bool = True):
    """Laedt eine Schrift in Blender und gibt das Font-Objekt zurueck (oder None)."""
    require_bpy()
    path = fonts.resolve(style, allow_download=allow_download)
    if path is None:
        return None
    try:
        return bpy.data.fonts.load(str(path), check_existing=True)
    except RuntimeError:
        return None


def _text_object(name: str, body: str, size: float, font_style: str,
                 color: Optional[str], emission: Optional[float],
                 extrude: float, align_x: str = "CENTER", align_y: str = "CENTER",
                 collection=None):
    require_bpy()
    curve = bpy.data.curves.new(f"{name}_text", type="FONT")
    curve.body = body
    curve.size = size
    curve.extrude = extrude
    curve.align_x = align_x
    curve.align_y = align_y
    curve.resolution_u = 6
    font = get_font(font_style)
    if font is not None:
        curve.font = font
    obj = bpy.data.objects.new(name, curve)
    (collection or bpy.context.scene.collection).objects.link(obj)
    material = bpy.data.materials.new(f"{name}_textmat")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    rgba = textures.brickcolor_rgba(color or "#F2F3F3")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Roughness"].default_value = 0.45
        if emission:
            bsdf.inputs["Emission Color"].default_value = rgba[:3] + (1.0,)
            bsdf.inputs["Emission Strength"].default_value = float(emission)
    obj.data.materials.append(material)
    return obj


def _board(name: str, size: tuple[float, float, float], color: str,
           world, texture: str = "wood_planks", uv_scale: float = 0.6):
    require_bpy()
    obj = world.block(f"{name}_brett", (0, 0, 0), size, color=color, texture=texture,
                      uv_scale=uv_scale, bevel=0.015)
    return obj


def make_sign(world, name: str, position, text: str, size: float = 0.8,
              width: Optional[float] = None, height: Optional[float] = None,
              font: str = "oswald", color: str = "#F2F3F3",
              board_color: str = "#7C5C46", board_texture: str = "wood_planks",
              border: bool = True, border_color: str = "#E5E4DE",
              neon: float = 0.0, rotation=(0, 0, 0), rotation_z: Optional[float] = None,
              depth: float = 0.12, double_sided: bool = True, uv_scale: float = 0.6,
              collection=None):
    """Baut ein komplettes Schild an ``position`` (Tafel + Text + Rahmen).

    ``rotation`` in Grad; ``rotation_z`` ist die Kurzform fuer reine Drehung um die
    Hochachse. ``neon`` > 0 laesst die Schrift leuchten (Ladenfront bei Nacht).
    """
    require_bpy()
    if rotation_z is not None:
        rotation = (rotation[0], rotation[1], rotation_z)
    if width is None:
        width = max(0.9, len(text) * size * 0.62 + size * 0.6)
    if height is None:
        height = size * 1.9
    collection = collection or world.collection

    root = bpy.data.objects.new(name, None)
    root.empty_display_size = 0.3
    collection.objects.link(root)
    root.location = position
    root.rotation_euler = tuple(math.radians(a) for a in rotation)

    world.collection = collection
    board = _board(name, (width, depth, height), board_color, world, board_texture, uv_scale)
    board.parent = root
    board.location = (0, 0, 0)

    text_height = min(height * 0.72, size)
    label = _text_object(f"{name}_schrift", text, text_height, font, color,
                         neon if neon > 0 else None, extrude=0.012, collection=collection)
    label.parent = root
    label.location = (0, -depth / 2 - 0.02, 0)
    label.rotation_euler = (math.radians(90), 0, 0)

    if double_sided:
        back = _text_object(f"{name}_schrift_heck", text, text_height, font, color,
                            neon if neon > 0 else None, extrude=0.012, collection=collection)
        back.parent = root
        back.location = (0, depth / 2 + 0.02, 0)
        back.rotation_euler = (math.radians(-90), 0, 0)

    if border:
        for sx, sz, sw, sh in ((0, height / 2, width, 0.06), (0, -height / 2, width, 0.06),
                               (width / 2, 0, 0.06, height), (-width / 2, 0, 0.06, height)):
            rail = world.block(f"{name}_rahmen_{sx}_{sz}", (0, 0, 0),
                               (sw, depth * 1.1, sh), color=border_color, texture="metal",
                               bevel=0.005)
            rail.parent = root
            rail.location = (sx, 0, sz)

    for child in root.children:
        if child.name.startswith(f"{name}_"):
            pass
    root["text"] = text
    root["font"] = font
    world.objects[name] = root
    return root


def make_3d_text(world, name: str, position, text: str, size: float = 1.0,
                 font: str = "bebas", color: str = "#F2F3F3", extrude: float = 0.06,
                 bevel: float = 0.01, rotation=(0, 0, 0), emission: Optional[float] = None,
                 align: str = "CENTER", collection=None):
    """Freistehender 3D-Text (z. B. grosser Ortsschild-Schriftzug am Himmel)."""
    require_bpy()
    collection = collection or world.collection
    obj = _text_object(name, text, size, font, color, emission, extrude,
                       align_x=align, collection=collection)
    obj.location = position
    obj.rotation_euler = tuple(math.radians(a) for a in rotation)
    obj.data.bevel_depth = bevel
    obj.data.bevel_resolution = 2
    world.objects[name] = obj
    return obj


def make_billboard_counter(character: dict, text: str, offset_z: float = 1.15,
                           size: float = 0.32, color: str = "#FFE9A8",
                           background: str = "#101418", background_alpha: float = 0.72,
                           font: str = "spacemono", camera=None,
                           start_frame: int = 1, collection=None):
    """Schwebender Zaehler ueber dem Kopf (immer zur Kamera gedreht)."""
    require_bpy()
    collection = collection or bpy.context.scene.collection
    head = character["parts"].get("Head")
    if head is None:
        raise KeyError("Figur ohne Head-Teil")
    parent = bpy.data.objects.new(f"{character['name']}_CounterRoot", None)
    collection.objects.link(parent)
    parent.parent = head
    # Kopf-Teil ist knochengeparentet -> Zaehler sitzt ueber dem Kopf
    parent.location = (0.0, 0.0, 0.75 + offset_z)

    plate_width = max(0.7, 0.3 * len(text) * size / 0.32)
    plate = world_plate = None
    bpy.ops.mesh.primitive_plane_add(size=1.0)
    plate = bpy.context.object
    plate.name = f"{character['name']}_CounterPlate"
    for link in list(plate.users_collection):
        link.objects.unlink(plate)
    collection.objects.link(plate)
    plate.scale = (plate_width, size * 1.9, 1.0)
    material = bpy.data.materials.new(f"{character['name']}_counter_bg")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = textures.brickcolor_rgba(background)
        bsdf.inputs["Roughness"].default_value = 0.6
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = background_alpha
    material.blend_method = "BLEND"
    plate.data.materials.append(material)
    plate.parent = parent

    label = _text_object(f"{character['name']}_CounterText", text, size, font, color,
                         emission=4.0, extrude=0.004, collection=collection)
    label.parent = parent
    label.location = (0.0, 0.0, 0.012)

    scene_camera = camera or bpy.context.scene.camera
    if scene_camera is not None:
        for obj in (plate, label):
            constraint = obj.constraints.new("TRACK_TO")
            constraint.target = scene_camera
            constraint.track_axis = "TRACK_Z"
            constraint.up_axis = "UP_Y"
    if start_frame > 1:
        for obj in (plate, label):
            obj.scale = (0, 0, 0)
            obj.keyframe_insert("scale", frame=start_frame - 1)
            obj.scale = (plate.scale.x if obj is plate else 1.0,
                         plate.scale.y if obj is plate else 1.0, 1.0)
            obj.keyframe_insert("scale", frame=start_frame + 4)

    handle = {
        "root": parent, "plate": plate, "label": label,
        "labels": [label],
        "character": character["name"], "text": text,
        "size": size, "font": font, "color": color,
        "camera": scene_camera, "collection": collection,
    }
    character.setdefault("counters", []).append(handle)
    return handle


def update_counter(handle: dict, new_text: str, frame: Optional[int] = None,
                   pop: bool = True) -> None:
    """Aendert den Zaehlerstand framegenau; optional mit 'Plopp' beim Umschalten."""
    require_bpy()
    current = handle["label"]
    new_text = str(new_text)
    if current.data.body == new_text:
        return
    if frame is None:
        current.data.body = new_text
        handle["text"] = new_text
        return

    trigger_frame = max(1, int(frame))
    prev_frame = max(1, trigger_frame - 1)
    collection = handle.get("collection") or bpy.context.scene.collection
    index = len(handle.get("labels", [current]))
    next_label = _text_object(
        f"{handle['character']}_CounterText_{index}", new_text,
        float(handle.get("size", 0.28)), str(handle.get("font", "spacemono")),
        str(handle.get("color", "#FFE8A3")),
        emission=4.0, extrude=0.004, collection=collection)
    next_label.parent = handle["root"]
    next_label.location = current.location.copy()
    scene_camera = handle.get("camera") or bpy.context.scene.camera
    if scene_camera is not None:
        constraint = next_label.constraints.new("TRACK_TO")
        constraint.target = scene_camera
        constraint.track_axis = "TRACK_Z"
        constraint.up_axis = "UP_Y"

    # Altes Label bis prev_frame sichtbar, ab trigger_frame ausgeblendet
    current.hide_render = False
    current.hide_viewport = False
    current.keyframe_insert("hide_render", frame=prev_frame)
    current.keyframe_insert("hide_viewport", frame=prev_frame)
    current.hide_render = True
    current.hide_viewport = True
    current.keyframe_insert("hide_render", frame=trigger_frame)
    current.keyframe_insert("hide_viewport", frame=trigger_frame)

    # Neues Label vor trigger_frame ausgeblendet, ab trigger_frame sichtbar
    next_label.hide_render = True
    next_label.hide_viewport = True
    next_label.keyframe_insert("hide_render", frame=prev_frame)
    next_label.keyframe_insert("hide_viewport", frame=prev_frame)
    next_label.hide_render = False
    next_label.hide_viewport = False
    next_label.keyframe_insert("hide_render", frame=trigger_frame)
    next_label.keyframe_insert("hide_viewport", frame=trigger_frame)

    if pop:
        base = next_label.scale.copy()
        next_label.scale = (base.x * 1.25, base.y * 1.25, base.z)
        next_label.keyframe_insert("scale", frame=trigger_frame)
        next_label.scale = base
        next_label.keyframe_insert("scale", frame=trigger_frame + 4)

    # Hintergrundplatte verbreitern falls der neue Text laenger ist
    plate = handle.get("plate")
    if plate is not None:
        size = float(handle.get("size", 0.28))
        new_w = max(plate.scale.x, max(0.7, 0.3 * len(new_text) * size / 0.32))
        if new_w > plate.scale.x + 0.01:
            plate.keyframe_insert("scale", frame=prev_frame)
            plate.scale = (new_w, plate.scale.y, plate.scale.z)
            plate.keyframe_insert("scale", frame=trigger_frame + 2)

    handle.setdefault("labels", [current]).append(next_label)
    handle["label"] = next_label
    handle["text"] = new_text


def make_wall_text(world, name: str, position, text: str, **kwargs):
    """Text direkt auf eine Wand (ohne Brett)."""
    return make_3d_text(world, name, position, text, **kwargs)


def make_chalkboard(world, name: str, position, title: str, lines: list[str],
                    size: float = 0.22, board_color: str = "#27462D",
                    rotation_z: float = 0.0, font: str = "chalk",
                    collection=None):
    """Schultafel mit Kreideschrift (Titel gross, Zeilen darunter)."""
    require_bpy()
    collection = collection or world.collection
    width = max(3.2, size * 0.62 * max(len(line) for line in lines + [title]) + 0.8)
    height = 1.0 + len(lines) * size * 1.9
    root = make_sign(world, name, position, title, size=size * 1.5, width=width,
                     height=height, font=font, color="#F4F1E4",
                     board_color=board_color, board_texture="slate", border=True,
                     border_color="#7C5C46", rotation_z=rotation_z,
                     collection=collection)
    for index, line in enumerate(lines):
        text_obj = _text_object(f"{name}_zeile_{index}", line, size, font, "#EDE9DA",
                                None, 0.004, align_x="LEFT", collection=collection)
        text_obj.parent = root
        text_obj.location = (-width / 2 + 0.25, -0.075,
                             height / 2 - size * 2.4 - index * size * 1.7)
        text_obj.rotation_euler = (math.radians(90), 0, 0)
    return root


def list_font_styles() -> list[str]:
    return sorted(fonts.FONT_FAMILIES)

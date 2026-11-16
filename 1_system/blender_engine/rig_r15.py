"""Authentisches Roblox-R15-Rig fuer Blender (15 Koerperteile + HumanoidRootPart).

Warum starre Teile statt Skin-Skinning?
---------------------------------------
Roblox-Avatare bestehen aus starren Teilen, die ueber Motoren (Waist, Neck,
Shoulders, Elbows, Wrists, Hips, Knees, Ankles) verbunden sind. Genau so ist dieses
Rig gebaut: ein Armature ``R15`` mit einem Bone pro Koerperteil, die Mesh-Teile sind
knochengeparent und folgen dadurch exakt wie im Roblox-Studio. Das Ergebnis sieht
aus wie Roblox, nicht wie ein weich verformter Mensch - und ist dabei robust.

Enthalten
---------
* Alle 15 R15-Teile (Head, UpperTorso, LowerTorso, je 2x UpperArm/LowerArm/Hand,
  UpperLeg/LowerLeg/Foot) und ``HumanoidRootPart``.
* Alle Standard-Attachments (Haare, Huete, Gesicht, Rucken, Hals, Schulter, Halskette,
  Taille), damit Katalog-Artikel an der richtigen Stelle sitzen.
* Classic-Shirt/Hose-Farben inkl. optionalem UV-Mapping fuer echte Shirt-Texturen.
* Wechselbare Gesichter mit Blinzeln, Traenen und Sprechbewegung (Mund).
* ``set_skin_color`` fuer alle unbekleideten Teile.

Alle Masse sind in Blender-Einheiten = Roblox-Studs (Avatar ca. 6,7 hoch), damit
Kamera- und Lichtwerte im ganzen System zusammenpassen. ``height_scale`` skaliert
den kompletten Avatar (z. B. 0,92 fuer ein Kind).
"""
from __future__ import annotations

import math
from typing import Optional

try:  # bpy existiert nur in Blender / im bpy-Wheel
    import bpy  # type: ignore
    from mathutils import Vector  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover - headless Import fuer Tests/Validierung
    bpy = None  # type: ignore
    Vector = None  # type: ignore
    HAS_BPY = False

# --------------------------------------------------------------------------- #
# Reine Daten (auch ohne Blender nutzbar -> Validierung, Kamerabau, Doku)
# --------------------------------------------------------------------------- #
#: Teil -> (Breite X, Tiefe Y, Hoehe Z) in Studs
PART_SIZES: dict[str, tuple[float, float, float]] = {
    "HumanoidRootPart": (2.0, 1.0, 2.0),
    "LowerTorso": (1.9, 1.0, 1.0),
    "UpperTorso": (1.9, 1.0, 1.2),
    "Head": (1.25, 1.15, 1.2),
    "LeftUpperArm": (0.85, 0.85, 1.3),
    "LeftLowerArm": (0.8, 0.8, 1.25),
    "LeftHand": (0.8, 0.8, 0.55),
    "RightUpperArm": (0.85, 0.85, 1.3),
    "RightLowerArm": (0.8, 0.8, 1.25),
    "RightHand": (0.8, 0.8, 0.55),
    "LeftUpperLeg": (0.9, 0.9, 1.4),
    "LeftLowerLeg": (0.85, 0.85, 1.4),
    "LeftFoot": (0.9, 1.55, 0.45),
    "RightUpperLeg": (0.9, 0.9, 1.4),
    "RightLowerLeg": (0.85, 0.85, 1.4),
    "RightFoot": (0.9, 1.55, 0.45),
}

#: Teil -> Mittelpunkt (X, Y, Z) bei Standardpose, Fuesse auf Z=0, Blick nach -Y
PART_CENTERS: dict[str, tuple[float, float, float]] = {
    "HumanoidRootPart": (0.0, 0.0, 3.2),
    "LowerTorso": (0.0, 0.0, 3.7),
    "UpperTorso": (0.0, 0.0, 4.8),
    "Head": (0.0, 0.0, 6.12),
    "LeftUpperArm": (-1.35, 0.0, 4.6),
    "LeftLowerArm": (-1.35, 0.0, 3.33),
    "LeftHand": (-1.35, 0.0, 2.43),
    "RightUpperArm": (1.35, 0.0, 4.6),
    "RightLowerArm": (1.35, 0.0, 3.33),
    "RightHand": (1.35, 0.0, 2.43),
    "LeftUpperLeg": (-0.5, 0.0, 3.2),
    "LeftLowerLeg": (-0.5, 0.0, 1.72),
    "LeftFoot": (-0.5, -0.28, 0.225),
    "RightUpperLeg": (0.5, 0.0, 3.2),
    "RightLowerLeg": (0.5, 0.0, 1.72),
    "RightFoot": (0.5, -0.28, 0.225),
}

#: Bone -> (Parent, Kopfpunkt, Fusspunkt) - Gelenke exakt an den Teilgrenzen
BONE_LAYOUT: dict[str, tuple[Optional[str], tuple[float, float, float], tuple[float, float, float]]] = {
    "HumanoidRootPart": (None, (0.0, 0.0, 3.2), (0.0, 0.0, 3.7)),
    "LowerTorso": ("HumanoidRootPart", (0.0, 0.0, 3.2), (0.0, 0.0, 4.2)),
    "UpperTorso": ("LowerTorso", (0.0, 0.0, 4.2), (0.0, 0.0, 5.4)),
    "Head": ("UpperTorso", (0.0, 0.0, 5.4), (0.0, 0.0, 6.72)),
    "LeftUpperArm": ("UpperTorso", (-1.35, 0.0, 5.25), (-1.35, 0.0, 3.95)),
    "LeftLowerArm": ("LeftUpperArm", (-1.35, 0.0, 3.95), (-1.35, 0.0, 2.7)),
    "LeftHand": ("LeftLowerArm", (-1.35, 0.0, 2.7), (-1.35, 0.0, 2.15)),
    "RightUpperArm": ("UpperTorso", (1.35, 0.0, 5.25), (1.35, 0.0, 3.95)),
    "RightLowerArm": ("RightUpperArm", (1.35, 0.0, 3.95), (1.35, 0.0, 2.7)),
    "RightHand": ("RightLowerArm", (1.35, 0.0, 2.7), (1.35, 0.0, 2.15)),
    "LeftUpperLeg": ("LowerTorso", (-0.5, 0.0, 3.2), (-0.5, 0.0, 1.8)),
    "LeftLowerLeg": ("LeftUpperLeg", (-0.5, 0.0, 1.8), (-0.5, 0.0, 0.4)),
    "LeftFoot": ("LeftLowerLeg", (-0.5, 0.0, 0.4), (-0.5, -1.0, 0.4)),
    "RightUpperLeg": ("LowerTorso", (0.5, 0.0, 3.2), (0.5, 0.0, 1.8)),
    "RightLowerLeg": ("RightUpperLeg", (0.5, 0.0, 1.8), (0.5, 0.0, 0.4)),
    "RightFoot": ("RightLowerLeg", (0.5, 0.0, 0.4), (0.5, -1.0, 0.4)),
}

#: Alle Knochennamen fuer Animationen und Validierung
BONE_NAMES: tuple[str, ...] = tuple(BONE_LAYOUT.keys())

#: Welche Teile "Haut" sind (Gesicht, Haende, Koerper ohne Kleidung)
SKIN_PARTS = ("Head", "LeftHand", "RightHand")

#: Teile, die standardmaessig Shirt-/Hosenfarbe tragen
SHIRT_PARTS = ("UpperTorso", "LeftUpperArm", "RightUpperArm")
PANTS_PARTS = ("LowerTorso", "LeftUpperLeg", "RightUpperLeg",
               "LeftLowerLeg", "RightLowerLeg", "LeftFoot", "RightFoot")
SKIN_LOWER_ARMS = ("LeftLowerArm", "RightLowerArm")

#: Roblox-R15-Standard-Attachments: Name -> (Teil, Offset (X,Y,Z), Rotation XYZ Grad)
ATTACHMENTS: dict[str, tuple[str, tuple[float, float, float], tuple[float, float, float]]] = {
    "HatAttachment": ("Head", (0.0, 0.0, 0.6), (0.0, 0.0, 0.0)),
    "HairAttachment": ("Head", (0.0, 0.0, 0.45), (0.0, 0.0, 0.0)),
    "FaceFrontAttachment": ("Head", (0.0, -0.58, 0.0), (0.0, 0.0, 0.0)),
    "FaceCenterAttachment": ("Head", (0.0, -0.57, 0.0), (0.0, 0.0, 0.0)),
    "NeckAttachment": ("Head", (0.0, 0.0, -0.55), (0.0, 0.0, 0.0)),
    "FrontAttachment": ("UpperTorso", (0.0, -0.52, 0.0), (0.0, 0.0, 0.0)),
    "BackAttachment": ("UpperTorso", (0.0, 0.52, 0.0), (0.0, 0.0, 0.0)),
    "LeftCollarAttachment": ("UpperTorso", (-0.95, 0.0, 0.5), (0.0, 0.0, 0.0)),
    "RightCollarAttachment": ("UpperTorso", (0.95, 0.0, 0.5), (0.0, 0.0, 0.0)),
    "WaistCenterAttachment": ("LowerTorso", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    "LeftGripAttachment": ("LeftHand", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    "RightGripAttachment": ("RightHand", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
}

#: Gesichter: Name -> (Augen-Stil, Mund-Stil, Brauen-Winkel, Traenen)
FACES: dict[str, dict] = {
    "neutral": dict(eyes="open", mouth="line", brows=0.0, tears=False),
    "sad": dict(eyes="open_droopy", mouth="frown", brows=-14.0, tears=False),
    "crying": dict(eyes="squeezed", mouth="open_sad", brows=-18.0, tears=True),
    "hopeful": dict(eyes="open_wide", mouth="smile_small", brows=6.0, tears=False),
    "happy": dict(eyes="smile", mouth="smile", brows=8.0, tears=False),
    "surprised": dict(eyes="open_wide", mouth="o", brows=12.0, tears=False),
    "angry": dict(eyes="narrow", mouth="frown", brows=-20.0, tears=False),
    "shy": dict(eyes="look_down", mouth="line_small", brows=-4.0, tears=False),
    "tired": dict(eyes="half", mouth="line", brows=-8.0, tears=False),
    "talking": dict(eyes="open", mouth="open_mid", brows=0.0, tears=False),
}

FACE_NAMES: tuple[str, ...] = tuple(FACES.keys())

#: Material-Slots je Koerperteil (fuer Shirt/Hose/Haut/Face)
SLOT_SKIN = "skin"
SLOT_SHIRT = "shirt"
SLOT_PANTS = "pants"
SLOT_FACE = "face"


def require_bpy() -> None:
    if not HAS_BPY:
        raise RuntimeError(
            "Diese Funktion braucht Blender (bpy). Auf GitHub/Kaggle laeuft sie im "
            "Blender-Kontext, lokal z. B. mit: pip install bpy==4.2.0")


def part_height(name: str) -> float:
    return PART_SIZES[name][2]


# --------------------------------------------------------------------------- #
# Materialien
# --------------------------------------------------------------------------- #
def _material(name: str, color_rgba, roughness: float = 0.55, metallic: float = 0.0,
              emission: Optional[tuple[float, float, float, float]] = None,
              image_path: Optional[str] = None, uv_scale: float = 1.0):
    """Erzeugt (oder findet) ein Principled-Material."""
    require_bpy()
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if bsdf is None:  # pragma: no cover - sehr alte Blender-Version
        return material
    bsdf.inputs["Base Color"].default_value = color_rgba
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = emission[:3] + (1.0,)
        bsdf.inputs["Emission Strength"].default_value = emission[3] if len(emission) > 3 else 1.0
    if image_path:
        from pathlib import Path

        image = bpy.data.images.load(str(Path(image_path)), check_existing=True)
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.interpolation = "Linear"
        tex.extension = "REPEAT"
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (uv_scale, uv_scale, 1.0)
        coords = nodes.new("ShaderNodeTexCoord")
        links.new(coords.outputs["UV"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return material


def _cube_part(name: str, center, size, material, collection):
    require_bpy()
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = f"{name}_mesh"
    obj.scale = (size[0], size[1], size[2])
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for collection_link in list(obj.users_collection):
        collection_link.objects.unlink(obj)
    collection.objects.link(obj)
    # sanfte Kanten: Roblox-Teile sind leicht abgerundet
    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = min(size) * 0.08
    bevel.segments = 2
    obj.modifiers.new("Smooth", "WEIGHTED_NORMAL")
    if mesh.users == 0:  # pragma: no cover - Aufraeumen falls Blender Mesh ersetzt
        bpy.data.meshes.remove(mesh)
    return obj


# --------------------------------------------------------------------------- #
# Rig bauen
# --------------------------------------------------------------------------- #
def build_r15(name: str = "Mika", skin_color: str = "#E8BEAC", shirt_color: str = "#0D69AC",
              pants_color: str = "#1B2A35", face: str = "neutral",
              height_scale: float = 1.0, collection=None,
              face_texture_path: Optional[str] = None,
              shirt_texture_path: Optional[str] = None,
              pants_texture_path: Optional[str] = None,
              location: tuple[float, float, float] = (0.0, 0.0, 0.0),
              rotation_z_deg: float = 0.0,
              shirt_style: str = "classic") -> dict:
    """Baut einen kompletten R15-Avatar und gibt ein Charakter-Dict zurueck.

    Das Dict enthaelt: ``armature``, ``root`` (Empty fuer Weltposition),
    ``parts`` (Name->Objekt), ``bones`` (Name->Bone), ``attachments`` (Name->Empty),
    ``face``/``eyes``/``mouth`` (Gesichtsobjekte), ``scale``, ``meta``.
    """
    require_bpy()
    from importlib import import_module

    textures = import_module("1_system.blender_engine.roblox_textures")
    if collection is None:
        collection = bpy.context.scene.collection

    root = bpy.data.objects.new(f"{name}_Root", None)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.6
    root.location = location
    root.rotation_euler = (0.0, 0.0, math.radians(rotation_z_deg))
    collection.objects.link(root)

    armature_data = bpy.data.armatures.new(f"{name}_R15")
    armature = bpy.data.objects.new(f"{name}_R15", armature_data)
    armature.show_in_front = True
    collection.objects.link(armature)
    armature.parent = root

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones: dict[str, object] = {}
    for bone_name, (parent, head, tail) in BONE_LAYOUT.items():
        bone = armature_data.edit_bones.new(bone_name)
        bone.head = head
        bone.tail = tail
        bone.roll = 0.0
        edit_bones[bone_name] = bone
    for bone_name, (parent, _, _) in BONE_LAYOUT.items():
        if parent:
            edit_bones[bone_name].parent = edit_bones[parent]
            edit_bones[bone_name].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")

    skin = textures.brickcolor_rgba(skin_color)
    shirt = textures.brickcolor_rgba(shirt_color)
    pants = textures.brickcolor_rgba(pants_color)

    materials = {
        SLOT_SKIN: _material(f"{name}_skin", skin, roughness=0.62),
        SLOT_SHIRT: _material(f"{name}_shirt", shirt, roughness=0.58,
                              image_path=shirt_texture_path,
                              uv_scale=1.0 if shirt_style == "classic" else 2.0),
        SLOT_PANTS: _material(f"{name}_pants", pants, roughness=0.6,
                              image_path=pants_texture_path),
        "skin_hand": _material(f"{name}_skin_hand", skin, roughness=0.62),
    }

    parts: dict[str, object] = {}
    for part_name, size in PART_SIZES.items():
        if part_name == "HumanoidRootPart":
            continue  # nur Bone, kein sichtbares Teil
        if part_name in SKIN_PARTS:
            material = materials[SLOT_SKIN]
        elif part_name in SHIRT_PARTS:
            material = materials[SLOT_SHIRT]
        elif part_name in PANTS_PARTS:
            material = materials[SLOT_PANTS]
        else:
            material = materials["skin_hand"]
        obj = _cube_part(f"{name}_{part_name}", PART_CENTERS[part_name], size,
                         material, collection)
        obj.parent = armature
        obj.parent_type = "BONE"
        obj.parent_bone = part_name
        # Bone-Parenting nutzt das Bone-Ende als Ursprung -> Offset korrigieren
        bone_tail = BONE_LAYOUT[part_name][2]
        obj.location = (
            PART_CENTERS[part_name][0] - bone_tail[0],
            PART_CENTERS[part_name][1] - bone_tail[1],
            PART_CENTERS[part_name][2] - bone_tail[2],
        )
        obj["roblox_part"] = part_name
        parts[part_name] = obj

    # ---- Gesicht ------------------------------------------------------ #
    face_rig = _build_face(name, collection, particles_parent=parts["Head"],
                           skin=skin, face=face, texture_path=face_texture_path)

    # ---- Attachments als Empties -------------------------------------- #
    attachments: dict[str, object] = {}
    for attach_name, (part_name, offset, rotation) in ATTACHMENTS.items():
        empty = bpy.data.objects.new(f"{name}_{attach_name}", None)
        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = 0.25
        collection.objects.link(empty)
        empty.parent = parts[part_name]
        empty.location = offset
        empty.rotation_euler = tuple(math.radians(a) for a in rotation)
        empty["attachment"] = attach_name
        attachments[attach_name] = empty

    # ---- Skalierung ---------------------------------------------------- #
    if abs(height_scale - 1.0) > 1e-6:
        root.scale = (height_scale, height_scale, height_scale)

    bpy.context.view_layer.update()
    character = {
        "name": name,
        "root": root,
        "armature": armature,
        "bones": {b.name: b for b in armature.pose.bones},
        "parts": parts,
        "attachments": attachments,
        "face": face_rig["decal"],
        "eyes": face_rig["eyes"],
        "mouth": face_rig["mouth"],
        "brows": face_rig["brows"],
        "tears": face_rig["tears"],
        "scale": height_scale,
        "current_face": face,
        "collection": collection,
        "materials": materials,
        "meta": {
            "skin_color": skin_color, "shirt_color": shirt_color,
            "pants_color": pants_color, "face": face,
            "base_location": location, "rotation_z_deg": rotation_z_deg,
        },
    }
    set_face(character, face)
    return character


def _plane(name, size, location, material, collection, parent=None):
    require_bpy()
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = (size[0], size[1], 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.rotation_euler = (math.radians(90), 0.0, 0.0)
    obj.data.materials.clear()
    obj.data.materials.append(material)
    for link in list(obj.users_collection):
        link.objects.unlink(obj)
    collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def _build_face(name: str, collection, particles_parent, skin, face: str,
                texture_path: Optional[str] = None) -> dict:
    """Gesicht als Decal-Plane plus separate Augen, Brauen und Traenen."""
    require_bpy()
    head_size = PART_SIZES["Head"]
    z_front = -head_size[1] / 2 - 0.005  # Roblox blickt nach -Y
    base_z = PART_CENTERS["Head"][2]

    if texture_path:
        decal_material = _material(f"{name}_face_decal", (1, 1, 1, 1),
                                   roughness=0.5, image_path=texture_path)
        decal = _plane(f"{name}_Face", (head_size[0] * 0.94, head_size[2] * 0.94),
                       (0.0, z_front, base_z), decal_material, collection)
        return {"decal": decal, "eyes": None, "mouth": None, "brows": None, "tears": None}

    eye_material = _material(f"{name}_eye_white", (0.93, 0.94, 0.95, 1.0), roughness=0.25)
    pupil_material = _material(f"{name}_pupil", (0.05, 0.06, 0.07, 1.0), roughness=0.2)
    mouth_material = _material(f"{name}_mouth", (0.32, 0.14, 0.14, 1.0), roughness=0.55)
    brow_material = _material(f"{name}_brow", (0.18, 0.12, 0.1, 1.0), roughness=0.6)
    tear_material = _material(f"{name}_tear", (0.62, 0.82, 0.95, 1.0), roughness=0.05,
                              emission=(0.2, 0.4, 0.6, 0.25))

    eyes = []
    for side in (-1, 1):
        eye = _plane(f"{name}_Eye{side}", (0.2, 0.15),
                     (side * 0.24, z_front - 0.002, base_z + 0.1), eye_material, collection)
        pupil = _plane(f"{name}_Pupil{side}", (0.09, 0.1),
                       (side * 0.24, z_front - 0.004, base_z + 0.09), pupil_material, collection)
        pupil.parent = eye
        eyes.append(eye)
    mouth = _plane(f"{name}_Mouth", (0.26, 0.07),
                   (0.0, z_front - 0.002, base_z - 0.24), mouth_material, collection)
    brows = []
    for side in (-1, 1):
        brow = _plane(f"{name}_Brow{side}", (0.18, 0.035),
                      (side * 0.24, z_front - 0.003, base_z + 0.26), brow_material, collection)
        brows.append(brow)
    tears = []
    for side in (-1, 1):
        tear = _plane(f"{name}_Tear{side}", (0.06, 0.16),
                      (side * 0.24, z_front - 0.005, base_z - 0.06), tear_material, collection)
        tear.hide_render = True
        tear.hide_viewport = True
        tears.append(tear)
    decal = None
    return {"decal": decal, "eyes": eyes, "mouth": mouth, "brows": brows, "tears": tears}


# --------------------------------------------------------------------------- #
# Gesicht / Mimik
# --------------------------------------------------------------------------- #
def set_face(character: dict, face_name: str) -> None:
    """Setzt Augenform, Mundform, Brauen und Traenen (ohne Neuaufbau des Rig)."""
    require_bpy()
    if face_name not in FACES:
        raise KeyError(f"Unbekanntes Gesicht '{face_name}'. Erlaubt: {FACE_NAMES}")
    spec = FACES[face_name]
    character["current_face"] = face_name
    eyes = character.get("eyes") or []
    mouth = character.get("mouth")
    brows = character.get("brows") or []
    tears = character.get("tears") or []

    eye_shapes = {
        "open": (0.2, 0.15), "open_droopy": (0.2, 0.12), "squeezed": (0.2, 0.035),
        "open_wide": (0.23, 0.19), "smile": (0.2, 0.06), "narrow": (0.21, 0.06),
        "look_down": (0.19, 0.1), "half": (0.2, 0.08),
    }
    width, height = eye_shapes.get(spec["eyes"], (0.2, 0.15))
    for eye in eyes:
        eye.scale = (width, height, 1.0)
        eye.location.z = PART_CENTERS["Head"][2] + (0.14 if spec["eyes"] == "smile" else 0.1)
        for child in eye.children:
            child.location = (child.location.x, child.location.y,
                              -0.02 if spec["eyes"] in ("look_down", "half") else 0.0)

    mouth_shapes = {
        "line": (0.26, 0.05), "frown": (0.22, 0.06), "open_sad": (0.18, 0.16),
        "smile_small": (0.24, 0.09), "smile": (0.3, 0.14), "o": (0.14, 0.16),
        "line_small": (0.18, 0.045), "open_mid": (0.24, 0.14),
    }
    if mouth is not None:
        mw, mh = mouth_shapes.get(spec["mouth"], (0.26, 0.05))
        mouth.scale = (mw, mh, 1.0)
        mouth.location.z = PART_CENTERS["Head"][2] - (0.22 if mh > 0.1 else 0.24)
        if spec["mouth"] == "smile":
            mouth.rotation_euler = (math.radians(90), math.radians(180), 0.0)
        elif spec["mouth"] == "frown":
            mouth.rotation_euler = (math.radians(90), 0.0, 0.0)
        else:
            mouth.rotation_euler = (math.radians(90), 0.0, 0.0)

    for index, brow in enumerate(brows):
        side = -1.0 if index == 0 else 1.0
        brow.rotation_euler = (math.radians(90), 0.0,
                               math.radians(spec["brows"]) * side)
    for tear in tears:
        tear.hide_render = not spec["tears"]
        tear.hide_viewport = not spec["tears"]


def blink(character: dict, frame: int, duration: int = 4) -> None:
    """Keyframed ein Blinzeln (Augen schliessen und wieder oeffnen)."""
    require_bpy()
    for eye in character.get("eyes") or []:
        base = eye.scale.copy()
        for offset, factor in ((0, 1.0), (duration // 2, 0.08), (duration, 1.0)):
            eye.scale = (base.x, base.y * factor, base.z)
            eye.keyframe_insert("scale", frame=frame + offset)
        eye.scale = base


def set_talking(character: dict, start_frame: int, end_frame: int, seed: int = 0) -> None:
    """Oeffnet/schliesst den Mund unregelmaessig (Sprechbewegung waehrend einer Stimme)."""
    require_bpy()
    mouth = character.get("mouth")
    if mouth is None:
        return
    base = mouth.scale.copy()
    frame = start_frame
    step = 3
    index = 0
    while frame < end_frame:
        wobble = 0.5 + 0.5 * math.sin(frame * 0.9 + seed + index * 0.7)
        height = base.y * (0.55 + 1.35 * wobble)
        mouth.scale = (base.x * (0.95 + 0.1 * wobble), height, base.z)
        mouth.keyframe_insert("scale", frame=frame)
        frame += step
        index += 1
    mouth.scale = base


# --------------------------------------------------------------------------- #
# Koerperfarben / Kleidung
# --------------------------------------------------------------------------- #
def set_body_colors(character: dict, skin_color: Optional[str] = None,
                    shirt_color: Optional[str] = None,
                    pants_color: Optional[str] = None) -> None:
    """Aendert Farben nachtraeglich (z. B. Statue-Moment, Kostuemwechsel)."""
    require_bpy()
    from importlib import import_module

    textures = import_module("1_system.blender_engine.roblox_textures")
    materials = character["materials"]
    if skin_color:
        textures_rgba = textures.brickcolor_rgba(skin_color)
        materials[SLOT_SKIN].node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = textures_rgba
        materials["skin_hand"].node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = textures_rgba
    if shirt_color:
        materials[SLOT_SHIRT].node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = textures.brickcolor_rgba(shirt_color)
    if pants_color:
        materials[SLOT_PANTS].node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = textures.brickcolor_rgba(pants_color)


def set_stone(character: dict, enabled: bool = True) -> None:
    """Verwandelt den Avatar in eine Statue (grau, rau) - fuer 'freeze_as_statue'."""
    require_bpy()
    from importlib import import_module

    textures = import_module("1_system.blender_engine.roblox_textures")
    stone = textures.brickcolor_rgba("#9A9A95")
    for slot in (SLOT_SKIN, SLOT_SHIRT, SLOT_PANTS, "skin_hand"):
        material = character["materials"].get(slot)
        if not material or not material.use_nodes:
            continue
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        if not bsdf:
            continue
        bsdf.inputs["Base Color"].default_value = stone if enabled else (
            textures.brickcolor_rgba(
                character["meta"].get("shirt_color", "#0D69AC") if slot == SLOT_SHIRT else
                character["meta"].get("pants_color", "#1B2A35") if slot == SLOT_PANTS else
                character["meta"].get("skin_color", "#E8BEAC")))
        bsdf.inputs["Roughness"].default_value = 0.92 if enabled else 0.58


def place_character(character: dict, x: float, y: float, z: float = 0.0,
                    rotation_z_deg: float = 0.0) -> None:
    """Setzt den Avatar auf den Boden (Fusssohle = z) und dreht ihn."""
    require_bpy()
    root = character["root"]
    root.location = (x, y, z)
    root.rotation_euler = (0.0, 0.0, math.radians(rotation_z_deg))


def character_head_world(character: dict) -> tuple[float, float, float]:
    """Weltposition des Kopfes (ohne Blender-Abhaengigkeit berechenbar)."""
    root = character.get("_location") or character["meta"]["base_location"]
    scale = float(character.get("scale", 1.0))
    return (root[0], root[1], root[2] + PART_CENTERS["Head"][2] * scale + 0.6 * scale)


def character_eye_height(height_scale: float = 1.0) -> float:
    """Augenhoehe in Weltkoordinaten (fuer Kamera-Framing und Safe-Zone-Checks)."""
    return PART_CENTERS["Head"][2] * height_scale


def attach_to_slot(character: dict, slot: str, obj, scale: float = 1.0,
                   offset: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
    """Haengt ein importiertes Objekt an ein Standard-Attachment (Hut, Haare, Rucksack)."""
    require_bpy()
    if slot not in character["attachments"]:
        raise KeyError(f"Unbekanntes Attachment '{slot}'. Erlaubt: {sorted(character['attachments'])}")
    obj.parent = character["attachments"][slot]
    obj.location = offset
    obj.scale = (scale, scale, scale)


def bone_rotation(character: dict, bone: str, degrees: tuple[float, float, float],
                  frame: Optional[int] = None) -> None:
    """Setzt (optional keyframed) eine Bone-Rotation in Grad."""
    require_bpy()
    pose_bone = character["bones"].get(bone)
    if pose_bone is None:
        raise KeyError(f"Unbekannter Bone '{bone}'. Erlaubt: {BONE_NAMES}")
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = tuple(math.radians(a) for a in degrees)
    if frame is not None:
        pose_bone.keyframe_insert("rotation_euler", frame=frame)


def reset_pose(character: dict) -> None:
    require_bpy()
    for pose_bone in character["bones"].values():
        pose_bone.rotation_mode = "XYZ"
        pose_bone.rotation_euler = (0.0, 0.0, 0.0)
        pose_bone.location = (0.0, 0.0, 0.0)


if __name__ == "__main__":  # pragma: no cover
    print(f"R15-Rig mit {len(BONE_NAMES)} Bones: {', '.join(BONE_NAMES)}")
    print(f"Gesichter: {', '.join(FACE_NAMES)}")
    print(f"Attachments: {', '.join(ATTACHMENTS)}")

"""Formen-Baukasten + organische Stadt-Generatoren fuer Blender.

Ein-Zeilen-API
--------------
Jede Form ist eine Methode von :class:`WorldBuilder`::

    w = WorldBuilder(collection)
    w.organic_ground("boden", size=(70, 70), hills=1.6, texture="grass")
    w.curved_road("strasse", [(0, -30), (3, -10), (-4, 8), (2, 26)], width=5.0)
    w.block("haus", (8, -6, 3), (5, 6, 6), color="brick yellow", texture="classic_brick")
    w.gable_roof("dach", (8, -6, 6.4), (5.8, 6.8), height=2.2, rotation_z=8)
    w.hanging_cable("kabel", (0, -6, 7), (0, 12, 6.2), sag=0.9)

Verfuegbare Formen
------------------
``block``, ``cylinder``, ``ball``, ``wedge``, ``corner_wedge``, ``cone``, ``arch``,
``torus``, ``truss``, ``stairs``, ``gable_roof``, ``hanging_cable``,
``organic_ground``, ``curved_road``, ``puddle``, ``fence``, ``tree``, ``bush``,
``grass_tuft``, ``stone``, ``street_lamp``, ``bench``, ``bicycle``, ``mailbox``,
``trash_can``, ``window_light``, ``pipe``, ``scatter``, ``import_model``.

Jedes Objekt kann eine Roblox-``BrickColor`` (Name/Nummer/Hex) und eine Textur
aus ``roblox_textures.TEXTURE_CATALOG`` bekommen. Fuer den 2006er-Look lassen sich
Wuerfelflaechen einzeln texturieren (``top_texture``, ``bottom_texture``,
``side_texture``) - genau wie die alten Roblox-Surfaces.
"""
from __future__ import annotations

import importlib
import math
import random
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence

try:
    import bpy  # type: ignore
    from mathutils import Vector, Euler  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    Vector = Euler = None  # type: ignore
    HAS_BPY = False

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

textures = importlib.import_module("1_system.blender_engine.roblox_textures")

SHAPE_TYPES = (
    "block", "cylinder", "ball", "wedge", "corner_wedge", "cone", "arch", "torus",
    "truss", "stairs", "gable_roof", "hanging_cable", "organic_ground",
    "curved_road", "puddle", "fence", "tree", "bush", "grass_tuft", "stone",
    "street_lamp", "bench", "bicycle", "mailbox", "trash_can", "window_light",
    "pipe", "scatter", "import_model", "sign", "billboard_counter", "text3d",
    "custom_model", "creator_store",
)


def require_bpy() -> None:
    if not HAS_BPY:
        raise RuntimeError("Formen brauchen Blender (bpy). Headless nur fuer Validierung nutzen.")


# --------------------------------------------------------------------------- #
# Textur-/Materialbibliothek
# --------------------------------------------------------------------------- #
class TextureLibrary:
    """Erzeugt und cached Blender-Materialien mit echten Bild-Texturen."""

    def __init__(self, cache_dir: Path = Path("assets_cache/textures"),
                 size: int = 512, preview: bool = False):
        require_bpy()
        self.cache_dir = Path(cache_dir)
        self.size = textures.TEXTURE_SIZE_PREVIEW if preview else int(size)
        self._manifest: dict[str, dict[str, str]] = {}
        self._materials: dict[tuple, object] = {}

    def manifest(self, keys: Iterable[str]) -> dict[str, dict[str, str]]:
        keys = [k for k in dict.fromkeys(keys) if k]
        missing = [k for k in keys if k not in self._manifest]
        if missing:
            self._manifest.update(textures.ensure_texture_files(missing, self.cache_dir, self.size))
        return {k: self._manifest[k] for k in keys}

    def material(self, texture_key: str = "smooth_plastic",
                 color: Optional[str] = None, era: str = "modern",
                 uv_scale: float = 1.0, roughness: Optional[float] = None,
                 emission: Optional[float] = None, image: Optional[str] = None):
        require_bpy()
        texture_key = texture_key or textures.texture_for_material("plastic", era)
        if texture_key not in textures.TEXTURE_CATALOG:
            raise KeyError(f"Unbekannte Textur '{texture_key}'. Erlaubt: {sorted(textures.TEXTURE_CATALOG)}")
        key = (texture_key, color, era, round(uv_scale, 3), roughness, emission, image)
        if key in self._materials:
            return self._materials[key]
        pbr = textures.material_pbr(texture_key)
        paths = self.manifest([texture_key])[texture_key]
        material = bpy.data.materials.new(f"mat_{texture_key}_{abs(hash(key)) % 99999}")
        material.use_nodes = True
        nodes, links = material.node_tree.nodes, material.node_tree.links
        bsdf = nodes.get("Principled BSDF")
        bsdf.inputs["Roughness"].default_value = pbr["roughness"] if roughness is None else roughness
        bsdf.inputs["Metallic"].default_value = pbr["metallic"]
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = pbr["transmission"]
        elif "Transmission" in bsdf.inputs:  # aeltere Blender-Version
            bsdf.inputs["Transmission"].default_value = pbr["transmission"]
        if pbr["emission_strength"] > 0 or emission:
            strength = emission if emission is not None else pbr["emission_strength"]
            bsdf.inputs["Emission Color"].default_value = textures.brickcolor_rgba(color or pbr["base_color"])
            bsdf.inputs["Emission Strength"].default_value = float(strength)
        if color:
            tint = textures.brickcolor_rgba(color)
            bsdf.inputs["Base Color"].default_value = tint
        # Bild-Texturen mit Box-UV
        coords = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (uv_scale, uv_scale, 1.0)
        links.new(coords.outputs["UV"], mapping.inputs["Vector"])
        albedo = nodes.new("ShaderNodeTexImage")
        albedo.image = bpy.data.images.load(paths["albedo"], check_existing=True)
        links.new(mapping.outputs["Vector"], albedo.inputs["Vector"])
        if color:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs[0].default_value = 0.65
            links.new(albedo.outputs["Color"], mix.inputs[6])
            mix.inputs[7].default_value = textures.brickcolor_rgba(color)
            links.new(mix.outputs[2], bsdf.inputs["Base Color"])
        else:
            links.new(albedo.outputs["Color"], bsdf.inputs["Base Color"])
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.inputs["Strength"].default_value = 0.6
        normal_tex = nodes.new("ShaderNodeTexImage")
        normal_tex.image = bpy.data.images.load(paths["normal"], check_existing=True)
        normal_tex.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], normal_tex.inputs["Vector"])
        links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        rough_tex = nodes.new("ShaderNodeTexImage")
        rough_tex.image = bpy.data.images.load(paths["roughness"], check_existing=True)
        rough_tex.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs["Vector"], rough_tex.inputs["Vector"])
        links.new(rough_tex.outputs["Color"], bsdf.inputs["Roughness"])
        if image:
            decal = nodes.new("ShaderNodeTexImage")
            decal.image = bpy.data.images.load(str(image), check_existing=True)
            links.new(decal.outputs["Color"], bsdf.inputs["Base Color"])
        self._materials[key] = material
        return material


# --------------------------------------------------------------------------- #
# Mesh-Helfer
# --------------------------------------------------------------------------- #
def _new_object(name: str, mesh, collection, material=None):
    require_bpy()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if material is not None:
        obj.data.materials.append(material)
    return obj


def _box_uv(obj, scale: float = 1.0) -> None:
    """Box-Projektion der UVs, damit gekachelte Texturen ueberall gleich gross sind."""
    require_bpy()
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers.active.data
    for polygon in mesh.polygons:
        normal = polygon.normal
        axis = max(range(3), key=lambda i: abs(normal[i]))
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            if axis == 0:
                uv = (vertex.y, vertex.z)
            elif axis == 1:
                uv = (vertex.x, vertex.z)
            else:
                uv = (vertex.x, vertex.y)
            uv_layer[loop_index].uv = (uv[0] * scale, uv[1] * scale)


def _boxes_mesh(name: str, boxes: Sequence[tuple[tuple, tuple]], material, collection,
                uv_scale: float = 1.0):
    """Mehrere Quader in einem Mesh (fuer Traeger, Zaeune, Treppen, Baenke)."""
    require_bpy()
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    for center, size in boxes:
        cx, cy, cz = center
        sx, sy, sz = (s / 2 for s in size)
        base = len(verts)
        for dz in (-1, 1):
            for dy in (-1, 1):
                for dx in (-1, 1):
                    verts.append((cx + dx * sx, cy + dy * sy, cz + dz * sz))
        # 8 Ecken in Reihenfolge (dz, dy, dx)
        quads = [
            (0, 1, 3, 2), (4, 6, 7, 5),   # unten / oben
            (0, 4, 5, 1), (2, 3, 7, 6),   # -z / +z ... konsistent gewickelt
            (0, 2, 6, 4), (1, 5, 7, 3),
        ]
        for quad in quads:
            faces.append(tuple(base + i for i in quad))
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    mesh.update()
    obj = _new_object(name, mesh, collection, material)
    _box_uv(obj, uv_scale)
    return obj


def _set_rotation(obj, rotation_xyz_deg: Sequence[float]) -> None:
    require_bpy()
    obj.rotation_euler = tuple(math.radians(float(a)) for a in rotation_xyz_deg[:3])


def _add_bevel(obj, width: float = 0.03, segments: int = 2) -> None:
    require_bpy()
    bevel = obj.modifiers.new("Bevel", "BEVEL")
    bevel.width = max(0.004, width)
    bevel.segments = segments
    obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")


def _noise(u: float, v: float, seed: float) -> float:
    """Deterministisches, glattes Pseudorauschen (ohne numpy)."""
    return (math.sin(u * 3.1 + seed) * math.cos(v * 2.7 - seed) * 0.5
            + math.sin(u * 7.3 - seed * 1.7) * math.cos(v * 5.1 + seed * 0.6) * 0.3
            + math.sin((u + v) * 11.0 + seed) * 0.2)


# --------------------------------------------------------------------------- #
# WorldBuilder
# --------------------------------------------------------------------------- #
class WorldBuilder:
    """Sammelt alle Stadt-Objekte eines Shots in einer Collection."""

    def __init__(self, collection=None, texture_library: Optional[TextureLibrary] = None,
                 era: str = "modern", preview: bool = False):
        require_bpy()
        self.collection = collection or bpy.context.scene.collection
        self.textures = texture_library or TextureLibrary(preview=preview)
        self.era = era
        self.objects: dict[str, object] = {}
        self._rng = random.Random(20260101)

    # -- intern ---------------------------------------------------------- #
    def _material_for(self, texture_key: Optional[str], color: Optional[str],
                      metallic: Optional[str], uv_scale: float, emission: Optional[float],
                      image: Optional[str] = None):
        era = self.era
        if texture_key:
            resolved = texture_key
        else:
            resolved = textures.texture_for_material(metallic or "plastic", era)
        return self.textures.material(resolved, color=color, era=era,
                                      uv_scale=uv_scale, emission=emission, image=image)

    def _register(self, name: str, obj):
        self.objects[name] = obj
        return obj

    def _cube(self, name: str, pos, size, material, rotation=(0, 0, 0), bevel: float = 0.02):
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        sx, sy, sz = (s / 2 for s in size)
        verts = [(x * sx, y * sy, z * sz) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 2, 6, 4), (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6)]
        mesh.from_pydata(verts, [], faces)
        mesh.validate()
        mesh.update()
        obj = _new_object(name, mesh, self.collection, material)
        obj.location = pos
        _set_rotation(obj, rotation)
        _box_uv(obj, 1.0)
        if bevel > 0:
            _add_bevel(obj, bevel)
        return obj

    # -- Grundformen ----------------------------------------------------- #
    def block(self, name: str, pos, size, color: Optional[str] = None,
              texture: Optional[str] = None, material: Optional[str] = None,
              rotation=(0, 0, 0), top_texture: Optional[str] = None,
              bottom_texture: Optional[str] = None, side_texture: Optional[str] = None,
              uv_scale: float = 0.5, bevel: float = 0.02, era: Optional[str] = None,
              emission: Optional[float] = None):
        """Wuerfel/Quader - mit optionalen Flaechentexturen wie 2006."""
        require_bpy()
        if era:
            self.era = era
        main = self._material_for(texture or side_texture, color, material, uv_scale, emission)
        obj = self._cube(name, pos, size, main, rotation, bevel)
        if top_texture or bottom_texture:
            top = self._material_for(top_texture or texture, color, material, uv_scale, emission)
            bottom = self._material_for(bottom_texture or texture, color, material, uv_scale, emission)
            obj.data.materials.clear()
            # Slot-Reihenfolge: 0=Seiten, 1=oben, 2=unten
            obj.data.materials.append(main)
            obj.data.materials.append(top)
            obj.data.materials.append(bottom)
            mesh = obj.data
            for polygon in mesh.polygons:
                if polygon.normal.z > 0.7:
                    polygon.material_index = 1
                elif polygon.normal.z < -0.7:
                    polygon.material_index = 2
                else:
                    polygon.material_index = 0
            _box_uv(obj, 1.0)
        return self._register(name, obj)

    def cylinder(self, name: str, pos, radius: float, depth: float,
                 color: Optional[str] = None, texture: Optional[str] = None,
                 material: Optional[str] = None, rotation=(0, 0, 0),
                 vertices: int = 24, cap_texture: Optional[str] = None):
        require_bpy()
        mat = self._material_for(texture, color, material, 1.0, None)
        bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius,
                                            depth=depth, location=pos)
        obj = bpy.context.object
        obj.name = name
        for link in list(obj.users_collection):
            link.objects.unlink(obj)
        self.collection.objects.link(obj)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        if cap_texture:
            obj.data.materials.append(self._material_for(cap_texture, color, material, 1.0, None))
            for polygon in obj.data.polygons:
                if abs(polygon.normal.z) > 0.7:
                    polygon.material_index = 1
        _box_uv(obj, 0.6)
        _set_rotation(obj, rotation)
        return self._register(name, obj)

    def ball(self, name: str, pos, radius: float, color: Optional[str] = None,
             texture: Optional[str] = None, material: Optional[str] = None,
             segments: int = 24, rotation=(0, 0, 0), smooth: bool = True):
        require_bpy()
        mat = self._material_for(texture, color, material, 1.0, None)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=segments // 2,
                                             radius=radius, location=pos)
        obj = bpy.context.object
        obj.name = name
        for link in list(obj.users_collection):
            link.objects.unlink(obj)
        self.collection.objects.link(obj)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        if smooth:
            bpy.ops.object.shade_smooth()
        _box_uv(obj, 0.5)
        _set_rotation(obj, rotation)
        return self._register(name, obj)

    def wedge(self, name: str, pos, size, color: Optional[str] = None,
              texture: Optional[str] = None, rotation=(0, 0, 0), flip: bool = False):
        """Klassischer Roblox-Wedge (Dreiecksprisma)."""
        require_bpy()
        w, d, h = size
        sign = -1 if flip else 1
        verts = [
            (-w / 2, -d / 2, 0), (w / 2, -d / 2, 0),
            (sign * w / 2, -d / 2, h), (-sign * w / 2, -d / 2, h),
            (-w / 2, d / 2, 0), (w / 2, d / 2, 0),
            (sign * w / 2, d / 2, h), (-sign * w / 2, d / 2, h),
        ]
        faces = [(0, 1, 5, 4), (0, 4, 7, 3), (1, 2, 6, 5), (3, 7, 6, 2), (0, 3, 2, 1), (4, 5, 6, 7)]
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.validate()
        mesh.update()
        obj = _new_object(name, mesh, self.collection,
                          self._material_for(texture, color, "plastic", 0.6, None))
        obj.location = pos
        _set_rotation(obj, rotation)
        _box_uv(obj, 0.6)
        _add_bevel(obj, 0.01)
        return self._register(name, obj)

    def corner_wedge(self, name: str, pos, size, color=None, texture=None, rotation=(0, 0, 0)):
        require_bpy()
        w, d, h = size
        verts = [(-w / 2, -d / 2, 0), (w / 2, -d / 2, 0), (w / 2, d / 2, 0), (-w / 2, d / 2, 0),
                 (-w / 2, -d / 2, h), (w / 2, d / 2, h)]
        faces = [(0, 1, 2, 3), (0, 4, 1), (3, 2, 5), (0, 3, 5, 4), (1, 4, 5, 2)]
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.validate()
        mesh.update()
        obj = _new_object(name, mesh, self.collection,
                          self._material_for(texture, color, "plastic", 0.6, None))
        obj.location = pos
        _set_rotation(obj, rotation)
        _box_uv(obj, 0.6)
        return self._register(name, obj)

    def cone(self, name: str, pos, radius: float, depth: float, color=None,
             texture=None, rotation=(0, 0, 0), vertices: int = 20):
        require_bpy()
        mat = self._material_for(texture, color, "plastic", 0.6, None)
        bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius, radius2=0.0,
                                        depth=depth, location=pos)
        obj = bpy.context.object
        obj.name = name
        for link in list(obj.users_collection):
            link.objects.unlink(obj)
        self.collection.objects.link(obj)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        _box_uv(obj, 0.6)
        _set_rotation(obj, rotation)
        return self._register(name, obj)

    def arch(self, name: str, pos, width: float, height: float, depth: float,
             thickness: float = 0.4, segments: int = 16, color=None, texture=None,
             rotation=(0, 0, 0)):
        """Runder Torbogen (mesh-basiert, halber Ring)."""
        require_bpy()
        verts = []
        faces = []
        inner = width / 2 - thickness
        for i in range(segments + 1):
            angle = math.pi * i / segments
            ox, oz = math.cos(angle) * width / 2, math.sin(angle) * height
            ix, iz = math.cos(angle) * inner, math.sin(angle) * max(0.05, height - thickness)
            for dy in (-depth / 2, depth / 2):
                verts.append((ox, dy, oz))
                verts.append((ix, dy, iz))
        for i in range(segments):
            base = i * 4
            faces.extend([
                (base + 0, base + 2, base + 6, base + 4),
                (base + 1, base + 5, base + 7, base + 3),
                (base + 4, base + 6, base + 7, base + 5),
                (base + 0, base + 1, base + 3, base + 2),
            ])
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.validate()
        mesh.update()
        obj = _new_object(name, mesh, self.collection,
                          self._material_for(texture, color, "concrete", 0.6, None))
        obj.location = pos
        _set_rotation(obj, rotation)
        _box_uv(obj, 0.5)
        return self._register(name, obj)

    def torus(self, name: str, pos, major_radius: float = 1.0, minor_radius: float = 0.2,
              color=None, texture=None, rotation=(0, 0, 0), major_segments: int = 32,
              minor_segments: int = 12):
        require_bpy()
        mat = self._material_for(texture, color, "metal", 1.0, None)
        bpy.ops.mesh.primitive_torus_add(major_radius=major_radius, minor_radius=minor_radius,
                                         major_segments=major_segments,
                                         minor_segments=minor_segments, location=pos)
        obj = bpy.context.object
        obj.name = name
        for link in list(obj.users_collection):
            link.objects.unlink(obj)
        self.collection.objects.link(obj)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        _set_rotation(obj, rotation)
        return self._register(name, obj)

    def truss(self, name: str, pos, size, color=None, texture=None, rotation=(0, 0, 0),
              segments: int = 3):
        """Fachwerk-Traeger aus Stahlstaeben (Roblox-TrussPart-Look)."""
        require_bpy()
        w, d, h = size
        bar = min(w, d) * 0.16
        boxes = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                boxes.append((((sx * (w / 2 - bar / 2)), (sy * (d / 2 - bar / 2)), 0),
                              (bar, bar, h)))
        step = h / max(1, segments)
        for i in range(segments):
            z = -h / 2 + step * (i + 0.5)
            boxes.append(((0, -d / 2 + bar / 2, z), (w - bar, bar * 0.7, bar * 0.7)))
            boxes.append(((0, 0, z), (bar * 0.7, d - bar, bar * 0.7)))
        mat = self._material_for(texture or "classic_diamond_plate", color, "metal", 1.0, None)
        obj = _boxes_mesh(name, boxes, mat, self.collection)
        obj.location = pos
        _set_rotation(obj, rotation)
        return self._register(name, obj)

    def stairs(self, name: str, pos, width: float, height: float, depth: float,
               steps: int = 8, color=None, texture=None, rotation=(0, 0, 0)):
        require_bpy()
        boxes = []
        rise = height / steps
        run = depth / steps
        for i in range(steps):
            boxes.append(((0, -depth / 2 + run * (i + 0.5), -height / 2 + rise * (i + 0.5)),
                          (width, run * 1.02, rise)))
        mat = self._material_for(texture or "concrete", color, "concrete", 0.6, None)
        obj = _boxes_mesh(name, boxes, mat, self.collection)
        obj.location = pos
        _set_rotation(obj, rotation)
        return self._register(name, obj)

    def gable_roof(self, name: str, pos, footprint, height: float = 2.0,
                   color=None, texture=None, rotation=(0, 0, 0), overhang: float = 0.35):
        """Satteldach als Prisma."""
        require_bpy()
        w, d = footprint
        w += overhang * 2
        d += overhang * 2
        verts = [(-w / 2, -d / 2, 0), (w / 2, -d / 2, 0), (w / 2, d / 2, 0), (-w / 2, d / 2, 0),
                 (-w / 2, 0, height), (w / 2, 0, height)]
        faces = [(0, 1, 5, 4), (2, 3, 4, 5), (0, 4, 3), (1, 2, 5), (0, 3, 2, 1)]
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.validate()
        mesh.update()
        mat = self._material_for(texture or "roof_shingles", color, "slate", 0.7, None)
        obj = _new_object(name, mesh, self.collection, mat)
        obj.location = pos
        _set_rotation(obj, rotation)
        _box_uv(obj, 0.6)
        return self._register(name, obj)

    def hanging_cable(self, name: str, start, end, sag: float = 0.8,
                      radius: float = 0.035, color=None, texture=None,
                      segments: int = 14, bulbs: bool = True,
                      bulb_color: str = "#FFD79A"):
        """Durchhaengende Stromleitung/Lichterkette als Kurve mit echten Katheten."""
        require_bpy()
        curve_data = bpy.data.curves.new(f"{name}_curve", type="CURVE")
        curve_data.dimensions = "3D"
        curve_data.bevel_depth = radius
        curve_data.bevel_resolution = 2
        spline = curve_data.splines.new("POLY")
        spline.points.add(segments)
        for i in range(segments + 1):
            t = i / segments
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            z = start[2] + (end[2] - start[2]) * t - sag * math.sin(math.pi * t)
            spline.points[i].co = (x, y, z, 1.0)
        obj = _new_object(name, curve_data, self.collection,
                          self._material_for(texture or "classic_plastic", color or "#1B2A35",
                                             "fabric", 1.0, None))
        if bulbs:
            bulb_mat = self._material_for(None, bulb_color, "neon", 1.0, 2.5)
            for i in range(2, segments - 1, 3):
                t = i / segments
                x = start[0] + (end[0] - start[0]) * t
                y = start[1] + (end[1] - start[1]) * t
                z = start[2] + (end[2] - start[2]) * t - sag * math.sin(math.pi * t)
                bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=6, radius=0.075,
                                                     location=(x, y, z - 0.12))
                bulb = bpy.context.object
                bulb.name = f"{name}_birne_{i}"
                for link in list(bulb.users_collection):
                    link.objects.unlink(bulb)
                self.collection.objects.link(bulb)
                bulb.data.materials.clear()
                bulb.data.materials.append(bulb_mat)
        return self._register(name, obj)

    # -- Organische Stadt ------------------------------------------------ #
    def organic_ground(self, name: str = "boden", size: tuple[float, float] = (80.0, 80.0),
                       subdivisions: int = 64, hills: float = 1.2, roughness: float = 0.5,
                       texture: str = "grass", color: Optional[str] = None,
                       seed: float = 3.7, base_z: float = 0.0):
        """Sanft gewellter Boden mit echten Hoehen (kein flaches Schachbrett)."""
        require_bpy()
        nx = ny = max(8, subdivisions)
        sx, sy = size
        verts: list[tuple[float, float, float]] = []
        for j in range(ny + 1):
            v = j / ny
            for i in range(nx + 1):
                u = i / nx
                x = (u - 0.5) * sx
                y = (v - 0.5) * sy
                edge = min(u, 1 - u, v, 1 - v) * 2.0
                falloff = min(1.0, edge * 3.0)
                z = base_z + (_noise(u * 2.4, v * 2.4, seed) * hills
                              + _noise(u * 7.1, v * 6.3, seed + 4) * hills * roughness * 0.35) * falloff
                verts.append((x, y, z))
        faces = []
        for j in range(ny):
            for i in range(nx):
                a = j * (nx + 1) + i
                b = a + 1
                c = a + nx + 1
                d = c + 1
                faces.append((a, b, d, c))
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.validate()
        mesh.update()
        mat = self._material_for(texture, color, "grass", 0.12, None)
        obj = _new_object(name, mesh, self.collection, mat)
        _box_uv(obj, 0.12)
        for polygon in mesh.polygons:
            polygon.use_smooth = True
        return self._register(name, obj)

    def curved_road(self, name: str = "strasse", points: Sequence[Sequence[float]] = (),
                    width: float = 5.0, texture: str = "asphalt",
                    sidewalk: float = 1.2, sidewalk_texture: str = "pavement",
                    curb_height: float = 0.12, color: Optional[str] = None,
                    z: float = 0.03, seed: float = 1.0):
        """Geschwungene Strasse mit Gehwegen - aus einer Punktliste (Bezier-artig)."""
        require_bpy()
        if len(points) < 2:
            raise ValueError("curved_road braucht mindestens 2 Punkte")
        # Catmull-Rom-Interpolation fuer weiche Kurven
        dense: list[tuple[float, float]] = []
        pts = [(float(p[0]), float(p[1])) for p in points]
        for i in range(len(pts) - 1):
            p0 = pts[max(0, i - 1)]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[min(len(pts) - 1, i + 2)]
            for t in (0.0, 0.25, 0.5, 0.75):
                t2, t3 = t * t, t * t * t
                x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                           + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                           + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
                y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                           + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                           + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                dense.append((x, y))
        dense.append(pts[-1])

        def ribbon(offset: float, half_width: float, height: float, texture_key: str,
                   object_name: str):
            verts = []
            faces = []
            for index, (x, y) in enumerate(dense):
                prev = dense[max(0, index - 1)]
                nxt = dense[min(len(dense) - 1, index + 1)]
                dx, dy = nxt[0] - prev[0], nxt[1] - prev[1]
                length = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / length, dx / length
                cx = x + nx * offset
                cy = y + ny * offset
                verts.append((cx + nx * half_width, cy + ny * half_width, height))
                verts.append((cx - nx * half_width, cy - ny * half_width, height))
            for i in range(len(dense) - 1):
                a = i * 2
                faces.append((a, a + 1, a + 3, a + 2))
            mesh = bpy.data.meshes.new(f"{object_name}_mesh")
            mesh.from_pydata(verts, [], faces)
            mesh.validate()
            mesh.update()
            mat = self._material_for(texture_key, color, texture_key, 0.25, None)
            obj = _new_object(object_name, mesh, self.collection, mat)
            obj.location = (0.0, 0.0, z)
            _box_uv(obj, 0.25)
            return obj

        road = ribbon(0.0, width / 2, 0.0, texture, name)
        ribbons = [road]
        if sidewalk > 0:
            for side in (-1, 1):
                ribbons.append(ribbon(side * (width / 2 + sidewalk / 2), sidewalk / 2,
                                      curb_height, sidewalk_texture, f"{name}_gehweg_{side}"))
        self._register(name, road)
        return road

    def puddle(self, name: str, pos, radius: float = 1.4, color: str = "#2C3A44"):
        """Pfuetze als flache, leicht spiegelnde Scheibe (nasse Daemmerung)."""
        require_bpy()
        mat = self.textures.material("water", color=color, era=self.era, uv_scale=1.0,
                                     roughness=0.05)
        bpy.ops.mesh.primitive_circle_add(vertices=28, radius=radius, fill_type="NGON",
                                          location=pos)
        obj = bpy.context.object
        obj.name = name
        for link in list(obj.users_collection):
            link.objects.unlink(obj)
        self.collection.objects.link(obj)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        obj.scale.z = 0.02
        return self._register(name, obj)

    def fence(self, name: str, start, end, height: float = 1.5, posts: int = 6,
              color: str = "#7C5C46", texture: str = "wood", rotation=0.0):
        require_bpy()
        x0, y0 = start[0], start[1]
        x1, y1 = end[0], end[1]
        boxes = []
        for i in range(posts):
            t = i / max(1, posts - 1)
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            boxes.append(((x, y, height / 2), (0.12, 0.12, height)))
        boxes.append((((x0 + x1) / 2, (y0 + y1) / 2, height * 0.72),
                      (abs(x1 - x0) or 0.12, abs(y1 - y0) or 0.12, 0.1)))
        boxes.append((((x0 + x1) / 2, (y0 + y1) / 2, height * 0.42),
                      (abs(x1 - x0) or 0.12, abs(y1 - y0) or 0.12, 0.1)))
        mat = self._material_for(texture, color, "wood", 0.5, None)
        obj = _boxes_mesh(name, boxes, mat, self.collection, 0.5)
        _set_rotation(obj, (0, 0, rotation))
        return self._register(name, obj)

    def tree(self, name: str, pos, height: float = 6.0, crown: float = 1.0,
             trunk_color: str = "#694028", leaf_color: str = "#3F6B34",
             seed: float = 1.0, era: Optional[str] = None):
        """Organischer Baum: krummer Stamm, mehrlagige Blattkronen."""
        require_bpy()
        if era:
            self.era = era
        trunk_mat = self._material_for("wood", trunk_color, "wood", 0.6, None)
        leaf_tex = "classic_grass" if self.era == "classic" else "leafy_grass"
        leaf_mat = self._material_for(leaf_tex, leaf_color, "grass", 0.6, None)
        lean = _noise(pos[0] * 0.3, pos[1] * 0.3, seed) * 0.5
        bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=height * 0.055,
                                        radius2=height * 0.03, depth=height * 0.62,
                                        location=(pos[0] + lean * 0.3, pos[1], pos[2] + height * 0.31))
        trunk = bpy.context.object
        trunk.name = f"{name}_stamm"
        for link in list(trunk.users_collection):
            link.objects.unlink(trunk)
        self.collection.objects.link(trunk)
        trunk.data.materials.clear()
        trunk.data.materials.append(trunk_mat)
        _set_rotation(trunk, (lean * 4, 0, 0))
        crowns = []
        for index, (offset_z, scale) in enumerate(((0.62, 1.0), (0.82, 0.72), (0.97, 0.45))):
            bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=height * 0.3 * crown * scale,
                                                  location=(pos[0] + lean * (0.4 + index * 0.2),
                                                            pos[1] + _noise(index, seed, seed) * 0.3,
                                                            pos[2] + height * offset_z))
            blob = bpy.context.object
            blob.name = f"{name}_krone_{index}"
            for link in list(blob.users_collection):
                link.objects.unlink(blob)
            self.collection.objects.link(blob)
            blob.data.materials.clear()
            blob.data.materials.append(leaf_mat)
            blob.scale = (1.0, 1.0, 0.82 + 0.1 * index)
            crowns.append(blob)
        bpy.context.view_layer.update()
        return self._register(name, trunk)

    def bush(self, name: str, pos, radius: float = 0.7, color: str = "#4E7A3A", seed: float = 1.0):
        require_bpy()
        mat = self._material_for("leafy_grass", color, "grass", 0.8, None)
        parent = None
        for index in range(3):
            offset = (_noise(index, seed, seed) * radius * 0.6,
                      _noise(seed, index, seed) * radius * 0.6, 0.0)
            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=1, radius=radius * (1.0 - index * 0.18),
                location=(pos[0] + offset[0], pos[1] + offset[1], pos[2] + radius * 0.7))
            blob = bpy.context.object
            blob.name = f"{name}_{index}"
            for link in list(blob.users_collection):
                link.objects.unlink(blob)
            self.collection.objects.link(blob)
            blob.data.materials.clear()
            blob.data.materials.append(mat)
            blob.scale.z = 0.8
            parent = parent or blob
        return self._register(name, parent)

    def grass_tuft(self, name: str, pos, size: float = 0.22, color: str = "#5C8B3E"):
        require_bpy()
        return self.block(f"{name}", (pos[0], pos[1], pos[2] + size * 0.5),
                          (size, size * 0.4, size), color=color, texture="grass",
                          bevel=0.0)

    def stone(self, name: str, pos, radius: float = 0.3, color: str = "#8C8C8C",
              seed: float = 1.0):
        require_bpy()
        obj = self.ball(name, pos, radius, color=color, texture="classic_pebble", segments=12)
        obj.scale = (1.0, 0.8, 0.6)
        _set_rotation(obj, (0, _noise(seed, 1, seed) * 30, _noise(seed, 2, seed) * 40))
        return obj

    def street_lamp(self, name: str, pos, height: float = 5.2, color: str = "#1B2A35",
                    warm: str = "#FFC978", energy: float = 8.0, arm: float = 0.7):
        """Strassenlaterne mit echtem Punktlicht (warm, fuer Regen/Daemmerung)."""
        require_bpy()
        self.cylinder(f"{name}_mast", (pos[0], pos[1], pos[2] + height / 2),
                      0.09, height, color=color, texture="metal", vertices=12)
        self.block(f"{name}_arm", (pos[0] + arm / 2, pos[1], pos[2] + height),
                   (arm, 0.12, 0.12), color=color, texture="metal")
        bulb = self.block(f"{name}_lampe", (pos[0] + arm, pos[1], pos[2] + height - 0.12),
                          (0.42, 0.42, 0.22), color=warm, texture="neon", emission=energy)
        bpy.ops.object.light_add(type="POINT",
                                 location=(pos[0] + arm, pos[1], pos[2] + height - 0.3))
        light = bpy.context.object
        light.name = f"{name}_licht"
        light.data.energy = energy * 45.0
        light.data.color = textures.rgb_to_linear(textures.brickcolor(warm))
        light.data.shadow_soft_size = 0.45
        for link in list(light.users_collection):
            link.objects.unlink(light)
        self.collection.objects.link(light)
        return self._register(name, bulb)

    def bench(self, name: str, pos, rotation_z: float = 0.0, length: float = 2.2,
              color: str = "#7C5C46"):
        require_bpy()
        boxes = [((0, 0, 0.45), (length, 0.5, 0.1)),
                 ((0, -0.22, 0.75), (length, 0.08, 0.5)),
                 ((-length / 2 + 0.15, 0, 0.22), (0.12, 0.5, 0.45)),
                 ((length / 2 - 0.15, 0, 0.22), (0.12, 0.5, 0.45))]
        mat = self._material_for("wood_planks", color, "wood", 0.6, None)
        obj = _boxes_mesh(name, boxes, mat, self.collection)
        obj.location = pos
        _set_rotation(obj, (0, 0, rotation_z))
        return self._register(name, obj)

    def bicycle(self, name: str, pos, rotation_z: float = 0.0,
                color: str = "#1B2A35"):
        require_bpy()
        wheels = 2
        for side in (-1, 1):
            self.torus(f"{name}_rad_{side}",
                       (pos[0], pos[1] + side * 0.62, pos[2] + 0.34),
                       0.34, 0.035, color=color, texture="metal",
                       rotation=(0, 90, 0))
        boxes = [((pos[0], pos[1], pos[2] + 0.52), (0.06, 1.1, 0.06)),
                 ((pos[0], pos[1] + 0.5, pos[2] + 0.78), (0.05, 0.05, 0.55)),
                 ((pos[0], pos[1] - 0.35, pos[2] + 0.62), (0.4, 0.06, 0.05))]
        mat = self._material_for("metal", color, "metal", 1.0, None)
        obj = _boxes_mesh(name, boxes, mat, self.collection)
        _set_rotation(obj, (0, 0, rotation_z))
        return self._register(name, obj)

    def mailbox(self, name: str, pos, color: str = "#0D69AC", rotation_z: float = 0.0):
        require_bpy()
        self.cylinder(f"{name}_pfosten", (pos[0], pos[1], pos[2] + 0.4), 0.06, 0.8,
                      color="#635F62", texture="metal", vertices=10)
        box = self.block(name, (pos[0], pos[1], pos[2] + 1.0), (0.42, 0.5, 0.34),
                         color=color, texture="metal", rotation=(0, 0, rotation_z))
        self.block(f"{name}_klappe", (pos[0], pos[1] - 0.26, pos[2] + 1.02),
                   (0.3, 0.05, 0.06), color="#E5E4DE", texture="metal",
                   rotation=(0, 0, rotation_z))
        return box

    def trash_can(self, name: str, pos, radius: float = 0.35, color: str = "#287F47"):
        require_bpy()
        self.cylinder(name, (pos[0], pos[1], pos[2] + 0.55), radius, 1.1,
                      color=color, texture="metal", vertices=16)
        return self.cylinder(f"{name}_deckel", (pos[0], pos[1], pos[2] + 1.12),
                             radius * 1.08, 0.08, color="#635F62", texture="metal",
                             vertices=16)

    def window_light(self, name: str, pos, size=(0.9, 0.06, 1.1), color: str = "#FFC978",
                     emission: float = 3.0, rotation=(0, 0, 0)):
        """Warm leuchtendes Fenster (Glas mit Emission) - Herz der Abendstadt."""
        return self.block(name, pos, size, color=color, texture="glass",
                          emission=emission, rotation=rotation, bevel=0.0)

    def pipe(self, name: str, start, end, radius: float = 0.12, color: str = "#635F62",
             texture: str = "metal"):
        require_bpy()
        sx, sy, sz = start
        ex, ey, ez = end
        length = math.dist(start, end)
        mid = ((sx + ex) / 2, (sy + ey) / 2, (sz + ez) / 2)
        obj = self.cylinder(name, mid, radius, length, color=color, texture=texture,
                            vertices=12)
        direction = Vector((ex - sx, ey - sy, ez - sz))
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = direction.to_track_quat("Z", "Y")
        return obj

    def scatter(self, name: str, builder_name: str, count: int, area=(-20, 20, -20, 20),
                seed: float = 1.0, avoid: Optional[list[tuple[float, float, float]]] = None,
                **kwargs):
        """Verteilt Objekte (Grasbueschel, Steine, Blumen) organisch im Gebiet."""
        require_bpy()
        x0, x1, y0, y1 = area
        rng = random.Random(int(seed * 1000) + 7)
        placed = []
        for index in range(count):
            for _attempt in range(12):
                x = rng.uniform(x0, x1)
                y = rng.uniform(y0, y1)
                if avoid and any(math.dist((x, y), (a[0], a[1])) < a[2] for a in avoid):
                    continue
                break
            method = getattr(self, builder_name, None)
            if method is None:
                raise KeyError(f"scatter: unbekannte Form '{builder_name}'")
            obj = method(f"{name}_{index}", (x, y, 0.0), **kwargs)
            if obj is not None:
                obj.scale = tuple(c * rng.uniform(0.7, 1.35) for c in obj.scale)
                _set_rotation(obj, (0, 0, rng.uniform(0, 360)))
            placed.append(obj)
        return placed

    # -- Importe --------------------------------------------------------- #
    def import_model(self, name: str, path: Path, pos=(0, 0, 0), scale: float = 1.0,
                     rotation_z: float = 0.0, collection=None):
        """Importiert OBJ/glTF/FBX (konvertierte Roblox-Modelle) und registriert sie."""
        require_bpy()
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Modell fehlt: {path}")
        before = set(bpy.data.objects)
        suffix = path.suffix.lower()
        if suffix == ".obj":
            bpy.ops.wm.obj_import(filepath=str(path))
        elif suffix in (".gltf", ".glb"):
            bpy.ops.import_scene.gltf(filepath=str(path))
        elif suffix == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(path))
        else:
            raise ValueError(f"Nicht unterstuetztes Format: {suffix}")
        imported = [obj for obj in bpy.data.objects if obj not in before]
        parent = None
        for index, obj in enumerate(imported):
            if obj.users_collection:
                for link in list(obj.users_collection):
                    link.objects.unlink(obj)
            self.collection.objects.link(obj)
            obj.name = f"{name}_{index}" if index else name
            parent = parent or obj
        if parent is not None:
            parent.location = pos
            parent.scale = (scale, scale, scale)
            parent.rotation_euler = (0.0, 0.0, math.radians(rotation_z))
        return self._register(name, parent)

    # -- Spezielle Formen aus anderen Modulen ---------------------------- #
    def sign(self, name: str, pos, text: str, **kwargs):
        module = importlib.import_module("1_system.blender_engine.text_and_signs")
        obj = module.make_sign(self, name=name, position=pos, text=text, **kwargs)
        self.objects[name] = obj
        return obj

    def text3d(self, name: str, pos, text: str, **kwargs):
        module = importlib.import_module("1_system.blender_engine.text_and_signs")
        obj = module.make_3d_text(self, name=name, position=pos, text=text, **kwargs)
        self.objects[name] = obj
        return obj

    def billboard_counter(self, character: dict, text: str, **kwargs):
        module = importlib.import_module("1_system.blender_engine.text_and_signs")
        return module.make_billboard_counter(character, text, **kwargs)


# --------------------------------------------------------------------------- #
# Declarative maps (map_and_props.py)
# --------------------------------------------------------------------------- #
def build_spec(entries: Sequence[dict], world: WorldBuilder) -> list[str]:
    """Baut eine deklarative Objektliste (``OBJECTS`` aus map_and_props.py).

    Jeder Eintrag ist ein Dict mit ``type`` und ``name``. Optionale Schluessel:
    ``pos``, ``size``, ``color``, ``texture``, ``material``, ``rotation``, ``params``.
    Unbekannte Typen loesen einen klaren Fehler aus (kein stilles Ignorieren).
    """
    built: list[str] = []
    for entry in entries:
        shape = str(entry.get("type", "")).strip()
        name = str(entry.get("name") or f"{shape}_{len(built)}")
        params = dict(entry.get("params") or {})
        for key in ("pos", "size", "color", "texture", "material", "rotation"):
            if key in entry and entry[key] is not None:
                params[key] = entry[key]
        if shape == "sign" or shape == "billboard_counter" or shape == "text3d":
            text = entry.get("text") or params.pop("text", "")
            params.pop("pos", None)
            if shape == "sign":
                world.sign(name, params.pop("pos", entry.get("pos", (0, 0, 0))), text, **params)
            elif shape == "text3d":
                world.text3d(name, params.pop("pos", entry.get("pos", (0, 0, 0))), text, **params)
            else:
                raise ValueError("billboard_counter wird direkt an Figuren gehaengt, "
                                 "nicht als Map-Objekt")
        elif shape == "custom_model":
            model_name = entry.get("model")
            models = getattr(world, "custom_models", {}) or {}
            if model_name not in models:
                raise KeyError(f"custom_model '{model_name}' fehlt in custom_models.py "
                               f"(verfuegbar: {sorted(models)})")
            pos = params.pop("pos", (0, 0, 0))
            rotation = params.pop("rotation", (0, 0, 0))
            models[model_name](world, pos=pos, rotation=rotation, **params)
        elif shape == "creator_store":
            world.import_model(name, Path(entry["path"]), pos=entry.get("pos", (0, 0, 0)),
                               scale=float(entry.get("scale", 1.0)),
                               rotation_z=float(entry.get("rotation_z", 0.0)))
        else:
            method = getattr(world, shape, None)
            if method is None or shape not in SHAPE_TYPES:
                raise KeyError(f"Unbekannte Form '{shape}'. Erlaubt: {', '.join(SHAPE_TYPES)}")
            method(name, **params)
        built.append(name)
    return built


if __name__ == "__main__":  # pragma: no cover
    print("Formen:", ", ".join(SHAPE_TYPES))
    print(f"{len(textures.TEXTURE_CATALOG)} Texturen, {len(textures.BRICKCOLORS)} BrickColors")

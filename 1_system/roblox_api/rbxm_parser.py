"""Roblox-Modelle lesen: .rbxm (binaer), .rbxmx (XML) und Mesh-Formate.

Unterstuetzt
------------
* **RBXMX** (XML): Parts, MeshParts, Wedges, Attachments, SpecialMesh, Decals,
  verschachtelte Models - inklusive CFrame, Groesse, Farbe, Material.
* **RBXM** (binaer): Header, Klassen-/Instanz-Chunks, SSTR, PROP (mit
  interleaved Kodierung), PRNT, META. LZ4- und (falls installiert) ZSTD-Kompression.
* **Roblox FileMesh** (``.mesh``): Versionen 1.00 bis 5.00.
* **OBJ** und **glTF/GLB** als Fallback fuer ``assets-thumbnail-3d``-Downloads.

Alle Parser sind reines Python (kein Blender) und liefern ein einheitliches
``RbxmModel`` mit Teilen, Meshes und Attachments. Blender-Import passiert in
:func:`import_into_blender`.
"""
from __future__ import annotations

import json
import math
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

BINARY_MAGIC = b"<roblox!\x89\xff\r\n\x1a\n"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


# --------------------------------------------------------------------------- #
# Datenmodell
# --------------------------------------------------------------------------- #
@dataclass
class RbxmPart:
    name: str = ""
    class_name: str = "Part"
    size: tuple = (1.0, 1.0, 1.0)
    position: tuple = (0.0, 0.0, 0.0)
    rotation_matrix: tuple = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    color: tuple = (0.64, 0.64, 0.64)
    material: str = "Plastic"
    transparency: float = 0.0
    mesh_id: str = ""
    mesh_scale: tuple = (1.0, 1.0, 1.0)
    attachments: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "class_name": self.class_name, "size": list(self.size),
            "position": list(self.position),
            "rotation_matrix": list(self.rotation_matrix),
            "color": list(self.color), "material": self.material,
            "transparency": self.transparency, "mesh_id": self.mesh_id,
            "attachments": self.attachments,
        }


@dataclass
class RbxmInstance:
    class_name: str
    name: str = ""
    properties: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: Optional["RbxmInstance"] = None


@dataclass
class RbxmModel:
    parts: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    name: str = ""
    instances: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def bounds(self) -> dict:
        if not self.parts:
            return {"min": [0, 0, 0], "max": [0, 0, 0]}
        lows = [min(p.position[i] - p.size[i] / 2 for p in self.parts) for i in range(3)]
        highs = [max(p.position[i] + p.size[i] / 2 for p in self.parts) for i in range(3)]
        return {"min": lows, "max": highs}

    def summary(self) -> dict:
        classes:dict[str, int] = {}
        for part in self.parts:
            classes[part.class_name] = classes.get(part.class_name, 0) + 1
        return {"name": self.name, "parts": len(self.parts), "meshes": len(self.meshes),
                "classes": classes, "attachments": sum(len(p.attachments) for p in self.parts),
                "bounds": self.bounds(), "warnings": self.warnings}


# --------------------------------------------------------------------------- #
# Material / Farbe
# --------------------------------------------------------------------------- #
ROBLOX_MATERIALS = {
    # Enum.Material, Werte von create.roblox.com/docs/reference/engine/enums/Material
    256: "Plastic", 272: "SmoothPlastic", 288: "Neon", 512: "Wood", 528: "WoodPlanks",
    784: "Marble", 788: "Basalt", 800: "Slate", 804: "CrackedLava", 816: "Concrete",
    820: "Limestone", 832: "Granite", 836: "Pavement", 848: "Brick", 864: "Pebble",
    880: "Cobblestone", 896: "Rock", 912: "Sandstone", 1040: "CorrodedMetal",
    1056: "DiamondPlate", 1072: "Foil", 1088: "Metal", 1280: "Grass",
    1284: "LeafyGrass", 1296: "Sand", 1312: "Fabric", 1328: "Snow", 1344: "Mud",
    1360: "Ground", 1376: "Asphalt", 1392: "Salt", 1536: "Ice", 1552: "Glacier",
    1568: "Glass", 1584: "ForceField", 1792: "Air", 2048: "Water", 2304: "Cardboard",
    2305: "Carpet", 2306: "CeramicTiles", 2307: "ClayRoofTiles", 2308: "RoofShingles",
    2309: "Leather", 2310: "Plaster", 2311: "Rubber",
}


def _material_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return ROBLOX_MATERIALS.get(value, f"Material{value}")
    return "Plastic"


def _color_from_uint8(value: int) -> tuple:
    return ((value >> 16 & 255) / 255.0, (value >> 8 & 255) / 255.0, (value & 255) / 255.0)


# --------------------------------------------------------------------------- #
# LZ4 / ZSTD
# --------------------------------------------------------------------------- #
def lz4_decompress_block(data: bytes, expected_size: int) -> bytes:
    """Dekodiert einen LZ4-Block (ohne Frame-Header), wie Roblox ihn nutzt."""
    output = bytearray()
    index = 0
    length = len(data)
    while index < length:
        token = data[index]
        index += 1
        literal_length = token >> 4
        if literal_length == 15:
            while index < length:
                extra = data[index]
                index += 1
                literal_length += extra
                if extra != 255:
                    break
        if literal_length:
            output.extend(data[index:index + literal_length])
            index += literal_length
        if index >= length:
            break
        offset = data[index] | (data[index + 1] << 8)
        index += 2
        if offset == 0:
            raise ValueError("LZ4: ungueltiger Offset 0")
        match_length = token & 0x0F
        if match_length == 15:
            while index < length:
                extra = data[index]
                index += 1
                match_length += extra
                if extra != 255:
                    break
        match_length += 4
        start = len(output) - offset
        if start < 0:
            raise ValueError("LZ4: Offset zeigt vor den Anfang")
        for _ in range(match_length):
            output.append(output[start])
            start += 1
    if expected_size and len(output) != expected_size:
        raise ValueError(f"LZ4: {len(output)} statt {expected_size} Bytes")
    return bytes(output)


def _decompress(payload: bytes, uncompressed_size: int) -> bytes:
    if not payload:
        return b""
    if payload.startswith(ZSTD_MAGIC):
        try:
            import zstandard  # type: ignore
        except ImportError as exc:
            raise NotImplementedError(
                "Dieses RBXM ist ZSTD-komprimiert. Bitte 'pip install zstandard' "
                "installieren oder das Modell in Studio als .rbxmx speichern.") from exc
        return zstandard.ZstdDecompressor().decompress(payload, max_output_size=uncompressed_size)
    return lz4_decompress_block(payload, uncompressed_size)


# --------------------------------------------------------------------------- #
# Binaerleser
# --------------------------------------------------------------------------- #
class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def bytes(self, count: int) -> bytes:
        if self.offset + count > len(self.data):
            raise ValueError("RBXM: unerwartetes Dateiende")
        chunk = self.data[self.offset:self.offset + count]
        self.offset += count
        return chunk

    def u8(self) -> int:
        return self.bytes(1)[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.bytes(2))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.bytes(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.bytes(4))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.bytes(4))[0]

    #: CFrame-Rotationen und Sequenz-Keypoints sind little-endian IEEE-Floats
    f32_le = f32

    def f64(self) -> float:
        return struct.unpack("<d", self.bytes(8))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.bytes(8))[0]

    def string(self) -> str:
        length = self.u32()
        return self.bytes(length).decode("utf-8", errors="replace")

    def remaining(self) -> int:
        return len(self.data) - self.offset


#: Typ-ID -> Name (Roblox-Binary-Format, dokumentiert in rbx-dom/docs/binary.md)
PROPERTY_TYPES = {
    0x01: "String", 0x02: "Bool", 0x03: "Int32", 0x04: "Float32", 0x05: "Float64",
    0x06: "UDim", 0x07: "UDim2", 0x08: "Ray", 0x09: "Faces", 0x0A: "Axes",
    0x0B: "BrickColor", 0x0C: "Color3", 0x0D: "Vector2", 0x0E: "Vector3",
    0x0F: "Vector2int16", 0x10: "CFrame", 0x11: "Quaternion", 0x12: "Enum",
    0x13: "Ref", 0x14: "Vector3int16", 0x15: "NumberSequence", 0x16: "ColorSequence",
    0x17: "NumberRange", 0x18: "Rect", 0x19: "PhysicalProperties", 0x1A: "Color3uint8",
    0x1B: "Int64", 0x1C: "SharedString", 0x1D: "ProtectedString", 0x1E: "OptionalCFrame",
    0x1F: "UniqueId", 0x20: "Font", 0x21: "SecurityCapabilities",
}

#: CFrame-Sonderfaelle: ID -> Rotation (Y -> X -> Z, Grad)
CFRAME_ROTATION_IDS = {
    0x02: (0, 0, 0), 0x03: (90, 0, 0), 0x05: (0, 180, 180), 0x06: (-90, 0, 0),
    0x07: (0, 180, 90), 0x09: (0, 90, 90), 0x0A: (0, 0, 90), 0x0C: (0, -90, 90),
    0x0D: (-90, -90, 0), 0x0E: (0, -90, 0), 0x10: (90, -90, 0), 0x11: (0, 90, 180),
    0x14: (0, 180, 0), 0x15: (-90, -180, 0), 0x17: (0, 0, 180), 0x18: (90, 180, 0),
    0x19: (0, 0, -90), 0x1B: (0, -90, -90), 0x1C: (0, -180, -90), 0x1E: (0, 90, -90),
    0x1F: (90, 90, 0), 0x20: (0, 90, 0), 0x22: (-90, 90, 0), 0x23: (0, -90, 180),
}


def _untransform_integer(value: int) -> int:
    """Hebt Roblox' Zigzag-Transformation auf (siehe Spec, Integer Transformations)."""
    return (value >> 1) ^ -(value & 1)


def _roblox_float(bits: int) -> float:
    """Wandelt ein Roblox-Float (Vorzeichenbit an letzter Stelle) in eine Zahl um."""
    standard = ((bits & 1) << 31) | (bits >> 1)
    return struct.unpack("<f", struct.pack("<I", standard))[0]


def _euler_matrix_deg(x_deg: float, y_deg: float, z_deg: float) -> tuple:
    """Rotationsmatrix fuer Roblox-CFrames (Reihenfolge Y -> X -> Z)."""
    x, y, z = (math.radians(v) for v in (x_deg, y_deg, z_deg))
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return (
        cy * cz, -cy * sz, sy,
        cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy,
        sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy,
    )


class RbxmBinaryParser:
    """Liest binaere ``.rbxm``-Dateien exakt nach der rbx-dom-Spezifikation."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    # -- Einstieg --------------------------------------------------------- #
    def parse(self, data: bytes) -> RbxmModel:
        if not data.startswith(BINARY_MAGIC):
            raise ValueError("Kein binaeres RBXM (Header fehlt)")
        reader = _Reader(data)
        reader.bytes(len(BINARY_MAGIC))
        reader.u16()          # Version (immer 0)
        reader.u32()          # Klassenanzahl
        reader.u32()          # Instanzanzahl
        reader.bytes(8)       # reserviert
        classes: dict[int, str] = {}
        referents_by_class: dict[int, list[int]] = {}
        shared_strings: list[str] = []
        props_by_class: dict[int, dict[str, list]] = {}
        parents: list[tuple[int, Optional[int]]] = []
        meta: dict[str, str] = {}
        while reader.remaining() >= 16:
            name = reader.bytes(4)
            compressed = reader.u32()
            uncompressed = reader.u32()
            reader.u32()  # reserviert
            payload = reader.bytes(compressed if compressed else uncompressed)
            chunk = _decompress(payload, uncompressed) if compressed else payload
            if name.strip(b"\x00") == b"END":
                break
            if name == b"META":
                meta.update(self._parse_meta(chunk))
            elif name == b"SSTR":
                shared_strings = self._parse_strings(chunk)
            elif name == b"INST":
                class_id, class_name, referents = self._parse_instances(chunk)
                classes[class_id] = class_name
                referents_by_class[class_id] = referents
            elif name == b"PROP":
                class_id, prop_name, values = self._parse_property(
                    chunk, classes, referents_by_class, shared_strings)
                props_by_class.setdefault(class_id, {})[prop_name] = values
            elif name == b"PRNT":
                parents.extend(self._parse_parents(chunk))
        if not classes:
            raise ValueError("RBXM enthaelt keine INST-Chunks")

        instances: dict[int, RbxmInstance] = {}
        for class_id, class_name in classes.items():
            for referent in referents_by_class.get(class_id, []):
                instances[referent] = RbxmInstance(class_name=class_name)
        for class_id, prop_map in props_by_class.items():
            referents = referents_by_class.get(class_id, [])
            for prop_name, values in prop_map.items():
                for referent, value in zip(referents, values):
                    instance = instances.get(referent)
                    if instance is not None:
                        instance.properties[prop_name] = value
        for instance in instances.values():
            # Roblox speichert den Namen je nach Version als "Name"
            instance.name = str(instance.properties.get("Name") or instance.class_name)
        for child_ref, parent_ref in parents:
            child = instances.get(child_ref)
            if child is None:
                continue
            if parent_ref is not None:
                parent = instances.get(parent_ref)
                if parent is not None:
                    child.parent = parent
                    parent.children.append(child)

        model = RbxmModel(name=meta.get("ExportedBy") or "", warnings=list(self.warnings))
        model.instances = list(instances.values())
        for instance in model.instances:
            part = self._instance_to_part(instance)
            if part is None:
                continue
            model.parts.append(part)
            if part.mesh_id:
                model.meshes.append({"part": part.name, "mesh_id": part.mesh_id,
                                     "scale": list(part.mesh_scale)})
        return model

    # -- Chunks ---------------------------------------------------------- #
    def _parse_meta(self, chunk: bytes) -> dict[str, str]:
        reader = _Reader(chunk)
        count = reader.u32()
        return {reader.string(): reader.string() for _ in range(count)}

    def _parse_strings(self, chunk: bytes) -> list[str]:
        reader = _Reader(chunk)
        reader.u32()  # Version
        count = reader.u32()
        strings: list[str] = []
        for _ in range(count):
            reader.bytes(16)  # MD5-Hash (ungenutzt)
            strings.append(reader.string())
        return strings

    def _parse_instances(self, chunk: bytes) -> tuple[int, str, list[int]]:
        reader = _Reader(chunk)
        class_id = reader.u32()
        class_name = reader.string()
        is_service = reader.u8()
        count = reader.u32()
        referents = _read_int32_array(reader, count)
        if is_service:
            reader.bytes(count)  # Service-Marker
        return class_id, class_name, referents

    def _parse_parents(self, chunk: bytes) -> list[tuple[int, Optional[int]]]:
        reader = _Reader(chunk)
        reader.u8()  # Version
        count = reader.u32()
        children = _read_int32_array(reader, count)
        parent_refs = _read_int32_array(reader, count)
        pairs = []
        for child, parent in zip(children, parent_refs):
            pairs.append((child, None if parent < 0 else parent))
        return pairs

    def _parse_property(self, chunk: bytes, classes: dict[int, str],
                        referents_by_class: dict[int, list[int]],
                        shared_strings: list[str]) -> tuple[int, str, list]:
        reader = _Reader(chunk)
        class_id = reader.u32()
        prop_name = reader.string()
        type_id = reader.u8()
        type_name = PROPERTY_TYPES.get(type_id)
        if type_name is None:
            raise ValueError(f"RBXM: unbekannter Eigenschaftstyp 0x{type_id:02x} "
                             f"({prop_name}) - bitte Modell als .rbxmx speichern")
        referents = referents_by_class.get(class_id, [])
        values = _read_value_array(reader, type_name, len(referents), shared_strings)
        return class_id, prop_name, values

    # -- Instanzen ------------------------------------------------------- #
    def _instance_to_part(self, instance: RbxmInstance) -> Optional[RbxmPart]:
        if instance.class_name not in ( "Part", "MeshPart", "WedgePart", "CornerWedgePart",
                                        "TrussPart", "SpawnLocation", "UnionOperation"):
            return None
        props = instance.properties
        size = props.get("size") or props.get("Size") or (1.0, 1.0, 1.0)
        cframe = props.get("CFrame") or {}
        position = tuple(cframe.get("position", (0.0, 0.0, 0.0))) if isinstance(cframe, dict) else (0.0, 0.0, 0.0)
        rotation = tuple(cframe.get("rotation", (1, 0, 0, 0, 1, 0, 0, 0, 1))) if isinstance(cframe, dict) else (1, 0, 0, 0, 1, 0, 0, 0, 1)
        color = props.get("Color3uint8") or props.get("Color") or props.get("Color3")
        color_tuple = tuple(float(c) for c in color) if isinstance(color, tuple) and len(color) == 3 else (0.64, 0.64, 0.64)
        mesh_id = ""
        mesh_scale = (1.0, 1.0, 1.0)
        for child in instance.children:
            if child.class_name in ("SpecialMesh", "FileMesh"):
                mesh_id = str(child.properties.get("MeshId") or child.properties.get("MeshID") or "")
                mesh_scale = tuple(child.properties.get("Scale") or (1.0, 1.0, 1.0))
        if instance.class_name == "MeshPart":
            mesh_id = str(props.get("MeshId") or props.get("MeshID") or mesh_id)
        part = RbxmPart(
            name=instance.name, class_name=instance.class_name,
            size=tuple(float(v) for v in size) if isinstance(size, (list, tuple)) else (1.0, 1.0, 1.0),
            position=tuple(float(v) for v in position),
            rotation_matrix=tuple(float(v) for v in rotation),
            color=color_tuple,
            material=_material_name(props.get("Material")),
            transparency=float(props.get("Transparency") or 0.0),
            mesh_id=mesh_id, mesh_scale=tuple(float(v) for v in mesh_scale),
        )
        for child in instance.children:
            if child.class_name == "Attachment":
                cframe = child.properties.get("CFrame") or {}
                part.attachments.append({
                    "name": child.name or child.properties.get("Name", ""),
                    "position": list(cframe.get("position", (0, 0, 0))) if isinstance(cframe, dict) else [0, 0, 0],
                    "rotation_matrix": list(cframe.get("rotation", (1, 0, 0, 0, 1, 0, 0, 0, 1))) if isinstance(cframe, dict) else [1, 0, 0, 0, 1, 0, 0, 0, 1],
                })
        return part


# --------------------------------------------------------------------------- #
# Typleser (Byte-Interleaving, Zigzag, Roblox-Floats)
# --------------------------------------------------------------------------- #
def _deinterleave(raw: bytes, size: int, count: int) -> list[bytes]:
    """Spaltenweise gespeicherte Bytes in Werte zurueckverwandeln (siehe Spec)."""
    if count <= 0:
        return []
    if len(raw) < size * count:
        raise ValueError(f"RBXM: {len(raw)} Bytes fuer {count} Werte zu {size} Bytes")
    out = [bytearray(size) for _ in range(count)]
    for byte_index in range(size):
        column = raw[byte_index * count:(byte_index + 1) * count]
        for value_index in range(count):
            out[value_index][byte_index] = column[value_index]
    return [bytes(blob) for blob in out]


def _read_float32_array(reader: "_Reader", count: int) -> list[float]:
    blobs = _deinterleave(reader.bytes(4 * count), 4, count)
    return [_roblox_float(int.from_bytes(blob, "big")) for blob in blobs]


def _read_float64_array(reader: "_Reader", count: int) -> list[float]:
    return [reader.f64() for _ in range(count)]


def _read_int32_array(reader: "_Reader", count: int) -> list[int]:
    blobs = _deinterleave(reader.bytes(4 * count), 4, count)
    return [_untransform_integer(int.from_bytes(blob, "big")) for blob in blobs]


def _read_enum_array(reader: "_Reader", count: int) -> list[int]:
    blobs = _deinterleave(reader.bytes(4 * count), 4, count)
    return [int.from_bytes(blob, "big") for blob in blobs]


def _read_uint8_array(reader: "_Reader", count: int) -> list[int]:
    return list(reader.bytes(count))


def _read_vector_array(reader: "_Reader", count: int, components: int) -> list[tuple]:
    columns = [_read_float32_array(reader, count) for _ in range(components)]
    return [tuple(column[i] for column in columns) for i in range(count)]


def _read_string(reader: "_Reader") -> str:
    return reader.string()


def _read_number_sequence(reader: "_Reader") -> list[tuple]:
    count = reader.u32()
    return [(reader.f32_le(), reader.f32_le(), reader.f32_le()) for _ in range(count)]


def _read_color_sequence(reader: "_Reader") -> list[tuple]:
    count = reader.u32()
    return [(reader.f32_le(), (reader.f32_le(), reader.f32_le(), reader.f32_le()), reader.f32_le())
            for _ in range(count)]


def _read_cframe_values(reader: "_Reader", count: int) -> list[dict]:
    ids = _read_uint8_array(reader, count)
    rotations: list[Optional[tuple]] = []
    for cframe_id in ids:
        if cframe_id == 0x00:
            rotations.append(tuple(reader.f32_le() for _ in range(9)))
        elif cframe_id in CFRAME_ROTATION_IDS:
            rotations.append(_euler_matrix_deg(*CFRAME_ROTATION_IDS[cframe_id]))
        else:
            raise ValueError(f"RBXM: unbekannter CFrame-Sonderfall 0x{cframe_id:02x}")
    positions = _read_vector_array(reader, count, 3)
    return [{"position": positions[i], "rotation": rotations[i] or (1, 0, 0, 0, 1, 0, 0, 0, 1)}
            for i in range(count)]


def _read_value_array(reader: "_Reader", type_name: str, count: int,
                      shared_strings: list[str]) -> list:
    """Liest eine Werteliste eines PROP-Chunks (Reihenfolge = Klassen-Referenten)."""
    if count == 0:
        return []
    if type_name == "String" or type_name == "ProtectedString":
        return [_read_string(reader) for _ in range(count)]
    if type_name == "Bool":
        return [value == 1 for value in _read_uint8_array(reader, count)]
    if type_name == "Faces" or type_name == "Axes":
        return _read_uint8_array(reader, count)
    if type_name == "Int32":
        return _read_int32_array(reader, count)
    if type_name == "Int64":
        return [struct.unpack("<q", reader.bytes(8))[0] for _ in range(count)]
    if type_name == "Float32":
        return _read_float32_array(reader, count)
    if type_name == "Float64":
        return _read_float64_array(reader, count)
    if type_name == "Enum":
        return _read_enum_array(reader, count)
    if type_name == "Ref":
        return _read_int32_array(reader, count)
    if type_name == "BrickColor":
        return _read_enum_array(reader, count)
    if type_name == "SharedString":
        indexes = _read_enum_array(reader, count)
        return [shared_strings[i] if 0 <= i < len(shared_strings) else "" for i in indexes]
    if type_name == "Color3uint8":
        reds = _read_uint8_array(reader, count)
        greens = _read_uint8_array(reader, count)
        blues = _read_uint8_array(reader, count)
        return [(reds[i] / 255.0, greens[i] / 255.0, blues[i] / 255.0) for i in range(count)]
    if type_name == "Color3":
        return _read_vector_array(reader, count, 3)
    if type_name == "Vector2":
        return _read_vector_array(reader, count, 2)
    if type_name == "Vector3":
        return _read_vector_array(reader, count, 3)
    if type_name == "Ray":
        return _read_vector_array(reader, count, 6)
    if type_name == "NumberRange":
        return _read_vector_array(reader, count, 2)
    if type_name == "Rect":
        return _read_vector_array(reader, count, 4)
    if type_name == "Vector2int16":
        return [struct.unpack("<hh", reader.bytes(4)) for _ in range(count)]
    if type_name == "Vector3int16":
        return [struct.unpack("<hhh", reader.bytes(6)) for _ in range(count)]
    if type_name == "UDim":
        scales = _read_float32_array(reader, count)
        offsets = _read_int32_array(reader, count)
        return [(scales[i], offsets[i]) for i in range(count)]
    if type_name == "UDim2":
        x_scales = _read_float32_array(reader, count)
        y_scales = _read_float32_array(reader, count)
        x_offsets = _read_int32_array(reader, count)
        y_offsets = _read_int32_array(reader, count)
        return [((x_scales[i], x_offsets[i]), (y_scales[i], y_offsets[i])) for i in range(count)]
    if type_name == "CFrame":
        return _read_cframe_values(reader, count)
    if type_name == "Quaternion":
        return _read_vector_array(reader, count, 4)
    if type_name == "NumberSequence":
        return [_read_number_sequence(reader) for _ in range(count)]
    if type_name == "ColorSequence":
        return [_read_color_sequence(reader) for _ in range(count)]
    if type_name == "PhysicalProperties":
        values = []
        for _ in range(count):
            flags = reader.u8()
            if flags & 0x01:
                values.append({"custom": True, "density": reader.f32_le(),
                               "friction": reader.f32_le(), "elasticity": reader.f32_le()})
            else:
                values.append({"custom": False})
        return values
    if type_name == "OptionalCFrame":
        values = []
        for _ in range(count):
            has_value = reader.u8()
            if has_value:
                ids = _read_uint8_array(reader, 1)
                rotation = (tuple(reader.f32_le() for _ in range(9)) if ids[0] == 0
                            else _euler_matrix_deg(*CFRAME_ROTATION_IDS.get(ids[0], (0, 0, 0))))
                position = _read_vector_array(reader, 1, 3)[0]
                values.append({"position": position, "rotation": rotation})
            else:
                values.append(None)
        return values
    if type_name == "UniqueId":
        return [reader.bytes(16).hex() for _ in range(count)]
    if type_name == "Font":
        values = []
        for _ in range(count):
            family = reader.string()
            weight = reader.u16()
            style = reader.u8()
            values.append({"family": family, "weight": weight, "style": style})
        return values
    if type_name == "SecurityCapabilities":
        return [reader.u64() for _ in range(count)]
    raise ValueError(f"RBXM: Typ {type_name} wird noch nicht gelesen - "
                     "bitte Modell als .rbxmx speichern")


# --------------------------------------------------------------------------- #
# XML-Leser
# --------------------------------------------------------------------------- #
class RbxmXmlParser:
    """Liest ``.rbxmx``-Dateien (XML-Export aus Roblox Studio)."""

    PART_CLASSES = ("Part", "MeshPart", "WedgePart", "CornerWedgePart", "TrussPart",
                    "SpawnLocation", "UnionOperation")

    def parse(self, data: bytes) -> RbxmModel:
        import xml.etree.ElementTree as ET

        text = data.decode("utf-8", errors="replace")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ValueError(f"RBXMX: XML ist fehlerhaft - {exc}") from exc
        if root.tag != "roblox":
            raise ValueError("Kein Roblox-XML-Dokument (Wurzel 'roblox' fehlt)")
        model = RbxmModel()
        for item in root.findall("Item"):
            self._walk(item, model, None)
        return model

    def _properties(self, item) -> dict:
        props = item.find("Properties")
        if props is None:
            return {}
        return {child.get("name"): child for child in props}

    @staticmethod
    def _floats(node, names) -> Optional[tuple]:
        try:
            values = tuple(float(node.findtext(name)) for name in names)
        except (TypeError, ValueError):
            return None
        return values if all(v is not None for v in values) else None

    def _walk(self, item, model: RbxmModel, parent_part: Optional[RbxmPart]) -> None:
        class_name = item.get("class", "")
        props = self._properties(item)
        current_part = parent_part

        if class_name in self.PART_CLASSES:
            size = None
            for name in ("size", "Size"):
                node = props.get(name)
                if node is not None:
                    size = self._floats(node, ("X", "Y", "Z"))
            cframe_node = props.get("CFrame")
            position, rotation = (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1)
            if cframe_node is not None:
                position = self._floats(cframe_node, ("X", "Y", "Z")) or position
                rotation = self._floats(cframe_node, ("R00", "R01", "R02", "R10", "R11",
                                                      "R12", "R20", "R21", "R22")) or rotation
            color = None
            color_node = props.get("Color3uint8")
            if color_node is not None and color_node.text:
                try:
                    color = _color_from_uint8(int(color_node.text))
                except ValueError:
                    color = None
            if color is None:
                color_node = props.get("Color")
                if color_node is not None:
                    color = self._floats(color_node, ("R", "G", "B"))
            material_node = props.get("Material")
            material = _material_name(material_node.text if material_node is not None else None)
            name_node = props.get("Name")
            current_part = RbxmPart(
                name=(name_node.text or "") if name_node is not None else "",
                class_name=class_name,
                size=size or (1.0, 1.0, 1.0),
                position=position, rotation_matrix=rotation,
                color=tuple(float(c) for c in (color or (0.64, 0.64, 0.64))),
                material=material,
            )
            transparency_node = props.get("Transparency")
            if transparency_node is not None and transparency_node.text:
                try:
                    current_part.transparency = float(transparency_node.text)
                except ValueError:
                    pass
            model.parts.append(current_part)

        elif class_name == "Attachment" and parent_part is not None:
            name_node = props.get("Name")
            cframe_node = props.get("CFrame")
            position, rotation = (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1)
            if cframe_node is not None:
                position = self._floats(cframe_node, ("X", "Y", "Z")) or position
                rotation = self._floats(cframe_node, ("R00", "R01", "R02", "R10", "R11",
                                                      "R12", "R20", "R21", "R22")) or rotation
            parent_part.attachments.append({
                "name": (name_node.text or "") if name_node is not None else "",
                "position": list(position), "rotation_matrix": list(rotation)})

        elif class_name in ("SpecialMesh", "FileMesh") and parent_part is not None:
            mesh_node = props.get("MeshId") or props.get("MeshID")
            if mesh_node is not None and mesh_node.text:
                parent_part.mesh_id = mesh_node.text.strip()
                model.meshes.append({"part": parent_part.name, "mesh_id": parent_part.mesh_id})
            scale_node = props.get("Scale")
            if scale_node is not None:
                scale = self._floats(scale_node, ("X", "Y", "Z"))
                if scale:
                    parent_part.mesh_scale = scale

        for child in item.findall("Item"):
            self._walk(child, model, current_part)


# --------------------------------------------------------------------------- #
# FileMesh / OBJ / glTF
# --------------------------------------------------------------------------- #
def parse_filemesh(data: bytes) -> dict:
    """Liest ein Roblox-``.mesh`` (Version 1.00 bis 5.00)."""
    text_head = data[:32].decode("ascii", errors="replace")
    if not text_head.startswith("version"):
        raise ValueError("Kein Roblox-FileMesh (Versionskopf fehlt)")
    version = text_head.split("version", 1)[1].strip().split()[0]
    body = data.split(b"\n", 1)[1] if b"\n" in data else b""

    def read(count, fmt, offset):
        size = struct.calcsize(fmt)
        values = struct.unpack_from(fmt, body, offset)
        return values, offset + size

    if version == "1.00":
        (num_faces,), offset = read(1, "<H", 0)
        indices, offset = read(num_faces * 3, f"<{num_faces * 3}I", offset)
        (num_verts,), offset = read(1, "<H", offset)
        verts, offset = read(num_verts * 3, f"<{num_verts * 3}f", offset)
    elif version in ("2.00", "3.00", "4.00", "5.00"):
        if version == "2.00":
            (num_verts,), offset = read(1, "<I", 0)
            (num_faces,), offset = read(1, "<I", offset)
            verts, offset = read(num_verts * 3, f"<{num_verts * 3}f", offset)
            indices, offset = read(num_faces * 3, f"<{num_faces * 3}I", offset)
        else:
            width = 2 if version == "3.00" else 4
            fmt = "<H" if width == 2 else "<I"
            (num_verts,), offset = read(1, fmt, 0)
            (num_faces,), offset = read(1, fmt, offset)
            verts, offset = read(num_verts * 3, f"<{num_verts * 3}f", offset)
            index_fmt = "<H" if num_verts < 65536 else "<I"
            indices, offset = read(num_faces * 3, f"<{num_faces * 3}{index_fmt[-1]}", offset)
    else:
        raise NotImplementedError(f"FileMesh-Version {version} wird nicht unterstuetzt")
    vertices = [tuple(verts[i:i + 3]) for i in range(0, len(verts), 3)]
    faces = [tuple(int(v) for v in indices[i:i + 3]) for i in range(0, len(indices), 3)]
    return {"version": version, "vertices": vertices, "faces": faces}


def parse_obj(path: Path) -> dict:
    vertices: list[tuple] = []
    faces: list[tuple] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v" and len(parts) >= 4:
            vertices.append(tuple(float(v) for v in parts[1:4]))
        elif parts[0] == "f" and len(parts) >= 4:
            indices = []
            for token in parts[1:]:
                index = int(token.split("/")[0])
                indices.append(index - 1 if index > 0 else len(vertices) + index)
            for i in range(1, len(indices) - 1):
                faces.append((indices[0], indices[i], indices[i + 1]))
    if not vertices:
        raise ValueError(f"OBJ ohne Vertices: {path}")
    return {"vertices": vertices, "faces": faces}


def parse_gltf(path: Path) -> dict:
    """Minimaler glTF/GLB-Leser: POSITION-Zugriffe und Indizes."""
    path = Path(path)
    raw = path.read_bytes()
    if raw[:4] == b"glTF":
        # GLB: Chunk 0 = JSON
        length = struct.unpack_from("<I", raw, 12)[0]
        document = json.loads(raw[20:20 + length].decode("utf-8"))
        buffer_offset = 20 + length + 8
        binary = raw[buffer_offset:]
    else:
        document = json.loads(raw.decode("utf-8"))
        binary = b""
        for buffer in document.get("buffers", []):
            uri = buffer.get("uri", "")
            if uri.startswith("data:"):
                import base64

                binary += base64.b64decode(uri.split(",", 1)[1])
            elif uri:
                binary += (path.parent / uri).read_bytes()
    vertices: list[tuple] = []
    faces: list[tuple] = []
    views = document.get("bufferViews", [])
    accessors = document.get("accessors", [])
    component_formats = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
    type_sizes = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

    def read_accessor(index: int) -> list:
        accessor = accessors[index]
        view = views[accessor["bufferView"]]
        count = accessor["count"]
        components = type_sizes[accessor["type"]]
        fmt = component_formats[accessor["componentType"]]
        start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        stride = view.get("byteStride") or struct.calcsize(fmt) * components
        values = []
        for i in range(count):
            offset = start + i * stride
            values.append(struct.unpack_from("<" + fmt * components, binary, offset))
        return values

    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            attributes = primitive.get("attributes", {})
            if "POSITION" not in attributes:
                continue
            base = len(vertices)
            vertices.extend(read_accessor(attributes["POSITION"]))
            if "indices" in primitive:
                indices = [v[0] for v in read_accessor(primitive["indices"])]
                for i in range(0, len(indices) - 2, 3):
                    faces.append((base + indices[i], base + indices[i + 1], base + indices[i + 2]))
            else:
                for i in range(0, len(vertices) - base - 2, 3):
                    faces.append((base + i, base + i + 1, base + i + 2))
    if not vertices:
        raise ValueError(f"glTF ohne Geometrie: {path}")
    return {"vertices": vertices, "faces": faces}


# --------------------------------------------------------------------------- #
# Einheitliche API
# --------------------------------------------------------------------------- #
class RbxmParser:
    """Fassade: erkennt das Format und liefert ein ``RbxmModel``."""

    def parse_bytes(self, data: bytes) -> RbxmModel:
        """Erkennt binaeres RBXM und XML-RBXMX anhand des Inhalts."""
        if data.startswith(BINARY_MAGIC):
            return RbxmBinaryParser().parse(data)
        if data.lstrip().startswith((b"<?xml", b"<roblox")):
            return RbxmXmlParser().parse(data)
        raise ValueError("Weder binaeres RBXM noch XML-RBXMX")

    def parse_file(self, path: Path) -> RbxmModel:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Modell fehlt: {path}")
        data = path.read_bytes()
        suffix = path.suffix.lower()
        if data.startswith(BINARY_MAGIC) or data.lstrip().startswith((b"<?xml", b"<roblox")):
            return self.parse_bytes(data)
        if suffix in (".obj", ".gltf", ".glb"):
            geometry = parse_obj(path) if suffix == ".obj" else parse_gltf(path)
            part = RbxmPart(name=path.stem, class_name="MeshPart",
                            mesh_id=str(path), size=(1.0, 1.0, 1.0))
            model = RbxmModel(parts=[part], name=path.stem)
            model.meshes.append({"part": part.name, "path": str(path),
                                 "vertices": len(geometry["vertices"]),
                                 "faces": len(geometry["faces"])})
            return model
        raise ValueError(f"Unbekanntes Modellformat: {path.suffix} "
                         "(unterstuetzt: .rbxm, .rbxmx, .obj, .gltf, .glb)")

    def parse_filemesh(self, data: bytes) -> dict:
        return parse_filemesh(data)

    @staticmethod
    def extract_asset_id(uri: str) -> Optional[int]:
        import re
        match = re.search(r"(\d{3,})", str(uri or ""))
        return int(match.group(1)) if match else None

    def import_into_blender(self, model: RbxmModel, collection=None,
                            offset=(0.0, 0.0, 0.0), scale: float = 1.0,
                            material_factory=None,
                            mesh_dir: Optional[Path] = None) -> list:
        """Baut die Teile eines Roblox-Modells als Blender-Objekte (inkl. FileMesh falls vorhanden)."""
        try:
            import bpy  # type: ignore
            from mathutils import Matrix  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Der Blender-Import braucht bpy") from exc
        collection = collection or bpy.context.scene.collection
        search_dirs = [Path(d) for d in (mesh_dir, Path("assets_cache/roblox"), Path("assets/models"))
                       if d is not None]
        created = []
        for index, part in enumerate(model.parts):
            obj = None
            mesh_asset_id = self.extract_asset_id(part.mesh_id)
            if mesh_asset_id:
                for folder in search_dirs:
                    for candidate in (folder / f"mesh_{mesh_asset_id}.mesh",
                                      folder / f"{mesh_asset_id}.mesh"):
                        if candidate.is_file():
                            try:
                                geo = parse_filemesh(candidate.read_bytes())
                                ms = part.mesh_scale or (1.0, 1.0, 1.0)
                                verts = [(v[0] * ms[0] * scale,
                                          v[2] * ms[2] * scale,
                                          v[1] * ms[1] * scale)
                                         for v in geo["vertices"]]
                                bmesh_data = bpy.data.meshes.new(f"mesh_{mesh_asset_id}_{index}")
                                bmesh_data.from_pydata(verts, [], geo["faces"])
                                bmesh_data.validate()
                                bmesh_data.update()
                                obj = bpy.data.objects.new(
                                    f"{model.name or 'asset'}_{part.name or index}", bmesh_data)
                                collection.objects.link(obj)
                                break
                            except Exception:  # noqa: BLE001
                                obj = None
                    if obj is not None:
                        break
            if obj is None:
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
                obj = bpy.context.object
                obj.name = f"{model.name or 'asset'}_{part.name or index}"
                obj.scale = tuple(max(0.02, s) * scale for s in part.size)
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                for link in list(obj.users_collection):
                    link.objects.unlink(obj)
                collection.objects.link(obj)
            matrix = Matrix.Identity(4)
            rotation = part.rotation_matrix
            if len(rotation) == 9:
                matrix = Matrix(((rotation[0], rotation[3], rotation[6], 0.0),
                                 (rotation[1], rotation[4], rotation[7], 0.0),
                                 (rotation[2], rotation[5], rotation[8], 0.0),
                                 (0.0, 0.0, 0.0, 1.0)))
            obj.matrix_world = matrix
            obj.location = (part.position[0] * scale + offset[0],
                            part.position[2] * scale + offset[1],
                            part.position[1] * scale + offset[2])
            if material_factory is not None:
                obj.data.materials.append(material_factory(part))
            elif not obj.data.materials:
                mat = bpy.data.materials.new(f"rbx_{part.name or index}")
                mat.use_nodes = True
                bsdf = mat.node_tree.nodes.get("Principled BSDF")
                if bsdf is not None:
                    c = part.color or (0.64, 0.64, 0.64)
                    bsdf.inputs["Base Color"].default_value = (c[0], c[1], c[2], 1.0)
                    bsdf.inputs["Roughness"].default_value = 0.55
                obj.data.materials.append(mat)
            created.append(obj)
        return created


def load_model(path: Path) -> RbxmModel:
    return RbxmParser().parse_file(path)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Roblox-Modell pruefen")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = load_model(args.path)
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2))

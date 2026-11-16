"""Tests fuer den RBXM-Parser (binaer + XML) und den Animations-Loader.

Die Testvektoren stammen direkt aus der rbx-dom-Spezifikation
(``docs/binary.md``), damit die Dekodierung nachweislich stimmt:
Byte-Interleaving, Zigzag-Transformation, Roblox-Floats und CFrame-Sonderfaelle.
"""
from __future__ import annotations

import importlib
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

rbxm = importlib.import_module("1_system.roblox_api.rbxm_parser")
anims = importlib.import_module("1_system.roblox_api.animation_loader")


# --------------------------------------------------------------------------- #
# Hilfsfunktionen zum Schreiben von RBXM-Dateien
# --------------------------------------------------------------------------- #
def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def rb_string(text: str) -> bytes:
    data = text.encode("utf-8")
    return u32(len(data)) + data


def roblox_float(value: float) -> bytes:
    standard = struct.unpack("<I", struct.pack("<f", value))[0]
    rotated = ((standard << 1) & 0xFFFFFFFF) | (standard >> 31)
    return struct.pack(">I", rotated)


def f32_array(values) -> bytes:
    """Float32-Array: big-endian Roblox-Floats, byte-interleaved."""
    blobs = [roblox_float(float(v)) for v in values]
    return _interleave(blobs)


def int32_array(values) -> bytes:
    """Int32-Array: big-endian, zigzag-transformiert, byte-interleaved."""
    blobs = []
    for value in values:
        transformed = ((value << 1) ^ (value >> 31)) & 0xFFFFFFFF
        blobs.append(struct.pack(">I", transformed))
    return _interleave(blobs)


def _interleave(blobs) -> bytes:
    if not blobs:
        return b""
    size = len(blobs[0])
    out = bytearray()
    for byte_index in range(size):
        for blob in blobs:
            out.append(blob[byte_index])
    return bytes(out)


def vector3_array(values) -> bytes:
    return b"".join(f32_array([value[i] for value in values]) for i in range(3))


def chunk(name: bytes, data: bytes, compress: bool = False) -> bytes:
    header_name = name + b"\x00" * (4 - len(name))
    if compress:
        body = lz4_literal_block(data)
        return header_name + u32(len(body)) + u32(len(data)) + u32(0) + body
    return header_name + u32(0) + u32(len(data)) + u32(0) + data


def lz4_literal_block(data: bytes) -> bytes:
    """Gueltiger LZ4-Block, der nur Literale enthaelt (fuer Tests)."""
    out = bytearray()
    length = len(data)
    token = (min(length, 15) << 4)
    out.append(token)
    if length >= 15:
        rest = length - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    out.extend(data)
    return bytes(out)


def build_rbxm(compress: bool = True) -> bytes:
    """Baut ein kleines, aber vollstaendiges Modell mit zwei Parts und einem Mesh."""
    part_class, mesh_class = 1, 2
    parts = [0, 1]
    meshes = [2]
    header = (rbxm.BINARY_MAGIC + struct.pack("<H", 0) + u32(2) + u32(3) + b"\x00" * 8)
    body = bytearray()
    meta = u32(1) + rb_string("ExplicitAutoJoints") + rb_string("true")
    body += chunk(b"META", meta)
    sstr = u32(0) + u32(1) + b"\x00" * 16 + rb_string("shared")
    body += chunk(b"SSTR", sstr, compress=compress)
    body += chunk(b"INST", u32(part_class) + rb_string("Part") + b"\x00" + u32(2)
                  + int32_array(parts), compress=compress)
    # Werte: zwei Parts an Position 1/2
    body += chunk(b"PROP", u32(part_class) + rb_string("Name") + b"\x01"
                  + rb_string("Bank") + rb_string("Laterne"), compress=compress)
    body += chunk(b"PROP", u32(part_class) + rb_string("size") + b"\x0e"
                  + vector3_array([(4.0, 1.0, 2.0), (0.5, 0.5, 0.5)]))
    # CFrame: erster Part Identitaet (Sonderfall 0x02), zweiter volle Rotation
    rotation = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    cframe_values = (bytes([0x02, 0x00])
                     + b"".join(struct.pack("<f", v) for v in rotation)
                     + vector3_array([(0.0, 0.5, 0.0), (1.5, 2.0, -3.0)]))
    body += chunk(b"PROP", u32(part_class) + rb_string("CFrame") + b"\x10" + cframe_values)
    body += chunk(b"PROP", u32(part_class) + rb_string("Color3uint8") + b"\x1a"
                  + bytes([255, 0]) + bytes([128, 64]) + bytes([0, 200]))
    body += chunk(b"PROP", u32(part_class) + rb_string("Material") + b"\x12"
                  + _interleave([struct.pack(">I", 256), struct.pack(">I", 1088)]))
    body += chunk(b"PROP", u32(part_class) + rb_string("Transparency") + b"\x04"
                  + f32_array([0.0, 0.5]))
    body += chunk(b"INST", u32(mesh_class) + rb_string("SpecialMesh") + b"\x00" + u32(1)
                  + int32_array(meshes))
    body += chunk(b"PROP", u32(mesh_class) + rb_string("MeshId") + b"\x01"
                  + rb_string("rbxassetid://123456"))
    body += chunk(b"PROP", u32(mesh_class) + rb_string("Scale") + b"\x0e"
                  + vector3_array([(1.0, 1.0, 1.0)]))
    # PRNT: mesh (2) haengt an Part 1, Part 1 an nichts, Part 0 an nichts
    body += chunk(b"PRNT", b"\x00" + u32(3) + int32_array([2, 1, 0])
                  + int32_array([1, -1, -1]))
    body += chunk(b"END", b"</roblox>")
    return header + bytes(body)


# --------------------------------------------------------------------------- #
# Spezifikations-Testvektoren
# --------------------------------------------------------------------------- #
def read_values(type_name: str, raw: bytes, count: int):
    reader = rbxm._Reader(raw)
    return rbxm._read_value_array(reader, type_name, count, [])


def test_vector3_spec_example():
    raw = bytes.fromhex("7F7F00000000000180800000000000018080808000000001")
    values = read_values("Vector3", raw, 2)
    assert values[0] == pytest.approx((1.0, 2.0, 3.0))
    assert values[1] == pytest.approx((-1.0, -2.0, -3.0))


def test_color3_spec_example():
    raw = bytes.fromhex("7f0000007e69696a7b414142")
    (red, green, blue), = read_values("Color3", raw, 1)
    assert red == pytest.approx(1.0, abs=1e-6)
    assert green == pytest.approx(180 / 255, abs=1e-3)
    assert blue == pytest.approx(20 / 255, abs=1e-3)


def test_udim_spec_example():
    raw = bytes.fromhex("7f800080000000000000000000000408")
    values = read_values("UDim", raw, 2)
    assert values[0] == pytest.approx((1.0, 2))
    assert values[1] == pytest.approx((3.0, 4))


def test_udim2_spec_example():
    raw = bytes.fromhex("7e8000007f8000010000003b00000078")
    (x, y), = read_values("UDim2", raw, 1)
    assert x == pytest.approx((0.75, -30))
    assert y == pytest.approx((-1.5, 60))


def test_brickcolor_spec_example():
    raw = bytes.fromhex("000000000000030003ec25f2")
    assert read_values("BrickColor", raw, 3) == [1004, 37, 1010]


def test_int32_zigzag_roundtrip():
    values = [0, 1, -1, 2004, -2004, -2147483648, 2147483647]
    raw = int32_array(values)
    assert read_values("Int32", raw, len(values)) == values


def test_cframe_array_decoding():
    """CFrame: Sonderfall-ID, little-endian-IEEE-Rotation, Vector3-Positionen."""
    quarter_turn = [0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    raw = (bytes([0x02, 0x00])
           + b"".join(struct.pack("<f", value) for value in quarter_turn)
           + vector3_array([(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]))
    values = read_values("CFrame", raw, 2)
    assert values[0]["rotation"] == pytest.approx((1, 0, 0, 0, 1, 0, 0, 0, 1))
    assert values[0]["position"] == pytest.approx((1.0, 2.0, 3.0))
    assert values[1]["position"] == pytest.approx((4.0, 5.0, 6.0))
    assert values[1]["rotation"] == pytest.approx(quarter_turn)


def test_cframe_rotation_is_orthonormal():
    matrix = rbxm._euler_matrix_deg(30.0, 45.0, 60.0)
    for row in range(3):
        length = sum(matrix[row * 3 + column] ** 2 for column in range(3))
        assert length == pytest.approx(1.0, abs=1e-9)
    # 90-Grad-Sonderfall entspricht einer Vierteldrehung um Y
    special = rbxm._euler_matrix_deg(*rbxm.CFRAME_ROTATION_IDS[0x20])
    assert special == pytest.approx((0, 0, 1, 0, 1, 0, -1, 0, 0), abs=1e-9)


def test_cframe_unknown_special_case_fails():
    with pytest.raises(ValueError):
        read_values("CFrame", bytes([0x33]) + b"\x00" * 12, 1)


def test_lz4_literal_block_roundtrip():
    data = b"<roblox>" * 40
    compressed = lz4_literal_block(data)
    assert rbxm.lz4_decompress_block(compressed, len(data)) == data


def test_parse_binary_model():
    model = rbxm.RbxmParser().parse_bytes(build_rbxm())
    assert model.name == ""
    assert len(model.parts) == 2
    names = [part.name for part in model.parts]
    assert names == ["Bank", "Laterne"]
    bank, laterne = model.parts
    assert bank.size == pytest.approx((4.0, 1.0, 2.0))
    assert bank.position == pytest.approx((0.0, 0.5, 0.0))
    assert bank.material == "Plastic"
    assert bank.color == pytest.approx((1.0, 128 / 255, 0.0), abs=1e-6)
    assert laterne.transparency == pytest.approx(0.5)
    assert laterne.material == "Metal"
    assert laterne.position == pytest.approx((1.5, 2.0, -3.0))
    assert laterne.mesh_id == "rbxassetid://123456"


def test_parse_binary_model_without_compression():
    model = rbxm.RbxmParser().parse_bytes(build_rbxm(compress=False))
    assert len(model.parts) == 2


def test_parser_rejects_xml_file_in_binary_mode():
    with pytest.raises(ValueError):
        rbxm.RbxmBinaryParser().parse(b"<roblox>nope</roblox>")


# --------------------------------------------------------------------------- #
# XML + Animation
# --------------------------------------------------------------------------- #
KEYFRAME_XML = """<roblox version="4">
  <Item class="KeyframeSequence" referent="1">
    <Properties>
      <string name="Name">Wave</string>
      <bool name="Looped">false</bool>
    </Properties>
    <Item class="Keyframe" referent="2">
      <Properties><float name="Time">0</float></Properties>
      <Item class="Pose" referent="3">
        <Properties>
          <string name="Name">RightUpperArm</string>
          <CoordinateFrame name="CFrame">
            <X>0</X><Y>0</Y><Z>0</Z>
            <R00>1</R00><R01>0</R01><R02>0</R02>
            <R10>0</R10><R11>1</R11><R12>0</R12>
            <R20>0</R20><R21>0</R21><R22>1</R22>
          </CoordinateFrame>
        </Properties>
      </Item>
    </Item>
    <Item class="Keyframe" referent="4">
      <Properties><float name="Time">0.5</float></Properties>
      <Item class="Pose" referent="5">
        <Properties>
          <string name="Name">RightUpperArm</string>
          <CoordinateFrame name="CFrame">
            <X>0</X><Y>0</Y><Z>0</Z>
            <R00>1</R00><R01>0</R01><R02>0</R02>
            <R10>0</R10><R11>0.866</R11><R12>-0.5</R12>
            <R20>0</R20><R21>0.5</R21><R22>0.866</R22>
          </CoordinateFrame>
        </Properties>
      </Item>
    </Item>
  </Item>
</roblox>
"""


def test_animation_xml_to_clip():
    animation = anims.parse_animation_bytes(KEYFRAME_XML.encode())
    assert animation.name == "Wave"
    assert animation.looped is False
    assert len(animation.frames) == 2
    clip = anims.animation_to_clip(animation)
    assert clip["loop"] is False
    assert clip["duration"] == 13  # 0.5 s * 24 fps + Endframe
    keys = clip["rotation"]["RightUpperArm"]
    assert keys[0] == pytest.approx((0.0, 0.0, 0.0))
    assert keys[12][0] == pytest.approx(30.0, abs=0.5)


def test_animation_register_in_library():
    from importlib import import_module

    animations = import_module("1_system.blender_engine.custom_animations")
    library = animations.AnimationLibrary()
    animation = anims.parse_animation_bytes(KEYFRAME_XML.encode())
    clip_name = anims.register_clip(library, animation, name="winken_test")
    assert clip_name == "winken_test"
    clip = library.get(clip_name)
    assert len(clip.rotation["RightUpperArm"]) == 3  # Start, Key, Endframe
    assert clip.validate() == []

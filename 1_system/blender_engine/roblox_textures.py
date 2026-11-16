"""Roblox-Texturen, Materialien und BrickColor-Palette - vollstaendig prozedural.

Zwei Aeren, ein System
----------------------
* **2006 / Classic Roblox:** Studs, Inlet, Universal, Weld, Glue (auch einzeln pro
  Wuerfelflaeche nutzbar) plus klassisches Plastik, Slate, Grass, Brick, Wood,
  Corroded Metal, Diamond Plate, Pebble, Sand, Foil und Ice.
* **Heute / Modern:** SmoothPlastic, Plastic, Wood, WoodPlanks, Brick, Cobblestone,
  Concrete, Pavement, Asphalt, Slate, Granite, Marble, Limestone, Plaster,
  RoofShingles, Grass, LeafyGrass, Ground, Mud, Sand, Snow, Metal, CorrodedMetal,
  Fabric, Carpet, Cardboard, Glass, Neon und Water.

Alle Texturen sind kachelbar (Nahtstellen werden periodisch erzeugt), damit grosse
Flaechen kein sichtbares Raster zeigen. Erzeugt werden pro Textur:

* ``albedo``  - Farbkarte (RGB, sRGB)
* ``roughness`` - Rauheit (Graustufen)
* ``normal``  - Normal Map aus der Hoehenkarte
* ``height``  - Hoehenkarte (Graustufen, fuer Bump/Displacement)

Es wird reines Python + Pillow benutzt (kein numpy, kein GPU-Zwang), damit die
Texturen sowohl auf GitHub-Runnern als auch auf Kaggle reproduzierbar entstehen.
Ergebnisse liegen im Cache (Standard ``assets_cache/textures``) und werden nur
einmal berechnet.

Farben
------
``brickcolor()`` akzeptiert BrickColor-Namen (``"Bright red"``, ``"Medium stone grey"``),
BrickColor-Nummern (``21``) und Hex-Werte (``"#C4281C"``). Die RGB-Naeherungen sind
die in der Community etablierten sRGB-Werte; fuer exakte Markenfarben kann jedes
Objekt direkt einen Hex-Wert bekommen.
"""
from __future__ import annotations

import hashlib
import math
import random
from pathlib import Path
from typing import Iterable, Optional

try:  # Pillow ist Pflicht, aber der Fehler soll verstaendlich sein
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise ImportError("Pillow fehlt: pip install 'Pillow>=10'") from exc

CACHE_DIR_DEFAULT = Path("assets_cache/textures")
TEXTURE_SIZE_DEFAULT = 512
TEXTURE_SIZE_PREVIEW = 192


# --------------------------------------------------------------------------- #
# BrickColor-Palette (Roblox-Standardnamen)
# --------------------------------------------------------------------------- #
#: Name -> (BrickColor-Nummer, sRGB-Hex)
BRICKCOLORS: dict[str, tuple[int, str]] = {
    "white": (1, "#F2F3F3"),
    "institutional white": (1001, "#FFFFFF"),
    "mid gray": (1002, "#CDCDCD"),
    "really black": (1003, "#111111"),
    "really red": (1004, "#FF0000"),
    "deep orange": (1005, "#FF6600"),
    "alder": (1006, "#B480FF"),
    "dusty rose": (1007, "#A0844B"),
    "olivine": (1008, "#918E85"),
    "grey": (2, "#A3A2A5"),
    "light yellow": (3, "#F9E999"),
    "brick yellow": (5, "#D7C59A"),
    "light green (mint)": (6, "#C2DAB8"),
    "light reddish violet": (9, "#E8BAC2"),
    "pastel blue": (11, "#8CA5C8"),
    "nougat": (18, "#CC9966"),
    "bright red": (21, "#C4281C"),
    "bright blue": (23, "#0D69AC"),
    "bright yellow": (24, "#F5CD30"),
    "black": (26, "#1B2A35"),
    "dark green": (28, "#287F47"),
    "medium brown": (29, "#A05F35"),
    "bright green": (37, "#4B974B"),
    "dark orange": (38, "#A05F35"),
    "light blue": (45, "#B4D2E3"),
    "medium red": (101, "#DA867A"),
    "medium blue": (102, "#6E99CA"),
    "bright violet": (104, "#8E5597"),
    "br. yellowish orange": (105, "#E29B40"),
    "bright orange": (106, "#DA8541"),
    "bright bluish green": (107, "#008F9C"),
    "earth yellow": (108, "#EFB838"),
    "bright bluish violet": (110, "#6874B9"),
    "br. yellowish green": (115, "#A4BD47"),
    "alder brown": (119, "#A4BD47"),
    "dark red": (125, "#A34B4B"),
    "sand blue": (135, "#74869D"),
    "earth green": (141, "#27462D"),
    "sand green": (151, "#789082"),
    "sand red": (153, "#957977"),
    "reddish brown": (192, "#694028"),
    "medium stone grey": (194, "#A3A2A5"),
    "dark stone grey": (199, "#635F62"),
    "light stone grey": (208, "#E5E4DE"),
    "brown": (217, "#7C5C46"),
    "bright yellowgreen": (226, "#A9E64B"),
    "teal": (1009, "#008F9C"),
    "gold": (1007, "#EEC63A"),
    "cork": (1008, "#A67C4E"),
    "rust": (1003, "#8B5A2B"),
    "cashmere": (1005, "#CBA3A1"),
    "cool yellow": (1006, "#FFF58A"),
    "lilac": (1004, "#B1A7FF"),
    "salmon": (1005, "#FF9494"),
    "seaside": (1005, "#7FA9A8"),
    "sky blue": (1006, "#7BC2E0"),
    "slime green": (1007, "#A3D977"),
    "moss": (1008, "#6E7B5E"),
    "neon green": (1004, "#00FF00"),
    "hot pink": (1004, "#FF66CC"),
    "pink": (1005, "#E89BA7"),
    "lavender": (1006, "#B9A6E3"),
    "baby blue": (1006, "#A6D5F2"),
    "maroon": (1004, "#7A2A2A"),
    "navy blue": (1003, "#1F2C4C"),
    "olive": (1004, "#6B7A3A"),
    "turquoise": (1004, "#3FA7A0"),
    "peach": (1005, "#F2B59C"),
}

_SKIN_COLORS = ("#E8BEAC", "#D7A17A", "#B4805C", "#8C5A3C", "#F2D2B6", "#C68E6D")


def normalize_brick_name(name: str) -> str:
    return " ".join(str(name).strip().lower().replace("_", " ").split())


def brickcolor(value, default: str = "#A3A2A5") -> tuple[int, int, int]:
    """Wandelt BrickColor-Name, Nummer oder Hex in einen RGB-Tupel (0-255)."""
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        if all(isinstance(c, (int, float)) and 0 <= float(c) <= 1 for c in value[:3]):
            return tuple(int(round(float(c) * 255)) for c in value[:3])  # type: ignore[return-value]
        return tuple(max(0, min(255, int(c))) for c in value[:3])  # type: ignore[return-value]
    if isinstance(value, int):
        for _, (number, hex_value) in BRICKCOLORS.items():
            if number == value:
                return _hex_to_rgb(hex_value)
        return _hex_to_rgb(default)
    text = str(value or "").strip()
    if not text:
        return _hex_to_rgb(default)
    if text.startswith("#"):
        return _hex_to_rgb(text)
    if text.isdigit():
        return brickcolor(int(text), default)
    key = normalize_brick_name(text)
    if key in BRICKCOLORS:
        return _hex_to_rgb(BRICKCOLORS[key][1])
    if key in _SKIN_COLORS:
        return _hex_to_rgb(key)
    # kleine Toleranz: "br. yellowish orange" vs. "bright yellowish orange"
    for name, (_, hex_value) in BRICKCOLORS.items():
        if name.replace("br.", "bright") == key.replace("br.", "bright"):
            return _hex_to_rgb(hex_value)
    return _hex_to_rgb(default)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return (163, 162, 165)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (163, 162, 165)


def rgb_to_linear(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def channel(c: int) -> float:
        value = c / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return tuple(channel(c) for c in rgb)  # type: ignore[return-value]


def brickcolor_rgba(value, alpha: float = 1.0) -> tuple[float, float, float, float]:
    r, g, b = rgb_to_linear(brickcolor(value))
    return (r, g, b, alpha)


SKIN_COLORS = {
    "light": "#F2D2B6", "fair": "#E8BEAC", "warm": "#D7A17A",
    "olive": "#C68E6D", "brown": "#B4805C", "deep": "#8C5A3C",
}


# --------------------------------------------------------------------------- #
# Texturkatalog
# --------------------------------------------------------------------------- #
#: key -> dict(era, material hints, base color, roughness, variation)
TEXTURE_CATALOG: dict[str, dict] = {
    # --- 2006 / Classic -------------------------------------------------- #
    "studs_2006": dict(era="classic", pattern="studs", base="#A3A2A5", roughness=0.62, scale=4),
    "inlet_2006": dict(era="classic", pattern="inlet", base="#A3A2A5", roughness=0.58, scale=3),
    "universal_2006": dict(era="classic", pattern="universal", base="#A3A2A5", roughness=0.6, scale=3),
    "weld_2006": dict(era="classic", pattern="weld", base="#A3A2A5", roughness=0.6, scale=2),
    "glue_2006": dict(era="classic", pattern="glue", base="#A3A2A5", roughness=0.6, scale=2),
    "classic_plastic": dict(era="classic", pattern="plastic", base="#D7C59A", roughness=0.42, scale=2),
    "classic_slate": dict(era="classic", pattern="slate", base="#635F62", roughness=0.78, scale=3),
    "classic_grass": dict(era="classic", pattern="grass", base="#4B974B", roughness=0.82, scale=4),
    "classic_brick": dict(era="classic", pattern="brick", base="#A34B4B", roughness=0.75, scale=3),
    "classic_wood": dict(era="classic", pattern="wood", base="#A05F35", roughness=0.68, scale=3),
    "classic_corroded_metal": dict(era="classic", pattern="corroded", base="#6E6250", roughness=0.7, scale=2),
    "classic_diamond_plate": dict(era="classic", pattern="diamond", base="#A3A2A5", roughness=0.5, scale=3),
    "classic_pebble": dict(era="classic", pattern="pebble", base="#8C8C8C", roughness=0.8, scale=4),
    "classic_sand": dict(era="classic", pattern="sand", base="#D7C59A", roughness=0.86, scale=4),
    "classic_foil": dict(era="classic", pattern="foil", base="#D5D5D5", roughness=0.32, scale=2),
    "classic_ice": dict(era="classic", pattern="ice", base="#BBE6F0", roughness=0.18, scale=2),
    # --- Modern ---------------------------------------------------------- #
    "smooth_plastic": dict(era="modern", pattern="plastic", base="#E5E4DE", roughness=0.3, scale=1),
    "plastic": dict(era="modern", pattern="plastic", base="#B4D2E3", roughness=0.42, scale=1),
    "wood": dict(era="modern", pattern="wood", base="#8A5A36", roughness=0.62, scale=1),
    "wood_planks": dict(era="modern", pattern="planks", base="#9A6A40", roughness=0.66, scale=2),
    "brick": dict(era="modern", pattern="brick", base="#8E4B3C", roughness=0.8, scale=2),
    "cobblestone": dict(era="modern", pattern="cobble", base="#6F6B66", roughness=0.78, scale=3),
    "concrete": dict(era="modern", pattern="concrete", base="#B0ACA6", roughness=0.74, scale=2),
    "pavement": dict(era="modern", pattern="pavement", base="#9C9892", roughness=0.72, scale=3),
    "asphalt": dict(era="modern", pattern="asphalt", base="#3A3A3D", roughness=0.52, scale=3),
    "slate": dict(era="modern", pattern="slate", base="#5A5C60", roughness=0.7, scale=2),
    "granite": dict(era="modern", pattern="granite", base="#7D7A76", roughness=0.55, scale=2),
    "marble": dict(era="modern", pattern="marble", base="#E8E6E1", roughness=0.24, scale=2),
    "limestone": dict(era="modern", pattern="limestone", base="#CFC6B4", roughness=0.68, scale=2),
    "plaster": dict(era="modern", pattern="plaster", base="#E4DCCB", roughness=0.72, scale=2),
    "roof_shingles": dict(era="modern", pattern="shingles", base="#4A4038", roughness=0.78, scale=3),
    "grass": dict(era="modern", pattern="grass", base="#4E7A3A", roughness=0.85, scale=3),
    "leafy_grass": dict(era="modern", pattern="leafy_grass", base="#3F6B34", roughness=0.86, scale=3),
    "ground": dict(era="modern", pattern="ground", base="#6B5A42", roughness=0.88, scale=3),
    "mud": dict(era="modern", pattern="mud", base="#4E3B2A", roughness=0.9, scale=2),
    "sand": dict(era="modern", pattern="sand", base="#D8C79E", roughness=0.86, scale=3),
    "snow": dict(era="modern", pattern="snow", base="#F2F5F7", roughness=0.6, scale=2),
    "metal": dict(era="modern", pattern="metal", base="#9FA3A6", roughness=0.32, metallic=0.9, scale=2),
    "corroded_metal": dict(era="modern", pattern="corroded", base="#7A5B43", roughness=0.72, metallic=0.6, scale=2),
    "fabric": dict(era="modern", pattern="fabric", base="#7C5C63", roughness=0.9, scale=3),
    "carpet": dict(era="modern", pattern="carpet", base="#6B4A50", roughness=0.95, scale=3),
    "cardboard": dict(era="modern", pattern="cardboard", base="#B08A5A", roughness=0.88, scale=3),
    "glass": dict(era="modern", pattern="glass", base="#DDEFF2", roughness=0.06, transmission=0.9, scale=1),
    "neon": dict(era="modern", pattern="neon", base="#FF5FA2", roughness=0.25, emission=2.4, scale=2),
    "water": dict(era="modern", pattern="water", base="#2C5F7C", roughness=0.12, transmission=0.55, scale=2),
}

#: Roblox-Materialname -> Textur-Key fuer den passenden Look
MATERIAL_TEXTURE_MAP = {
    "plastic": "smooth_plastic", "smoothplastic": "smooth_plastic",
    "slate": "slate", "concrete": "concrete", "brick": "brick",
    "granite": "granite", "marble": "marble", "limestone": "limestone",
    "wood": "wood", "woodplanks": "wood_planks", "planks": "wood_planks",
    "cobblestone": "cobblestone", "asphalt": "asphalt", "pavement": "pavement",
    "plaster": "plaster", "roofshingles": "roof_shingles", "shingles": "roof_shingles",
    "grass": "grass", "leafygrass": "leafy_grass", "ground": "ground",
    "mud": "mud", "sand": "sand", "snow": "snow", "metal": "metal",
    "corrodedmetal": "corroded_metal", "fabric": "fabric", "carpet": "carpet",
    "cardboard": "cardboard", "glass": "glass", "neon": "neon", "water": "water",
    "ice": "classic_ice", "foil": "classic_foil", "pebble": "classic_pebble",
    "diamondplate": "classic_diamond_plate", "studs": "studs_2006",
}

#: PBR-Werte je Textur (Basis; Einzelobjekte duerfen ueberschreiben)
def material_pbr(texture_key: str) -> dict:
    entry = TEXTURE_CATALOG.get(texture_key)
    if not entry:
        raise KeyError(f"Unbekannte Textur '{texture_key}'. Erlaubt: {sorted(TEXTURE_CATALOG)}")
    return {
        "roughness": float(entry.get("roughness", 0.6)),
        "metallic": float(entry.get("metallic", 0.0)),
        "transmission": float(entry.get("transmission", 0.0)),
        "emission_strength": float(entry.get("emission", 0.0)),
        "base_color": entry["base"],
    }


def texture_for_material(material: str, era: str = "modern") -> str:
    """Waehlt zu einem Roblox-Materialnamen eine Textur (Aera-bewusst)."""
    key = str(material or "plastic").strip().lower().replace(" ", "").replace("_", "")
    if era == "classic":
        classic = {
            "plastic": "classic_plastic", "slate": "classic_slate",
            "grass": "classic_grass", "brick": "classic_brick", "wood": "classic_wood",
            "corrodedmetal": "classic_corroded_metal", "diamondplate": "classic_diamond_plate",
            "pebble": "classic_pebble", "sand": "classic_sand", "foil": "classic_foil",
            "ice": "classic_ice", "concrete": "classic_slate", "granite": "classic_slate",
            "marble": "classic_plastic", "limestone": "classic_plastic",
            "smoothplastic": "classic_plastic", "metal": "classic_diamond_plate",
            "cobblestone": "classic_pebble", "pavement": "classic_slate",
            "asphalt": "classic_slate", "plaster": "classic_plastic",
            "roofshingles": "classic_slate", "leafygrass": "classic_grass",
            "ground": "classic_sand", "mud": "classic_sand", "snow": "classic_ice",
            "fabric": "classic_plastic", "carpet": "classic_fabric",
            "cardboard": "classic_wood", "glass": "classic_ice", "neon": "classic_plastic",
            "water": "classic_ice",
        }
        return classic.get(key, "classic_plastic")
    return MATERIAL_TEXTURE_MAP.get(key, "smooth_plastic")


# --------------------------------------------------------------------------- #
# Prozedurale Erzeugung
# --------------------------------------------------------------------------- #
def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(_lerp(a[i], b[i], t))) for i in range(3))  # type: ignore[return-value]


def _shade(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(round(c * factor)))) for c in rgb)  # type: ignore[return-value]


class _TileNoise:
    """Periodisches Wert-Rauschen (kachelbar) in beliebiger Aufloesung."""

    def __init__(self, seed: int, grid: int = 8):
        self.grid = grid
        rng = random.Random(seed)
        self.values = [[rng.random() for _ in range(grid)] for _ in range(grid)]

    def at(self, u: float, v: float) -> float:
        g = self.grid
        x, y = (u % 1.0) * g, (v % 1.0) * g
        x0, y0 = int(x) % g, int(y) % g
        x1, y1 = (x0 + 1) % g, (y0 + 1) % g
        fx, fy = x - int(x), y - int(y)
        sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        top = _lerp(self.values[y0][x0], self.values[y0][x1], sx)
        bottom = _lerp(self.values[y1][x0], self.values[y1][x1], sx)
        return _lerp(top, bottom, sy)

    def fbm(self, u: float, v: float, octaves: int = 4) -> float:
        total, amplitude, norm = 0.0, 1.0, 0.0
        freq = 1.0
        for octave in range(octaves):
            total += self.at(u * freq + octave * 0.137, v * freq + octave * 0.311) * amplitude
            norm += amplitude
            amplitude *= 0.5
            freq *= 2.0
        return total / norm


def _height_to_normal(height: list[list[float]], size: int, strength: float = 2.0) -> Image.Image:
    normal = Image.new("RGB", (size, size))
    pixels = normal.load()
    for y in range(size):
        row = height[y]
        prev_row = height[(y - 1) % size]
        next_row = height[(y + 1) % size]
        for x in range(size):
            dx = (row[(x + 1) % size] - row[(x - 1) % size]) * strength
            dy = (next_row[x] - prev_row[x]) * strength
            length = math.sqrt(dx * dx + dy * dy + 1.0)
            pixels[x, y] = (
                int(_clamp(0.5 + dx / length * 0.5) * 255),
                int(_clamp(0.5 - dy / length * 0.5) * 255),
                int(_clamp(0.5 + 1.0 / length * 0.5) * 255),
            )
    return normal


def _pattern_height(pattern: str, size: int, scale: int, seed: int) -> tuple[list[list[float]], list[list[float]]]:
    """Liefert (height, mask) wobei mask 0..1 Musterstaerke ist."""
    noise = _TileNoise(seed, grid=max(4, scale * 2))
    detail = _TileNoise(seed + 17, grid=max(8, scale * 6))
    height = [[0.0] * size for _ in range(size)]
    mask = [[0.0] * size for _ in range(size)]
    tile = max(4.0, size / max(1, scale * 2))

    for y in range(size):
        v = y / size
        for x in range(size):
            u = x / size
            base = 0.0
            m = 1.0
            if pattern in ("studs",):
                cx, cy = (x % tile) / tile - 0.5, (y % tile) / tile - 0.5
                r = math.sqrt(cx * cx + cy * cy) * 2.0
                if r < 0.62:
                    base = 0.55 * math.cos(min(1.0, r / 0.62) * math.pi / 2)
                    m = 0.9
                else:
                    base = noise.fbm(u, v, 3) * 0.12
            elif pattern == "inlet":
                cx, cy = (x % tile) / tile - 0.5, (y % tile) / tile - 0.5
                r = math.sqrt(cx * cx + cy * cy) * 2.0
                base = 0.7 if r < 0.38 else 0.1
                m = 0.8
            elif pattern == "universal":
                cx, cy = (x % tile) / tile - 0.5, (y % tile) / tile - 0.5
                base = 0.45 * math.cos(cx * math.pi * 2) * math.cos(cy * math.pi * 2)
            elif pattern == "weld":
                band = (x % tile) / tile
                base = 0.6 if band < 0.18 else 0.05
            elif pattern == "glue":
                base = 0.5 if ((x // max(2, int(tile / 8))) + (y // max(2, int(tile / 8)))) % 2 == 0 else 0.08
            elif pattern in ("brick",):
                row = int(y / (tile / 2)) % 2
                bx = (x + (tile / 2 if row else 0)) % tile
                by = y % (tile / 2)
                mortar = bx < 2 or by < 2 or abs(bx - tile) < 2
                base = 0.0 if mortar else 0.55 + noise.fbm(u, v, 2) * 0.2
                m = 0.9 if not mortar else 0.2
            elif pattern in ("planks",):
                plank = int(y / (tile / 4)) % 4
                groove = (y % (tile / 4)) < 2
                warped = math.sin((x / size) * math.pi * 6 + plank) * 0.04
                base = 0.1 if groove else 0.55 + warped + noise.fbm(u, v, 2) * 0.12
            elif pattern in ("wood",):
                base = 0.45 + math.sin((y / size) * math.pi * 26 + noise.fbm(u, v, 3) * 6) * 0.18
            elif pattern == "cobble":
                cw, ch = tile / 2, tile / 3
                cx, cy = (x % cw) / cw - 0.5, (y % ch) / ch - 0.5
                r = math.sqrt(cx * cx + (cy * 1.2) ** 2) * 2
                base = math.cos(min(1.0, r) * math.pi / 2) * 0.7 if r < 1.0 else 0.0
                m = 0.95
            elif pattern == "pavement":
                cell = tile / 2
                gx, gy = (x % cell), (y % cell)
                base = 0.15 if (gx < 2 or gy < 2) else 0.5 + noise.fbm(u, v, 2) * 0.1
            elif pattern == "shingles":
                row = int(y / (tile / 4))
                offset = (tile / 3) * (row % 2)
                bx = (x + offset) % (tile / 3)
                base = 0.15 if bx < 2 else 0.55 + noise.fbm(u, v, 2) * 0.12
            elif pattern == "asphalt":
                base = noise.fbm(u, v, 4) * 0.35 + detail.fbm(u, v, 2) * 0.06
            elif pattern in ("grass", "leafy_grass"):
                blade = detail.fbm(u * 3.0, v * 3.0, 3)
                base = noise.fbm(u, v, 3) * 0.5 + (0.35 if blade > 0.62 else 0.0)
            elif pattern in ("concrete", "plaster", "limestone", "ground"):
                base = noise.fbm(u, v, 4) * 0.35 + detail.fbm(u, v, 1) * 0.05
            elif pattern in ("slate", "granite", "marble"):
                veins = math.sin((u * 4 + noise.fbm(u, v, 3) * 3.4) * math.pi * 2)
                base = 0.3 + veins * 0.12 + noise.fbm(u, v, 4) * 0.18
            elif pattern == "corroded":
                patch = noise.fbm(u, v, 3)
                base = 0.45 + (0.35 if patch > 0.62 else 0.0)
                m = 0.8 if patch > 0.62 else 0.35
            elif pattern == "diamond":
                fx = (x % tile) / tile
                fy = (y % tile) / tile
                diamond = abs(fx - 0.5) + abs(fy - 0.5)
                base = 0.6 if diamond < 0.22 else 0.05
            elif pattern in ("pebble", "sand"):
                base = detail.fbm(u, v, 3) * 0.5
            elif pattern == "foil":
                base = noise.fbm(u, v, 2) * 0.2 + detail.fbm(u, v, 1) * 0.1
            elif pattern == "ice":
                base = 0.2 + noise.fbm(u, v, 2) * 0.4
            elif pattern == "fabric":
                weave = (math.sin(x / size * math.pi * 48) + math.sin(y / size * math.pi * 48)) * 0.12
                base = 0.4 + weave
            elif pattern == "carpet":
                base = 0.3 + detail.fbm(u, v, 3) * 0.4
            elif pattern == "cardboard":
                base = 0.35 + noise.fbm(u, v, 2) * 0.1
            elif pattern == "glass":
                base = noise.fbm(u, v, 2) * 0.05
            elif pattern == "neon":
                base = 0.5 + math.sin(x / size * math.pi * 8) * 0.1
            elif pattern == "water":
                base = 0.5 + math.sin((u * 6 + v * 3) * math.pi) * 0.2
            elif pattern == "mud":
                base = detail.fbm(u, v, 4) * 0.5
            elif pattern == "snow":
                base = 0.45 + detail.fbm(u, v, 2) * 0.2
            elif pattern == "metal":
                base = 0.4 + noise.fbm(u, v, 1) * 0.08
            else:  # plastic und Fallback
                base = noise.fbm(u, v, 2) * 0.08
            height[y][x] = _clamp(base)
            mask[y][x] = m
    return height, mask


def generate_texture(key: str, size: int = TEXTURE_SIZE_DEFAULT,
                     seed: Optional[int] = None) -> dict[str, Image.Image]:
    """Erzeugt albedo/roughness/normal/height einer Textur im Speicher."""
    if key not in TEXTURE_CATALOG:
        raise KeyError(f"Unbekannte Textur '{key}'. Erlaubt: {sorted(TEXTURE_CATALOG)}")
    entry = TEXTURE_CATALOG[key]
    size = max(32, int(size))
    seed = seed if seed is not None else abs(hash(key)) % 100_000
    pattern = entry["pattern"]
    scale = int(entry.get("scale", 2))
    base = _hex_to_rgb(entry["base"])
    light = _shade(base, 1.18)
    dark = _shade(base, 0.72)

    height, mask = _pattern_height(pattern, size, scale, seed)
    albedo = Image.new("RGB", (size, size))
    roughness = Image.new("L", (size, size))
    height_img = Image.new("L", (size, size))
    a_pixels, r_pixels, h_pixels = albedo.load(), roughness.load(), height_img.load()
    base_rough = float(entry.get("roughness", 0.6))

    for y in range(size):
        h_row = height[y]
        m_row = mask[y]
        for x in range(size):
            h = h_row[x]
            m = m_row[x]
            # Farbton: Musterfarbe zwischen dunkel und hell, leicht entsaettigt
            t = _clamp(h * 0.9 + 0.05)
            color = _mix_rgb(dark, light, t)
            if pattern == "corroded" and m > 0.6:
                color = _mix_rgb(color, (120, 64, 32), 0.55)
            elif pattern in ("grass", "leafy_grass"):
                color = _mix_rgb(color, (60, 110, 50), 0.35)
            elif pattern == "brick":
                color = _mix_rgb(color, (150, 70, 58), 0.3 * m)
            elif pattern in ("wood", "planks"):
                color = _mix_rgb(color, (150, 105, 62), 0.35)
            elif pattern == "marble":
                color = _mix_rgb(color, (120, 122, 130), 0.25 * (1.0 - t))
            elif pattern == "r15_skin":
                color = base
            a_pixels[x, y] = color
            r_pixels[x, y] = int(_clamp(base_rough + (0.5 - h) * 0.25) * 255)
            h_pixels[x, y] = int(h * 255)

    normal = _height_to_normal(height, size, strength=1.6 if pattern in ("studs", "inlet", "brick") else 1.0)
    return {"albedo": albedo, "roughness": roughness, "normal": normal, "height": height_img}


def ensure_texture_files(keys: Iterable[str], out_dir: Path = CACHE_DIR_DEFAULT,
                         size: int = TEXTURE_SIZE_DEFAULT) -> dict[str, dict[str, str]]:
    """Erzeugt fehlende Texturen als PNG im Cache und liefert die Pfade."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, str]] = {}
    for key in keys:
        if key not in TEXTURE_CATALOG:
            raise KeyError(f"Unbekannte Textur '{key}'. Erlaubt: {sorted(TEXTURE_CATALOG)}")
        paths: dict[str, str] = {}
        tag = f"{key}_{size}"
        missing = False
        for channel in ("albedo", "roughness", "normal", "height"):
            path = out_dir / f"{tag}_{channel}.png"
            paths[channel] = str(path)
            missing = missing or not path.is_file()
        if missing:
            images = generate_texture(key, size)
            for channel, image in images.items():
                image.save(paths[channel], optimize=True)
        manifest[key] = paths
    return manifest


def texture_manifest(era: str = "both") -> list[str]:
    keys = [key for key, value in TEXTURE_CATALOG.items()
            if era == "both" or value.get("era") == era]
    return sorted(keys)


if __name__ == "__main__":  # pragma: no cover - kleines Werkzeug
    import argparse

    parser = argparse.ArgumentParser(description="Roblox-Texturen erzeugen")
    parser.add_argument("--keys", nargs="*", default=None)
    parser.add_argument("--size", type=int, default=TEXTURE_SIZE_DEFAULT)
    parser.add_argument("--out", type=Path, default=CACHE_DIR_DEFAULT)
    args = parser.parse_args()
    keys = args.keys or texture_manifest()
    manifest = ensure_texture_files(keys, args.out, args.size)
    print(f"{len(manifest)} Texturen in {args.out}")
    print(f"Verfuegbar: {', '.join(sorted(TEXTURE_CATALOG))}")

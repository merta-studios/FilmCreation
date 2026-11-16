"""Die Stadt "Schrittstadt" - organisch, schief, detailreich, hoch gebaut.

Diese Datei beschreibt die Map als Liste ``OBJECTS``. Jeder Eintrag ist ein Dict:
    {"type": <Form>, "name": <eindeutig>, "pos": [x, y, z], "size": [w, d, h],
     "color": <BrickColor/Hex>, "texture": <Texturname>, "rotation": [x, y, z],
     "params": {...}}
Die Formen und Parameter stehen in 3_regeln/02_BAUKASTEN_HANDBUCH.md.

Wichtig fuer das 9:16-Hochformat: viel Vertikales (mehrstoeckige Haeuser, Turm,
Treppen, Kabel, Baumkronen) und Details in Vorder-, Mittel- und Hintergrund.
"shots": [..] beschraenkt ein Objekt auf bestimmte Shots (z. B. den Rollstuhl).
"""

# --------------------------------------------------------------------------- #
# Wiederkehrende Bausteine
# --------------------------------------------------------------------------- #
_HAEUSER = [
    # (x, y, breite, tiefe, hoehe, farbe, dachfarbe, drehung)
    (-9.5, -15.0, 6.4, 7.5, 7.2, "#A34B4B", "#4A4038", -4),
    (10.0, -13.0, 5.6, 7.0, 5.4, "#D7C59A", "#5A5C60", 5),
    (-10.5, -3.5, 6.0, 6.6, 8.4, "#8C8C8C", "#4A4038", 2),
    (9.6, -1.5, 5.4, 6.4, 4.8, "#789082", "#4A4038", -6),
    (-9.8, 9.0, 6.2, 7.2, 6.6, "#CC9966", "#5A5C60", 3),
    (10.2, 10.5, 5.8, 6.8, 7.6, "#74869D", "#4A4038", -3),
]

OBJECTS = [
    # ------------------------------------------------------------------ Boden
    {"type": "organic_ground", "name": "boden", "params": {
        "size": (96.0, 96.0), "subdivisions": 72, "hills": 1.15, "roughness": 0.6,
        "texture": "grass", "color": "#4E7A3A", "seed": 3.7}},
    {"type": "curved_road", "name": "strasse", "params": {
        "points": [(0.0, -30.0), (1.6, -12.0), (-1.8, 4.0), (0.9, 20.0), (0.0, 30.0)],
        "width": 6.0, "texture": "asphalt", "sidewalk": 1.5,
        "sidewalk_texture": "studs_2006", "curb_height": 0.14}},
]

# ------------------------------------------------------------------ Haeuser
for index, (x, y, width, depth, height, color, roof_color, rotation) in enumerate(_HAEUSER):
    OBJECTS.append({
        "type": "block", "name": f"haus_{index}", "pos": [x, y, height / 2],
        "size": [width, depth, height], "color": color, "texture": "brick",
        "rotation": [0, 0, rotation],
        "params": {"top_texture": "roof_shingles", "uv_scale": 0.35, "bevel": 0.05},
    })
    OBJECTS.append({
        "type": "gable_roof", "name": f"dach_{index}", "pos": [x, y, height],
        "params": {"footprint": (width, depth), "height": 2.1, "color": roof_color,
                   "texture": "roof_shingles", "rotation": (0, 0, rotation)},
    })
    # zwei warme Fenster je Haus (Abendlicht = Herz der Stadt)
    for window in range(2):
        OBJECTS.append({
            "type": "window_light", "name": f"fenster_{index}_{window}",
            "pos": [x - width / 2 + 1.1 + window * (width - 2.2), y - depth / 2 - 0.03,
                    height * (0.45 + 0.22 * window)],
            "size": [0.95, 0.07, 1.15], "color": "#FFC978",
            "rotation": [0, 0, rotation],
            "params": {"emission": 3.2},
        })
    # Hauseingang
    OBJECTS.append({
        "type": "block", "name": f"tuer_{index}",
        "pos": [x + width / 2 - 1.0, y - depth / 2 - 0.06, 1.1],
        "size": [1.0, 0.12, 2.2], "color": "#694028", "texture": "wood",
        "rotation": [0, 0, rotation],
    })
    # schiefer Schornstein (organische Silhouette)
    OBJECTS.append({
        "type": "cylinder", "name": f"schornstein_{index}",
        "pos": [x + width * 0.28, y + depth * 0.2, height + 2.6],
        "params": {"radius": 0.28, "depth": 1.8, "color": "#635F62",
                   "texture": "brick", "vertices": 12, "rotation": (0, 0, rotation)},
    })

# ------------------------------------------------------------------ Strassen
for index, y in enumerate((-18.0, -8.0, 2.0, 12.0, 22.0)):
    OBJECTS.append({
        "type": "street_lamp", "name": f"laterne_{index}",
        "pos": [(-4.3 if index % 2 == 0 else 4.3), y, 0.0],
        "params": {"height": 5.4, "warm": "#FFC978", "energy": 9.0, "arm": 0.8},
    })

for index, (start, end, sag) in enumerate((
    ((-4.3, -8.0, 6.4), (4.3, -2.0, 5.9), 0.85),
    ((4.3, 2.0, 6.4), (-4.3, 9.0, 6.0), 0.95),
    ((-4.3, 12.0, 6.2), (4.3, 18.0, 5.8), 0.75),
)):
    OBJECTS.append({
        "type": "hanging_cable", "name": f"kabel_{index}",
        "params": {"start": start, "end": end, "sag": sag, "radius": 0.035,
                   "color": "#1B2A35", "bulbs": True, "bulb_color": "#FFD79A"},
    })

# ------------------------------------------------------------------ Natur
for index, (x, y, height) in enumerate((
    (-14.0, -20.0, 7.0), (14.5, -6.0, 6.2), (-14.5, 6.0, 7.8), (14.0, 18.0, 6.6),
)):
    OBJECTS.append({
        "type": "tree", "name": f"baum_{index}", "pos": [x, y, 0.0],
        "params": {"height": height, "crown": 1.1, "trunk_color": "#694028",
                   "leaf_color": "#3F6B34", "seed": 1.0 + index},
    })

for index, (x, y) in enumerate(((-5.6, -14.0), (5.8, -4.0), (-6.0, 7.5), (6.0, 15.0))):
    OBJECTS.append({
        "type": "bush", "name": f"busch_{index}", "pos": [x, y, 0.0],
        "params": {"radius": 0.75, "color": "#4E7A3A", "seed": 2.0 + index},
    })

for index, (x, y) in enumerate(((-4.9, -11.0), (4.7, -6.5), (-5.2, 0.5), (5.1, 8.0),
                                (-4.6, 16.0), (4.9, 21.0))):
    OBJECTS.append({
        "type": "grass_tuft", "name": f"gras_{index}", "pos": [x, y, 0.0],
        "params": {"size": 0.24, "color": "#5C8B3E"},
    })

for index, (x, y, radius) in enumerate(((-3.9, -2.0, 0.28), (4.1, 5.0, 0.32), (-4.4, 13.0, 0.24))):
    OBJECTS.append({
        "type": "stone", "name": f"stein_{index}", "pos": [x, y, 0.0],
        "params": {"radius": radius, "color": "#8C8C8C", "seed": 3.0 + index},
    })

# ------------------------------------------------------------------ Alltag
OBJECTS += [
    {"type": "fence", "name": "zaun_links", "params": {
        "start": (-6.6, 4.0, 0.0), "end": (-6.6, 8.4, 0.0), "height": 1.5,
        "posts": 6, "color": "#7C5C46", "texture": "wood"}},
    {"type": "fence", "name": "zaun_rechts", "params": {
        "start": (6.7, -6.0, 0.0), "end": (6.7, -1.0, 0.0), "height": 1.4,
        "posts": 5, "color": "#7C5C46", "texture": "wood"}},
    {"type": "bench", "name": "bank_links", "pos": [-5.4, 2.5, 0.0],
     "params": {"rotation_z": 88.0, "length": 2.4, "color": "#7C5C46"}},
    {"type": "bench", "name": "bank_rechts", "pos": [5.6, 12.0, 0.0],
     "params": {"rotation_z": -92.0, "length": 2.2, "color": "#7C5C46"}},
    {"type": "mailbox", "name": "briefkasten_1", "pos": [-4.4, -1.0, 0.0],
     "params": {"color": "#0D69AC", "rotation_z": 12.0}},
    {"type": "mailbox", "name": "briefkasten_2", "pos": [4.4, 9.5, 0.0],
     "params": {"color": "#C4281C", "rotation_z": -8.0}},
    {"type": "trash_can", "name": "muelleimer_1", "pos": [-4.2, 6.2, 0.0],
     "params": {"radius": 0.34, "color": "#287F47"}},
    {"type": "trash_can", "name": "muelleimer_2", "pos": [4.3, -9.5, 0.0],
     "params": {"radius": 0.32, "color": "#287F47"}},
    {"type": "bicycle", "name": "fahrrad", "pos": [-5.0, -6.0, 0.0],
     "params": {"rotation_z": 96.0, "color": "#1B2A35"}},
    {"type": "puddle", "name": "pfuetze_1", "pos": [1.2, -5.0, 0.09],
     "params": {"radius": 1.5, "color": "#2C3A44"}},
    {"type": "puddle", "name": "pfuetze_2", "pos": [-2.0, 7.5, 0.09],
     "params": {"radius": 1.2, "color": "#2C3A44"}},
    {"type": "puddle", "name": "pfuetze_3", "pos": [2.4, 16.0, 0.09],
     "params": {"radius": 1.8, "color": "#2C3A44"}},
]

# ------------------------------------------------------------------ Vertikales
OBJECTS += [
    {"type": "stairs", "name": "treppe_huegel", "pos": [0.0, 24.0, 0.0],
     "params": {"width": 6.4, "height": 2.2, "depth": 4.0, "steps": 9,
                "color": "#B0ACA6", "texture": "concrete"}},
    {"type": "arch", "name": "tor_uhr", "pos": [0.0, 26.5, 0.0],
     "params": {"width": 5.0, "height": 3.4, "depth": 0.9, "thickness": 0.45,
                "color": "#CFC6B4", "texture": "limestone"}},
    {"type": "truss", "name": "fachwerk", "pos": [-11.5, 4.0, 4.0],
     "params": {"size": (0.9, 0.9, 8.0), "segments": 4,
                "color": "#635F62", "texture": "classic_diamond_plate"}},
    {"type": "scatter", "name": "grasflaeche", "params": {
        "builder_name": "grass_tuft", "count": 14, "area": (-16.0, 16.0, -22.0, 24.0),
        "seed": 11.0, "size": 0.2, "color": "#5C8B3E"}},
]

# ------------------------------------------------------------------ Schilder
OBJECTS += [
    {"type": "sign", "name": "ortsschild", "pos": [4.9, 20.5, 3.2],
     "text": "SCHRITTSTADT", "params": {
         "size": 0.55, "font": "oswald", "color": "#F2F3F3",
         "board_color": "#0D69AC", "board_texture": "metal", "border": True,
         "border_color": "#E5E4DE", "rotation_z": -92.0}},
    {"type": "sign", "name": "baeckerei", "pos": [8.4, -4.9, 3.4], "text": "BÄCKEREI KLEIN",
     "params": {"size": 0.36, "font": "marker", "color": "#FFF1CF",
                "board_color": "#7C5C46", "board_texture": "wood_planks",
                "border": False, "rotation_z": -4.0, "neon": 1.6}},
    {"type": "sign", "name": "briefkasten_schild", "pos": [-4.4, -1.55, 2.1],
     "text": "BRIEFE", "params": {"size": 0.22, "font": "inter", "color": "#FFFFFF",
                                  "board_color": "#0D69AC", "board_texture": "metal",
                                  "border": False}},
    {"type": "sign", "name": "warnschild", "pos": [-4.9, 13.5, 2.6],
     "text": "ACHTUNG: 0 SCHRITTE", "params": {
         "size": 0.28, "font": "oswald", "color": "#1B2A35",
         "board_color": "#F5CD30", "board_texture": "metal", "border": True,
         "border_color": "#1B2A35", "rotation_z": 180.0}},
    {"type": "sign", "name": "schultafel", "pos": [0.0, -20.4, 2.2],
     "text": "HEUTE: 10.000 SCHRITTE", "params": {
         "size": 0.38, "font": "chalk", "color": "#F4F1E4",
         "board_color": "#27462D", "board_texture": "slate", "border": True,
         "border_color": "#7C5C46", "rotation_z": 0.0}},
    {"type": "text3d", "name": "himmelszahl", "pos": [0.0, 30.0, 12.0], "text": "10.000",
     "params": {"size": 2.6, "font": "bebas", "color": "#FFE9A8",
                "extrude": 0.16, "bevel": 0.02, "rotation": (90, 0, 0),
                "emission": 1.2}},
]

# ------------------------------------------------------------------ Eigene Modelle
OBJECTS += [
    {"type": "custom_model", "name": "stadtuhr", "model": "stadtuhr",
     "pos": [0.0, 29.5, 0.0], "rotation": [0, 0, 0]},
    {"type": "custom_model", "name": "schrittzaehler_saeule", "model": "schrittzaehler",
     "pos": [-3.6, -9.0, 0.0]},
    {"type": "custom_model", "name": "lieblingsbriefkasten", "model": "roter_briefkasten",
     "pos": [3.9, 18.0, 0.0], "rotation": [0, 0, -15]},
    # Der Rollstuhl erscheint erst, wenn Mika ihn holt.
    {"type": "custom_model", "name": "rollstuhl", "model": "rollstuhl",
     "pos": [1.9, 7.1, 0.0], "rotation": [0, 0, 2], "shots": [9, 10, 11, 12, 13, 14]},
]

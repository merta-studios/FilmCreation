"""Die kleine Laternenstrasse - verwinkelte Nachbarschaft bei Regen."""

OBJECTS = [
    {"type": "organic_ground", "name": "nasser_gruenstreifen", "params": {
        "size": (76.0, 76.0), "subdivisions": 48, "hills": 0.45,
        "roughness": 0.35, "texture": "grass", "color": "#435C43", "seed": 8.2}},
    {"type": "curved_road", "name": "regenstrasse", "params": {
        "points": [(0.0, -27.0), (1.0, -12.0), (-0.6, 2.0), (0.7, 18.0), (0.0, 28.0)],
        "width": 5.5, "texture": "asphalt", "sidewalk": 1.4,
        "sidewalk_texture": "concrete", "curb_height": 0.12}},
]

# Gegenueberliegende, leicht versetzte Haeuser mit warmen Fenstern.
_HOUSES = [
    (-8.8, -15.0, 6.0, 6.2, 7.5, "#A34B4B"),
    (8.6, -12.0, 6.5, 6.0, 6.2, "#D7C59A"),
    (-9.2, -1.5, 6.3, 6.0, 8.2, "#789082"),
    (9.1, 2.0, 6.2, 6.5, 7.0, "#74869D"),
    (-8.5, 12.5, 6.8, 6.0, 6.8, "#CC9966"),
    (8.8, 15.0, 6.2, 6.0, 8.0, "#8C8C8C"),
]
for i, (x, y, w, d, h, color) in enumerate(_HOUSES):
    OBJECTS.append({"type": "block", "name": f"haus_{i}", "pos": [x, y, h / 2],
                    "size": [w, d, h], "color": color, "texture": "brick",
                    "rotation": [0, 0, (i % 3 - 1) * 3]})
    OBJECTS.append({"type": "gable_roof", "name": f"dach_{i}", "pos": [x, y, h],
                    "params": {"footprint": (w, d), "height": 1.8,
                               "color": "#4A4038", "texture": "roof_shingles"}})
    for j in range(2):
        OBJECTS.append({"type": "window_light", "name": f"fenster_{i}_{j}",
                        "pos": [x - 1.3 + j * 2.6, y - d / 2 - 0.05, h * 0.58],
                        "size": [0.95, 0.08, 1.1], "color": "#FFC978",
                        "params": {"emission": 2.0}})
    OBJECTS.append({"type": "block", "name": f"haustuer_{i}",
                    "pos": [x + w * 0.27, y - d / 2 - 0.08, 1.05],
                    "size": [0.95, 0.12, 2.1], "color": "#694028", "texture": "wood"})

for i, y in enumerate((-19.0, -10.0, -1.0, 8.0, 18.0, 25.0)):
    OBJECTS.append({"type": "street_lamp", "name": f"laterne_{i}",
                    "pos": [(-4.0 if i % 2 == 0 else 4.0), y, 0.0],
                    "params": {"height": 5.2, "warm": "#FFC978", "energy": 6.0}})

for i, (x, y) in enumerate(((-14, -19), (14, -8), (-14, 5), (14, 17), (-11, 25))):
    OBJECTS.append({"type": "tree", "name": f"regenbaum_{i}", "pos": [x, y, 0.0],
                    "params": {"height": 6.5 + (i % 2), "crown": 1.0,
                               "trunk_color": "#694028", "leaf_color": "#3F6B34",
                               "seed": 12 + i}})
for i, (x, y) in enumerate(((-5.4, -6), (5.5, 5), (-5.5, 14), (5.3, 22))):
    OBJECTS.append({"type": "bush", "name": f"busch_{i}", "pos": [x, y, 0.0],
                    "params": {"radius": 0.72, "color": "#4E7A3A", "seed": 20 + i}})
for i, (x, y) in enumerate(((-4.2, -14), (4.4, -3), (-4.5, 9), (4.2, 18))):
    OBJECTS.append({"type": "puddle", "name": f"pfuetze_{i}", "pos": [x, y, 0.08],
                    "params": {"radius": 1.0 + i * 0.12, "color": "#34434E"}})

OBJECTS += [
    # Kleine Kuechenecke, nur im vierten Shot sichtbar.
    {"type": "block", "name": "kuechenwand", "pos": [-5.0, -3.6, 3.0],
     "size": [8.0, 0.3, 6.0], "color": "#59636A", "texture": "plaster", "shots": [4]},
    {"type": "block", "name": "kuechentischplatte", "pos": [-1.4, -1.5, 1.35],
     "size": [2.8, 1.35, 0.16], "color": "#7C5C46", "texture": "wood", "shots": [4]},
    {"type": "block", "name": "tischbein_a", "pos": [-2.5, -1.5, 0.62],
     "size": [0.12, 0.12, 1.25], "color": "#635F62", "texture": "wood", "shots": [4]},
    {"type": "block", "name": "tischbein_b", "pos": [-0.3, -1.5, 0.62],
     "size": [0.12, 0.12, 1.25], "color": "#635F62", "texture": "wood", "shots": [4]},
    {"type": "cylinder", "name": "kalter_tee", "pos": [-1.7, -1.35, 1.55],
     "params": {"radius": 0.16, "depth": 0.38, "color": "#8A6846", "vertices": 16},
     "shots": [4]},
    {"type": "block", "name": "ungeoeffnete_briefstapel", "pos": [-0.9, -1.45, 1.48],
     "size": [0.5, 0.38, 0.08], "color": "#E8DECB", "texture": "cardboard", "shots": [4]},
    {"type": "bench", "name": "bank_am_laden", "pos": [-5.3, -2.0, 0.0],
     "params": {"length": 2.2, "rotation_z": 88, "color": "#7C5C46"}},
    {"type": "mailbox", "name": "briefkasten", "pos": [4.5, 4.0, 0.0],
     "params": {"color": "#C4281C", "rotation_z": -8}},
    {"type": "trash_can", "name": "muelleimer", "pos": [-4.2, 12.0, 0.0],
     "params": {"radius": 0.32, "color": "#287F47"}},
    {"type": "bicycle", "name": "abgestelltes_fahrrad", "pos": [5.1, -15.0, 0.0],
     "params": {"rotation_z": 92, "color": "#1B2A35"}},
    {"type": "fence", "name": "gartenzaun", "params": {
        "start": (-6.8, 8.0, 0.0), "end": (-6.8, 13.0, 0.0), "height": 1.3,
        "posts": 6, "color": "#7C5C46", "texture": "wood"}},
    {"type": "sign", "name": "regel_schild", "pos": [4.7, 21.0, 3.0],
     "text": "JEDER NAME ZAEHLT", "params": {
        "size": 0.38, "font": "oswald", "color": "#F2F3F3",
        "board_color": "#27462D", "board_texture": "wood_planks", "border": True}},
    {"type": "sign", "name": "laden_schild", "pos": [-8.8, -18.1, 4.0],
     "text": "KLEINER LADEN", "params": {
        "size": 0.36, "font": "marker", "color": "#FFF1CF",
        "board_color": "#7C5C46", "board_texture": "wood", "border": False}},
    {"type": "custom_model", "name": "namenslaterne", "model": "namenlaterne",
     "pos": [0.0, 26.0, 0.0]},
]

# Verteilt kleine Grasdetails ueber die Raender, ohne die Spielwege zu blockieren.
OBJECTS.append({"type": "scatter", "name": "grasdetails", "params": {
    "builder_name": "grass_tuft", "count": 18,
    "area": (-16.0, 16.0, -24.0, 24.0), "seed": 27,
    "size": 0.18, "color": "#5C8B3E"}})

"""Eigene, per Python modellierte Spezialobjekte fuer genau diese Story.

Jede Funktion bekommt den ``world``-Baukasten (1_system/blender_engine/primitives_and_map.py)
und baut daraus ein Objekt. So lassen sich Dinge erschaffen, die es im Creator Store
nicht gibt - hier: die Stadtuhr, die Schritt-Saeule, der rote Briefkasten und der
Rollstuhl, in dem Mikas Mutter sitzt.

Aufruf in map_and_props.py:
    {"type": "custom_model", "name": "stadtuhr", "model": "stadtuhr", "pos": [0, 29.5, 0]}
"""


def stadtuhr(world, pos=(0, 0, 0), rotation=(0, 0, 0), **params):
    """Der Turm mit der grossen Uhr - Ziel des letzten Spaziergangs."""
    x, y, z = pos
    height = float(params.get("height", 13.0))
    world.block("uhr_turm", (x, y, z + height / 2), (3.8, 3.8, height),
                color="#CFC6B4", texture="limestone", uv_scale=0.3)
    world.block("uhr_kranz", (x, y, z + height - 0.4), (4.4, 4.4, 0.8),
                color="#635F62", texture="metal")
    world.cone("uhr_spitze", (x, y, z + height + 2.1), 2.5, 4.0,
               color="#4A4038", texture="roof_shingles")
    # Ziffernblatt zur Strasse (Blick nach -Y)
    world.cylinder("uhr_blatt", (x, y - 1.95, z + height - 2.3), 1.5, 0.16,
                   color="#F2F3F3", texture="marble", rotation=(90, 0, 0), vertices=32)
    world.cylinder("uhr_rand", (x, y - 1.88, z + height - 2.3), 1.6, 0.08,
                   color="#EEC63A", texture="metal", rotation=(90, 0, 0), vertices=32)
    world.block("uhr_zeiger_stunde", (x, y - 2.02, z + height - 1.75), (0.1, 0.06, 1.05),
                color="#1B2A35", texture="metal")
    world.block("uhr_zeiger_minute", (x + 0.55, y - 2.02, z + height - 2.3), (1.15, 0.06, 0.1),
                color="#1B2A35", texture="metal")
    world.cylinder("uhr_nabe", (x, y - 2.06, z + height - 2.3), 0.12, 0.1,
                   color="#EEC63A", texture="metal", rotation=(90, 0, 0), vertices=12)
    # Inschrift am Sockel
    world.sign("uhr_inschrift", (x, y - 1.96, z + 3.2),
               "JEDER SCHRITT ZÄHLT",
               size=0.26, width=3.2, height=0.7, font="lora", color="#F2F3F3",
               board_color="#635F62", board_texture="slate", border=False)
    return None


def schrittzaehler(world, pos=(0, 0, 0), rotation=(0, 0, 0), **params):
    """Oeffentliche Saeule, die die Schritte der ganzen Stadt anzeigt."""
    x, y, z = pos
    world.cylinder("zaehler_mast", (x, y, z + 1.6), 0.12, 3.2,
                   color="#635F62", texture="metal", vertices=12)
    world.block("zaehler_kasten", (x, y, z + 3.4), (1.5, 0.36, 0.85),
                color="#1B2A35", texture="metal")
    world.sign("zaehler_schild", (x, y - 0.22, z + 3.4), "STADT-SCHRITTE",
               size=0.16, width=1.25, height=0.45, font="spacemono", color="#7BE0C1",
               board_color="#101418", board_texture="metal", border=False, neon=2.4)
    world.sign("zaehler_zahl", (x, y - 0.22, z + 2.85), "1.284.930",
               size=0.2, width=1.25, height=0.42, font="spacemono", color="#FFE9A8",
               board_color="#101418", board_texture="metal", border=False, neon=1.8)
    return None


def roter_briefkasten(world, pos=(0, 0, 0), rotation=(0, 0, 0), **params):
    """Alter, roter Briefkasten mit Schlitz - der Ort, an dem alle sparen."""
    x, y, z = pos
    world.block("briefkasten_korpus", (x, y, z + 1.25), (0.9, 0.55, 1.1),
                color="#C4281C", texture="metal", rotation=(0, 0, rotation[2]))
    world.block("briefkasten_dach", (x, y, z + 1.85), (1.0, 0.62, 0.12),
                color="#A34B4B", texture="metal", rotation=(0, 0, rotation[2]))
    world.block("briefkasten_schlitz", (x, y - 0.3, z + 1.55), (0.55, 0.04, 0.1),
                color="#1B2A35", texture="metal", rotation=(0, 0, rotation[2]))
    world.cylinder("briefkasten_fuss", (x, y, z + 0.35), 0.08, 0.7,
                   color="#635F62", texture="metal", vertices=10)
    world.sign("briefkasten_text", (x, y - 0.34, z + 1.05), "LETZTE LEERUNG 6:00",
               size=0.1, width=0.8, height=0.24, font="inter", color="#FFF1CF",
               board_color="#C4281C", board_texture="metal", border=False)
    return None


def rollstuhl(world, pos=(0, 0, 0), rotation=(0, 0, 0), **params):
    """Rollstuhl aus Rohren, Raedern und Sitz - Tragewerkzeug der Hoffnung."""
    x, y, z = pos
    angle = float(rotation[2]) if rotation else 0.0
    steel = "#9FA3A6"
    fabric = "#1B2A35"
    for side in (-1, 1):
        world.torus(f"rollstuhl_rad_{side}", (x + side * 0.62, y, z + 0.62),
                    0.6, 0.055, color=steel, texture="metal", rotation=(0, 90, 0))
        world.torus(f"rollstuhl_felge_{side}", (x + side * 0.62, y, z + 0.62),
                    0.45, 0.02, color="#635F62", texture="metal", rotation=(0, 90, 0))
        world.torus(f"rollstuhl_lenkrad_{side}", (x + side * 0.5, y - 0.75, z + 0.25),
                    0.16, 0.03, color="#1B2A35", texture="metal", rotation=(0, 90, 0))
    world.block("rollstuhl_sitz", (x, y, z + 0.78), (1.2, 1.05, 0.12),
                color=fabric, texture="fabric", rotation=(0, 0, angle))
    world.block("rollstuhl_lehne", (x, y + 0.55, z + 1.35), (1.2, 0.1, 1.0),
                color=fabric, texture="fabric", rotation=(0, 0, angle))
    world.block("rollstuhl_fussraste", (x, y - 0.62, z + 0.34), (1.0, 0.42, 0.06),
                color=steel, texture="metal", rotation=(0, 0, angle))
    for side in (-1, 1):
        world.pipe(f"rollstuhl_holm_{side}", (x + side * 0.56, y + 0.55, z + 0.8),
                   (x + side * 0.56, y + 0.55, z + 1.9), radius=0.045,
                   color=steel, texture="metal")
        world.pipe(f"rollstuhl_strebe_{side}", (x + side * 0.56, y - 0.5, z + 0.35),
                   (x + side * 0.56, y + 0.5, z + 1.1), radius=0.04,
                   color=steel, texture="metal")
    world.pipe("rollstuhl_schiebebuegel", (x - 0.6, y + 0.62, z + 1.9),
               (x + 0.6, y + 0.62, z + 1.9), radius=0.045, color="#1B2A35",
               texture="fabric")
    return None


MODELS = {
    "stadtuhr": stadtuhr,
    "schrittzaehler": schrittzaehler,
    "roter_briefkasten": roter_briefkasten,
    "rollstuhl": rollstuhl,
}

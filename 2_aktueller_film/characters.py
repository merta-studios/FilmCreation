"""Figuren des aktuellen Films.

Regeln (werden von validate_film.py geprueft):
* mindestens 3 Figuren: 1 Hauptfigur + mindestens 2 Nebenfiguren
* genau eine Rolle "hauptfigur"
* Farbe = Roblox-BrickColor-Name, Hex-Wert oder Hautton-Name
* Gesicht aus 1_system/blender_engine/rig_r15.py (FACES)
* counter = schwebender Stadt-Regel-Zaehler ueber dem Kopf (BillboardGui-Optik)
* relation = Beziehung zur Hauptfigur (Mutter, Mitschuelerin ...)
"""

CHARACTERS = [
    {
        "id": "mika",
        "name": "Mika",
        "role": "hauptfigur",
        "relation": "Ich-Erzähler, Sohn",
        "alter": 11,
        "skin": "fair",
        "shirt": "#0D69AC",          # verwaschenes Blau, zu klein gekauft
        "pants": "#635F62",
        "face": "sad",
        "height_scale": 0.92,
        "counter": {"start": "9.847", "label": "Schritte"},
        "accessories": [],           # nach der Asset-Anprobe hier eintragen
    },
    {
        "id": "mutter",
        "name": "Mama",
        "role": "nebenfigur",
        "relation": "Mutter von Mika",
        "alter": 39,
        "skin": "light",
        "shirt": "#8E5597",          # altes Lieblingskleid
        "pants": "#1B2A35",
        "face": "tired",
        "height_scale": 1.0,
        "counter": {"start": "300", "label": "Schritte"},
        "accessories": [],
    },
    {
        "id": "lina",
        "name": "Lina",
        "role": "nebenfigur",
        "relation": "Mitschülerin",
        "alter": 12,
        "skin": "warm",
        "shirt": "#DA867A",
        "pants": "#335882",
        "face": "angry",
        "height_scale": 0.96,
        "counter": {"start": "10.000", "label": "Schritte"},
        "accessories": [],
    },
    {
        "id": "opa",
        "name": "Opa Bert",
        "role": "statist",
        "relation": "Nachbar, sitzt immer auf der Bank",
        "alter": 78,
        "skin": "olive",
        "shirt": "#4E7A3A",
        "pants": "#7C5C46",
        "face": "neutral",
        "height_scale": 0.9,
        "counter": {"start": "12", "label": "Schritte"},
        "accessories": [],
    },
]

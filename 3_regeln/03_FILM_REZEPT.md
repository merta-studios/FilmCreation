# 03 – Film-Rezept: die sieben Dateien (mit echten Schemata)

Ein Film ist ein Ordner. Standard: `2_aktueller_film/`. Jede Datei hat genau
diesen Vertrag – `film_loader` liest sie, `validate_film` prüft sie.

```
2_aktueller_film/
├── film_config.yaml        # Format, Qualität, Untertitel, Licht-Look, Look-Ära
├── script_and_voices.yaml  # Sprechtext in Segmenten (Sprecher, Pause, Emotion)
├── characters.py           # CHARACTERS = [...]
├── map_and_props.py        # OBJECTS = [...], optional OPTIONAL_MAP_BUILD
├── custom_models.py        # MODELS = {"name": funktion(world, pos, rotation, **params)}
├── custom_animations.py    # def register(lib): ...   (optional)
└── shots.py                # SHOTS = [...]
```

## 1. `film_config.yaml`

```yaml
titel: "In dieser Stadt hat jeder nur 10.000 Schritte"
slug: schritte

format: {width: 1080, height: 1920, fps: 24}   # unveränderlich

qualitaet: high            # preview | high | max
subtitles: true            # Pflichtfeld, boolesch

musik:
  mood: melancholisch      # aus MUSIC_MOODS
  gain_db: -20
  auto_ducking: true
sfx_gain_db: -14

look_era: mix              # classic | modern | mix
color_look: "AgX - Medium High Contrast"

safe_zone: {bottom_px: 380, right_ui_px: 190, top_px: 110}

untertitel_stil:           # optional
  font: inter
  size: 62
  highlight: "#FFD700"
```

`titel` muss nicht leer sein, `qualitaet` muss in `preview|high|max` liegen,
`subtitles` muss ein echter Boolean sein (`true`/`false`, nicht `"true"`).

## 2. `script_and_voices.yaml`

```yaml
titel: "..."
segments:
  - id: 1
    speaker: haupt_erzaehler     # oder eine ID aus 3_regeln/empfohlene_elevenlabs_stimmen.yaml
    emotion: ruhig
    text: >
      In dieser Stadt hat jeder Mensch genau zehntausend Schritte.
    pause_after: 0.7             # Sekunden, 0–6
```

* 3–40 Segmente, insgesamt 60–120 s Sprechzeit.
* `text` wird 1:1 gesprochen. Zeichen zählen für die Credits: ca. 1 Zeichen =
  1 Credit, plus 15 % Puffer.
* Kein Markdown, keine Klammern, keine Regieanweisungen im Text.

**Stimmen** stehen in `3_regeln/empfohlene_elevenlabs_stimmen.yaml`:

```yaml
haupt_erzaehler:
  voice_id: "VR6AewLTigWG4xSOukaG"
  stability: 0.5
  similarity_boost: 0.75
nebenstimmen:
  neb_lina: {voice_id: "EXAVITQu4vr4xnSDxMaL", stability: 0.55}
```

Fehlt `voice_id`, kann nicht gesprochen werden (nur `--dry-run`/`--credits-only`
laufen). Jede Stimme muss auf mindestens einem der API-Keys freigeschaltet sein.

## 3. `characters.py`

```python
CHARACTERS = [
    {
        "id": "mika",                 # eindeutig, klein, ASCII
        "name": "Mika",               # Anzeigename
        "role": "hauptfigur",         # genau 1×; sonst nebenfigur | statist
        "relation": "Ich-Erzähler, Sohn",
        "alter": 11,
        "skin": "fair",               # fair|light|warm|olive|brown|deep
        "shirt": "#0D69AC",           # Hex oder BrickColor-Name
        "pants": "#635F62",
        "face": "sad",                # aus FACE_NAMES
        "height_scale": 0.92,         # 0.85–1.05
        "counter": {"start": "9.847", "label": "Schritte"},
        "accessories": [
            {"id": 123, "path": "assets/models/123.glb",
             "slot": "HatAttachment", "scale": 1.0, "offset": [0, 0, 0]},
        ],
    },
]
```

Regeln: genau eine `hauptfigur`, mindestens zwei `nebenfigur`, Füße auf z = 0,
`accessories` nur mit Pfaden, die `prepare_assets` erzeugt hat.

## 4. `map_and_props.py`

```python
OBJECTS = [
    {"type": "organic_ground", "name": "boden",
     "params": {"size": (96, 96), "texture": "grass", "hills": 1.15}},
    {"type": "curved_road", "name": "strasse",
     "params": {"points": [(0, -30), (1.6, -12), (-1.8, 4), (0.9, 20)],
                "width": 6.0, "sidewalk": 1.5}},
    {"type": "block", "name": "haus_1", "pos": [-9.5, -15, 3.6],
     "size": [6.4, 7.5, 7.2], "color": "#A34B4B", "texture": "brick",
     "rotation": [0, 0, -4]},
    {"type": "custom_model", "name": "stadtuhr", "model": "stadtuhr",
     "pos": [0, 29.5, 0], "params": {"height": 13.0}},
    {"type": "sign", "name": "schild", "pos": [2.0, 6.0, 2.4],
     "params": {"text": "JEDER SCHRITT ZÄHLT", "font": "lora"}},
]
OPTIONAL_MAP_BUILD = "nachbarschaft_ergaenzen"   # optional: def nachbarschaft_ergaenzen(world)
```

Pflicht: `organic_ground`, eine Straße (`curved_road` oder `block`-Straße),
mindestens 8 Detailobjekte (Bäume, Lampen, Mülltonnen, Pfützen, Büsche …),
mindestens 2 Schilder mit lesbarem Text, insgesamt mindestens 25 Objekte.
Alles, was sich auf Shots beschränken soll, bekommt `"shots": [7, 8]`.

## 5. `custom_models.py`

```python
def stadtuhr(world, pos=(0, 0, 0), rotation=(0, 0, 0), **params):
    """Der Turm mit der großen Uhr."""
    x, y, z = pos
    world.block("uhr_turm", (x, y, z + 6.5), (3.8, 3.8, 13.0),
                color="#CFC6B4", texture="limestone")

MODELS = {"stadtuhr": stadtuhr}
```

Jeder Name in `MODELS` muss eine aufrufbare Funktion sein; jedes `custom_model`
in der Map muss dort existieren. Rückgabe ist egal (None genügt).

## 6. `custom_animations.py`

```python
def register(lib):
    clip = lib.new("schritte_zaehlen", duration=48, loop=False)
    lib.key("RightUpperArm", {0: (0, 0, 0), 12: (-70, 0, 0), 24: (0, 0, 0)})
    lib.face(24, "hopeful")
```

Wird beim Laden von `scene_builder` und `validate_film` ausgeführt. Fehler hier
sind harte Fehler. (30 eingebaute Clips: siehe `02_BAUKASTEN_HANDBUCH.md`.)

## 7. `shots.py`

```python
SHOTS = [
    {
        "id": 1,
        "segment_id": 1,                 # muss existieren
        "title": "Die Stadt und ihre Regel",
        "camera": {
            "move": "crane_reveal",      # nie statisch
            "target": "mika",            # Figuren-ID oder Objektname
            "focal": 32,                 # 14–120 mm
            "fill": 0.40,                # 0.2–1.1 (Anteil Bildhöhe)
            "azimuth": -38,              # Grad um das Ziel
            "height": 3.2,               # m über dem Boden
            "fstop": 4.0,
            "breathing": 1.2,            # optional, Handheld-Atmung
            "arc_degrees": 40,           # optional für orbit_arc
            "start": [x, y, z],          # optional, nur wenn move es braucht
            "end": [x, y, z],
        },
        "lighting": "foggy_morning",     # aus MOOD_NAMES
        "characters": [
            {"id": "mika", "at": [0.4, 8.0, 0.0], "facing": 96,
             "anim": "walk_sad", "face": "sad",
             "counter": "9.847 Schritte", "speed": 0.8, "talking": False},
        ],
        "sfx": ["wind", {"kind": "city_ambience", "gain_db": -22}],
        "effects": {"particles": "mist", "fog": 1.5},
        "triggers": [
            {"on_word": "zehntausend", "action": "camera_focal", "value": 40},
            {"on_word": "Briefkasten", "action": "face", "value": "hopeful",
             "character": "mika"},
        ],
    },
]
```

* Jedes Segment braucht mindestens einen Shot; mindestens 3 Shots insgesamt.
* `triggers[].on_word` muss im Text des Segments vorkommen (Groß-/Kleinschreibung
  egal, Umlaute zählen) – sonst Fehler.
* `triggers[].action` ∈ `anim, camera_focal, camera_focus, counter, face, music,
  sfx, shake, statue`.
* `characters[].anim` ∈ eingebaute Clips + `custom_animations`, `face` ∈
  `FACE_NAMES`, `sfx` ∈ `SFX_KINDS`.
* `effects.particles` kennt `rain, mist, dust, snow, none`; `fog` skaliert die
  Stimmung (0.5–2.0).

## Zeitliche Auflösung

Shots tragen **keine** eigenen Frames. `timeline_sync.resolve_shots` verteilt sie
wortgenau über die Segmente: Segmente werden geteilt, Pausen verlängern den
vorherigen Shot. Willst du einen Shot länger, gib dem Segment mehr Text oder eine
längere `pause_after`.

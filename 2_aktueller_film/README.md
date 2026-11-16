# Aktueller Film

Dieser Ordner enthält den kompletten, renderbaren Film „In dieser Stadt hat jeder
nur 10.000 Schritte“: 13 Segmente, 14 Shots, 4 Figuren, eine Stadt mit Turm,
Straße, Briefkasten und Rollstuhl.

Er ist gleichzeitig die **Vorlage**: Wenn der Betreiber einen neuen Film
freigibt, werden diese sieben Dateien ersetzt (Schemata in
`3_regeln/03_FILM_REZEPT.md`):

| Datei | Inhalt |
|---|---|
| `film_config.yaml` | Titel, Qualität, Untertitel, Musikstimmung, Licht-Look |
| `script_and_voices.yaml` | Sprechtext in Segmenten mit Sprecher und Pause |
| `characters.py` | `CHARACTERS` (1 Hauptfigur, 2+ Nebenfiguren, Statisten) |
| `map_and_props.py` | `OBJECTS` (Boden, Straße, Häuser, Details, Schilder) |
| `custom_models.py` | `MODELS` – eigene Modelle in Python (Stadtuhr, Rollstuhl …) |
| `custom_animations.py` | `register(lib)` – zusätzliche Clips (optional) |
| `shots.py` | `SHOTS` – Kamera, Licht, Figuren, SFX, Wort-Trigger |

Nach jeder Änderung:

```bash
python -m 1_system.tools.validate_film
python -m 1_system.blender_engine.scene_builder --preview-storyboard --still --shots all
```

`subtitles: true` ist die Entscheidung des Betreibers für diesen Film. Für neue
Filme wird sie **vor** dem Schreiben erfragt, nicht angenommen.

Die Stimme (`haupt_erzaehler.voice_id`) steht in
`3_regeln/empfohlene_elevenlabs_stimmen.yaml` – ohne sie ist nur ein
`--dry-run` möglich.

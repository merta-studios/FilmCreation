# Einstieg für KI-Agenten

Dieses Repository produziert automatisch 60–120-Sekunden-Roblox-Kurzfilme im
TikTok-Hochformat (1080×1920, 24 fps). Du bist der Regisseur und Techniker.

## Bevor du irgendetwas tust

1. Lies **alle** Dateien in `3_regeln/`, inklusive `3_regeln/eigene_notizen/`.
   `00_START_HIER.md` (Arbeitsregeln), `01_STORY_FORMEL_UND_PITCH.md` (Pitch),
   `02_BAUKASTEN_HANDBUCH.md` (was es technisch gibt) und
   `03_FILM_REZEPT.md` (Dateiformate) sind verbindlich.
2. Prüfe Credits, bevor du Text schreibst:
   `python -m 1_system.audio.generate_timeline --credits-only`
3. Lege einen vollständigen Pitch vor und warte auf ausdrückliche Freigabe.

## Grenzen

* Filme ändern: nur `2_aktueller_film/`.
* `1_system/` und `.github/workflows/`: nur bei ausdrücklich angefordertem
  System-Update.
* Format 9:16 ist fix. Untertitel-Entscheidung kommt vom Betreiber und steht in
  `film_config.yaml`.
* Keine erfundenen Asset-IDs, Texturen, Animationen oder Kamerabewegungen – das
  Inventar steht in `3_regeln/02_BAUKASTEN_HANDBUCH.md`.
* Nie behaupten, ein Render laufe oder ein Film sei fertig, ohne bestätigten
  erfolgreichen Lauf. Aktueller Stand, Secrets und Workflows: `EINRICHTUNG.md`.

## Prüfkommandos

```bash
python -m compileall -q 1_system 2_aktueller_film tests
python -m pytest -q
python -m 1_system.tools.validate_film            # 0 Fehler = baubar
python -m 1_system.blender_engine.scene_builder --list-shots
python -m 1_system.blender_engine.scene_builder --preview-storyboard --still --shots all
```

`CLAUDE.md` ist absichtlich identisch zu dieser Datei.

# FilmCreation – Roblox-Kurzfilmstudio

Ein Repository, das aus einer Idee einen 60–120-Sekunden-Roblox-Film im
TikTok-Hochformat macht: Sprechtext und Stimme aus ElevenLabs, prozedural gebaute
Roblox-Stadt, R15-Figuren mit eigenen Animationen, Blender-Render (GitHub-Runner
oder Kaggle T4), Schnitt mit FFmpeg, Untertitel optional.

```
Credits  →  Pitch  →  Freigabe  →  Filmdaten  →  Validierung
         →  Storyboard  →  Stimme  →  Shots  →  Schnitt  →  Release
```

## Aufbau

| Ordner | Inhalt |
|---|---|
| `1_system/` | Renderer, Audio, Roblox-API, Kaggle-Brücke, Werkzeuge |
| `2_aktueller_film/` | der aktuelle Film: Config, Text, Figuren, Map, Shots |
| `3_regeln/` | Arbeitsregeln, Story-Formel, Baukasten, Rezept, Empfehlungen |
| `tests/` | 60+ Tests für Parser, Pipeline, Kaggle-Brücke, Watchdog, Assets |
| `.github/workflows/` | Render (1+2), Kaggle-Fallback, Agenten-Helfer, CI |

## Schnellstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r 1_system/requirements.txt          # + 'bpy==4.2.0' für lokale Renders

python -m pytest -q
python -m 1_system.tools.validate_film --allow-unconfigured
python -m 1_system.audio.generate_timeline --credits-only
```

Render über GitHub:

```bash
gh workflow run 1-start-render.yml -f shots=all -f quality=high \
  -f render_target=auto -f subtitles=true
```

Hol dir danach `film-<run_id>` aus den Releases. Details, Secrets und
Fehlerbehebung: `EINRICHTUNG.md`.

## Was das System kann

* **Stadt**: 34 Objekttypen (organischer Boden, geschwungene Straße, Häuser,
  Turm, Laternen, Bäume, Kabel, Schilder …), 45 Roblox-Texturen, 68 BrickColors,
  eigene Modelle in Python.
* **Figuren**: echtes R15-Rig, 10 Gesichter, 12 Attachment-Slots, Roblox-Accessoires
  nach GLB-Konvertierung, 30 eingebaute Animationen + eigene Clips.
* **Kamera**: 12 erzwungene Bewegungen (kein statisches Bild), echte
  Brennweiten-/Fill-Berechnung, 9:16-Sicherheitszone.
* **Licht**: 8 Stimmungen, Regen/Nebel/Partikel, Vignette, AgX-Look.
* **Ton**: mehrere ElevenLabs-Keys mit Rotation, prozedurale SFX (20), Musik (7
  Stimmungen), Ducking, −14 LUFS, wortgenaue Karaoke-Untertitel.
* **Render**: Kaggle mit dynamischer GPU-Erkennung, getrennten Worker-Ausgaben,
  asynchronem GitHub-Watchdog und GitHub-Fallback; Manifest-Merge und
  Shot-Vollständigkeitsprüfung.
* **Schnitt**: 1080×1920 @ 24 fps, hart geprüft, Release automatisch.

## Grenzen

* Ein vollständiger Live-Lauf über GitHub Actions + Kaggle ist in diesem Stand
  **nicht** verifiziert; alle Teile sind einzeln getestet (Unit-Tests,
  Blender-Rauchtest im CI, synthetische Clips).
* Bildqualität hängt von Kaggle-GPU-Zeit ab. Auf GitHub-Runnern wird automatisch
  `preview` gerendert.
* Roblox-Assets nur mit gültigem Open-Cloud-Key und geprüfter Lizenz; Marken- und
  Franchise-Artikel lehnt das System ab.

## Für KI-Agenten

`AGENTS.md` (identisch: `CLAUDE.md`) lesen, dann **alle** Dateien in `3_regeln/`.
Ohne Freigabe des Betreibers wird kein Film geschrieben.

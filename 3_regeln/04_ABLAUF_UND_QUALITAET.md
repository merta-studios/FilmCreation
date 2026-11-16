# 04 – Ablauf, Render und Qualitätskontrolle

## Der Ablauf in einem Blick

```
Credits prüfen  →  Pitch  →  Freigabe  →  Filmdaten schreiben
      →  validate_film  →  Storyboard ansehen  →  Audiospur (ElevenLabs)
      →  Shots rendern (GitHub / Kaggle)  →  Schnitt  →  Release  →  prüfen
```

Zwei GitHub-Workflows tragen den Lauf, weil ein vollständiger 1080×1920-Render auf
GitHub-Runnern zu lange dauert (6 h Limit). Workflow 1 endet nach Audio +
Shots-Start, Workflow 2 wird von 1 automatisch gestartet und schneidet.

| Datei | Aufgabe |
|---|---|
| `.github/workflows/1-start-render.yml` | Credits, `generate_timeline`, `mix_audio`, Shots auf Kaggle starten (oder GitHub-Runner), Manifeste mergen |
| `.github/workflows/2-finish-film.yml` | Artefakte holen, `check_shots`, `assemble_final`, ffprobe-Prüfung, Release `film-<run_id>` |
| `.github/workflows/check-kaggle-fallback.yml` | alle 15 min: hängt Kaggle in Warteschlange/Laufzeit? → GitHub-Render übernehmen |
| `.github/workflows/agent-helper.yml` | Credits, Asset-Anprobe, Storyboard – ohne Render |
| `.github/workflows/ci.yml` | Tests, Validator, Blender-Rauchtest (nur bei System-Änderungen) |

## Lokal (zum Prüfen, nicht für den Endrender)

```bash
python -m 1_system.tools.validate_film                 # muss fehlerfrei sein
python -m 1_system.audio.generate_timeline --credits-only
python -m 1_system.audio.generate_timeline --dry-run --out-dir render_session
python -m 1_system.blender_engine.scene_builder --list-shots
python -m 1_system.blender_engine.scene_builder --preview-storyboard --still --shots 1-6
python -m 1_system.tools.preview_storyboard --shots-dir render_output/shots
python -m 1_system.tools.render_local --quality preview --shots 1-4   # kompletter Testlauf
```

Auf einem Rechner mit Blender genügt `1_system/tools/render_local.py`
(Audio → Shots → Schnitt in einem Aufruf). Dort ist `bpy` als Modul verfügbar;
auf GitHub/Kaggle wird `bpy==4.2.0` installiert.

## Render starten (GitHub)

```bash
gh workflow run 1-start-render.yml \
  -f shots=all -f quality=high -f render_target=auto \
  -f subtitles=true -f kaggle_timeout_minutes=180
```

* `render_target=auto`: Kaggle, wenn `KAGGLE_USERNAME` + `KAGGLE_KEY` gesetzt
  sind, sonst GitHub. Auf GitHub wird `quality` automatisch auf `preview`
  heruntergestuft, weil ein 6-h-Runner sonst nicht reicht – das steht im Log.
* `skip_credit_check=true` nur, wenn bereits Audio aus einem früheren Lauf
  existiert.
* Workflow 2 startet automatisch. Manuell:
  `gh workflow run 2-finish-film.yml -f run_id=<ID> -f quality=high`.

## Qualitätstore (jedes muss grün sein)

1. **Credits**: `CreditsReport.ok` – sonst wird nichts gesprochen.
2. **Validator**: 0 Fehler. Warnungen lesen, nicht ignorieren.
3. **Storyboard**: Standbilder je Shot angesehen (Gesicht sichtbar,
   Vordergrund/Mittelgrund/Hintergrund gefüllt, kein leeres Bild, Schrift lesbar,
   Gesichter in der Safe Zone).
4. **Shot-Check**: `check_shots` meldet alle Shots gerendert und alle Frames
   abgedeckt (`frames_covered == frames_total`).
5. **Schnitt**: `assemble_final` prüft exakt 1080×1920, 24/1 fps, Audiospur
   vorhanden, Datei ≥ 100 kB.
6. **Sichtprüfung des Endfilms**: erste und letzte Sekunde, Untertitel nicht
   abgeschnitten, Ton nicht übersteuert.

## Wenn Kaggle hängt

`check-kaggle-fallback.yml` läuft alle 15 Minuten:

* `--max-queue-minutes 45`: Kernel wartet zu lange → Abbruch.
* `--max-run-minutes 240`: Lauf zu lang → Abbruch.
* Bei Übernahme wird der GitHub-Render gestartet und – falls Repo-Variable
  `KAGGLE_FALLBACK_AUTODISABLE=true` – der Watchdog schaltet sich selbst ab
  (`--disable-after-takeover`). Reaktivieren:
  `gh workflow enable check-kaggle-fallback.yml`.

Status: `render_output/fallback_report.json`, `render_output/kaggle_state.json`.

## Wiederaufsetzen statt neu rendern

* Shots: `scene_builder` überspringt fertige Shots laut Manifest (kein `--force`).
* Kaggle-Ergebnis erneut holen:
  `python -m 1_system.kaggle_bridge.parallel_render download --kernel USER/SLUG --out-dir render_output`.
* Schnitt: `assemble_final` ist idempotent, `render_output/final_film.mp4` wird
  überschrieben.

## Kosten und Zeit (Erfahrungswerte)

| Qualität | Wo | Dauer | Credits |
|---|---|---|---|
| `preview` | GitHub 1 Job | 10–25 min | 0 (nur TTS) |
| `preview` | Kaggle T4×2 | 5–12 min | 0 |
| `high` | Kaggle T4×2 | 20–45 min | 0 |
| `max` | Kaggle T4×2 | 60–120 min | 0 |

TTS kostet ca. 1 Credit pro Zeichen; ein 2.000-Zeichen-Film also ~2.300 Credits
inklusive Puffer. Blender-Render kostet nichts außer Laufzeit.

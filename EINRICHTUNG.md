# Einrichtung, Secrets und Betrieb

## Stand

Das System ist vollständig implementiert: Stadt-Generator, R15-Figuren,
Animationen, Kamera, Licht, ElevenLabs-TTS mit Key-Rotation, prozedurale Musik
und SFX, Mastering auf −14 LUFS, Untertitel, Shot-Render über Blender (lokal,
GitHub-Runner oder Kaggle T4×2), Kaggle-Watchdog mit GitHub-Fallback, Schnitt und
automatisches Release.

Was der Stand **nicht** belegt: einen vollständigen Live-Lauf über GitHub Actions
und Kaggle. Getestet sind Unit-Tests (Parser, Timeline, Pipeline, Kaggle-Brücke,
Watchdog, Assets), der Blender-Rauchtest im CI sowie Schnitt und Ton mit
synthetischen Clips. Bis zum ersten echten Lauf gilt: nichts als „fertig“
behaupten, ohne Log und Release zu sehen.

---

## 1. Lokale Umgebung

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r 1_system/requirements.txt

python -m pytest -q
python -m compileall -q 1_system 2_aktueller_film tests
python -m 1_system.tools.validate_film --allow-unconfigured
```

`requirements.txt` enthält `requests`, `PyYAML`, `Pillow`, `imageio-ffmpeg`.
FFmpeg wird über `imageio-ffmpeg` mitgeliefert – ein System-FFmpeg ist nicht
nötig. **Blender** (`bpy`) wird nicht mitinstalliert, weil es nur für echte
Renders gebraucht wird:

```bash
pip install 'bpy==4.2.0'
sudo apt-get install libxrender1 libxi6 libxxf86vm1 libxfixes3 libgl1 libsm6
```

Ohne `bpy` funktionieren Validierung, Timeline-Planung (`--dry-run`), Credits,
Asset-Analyse und Schnitt. `render_local` bricht vor jedem Credit-Verbrauch ab,
wenn `bpy` fehlt.

Lokaler Komplettlauf (verbraucht Credits und Rechenzeit):

```bash
python -m 1_system.tools.render_local --quality preview --shots 1-4
python -m 1_system.tools.render_local --reuse-audio --quality high
```

---

## 2. Secrets (Repository → Settings → Secrets and variables → Actions)

### Pflicht für einen Render

| Secret | Zweck | Ohne dieses Secret |
|---|---|---|
| `ELEVENLABS_API_KEYS` | Komma-/zeilengetrennte Keys; benötigt mindestens `user_read` für die Guthabenprüfung sowie die Berechtigungen für Stimmen und Text-to-Speech | keine Sprachausgabe |
| oder `ELEVENLABS_API_KEY_1` … `_6` | einzelne Keys | wie oben |
| `KAGGLE_USERNAME` | Kaggle-Konto | Render läuft auf GitHub (nur `preview`) |
| `KAGGLE_KEY` | Kaggle-API-Token | wie oben |

### Optional

| Secret | Zweck |
|---|---|
| `GH_CALLBACK_TOKEN` | Fine-grained PAT nur für dieses Repo, Recht *Actions: Read and write* + *Contents: Read and write* (Release). Optional für den Workflow-Dispatch aus GitHub Actions; wird niemals an Kaggle übergeben. |
| `ROBLOX_API_KEY` | Open-Cloud-Key für Asset-Suche/-Download (`creator-store-product:read`, `legacy-asset:manage`, bei Bedarf `asset:read`) |
| `ROBLOX_USER_ID` | eigene User-ID, optional für Store-Suchen |

Keys niemals in `2_aktueller_film/`, Workflows, Kernel-Metadaten oder Artefakte
schreiben. Die Workflows reichen sie ausschließlich als Umgebungsvariablen an
Python-Prozesse weiter; Logs zeigen nur maskierte Keys (`mask_key`).

### Repository-Variablen (Settings → Variables)

| Variable | Wirkung |
|---|---|
| `KAGGLE_FALLBACK_ACTIVE` | von Hand gesetzt, wenn Kaggle bewusst nicht genutzt wird |
| `KAGGLE_FALLBACK_AUTODISABLE` | `true` = Watchdog schaltet sich nach einer Übernahme selbst ab |

---

## 3. ElevenLabs

1. Account anlegen, Profil → API Keys → Key erstellen.
2. Key(s) als Secrets eintragen. Mehrere Keys verschiedener Konten werden
   addiert; mehrere Keys desselben Kontos zählen einmal (das erkennt der
   Credit-Check an der Konto-ID).
3. Stimme auswählen, **Voice ID** kopieren und in
   `3_regeln/empfohlene_elevenlabs_stimmen.yaml` unter `haupt_erzaehler.voice_id`
   eintragen. Nebenstimmen unter `nebenstimmen:`.
4. Prüfen:

```bash
python -m 1_system.audio.generate_timeline --credits-only
```

Ausgabe pro Konto: maskierter Key, Restzeichen, Reset-Datum. Reicht das Guthaben
nicht (Bedarf = Zeichen × 1,15), bricht der Lauf **vor** jeder Synthese ab.

Hinweise: Library-Stimmen müssen dem Konto hinzugefügt sein, sonst `404`.
`429`/`quota_exceeded` führt automatisch zur Rotation auf den nächsten Key.
Ein Zeichen ≈ ein Credit.

---

## 4. Kaggle

1. Konto anlegen, Telefon verifizieren (Voraussetzung für Internet und GPU).
2. **Account → Create New API Token** → `kaggle.json`; daraus `username` →
   `KAGGLE_USERNAME`, `key` → `KAGGLE_KEY`.
3. Im Notebook-Test prüfen: Accelerator **GPU T4 ×2** verfügbar, Internet **on**,
   Wochenquote noch frei.
4. Workflow 1 veröffentlicht automatisch ein privates Dataset
   (`filmcreation-<run>-<id>`) und einen privaten Kernel
   (`<user>/filmcreation-<run>-<id>`) mit `machine_shape: NvidiaTeslaT4`,
   `enable_internet: true`, `is_private: true`. Der Kernel klont exakt den
   Commit des Laufs, rendert auf erkannte GPUs in separaten Worker-Verzeichnissen
   und mergt die Manifeste. GitHub wartet nicht auf Kaggle: der 15-Minuten-Wächter
   überwacht den Kernel und startet nach Abschluss Workflow 2; bei Fehlern wird
   ein GitHub-Fallback-Render ausgelöst. Referenzierte Roblox-Assets in
   `render_session/roblox_assets` werden offline ins private Session-Dataset gepackt.
5. Ergebnis bei Bedarf manuell holen:

```bash
python -m 1_system.kaggle_bridge.parallel_render download \
  --kernel USER/SLUG --out-dir render_output
```

Die Kaggle-CLI muss dafür im `PATH` sein (`pip install kaggle`); die Workflows
installieren sie selbst.

**Wichtig:** Der Kernel bekommt keine GitHub-Callback-Tokens oder sonstigen
GitHub-Secrets. Er klont das öffentliche Repo und kennt nur Konfigurationsdaten,
Kernel-Slugs und offline gestagte Assets. Der automatische Callback erfolgt
bewusst durch den GitHub-Wächter, nicht aus Kaggle heraus.

---

## 5. Roblox Open Cloud

1. Creator Hub → **Open Cloud → API Keys** → Key erstellen.
2. Scopes: `legacy-asset:manage` (Download), `asset:read` (Metadaten),
   `thumbnail:read` (Vorschau).
3. IP-Freigabe: `0.0.0.0/0` nur bewusst; für GitHub-Runner ist eine feste IP
   nicht möglich, für lokale Arbeit die eigene IP eintragen.
4. Test:

```bash
python -m 1_system.roblox_api.open_cloud --verify
python -m 1_system.roblox_api.asset_inspector --search "Roblox beanie" --tryon
```

Lizenzen: `check_license()` lehnt Marken-/Franchise-Artikel und Audio-Assets ab.
Ein API-Key ist **keine** Lizenz – fremde UGC nur nach Sichtprüfung und eigener
rechtlicher Bewertung einsetzen.

---

## 6. GitHub

* Actions müssen erlaubt sein (Settings → Actions → General).
* Workflows erscheinen im „Run workflow“-Menü erst, wenn die Datei auf dem
  Standardbranch liegt.
* Releases brauchen `contents: write` – die Workflows setzen das selbst.
* Workflow 1 → Workflow 2 läuft über `workflow_run` (bei Erfolg) und optional
  per Dispatch aus dem GitHub-Runner. Workflow 2 prüft, ob das Release schon existiert.
* Artefakte: `render-session` (Timeline, Audio, Untertitel),
  `render-shots` (Clips + Manifest), `kaggle-state`.
  Aufbewahrung: 14 Tage (GitHub-Standard).
* `--disable-after-takeover` schaltet den Watchdog nach einer Übernahme ab;
  reaktivieren mit `gh workflow enable check-kaggle-fallback.yml`.

### Lauf starten

```bash
gh workflow run 1-start-render.yml \
  -f shots=all -f quality=high -f render_target=auto \
  -f subtitles=true -f kaggle_timeout_minutes=180

gh run watch
gh release download film-<run_id>
```

Parameter: `shots` (z. B. `1-4`), `quality` (`preview|high|max`), `render_target`
(`auto|kaggle|github`), `subtitles` (`auto|true|false`), `skip_credit_check`,
`kaggle_timeout_minutes`.

---

## 7. Betriebswerkzeuge

| Aufgabe | Befehl |
|---|---|
| Credits | `python -m 1_system.audio.generate_timeline --credits-only` |
| Struktur prüfen | `python -m 1_system.tools.validate_film` |
| Shots auflisten | `python -m 1_system.blender_engine.scene_builder --list-shots` |
| Storyboard (nur Bilder) | `python -m 1_system.blender_engine.scene_builder --preview-storyboard --still --shots all` |
| Raster aus Shots | `python -m 1_system.tools.preview_storyboard --shots-dir render_output/shots` |
| Shots prüfen | `python -m 1_system.tools.check_shots --timeline render_session/timeline_resolved.json --manifest render_output/shots/render_manifest.json` |
| Tonspur | `python -m 1_system.tools.mix_audio` |
| Schnitt | `python -m 1_system.tools.assemble_final --subtitles auto` |
| Kaggle-Status | `python -m 1_system.kaggle_bridge.parallel_render check --kernel USER/SLUG` |
| Kaggle-Ergebnis holen | `python -m 1_system.kaggle_bridge.parallel_render download --kernel USER/SLUG --out-dir render_output` |
| Fallback prüfen | `python -m 1_system.kaggle_bridge.fallback_watchdog --dry-run` |
| Assets anproben | `python -m 1_system.roblox_api.asset_inspector --assets 123,456 --tryon` |
| Assets zu GLB | `python -m 1_system.roblox_api.prepare_assets --assets 123,456 --out assets/models` |

---

## 8. Fehlerbehebung

| Symptom | Ursache / Lösung |
|---|---|
| `bpy fehlt` | `pip install bpy==4.2.0` + X11-Bibliotheken, oder Blender-Render über GitHub/Kaggle |
| `Format muss 1080x1920 @ 24 fps sein` | `film_config.yaml` verändert – zurückstellen |
| `'subtitles' muss ausdrücklich true oder false sein` | Boolean fehlt oder ist String |
| `keine voice_id` | Stimme in `3_regeln/empfohlene_elevenlabs_stimmen.yaml` eintragen |
| `401` bei ElevenLabs | Key ungültig oder gelöscht |
| `403` bei Roblox | fehlender Scope oder IP nicht freigegeben (Hint in der Meldung) |
| `429` | Rotation greift automatisch; sonst Key-Limit prüfen |
| `Shots fehlen` / `frames_covered < frames_total` | Shots erneut rendern (Manifest überspringt fertige), `--force` nur bei Verdacht auf defekte Dateien |
| Kaggle hängt in `queued` | Watchdog nach 45 min, GitHub übernimmt |
| `Keine GPU gefunden` | Renderer fällt auf CPU zurück; Dauer steigt deutlich |
| Release existiert nicht | `gh run view <id> --log` prüfen; Workflow 2 manuell starten |
| `Workflow nicht gefunden` | Workflow-Datei liegt noch nicht auf dem Standardbranch |

---

## 9. Kosten und Zeit

| Posten | Größe | Aufwand |
|---|---|---|
| TTS | ~2.000 Zeichen | ~2.300 Credits |
| Render `preview` | GitHub 1 Job | 10–25 min |
| Render `preview` | Kaggle T4×2 | 5–12 min |
| Render `high` | Kaggle T4×2 | 20–45 min |
| Render `max` | Kaggle T4×2 | 60–120 min |
| Schnitt | FFmpeg lokal | < 1 min |

Blender-Render kostet kein Geld, nur Laufzeit. Der teuerste Fehler ist ein
verspätet erkannter Textfehler, deshalb: Validierung und Storyboard **vor** dem
Render.

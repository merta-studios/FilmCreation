# Einrichtung und aktueller Stand

## Wichtig: noch kein fertiges Renderstudio

Dieser Stand ist weiterhin **nicht produktionsreif**. Neu sind ein einfacher
Blender-Demo-Szenenbau, Spracherzeugung mit Timeline und ein FFmpeg-Schnitt mit
optionalen Untertiteln. Die Figuren sind einfache 15-teilige Blockfiguren, kein
Roblox-kompatibles R15-Skelett. Der Renderer bildet ausschließlich die vier
fest codierten Demo-Shots ab und ignoriert viele Vorgaben in den Filmdateien.
Ein vollständiger Durchlauf mit ElevenLabs, Blender und Kaggle wurde nicht live
verifiziert. FFmpeg-Schnitt und Untertitel wurden mit synthetischen Clips getestet.

Roblox-Assets/Emotes, Anprobe, universeller Szenenbau, echte Animationen,
Kaggle-Bundle/Worker/Callback, Output-Abholung, Musik und SFX im Mastering fehlen
weiterhin. Start-, Finish- und Inspect-Modi melden dies als Fehler; der Fallback
hat keinen Zeitplan. Der Storyboard-Modus rendert nur Bilder der festen Demo.

### Experimenteller lokaler Demo-Render

Voraussetzungen: Python 3.11, Blender-Python-Wheel `bpy==4.2.0` mit benötigten
Linux-OpenGL/X11-Laufzeitbibliotheken, FFmpeg mit libx264 und libass, Pillow,
ElevenLabs-Key und eine gültige Voice-ID. In Ubuntu beispielsweise:

```bash
sudo apt-get install libxrender1 libxi6 libxxf86vm1 libxfixes3 libgl1 libsm6 libxkbcommon0 ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -r 1_system/requirements.txt 'bpy==4.2.0' Pillow
# ELEVENLABS_API_KEYS in der Umgebung setzen; niemals in Git speichern.
# In 3_regeln/empfohlene_elevenlabs_stimmen.yaml eine gültige voice_id eintragen.
python -m 1_system.tools.render_demo_local --preview
```

Ausgabe: `render_output/final_film.mp4` und `storyboard.png`. Der Vorgang kann
Credits verbrauchen und ist nicht als vollständig erprobter Produktionsweg zu
verstehen. `--preview` rendert 540×960 und skaliert im Mastering auf 1080×1920;
ohne diesen Schalter werden die Shots in 1080×1920 berechnet. Der lokale Weg
unterstützt nur die Demo, keine beliebigen Filme. Die Ausgabe ist bei fehlender
Roblox-Anbindung nicht authentisch und erzielt nicht die gewünschte Endqualität.

## 1. Lokaler Test der vorhandenen Grundfunktionen

Python 3.10+ und Internetzugriff auf PyPI nötig:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install 'requests>=2.31,<3' 'PyYAML>=6,<7' pytest
python -m compileall -q 1_system 2_aktueller_film
python -m pytest -q
python -m 1_system.tools.validate_film --strict
```

Die Prüfung betrifft nur das deklarative Beispiel. Sie prüft **nicht**, ob
Figuren auf dem Boden stehen, ob ein Shot gut aussieht oder gerendert werden
kann. SFX-Bausteine sind noch nicht in das Mastering integriert; ASS-Untertitel werden optional eingebrannt.

## 2. GitHub und erster Credit-Test

Repository auf GitHub öffnen → **Settings → Secrets and variables → Actions →
New repository secret**. Secrets dort speichern, niemals im Git einchecken oder
in Logs kopieren. Repository-Rechte und Workflow-Ausführung unter **Settings →
Actions → General** gemäß den eigenen Organisationsrichtlinien aktivieren.
Nach Aufnahme des Workflows in den Standardbranch: **Actions → Agent Helper →
Run workflow → check-credits**, geschätzte Zeichen inklusive 15 % Puffer
angeben. Zusammenfassung und Status prüfen. GitHub zeigt `workflow_dispatch`
gewöhnlich erst an, wenn die Workflow-Datei im Standardbranch existiert; beim
manuellen Start muss die gewünschte Branch-Version gewählt werden.

Die Prüfung stoppt, wenn ein Key ungültig oder das **höchste Einzelguthaben**
zu klein ist. Guthaben mehrerer Keys werden nicht addiert, weil verschiedene Keys
zum selben Konto gehören können. Account-übergreifende Verteilung und
Live-Verifikation gleicher Stimmen sind nicht umgesetzt. Reset kann fehlen, wenn
die API kein Datum liefert. `synthesize_segment` ist ein Einzelbaustein, kein
kompletter Workflow.

### Geplante Secret-Namen

| Secret | Zweck | Aktueller Stand |
|---|---|---|
| `ELEVENLABS_API_KEYS` | Kommaseparierte oder zeilengetrennte Keys | Credit-Test und TTS-Baustein |
| `ELEVENLABS_API_KEY_1` … `ELEVENLABS_API_KEY_10` | Einzelne Keys | Credit-Test und TTS-Baustein |
| `ROBLOX_API_KEY` | Open-Cloud-Zugriff | noch nicht angebunden |
| `ROBLOX_USER_ID` | optionale Roblox-Nutzer-ID | noch nicht angebunden |
| `KAGGLE_USERNAME` | Kaggle-Benutzername | noch nicht angebunden |
| `KAGGLE_KEY` | Kaggle API Key | noch nicht angebunden |
| `KAGGLE_API_TOKEN` | alternatives Kaggle-Token | noch nicht angebunden |
| `KAGGLE_KERNEL_SLUG` | Kernel-Name | noch nicht angebunden |
| `GH_CALLBACK_TOKEN` | späterer GitHub-Callback | noch nicht angebunden |

## 3. ElevenLabs vorbereiten

Bei ElevenLabs anmelden, im Profil-/Developer-Bereich einen API-Key erstellen
und als Secret eintragen. Für mehrere Keys `ELEVENLABS_API_KEYS` verwenden oder
nummerierte Secrets anlegen. Abrechnung, Guthaben und Nutzungsbedingungen pro
Account beachten; mehrere Accounts sind kein Ersatz für Nutzungsrechte oder
Tarifbedingungen. Stimme auswählen und Voice-ID im ElevenLabs-Interface oder per
API ermitteln. In `3_regeln/empfohlene_elevenlabs_stimmen.yaml` eintragen. Eine
Stimme muss auf jedem verwendeten Account verfügbar und lizenziert sein; dieselbe
Voice-ID oder Kompatibilität darf nicht einfach angenommen werden.

## 4. Kaggle vorbereiten – noch nicht nutzbar

Kaggle-Konto anlegen; unter Kontoeinstellungen API-Zugang einrichten und
GPU-/Internetfreischaltung gemäß den aktuellen Kaggle-Vorgaben durchführen
(unter Umständen inklusive Telefonverifizierung). Quoten und verfügbare
Beschleuniger im Notebook-/Kontingentbereich des Kontos prüfen: die Verfügbarkeit
von zwei T4, Internet und einer bestimmten Wochenstundenzahl ist nicht garantiert.
Die Kaggle-Integration und das sichere Session-Handling sind noch zu entwickeln.
API-Schlüssel nicht in ein öffentliches Notebook, Kernel-Metadaten, Artifact oder
Git einbetten. Insbesondere ist die sichere Übermittlung des Callback-Tokens an
Kaggle noch ungelöst.

## 5. Roblox vorbereiten – noch nicht nutzbar

Im Roblox Creator Hub den Bereich **Credentials / API Keys** suchen; UI und
angebotene Scopes können sich ändern. Für den eigenen Account nur erforderliche
Rechte vergeben und für jedes Asset Lizenz- und Nutzungsrechte prüfen.
Die in der Aufgabenstellung genannten Scopes `legacy-asset:manage` und
`thumbnail:read` sowie Creator-Store-Zugriff müssen gegen aktuelle Roblox-Doku
und Account-Freigaben geprüft werden; es ist nicht verifiziert, ob diese Scopes
für alle gewünschten APIs verfügbar oder ausreichend sind. `0.0.0.0/0` öffnet
Zugriff aus allen IPv4-Netzen und sollte nur bewusst verwendet werden. Ein Key
erlaubt nicht automatisch das Herunterladen oder kommerzielle Nutzen fremder
Assets. Die API-Anbindung ist hier noch nicht implementiert.

## 6. GitHub-Callback – noch nicht nutzbar

Unter GitHub **Settings → Developer settings → Personal access tokens →
Fine-grained tokens** ggf. einen Token nur für dieses Repository mit minimalem
Actions-Recht (Read and write) anlegen und als `GH_CALLBACK_TOKEN` speichern.
Branch-/Organisationsregeln können zusätzliche Freigaben verlangen. Token nie in
Kaggle-Bundles oder Artifacts packen; eine sichere Übergabe und idempotenter
Callback mit eindeutigem Session-/Run-Bezug müssen zuerst entwickelt werden.

## 7. Eigene Empfehlungen und zukünftige Nutzung

Dateien in `3_regeln/` enthalten konfigurierbare Voice-Einstellungen, vom Nutzer
vorgeschlagene (nicht live geprüfte) Roblox-IDs und Lieblingsmaterialien. Zusätzliche
Notizen unter `3_regeln/eigene_notizen/` ablegen. Agenten lesen sie vor jedem
Film. Wenn die Pipeline vervollständigt ist, Filmidee und Untertitelwunsch nennen;
der Agent muss zunächst Credits prüfen und einen vollständigen Pitch ausdrücklich
freigeben lassen. Ohne vollständige Implementierung ist ein erster Render nicht
möglich.

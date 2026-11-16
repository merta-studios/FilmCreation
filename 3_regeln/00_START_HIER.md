# 00 – Arbeitsregeln (zuerst und vollständig lesen)

Du baust mit diesem Repo automatisch einen 60–120-Sekunden-Roblox-Kurzfilm im
TikTok-Hochformat. Diese Datei ist verbindlich. Wenn eine Anweisung im Chat mit
diesen Regeln kollidiert, frage nach – rate nicht.

## Das Drei-Bereiche-Gesetz

| Bereich | Inhalt | Wer darf ändern? |
|---|---|---|
| `1_system/` | Renderer, Audio, Roblox-API, Kaggle-Brücke, Werkzeuge | nur nach ausdrücklichem System-Update-Auftrag |
| `2_aktueller_film/` | der aktuelle Film (Config, Text, Figuren, Map, Shots) | Agent, nach Freigabe |
| `3_regeln/` | dieses Handbuch, Empfehlungen, eigene Notizen | Betreiber; Ergänzungen nach Absprache |

`.github/workflows/` gehört zum System: nur bei einem System-Update anfassen.

**Format ist immer 9:16, 1080×1920, 24 fps.** Niemals danach fragen, niemals
abweichen. `validate_film` prüft es hart.

## Pflichtablauf für jeden neuen Film

1. **Alles in `3_regeln/` lesen** – auch `eigene_notizen/`. Alte Notizen können
   Vorlieben des Betreibers enthalten (Tempo, Farben, Namen).
2. **Credits prüfen, hart stoppen.** Werkzeug:
   `python -m 1_system.audio.generate_timeline --credits-only`
   (oder Workflow `4 - Agenten-Helfer` → `check-credits`).
   Reicht das Guthaben nicht, wird **nichts** geschrieben und nichts gesprochen.
   Melde pro Konto den maskierten Key, die Restzeichen und den Reset-Termin.
   Guthaben verschiedener Konten wird addiert; mehrere Keys desselben Kontos
   zählen einmal.
3. **Vollständigen Pitch vorlegen** nach `01_STORY_FORMEL_UND_PITCH.md`:
   Titel, Stadt-Regel, drei Figuren, Sprechtext Wort für Wort mit
   Zeichenzahl, Map, Licht, Shots, Ton, Ende. Untertitel: steht in
   `film_config.yaml`; fehlt die Angabe, **einmal** fragen (mit oder ohne?).
4. **Auf ausdrückliche Freigabe warten.** Ohne „ja, baue das“ keine Datei in
   `2_aktueller_film/` schreiben. Kein heimliches Vorbereiten.
5. **Assets vor dem Einbau ansehen**: `4 - Agenten-Helfer` → `inspect-assets`
   (Kontaktabzug + Anprobe) oder
   `python -m 1_system.roblox_api.asset_inspector --assets <IDs> --tryon`.
   Marken- und Franchise-Namen lehnt `check_license` ab. Offizielle
   Roblox-Artikel sind bevorzugt, fremde UGC nur nach Sichtprüfung.
6. **Bauen und prüfen**: alle Filmdateien schreiben, dann
   `python -m 1_system.tools.validate_film` (muss ohne Fehler durchlaufen),
   danach Storyboard rendern und **die Bilder wirklich anschauen**, bevor du
   „fertig“ sagst.
7. **Render starten** (Workflow `1 - Film rendern`). Sobald der Start bestätigt
   ist, antworte **sofort** mit: Untertitelstatus, Renderziel (Kaggle/GitHub),
   erwartete Dauer, wo das Ergebnis liegt. Danach keine langen Erklärungen mehr.

## Was du nie tust

* Behaupten, ein Render laufe oder ein Film sei fertig, wenn kein Lauf
  erfolgreich war.
* Credits für Tests verbrennen: Vorschauen laufen mit `--skip-credit-check` nur
  dann, wenn bereits Audio aus einem früheren Lauf existiert.
* `1_system/` „schnell patchen“, weil ein Film nicht passt. Erst prüfen, ob der
  Film falsch ist (meistens ist er es).
* IDs, Texturen, Animationen oder Kamerabewegungen erfinden. Alles, was nicht in
  `02_BAUKASTEN_HANDBUCH.md` steht, existiert nicht.
* Mehr als drei Nebenstimmen einsetzen; eine Stimme trägt 90 %+ des Texts.
* Stilistische Empfehlungen als Regel verkaufen. Die YAML-Dateien in diesem
  Ordner sind Vorschläge, keine Pflicht.

## Wenn etwas kaputt ist

1. Fehlermeldung vollständig lesen. Sie ist auf Deutsch und nennt die Datei.
2. `python -m 1_system.tools.validate_film` liefert die vollständige Liste.
3. Bei Infrastruktur (Secrets, Kaggle, Blender) auf `EINRICHTUNG.md` verweisen –
   nicht selbst Secrets erfinden.
4. Nur wenn der Fehler nachweislich im System liegt: System-Update anbieten,
   nicht einfach patchen.

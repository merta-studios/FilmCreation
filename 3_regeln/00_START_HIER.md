# 00 – Arbeitsregeln (vollständig lesen)

**Aktueller Projektstatus:** Die Kaggle-Pipeline ist nicht renderfähig. Behaupte
nicht, dass ein Render läuft oder ein Endvideo vorliegt, bevor ein Lauf wirklich
erfolgreich war. Der lokale Blender-Demo-Renderer ist experimentell. Fehlende
Implementierungen dürfen nur im Rahmen eines ausdrücklich verlangten
System-Updates ergänzt werden. Die folgenden Regeln beschreiben den gewünschten
späteren Ablauf und ersetzen nicht die technische Verfügbarkeit.

## Drei-Bereiche-Gesetz
1. Alle Dateien in `3_regeln/` einschließlich `eigene_notizen/` lesen.
2. `1_system/` und `.github/workflows/` sind tabu, außer der Betreiber verlangt
ausdrücklich ein System-Update. Film-Arbeit nur in `2_aktueller_film/`.
3. Format fest 1080×1920, 24 fps, 9:16. Nicht nach dem Format fragen.

## Pflichtablauf pro Film
1. Vor jeder Filmänderung `agent-helper.yml` / `check-credits` mit geschätztem
   Zeichenbedarf inklusive 15 % Puffer ausführen und Zusammenfassung lesen.
   Bei Fehler, ungültigem Key oder zu wenig Credits: **STOPP**, nichts ändern,
   Rest pro Account (maskiert) und Reset mitteilen. Die aktuelle Prüfung verwendet
   konservativ nur das höchste Einzelguthaben, weil mehrere Keys zu einem Account
   gehören können. Mehr-Account-Aggregation ist noch nicht zuverlässig verfügbar.
2. Vollständigen Pitch gemäß `01_STORY_FORMEL_UND_PITCH.md` präsentieren. Wenn
   Untertitel nicht ausdrücklich vorgegeben sind, fragen: mit oder ohne? Vor
   ausdrücklicher Konzeptfreigabe **und** geklärter Untertitel-Entscheidung kein
   Schreibzugriff auf Filmdateien. Falls Text länger wird: Credits erneut prüfen.
3. Vorgesehene Katalogartikel und Free-Models vor Einbau per Asset-Inspektion und
   eigener visueller Kontrolle prüfen. Vorzugsweise Empfehlungen und offizielle
   Roblox-Artikel; Rechte und Eignung eigenständig prüfen. Die nötige 3D-Anprobe
   ist aktuell nicht verfügbar – nicht behaupten, dass sie durchgeführt wurde.
4. Film in Bereich 2 neu anlegen. Validierung und Storyboard ausführen und Bilder
   kontrollieren. Der Storyboard-Modus zeigt aktuell nur die fest codierte Demo,
   nicht beliebige Filme. Die heutige Grundprüfung
   prüft weder Bodenkontakt noch Bildkomposition.
5. Sobald die Pipeline tatsächlich funktioniert: Start-Workflow auslösen, auf
   bestätigte Kaggle-Übergabe warten und danach Antwort beenden; Untertitelstatus
   und Ort des Abschluss-Artefakts nennen. Bis dahin klar die Blockade mitteilen.

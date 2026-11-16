# 01 – Story-Formel und Pflicht-Pitch

## Die Formel (bewährt, nicht verhandelbar im Kern)

* **Hook in Sekunde 1**, ohne Intro: „In dieser Stadt …“ – eine Regel, die für
  alle gilt und eine Figur benachteiligt.
* **Stadt-Erklärung** (ruhige Erzählerstimme, 2–3 Alltagsbeobachtungen): Was
  passiert jeden Tag? Wer schaut weg? Was ist normal geworden?
* **Ich-Perspektive**: dieselbe Stimme wechselt in die Sicht der Hauptfigur.
  „Ich habe aufgehört zu zählen, als …“
* **Höhepunkt**: Die Regel trifft die Figur persönlich, härter als erwartet.
* **Warmes Ende**: keine Rache, keine Strafe – eine kleine, konkrete menschliche
  Geste. Der letzte Satz bleibt hoffnungsvoll und kurz.
* **Figuren**: genau 1 Hauptfigur, mindestens 2 Nebenfiguren (Familie, Schule,
  Nachbarschaft), optional Statisten. Beziehungen klar benennen.
* **Länge**: 60–120 s, 140–290 deutsche Wörter, 1.800–2.200 Zeichen.
* **Stimmen**: eine Erzählerstimme trägt 90–100 %. Maximal 3 kurze Nebenstimmen
  mit je 1–2 Sätzen.

## Ideen, die funktionieren (nicht kopieren, weiterdenken)

* Stadt-Regeln mit Zähler über dem Kopf (Schritte, Wörter, Umarmungen).
* Eine Uhr, die nur für die Hauptfigur falsch geht.
* Ein Pfandhaus für Erinnerungen.
* Lügen lassen Blumen wachsen – oder Steine.
* Wer stehen bleibt, wird unsichtbar.

Erfinde lieber eine eigene, konkrete Regel mit sichtbarer Folge im Bild. Eine
Regel, die man in einem Standbild versteht, ist besser als eine kluge, die man
erklären muss.

## Der Pitch – jeder Punkt ist Pflicht

1. **Titel** und **Stadt-Regel** in einem Satz. Untertitel: an/aus (aus
   `film_config.yaml`; wenn dort nichts steht, einmal fragen).
2. **Figuren** (3+): ID, Rolle, Beziehung, Alter-Wirkung, Hautfarbe, Shirt, Hose,
   Gesicht, `height_scale`, geplante Accessoires/Emotes.
3. **Sprechtext Wort für Wort**, markiert mit
   `[ERZÄHLER – Stadt-Erklärung]`, `[ERZÄHLER – Ich-Perspektive]` und optional
   `[NEBENSTIMME: Rolle]`, dazu **Zeichenzahl gesamt** und Credit-Abgleich
   (Restguthaben minus Bedarf × 1,15).
4. **Map**: Ort, Jahreszeit, Wetter, 5–10 konkrete Objekte mit Textur und Farbe,
   mindestens 2 Schilder mit Text, eigene Modelle aus `custom_models.py`.
5. **Shots**: pro Segment mindestens ein Shot mit Kamera-Bewegung, Brennweite,
   `fill`, Lichtstimmung, Figuren samt Animation und Gesicht, SFX und
   Wort-Trigger. Vordergrund/Mittelgrund/Hintergrund benennen.
6. **Höhepunkt und warmes Ende** in je einem Satz – und welches Bild sie zeigt.
7. **Ton**: Musikstimmung, drei wichtigste SFX, Stille-Moment.
8. **Risiken**: Was könnte im 9:16-Bild nicht funktionieren (zu breite Map, zu
   viele Figuren, Text zu lang)? Sag es im Pitch, nicht erst nach dem Render.

## Harter Bestätigungsstopp

Ohne ausdrückliches „ja“ (oder eine eindeutige Formulierung wie „bau das“) wird
**keine Datei** in `2_aktueller_film/` angelegt oder geändert. Bei Änderungswünschen
danach: Pitch-Delta zeigen (was ändert sich, welche Zeichenzahl, welche Kosten),
dann erst schreiben.

## Beispiel-Pitch (gekürzt, aus dem Demo-Film)

> **Titel:** „In dieser Stadt hat jeder nur 10.000 Schritte“
> **Regel:** Jeder Mensch bekommt 10.000 Schritte pro Tag. Wer mehr geht, verliert
> die Erinnerung an den Weg.
> **Figuren:** Mika (Hauptfigur, 12, Tochter), Mutter (Nebenfigur), Herr Kaya
> (Nachbar, Rollstuhl), Frau Reim (Lehrerin, Statistenrolle).
> **Text:** 13 Segmente, 1.412 Zeichen, Bedarf 1.624 Credits, vorhanden 22.000.
> **Map:** Altstadt bei Regen, Kopfsteinpflaster, Laternen, Litfaßsäule mit
> Stadtuhr, Briefkasten, Rollstuhlrampe.
> **Shots:** 14, alle mit Bewegung (crane_reveal, dolly_right, slow_push_in,
> over_shoulder, rack_focus, orbit_arc, tilt_up_reveal, pull_out).
> **Ende:** Die Mutter geht die letzten Schritte für Mika – und Mika führt sie
> nach Hause. Letztes Bild: zwei Hände, warmes Licht.

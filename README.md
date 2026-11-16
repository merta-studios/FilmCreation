# FilmCreation – Grundlage für ein Roblox-Kurzfilmstudio

**Status: nicht produktionsreif.** Es gibt jetzt einen experimentellen lokalen
Blender-Demo-Renderer und FFmpeg-Schnitt; die komplette, automatisierte
Kaggle-/Roblox-Pipeline und der universelle Filmbaukasten fehlen weiterhin.
Renderstart und Asset-Anprobe melden dies ausdrücklich als Fehler.

- `1_system/`: vorhandene experimentelle Grundbausteine (Credits, Timeline,
  SFX/ASS, einfacher Blender-Demo-Renderer, FFmpeg-Schnitt, eingeschränkter
  RBXMX-Parser und deklarative Filmvalidierung).
- `2_aktueller_film/`: Demo-Konzept in festem Hochformat.
- `3_regeln/`: Arbeitsregeln und persönliche Empfehlungen.
- `EINRICHTUNG.md`: Tests, Secrets und die noch offenen Integrationen.

KI-Agenten lesen zuerst `AGENTS.md` und danach **alle** Dateien in `3_regeln/`.
Die Prüfungen sind nur Teilprüfungen und kein Nachweis für Bildqualität, Lizenzen
oder Renderfähigkeit. Externe APIs wurden hier nicht live getestet.

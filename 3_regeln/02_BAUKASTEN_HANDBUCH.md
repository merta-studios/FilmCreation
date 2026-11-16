# 02 – Tatsächlich vorhandene Bausteine

Nur die hier aufgelisteten Grundfunktionen existieren; sie garantieren keinen
vollständigen Film. Python-Paketname beginnt mit einer Zahl: Import über
`importlib.import_module('1_system.audio.timeline_sync')` oder Aufruf mit
`python -m 1_system.tools.validate_film --strict`.

- `audio.elevenlabs_pool`: `ElevenLabsPool.check_credits(estimated_chars)`;
  `synthesize_segment(text, voice_id, output_path, previous_text, next_text)`.
  Eine Gesamtzahl über Accounts ist mangels Account-Deduplizierung konservativ
  auf das höchste Einzelguthaben beschränkt. API und Stimmen nicht live geprüft.
- `audio.timeline_sync`: `build_timeline(segment_results, fps=24, pause_after={})`,
  `find_word_frame`, `find_word_by_text`. Nutzt Zeichen-Alignment; Segmentlängen
  müssen vom Aufrufer korrekt bestimmt werden.
- `audio.sound_design`: `build_tiktok_subtitles`, `generate_procedural_sfx`,
  `duck_music_under_voice`, `normalize_lufs`, `burn_subtitles`; FFmpeg erforderlich.
  Ein automatischer Mix oder Subtitle-Schalter im Mastering existiert noch nicht.
- `tools.validate_film`: deklaratives Schema aus der Demo, prüft Format,
  Untertitel, drei Figuren, Shot-Kameras und Text-Cues. Kein 3D-Check.
- `roblox_api.rbxm_parser`: eingeschränkter XML/RBXMX-Parser mit lokalen
  Attachment-CFrames; Binärformate, Meshes und Blender-Import fehlen.

Blender-3D-Engine, Kartenbau, korrekte R15-Verformung, Roblox-Emotes,
Asset-Inspektion, Kaggle-Anbindung, Asset-Lizenzen, Shot-Timing, Mastering und
visuelle Vorschauen sind **nicht einsatzbereit**. Keine Funktionen dafür erfinden.

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
  Das experimentelle Mastering unterstützt das Einbrennen per Boolean; Musik/SFX
  werden darin noch nicht automatisch gemischt.
- `tools.validate_film`: deklaratives Schema aus der Demo, prüft Format,
  Untertitel, drei Figuren, Shot-Kameras und Text-Cues. Kein 3D-Check.
- `roblox_api.rbxm_parser`: eingeschränkter XML/RBXMX-Parser mit lokalen
  Attachment-CFrames; Binärformate, Meshes und Blender-Import fehlen.

- `blender_engine.scene_builder`: vier fest codierte Demo-Bilder/-Shots, keine
  allgemeine Karten-API und keine echten R15-Rigs. `agent-helper.yml` bietet
  `preview-storyboard` dafür an; das ersetzt keine Storyboard-Prüfung neuer Filme.
- `audio.generate_timeline`: ElevenLabs-Segmente und Timeline generieren.
- `tools.assemble_final`: Videos/Audio passend zu Timeline-Frames schneiden,
  optionale Untertitel und Storyboard erzeugen; kein Musik-/SFX-Mix.
- `tools.render_demo_local`: experimenteller lokaler End-to-End-Demo-Aufruf.

Roblox-Emotes, Asset-Inspektion, Kaggle-Anbindung, Asset-Lizenzen und universeller
Szenenbau sind nicht einsatzbereit. Keine Funktionen dafür erfinden.

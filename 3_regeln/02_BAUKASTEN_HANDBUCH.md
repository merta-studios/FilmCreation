# 02 – Baukasten-Handbuch (was es wirklich gibt)

Alles hier ist implementiert und getestet. Was nicht hier steht, existiert nicht –
bitte nicht erfinden.

## Aufruf-Konventionen

* Paketnamen beginnen mit einer Ziffer. Deshalb:
  * Aufruf: `python -m 1_system.tools.validate_film …`
  * Import: `importlib.import_module("1_system.audio.timeline_sync")`
* Alle Module legen das Repo-Wurzelverzeichnis selbst in `sys.path`; Aufrufe aus
  dem Repo-Ordner funktionieren immer.
* Blender-Code (`1_system/blender_engine/*`) braucht `bpy` (Blender 4.2). Ohne
  Blender lassen sich Daten und Prüfungen trotzdem nutzen – genau dafür sind die
  Tabellen und reinen Funktionen getrennt.

---

## 1. Audio (`1_system/audio/`)

### `timeline_sync`
* `build_timeline(segment_results, fps=24, pause_after=None, width=1080,
  height=1920, film_title="")` → Timeline-Dict mit `segments`, `word_cues`,
  `total_frames`, `total_seconds`.
  `segment_results`: `{segment_id, role, text, alignment, duration, audio_path,
  voice_id, pause_after}`. `alignment` kommt 1:1 aus ElevenLabs
  (`characters`, `character_start_times_seconds`, `character_end_times_seconds`).
* `resolve_shots(timeline, shots_spec, min_frames=…)` → Shots mit
  `start_frame`/`end_frame`/`frames`, lückenlos; Pausen zwischen Segmenten
  verlängern den vorherigen Shot (`holds_through_pause`).
* `attach_shots(timeline, shots)` hängt die Shots an die Timeline.
* `find_word_frame(timeline, segment_id, word, occurrence=0)` → Startframe.
* `validate_timeline(timeline)` → Liste von Fehlern (leer = gut).
* `timeline_stats(timeline)` → Zahlen für Berichte.
* `write_timeline` / `load_timeline` (JSON).

### `elevenlabs_pool`
* `collect_api_keys()` liest `ELEVENLABS_API_KEYS` (Komma/Zeilen) und
  `ELEVENLABS_API_KEY_1..10`; dedupliziert.
* `ElevenLabsPool(keys=None, model_id=…, output_format="mp3_44100_128",
  voice_settings=…)`
  * `check_credits(estimated_chars, required_voice_id=None)` → `CreditReport`
    mit `total_remaining`, `account_remaining`, `ok`, `summary()`.
  * `synthesize_segment(text, voice_id, output_path, previous_text="",
    next_text="", voice_settings=None)` → `SynthesisResult(audio_bytes,
    alignment, duration_seconds, key_used, account, characters)`.
    Rotiert bei `quota_exceeded`/`429` automatisch über alle Keys.
  * `list_voices()`, `has_voice(entry, voice_id)`, `remaining_snapshot()`.
* `mask_key()` für Logs; Secrets erscheinen nie im Klartext.

### `sound_design`
* `SFX_KINDS` (20): `rain, wind, steps, clock_tick, heartbeat, city_ambience,
  door_creak, school_bell, paper, wheelchair, thunder, birds, traffic,
  breathing, pen_scratch, chalk, crowd_distant, church_bell, window_rain,
  bus_stop`
* `MUSIC_MOODS` (7): `melancholisch, traurig, hoffnungsvoll, angespannt, regen,
  warm, episch_leise` (`angspannt` ist ein Tippfehler-Alias, nicht verwenden)
* `generate_procedural_sfx(kind, duration_seconds, output_path)` – alles
  prozedural, keine fremden Samples.
* `generate_music(mood, duration_seconds, output_path)` – Klavier/Pad/Arpeggio,
  lizenzfrei erzeugt.
* `SubtitleStyle(font, font_size, primary, highlight, outline, outline_width,
  shadow, margin_v, bold, alignment)` – Farben in ASS-Notation (BGR).
* `build_tiktok_subtitles(timeline, path, style=None, width=1080, height=1920)`
  – wortgenau, 3-Wort-Blöcke, Karaoke-Hervorhebung.
* `build_sfx_events(timeline, shots_spec, config)` – SFX aus Shots + Wort-Triggern.
* `mix_master_audio(timeline, path, work_dir, music_mood=None, music_gain_db=-20,
  music_path=None, sfx_events=None, loudness_target=-14, keep_stems=False)`
  – Sidechain-Ducking, Loudnorm auf −14 LUFS, True Peak −1.5 dB.
* `probe_duration(path)`, `ffmpeg_binary()`, `ffprobe_binary()`.

### `generate_timeline` (Schritt 1)
```
python -m 1_system.audio.generate_timeline --out-dir render_session
python -m 1_system.audio.generate_timeline --credits-only      # nur Guthaben
python -m 1_system.audio.generate_timeline --dry-run --json-out z.json
```
`generate(film_dir, out_dir, pool=None, skip_credit_check=False, dry_run=False)`
prüft Pflichtfelder, Guthaben (harter Stopp), spricht alle Segmente, baut die
Timeline und schreibt `timeline_resolved.json`, `speech_report.json`,
`film_info.md`. Dauer außerhalb 60–120 s wird gewarnt.

---

## 2. Blender-Engine (`1_system/blender_engine/`)

### `rig_r15` – Figuren
* `build_r15(name, skin_color, shirt_color, pants_color, face, height_scale,
  collection, location, rotation_z_deg, shirt_style)` → Charakter-Dict
  (`armature`, `root`, `parts`, `bones`, `attachments`, `face`, `eyes`, `mouth`).
* `FACE_NAMES`: `neutral, sad, crying, hopeful, happy, surprised, angry, shy,
  tired, talking`
* `SKIN_COLORS` (aus `roblox_textures`): `fair, light, warm, olive, brown, deep`
* `ATTACHMENTS`: `HatAttachment, HairAttachment, FaceFrontAttachment,
  FaceCenterAttachment, NeckAttachment, FrontAttachment, BackAttachment,
  LeftCollarAttachment, RightCollarAttachment, WaistCenterAttachment,
  LeftGripAttachment, RightGripAttachment`
* `attach_to_slot(character, slot, obj, scale=1.0, offset=(0,0,0))`,
  `place_character(character, x, y, z=0, rotation_z_deg=…)`,
  `bone_rotation(character, bone, degrees, frame=None)`, `set_face`,
  `blink`, `set_talking`, `set_body_colors`, `set_stone`.
* Einheiten: Studs. Avatar ≈ 6,7 hoch, Figur schaut nach −Y, Füße bei z = 0.

### `custom_animations` – Clips
* `library()` → `AnimationLibrary` mit 30 eingebauten Clips:
  `comfort_shoulder, cover_eyes, cry_cover_face, fall_to_knees,
  freeze_as_statue, hand_over_object, head_shake, hold_hands, hug_a, hug_b,
  idle_breath, kneel_pray, lie_in_bed, look_up_wonder, nod, open_door_slowly,
  point_and_laugh, push_wheelchair, receive_object, run_scared, sit_desk_write,
  sit_ground, sit_wheelchair, stand_shy, step_back_scared, turn_away,
  walk_hurry, walk_sad, wave_goodbye_sad, wipe_tears`
* Eigene Clips in `2_aktueller_film/custom_animations.py`:
  ```python
  def register(lib):
      clip = lib.new("mein_clip", duration=36, loop=False, description="…")
      lib.key("RightUpperArm", {0: (0, 0, 0), 12: (30, 0, 0), 36: (0, 0, 0)})
      lib.move("Hips", {0: (0, 0, 0), 18: (0, 0.2, 0)})   # optional
      lib.face(18, "hopeful")
  ```
  Keys sind Grad-Tripel `(X, Y, Z)` pro Bone, Frames starten bei 0.
* `apply_clip(character, clip, start_frame)`, `sample_combined(...)`,
  `add_alive_layer(...)` verhindern komplette Starre.
* Roblox-Emotes laden: `1_system.roblox_api.animation_loader.AnimationLoader`
  (zweistufig: Emote → Animation → KeyframeSequence → Clip).

### `primitives_and_map` – Stadt
`WorldBuilder(collection, texture_library=None, era="modern", preview=False)`
mit Methoden (genau diese `type`-Werte gibt es):

| `type` | Signatur (Kurzform) |
|---|---|
| `block` | `block(name, pos, size, color=None, texture=None, rotation=(0,0,0))` |
| `cylinder` | `cylinder(name, pos, radius, depth, …)` |
| `ball` | `ball(name, pos, radius, …)` |
| `wedge` | `wedge(name, pos, size, …)` |
| `corner_wedge` | `corner_wedge(name, pos, size, …)` |
| `cone` | `cone(name, pos, radius, depth, …)` |
| `arch` | `arch(name, pos, width, height, depth, …)` |
| `torus` | `torus(name, pos, major_radius, minor_radius, …)` |
| `truss` | `truss(name, pos, size, …)` |
| `stairs` | `stairs(name, pos, width, height, depth, …)` |
| `gable_roof` | `gable_roof(name, pos, footprint, height=2.0, …)` |
| `hanging_cable` | `hanging_cable(name, start, end, sag=0.8, …)` |
| `organic_ground` | `organic_ground(name="boden", size=(80,80), …)` |
| `curved_road` | `curved_road(name="strasse", points=(), …)` |
| `puddle` | `puddle(name, pos, radius=1.4, …)` |
| `fence` | `fence(name, start, end, height=1.5, posts=6, …)` |
| `tree` | `tree(name, pos, height=6.0, crown=1.0, …)` |
| `bush`, `grass_tuft`, `stone` | kleine Details mit `radius`/`size` |
| `street_lamp`, `bench`, `bicycle`, `mailbox`, `trash_can`, `window_light` | Stadtmöbel |
| `pipe` | `pipe(name, start, end, radius=0.12, …)` |
| `scatter` | `scatter(name, builder_name, count, area=(-20,20,-20,20), seed=…)` |
| `sign`, `text3d` | Schild mit Text (Font/Größe/Farbe als Kwargs) |
| `billboard_counter` | Zähler über einer Figur (9:16-taugliche Zahl) |
| `custom_model` | `{"type": "custom_model", "model": "<Name aus custom_models.py>"}` |
| `import_model` | importiertes OBJ/glTF (`path`) |
| `creator_store` | kuratierter Store-Eintrag (`asset_id`, `path`) |

* `SHAPE_TYPES` enthält genau die `type`-Werte oben; `validate_film` prüft sie.
* `build_spec(entries, world)` baut eine Liste von Dicts in einem Rutsch – das
  nutzt der Scene-Builder für `OBJECTS`.
* `TextureLibrary(preview=False)` liefert Materialien zu Textur-Keys.

### `roblox_textures`
* `TEXTURE_CATALOG` (45): `studs_2006, classic_brick, classic_grass,
  classic_plastic, classic_wood, classic_slate, classic_ice, classic_sand,
  classic_foil, classic_pebble, classic_corroded_metal, classic_diamond_plate,
  universal_2006, inlet_2006, glue_2006, weld_2006, plastic, smooth_plastic,
  neon, wood, wood_planks, concrete, brick, cobblestone, asphalt, pavement,
  granite, marble, limestone, plaster, roof_shingles, glass, metal,
  corroded_metal, fabric, carpet, cardboard, ground, grass, leafy_grass, mud,
  sand, snow, water, slate`
* `brickcolor(name, default=…)` kennt 68 Roblox-BrickColors;
  `SKIN_COLORS` = `fair, light, warm, olive, brown, deep`.
* Hex-Farben (`"#8B5A2B"`) funktionieren überall, wo `color` erlaubt ist.

### `lighting_and_style`
* `MOOD_NAMES`: `golden_hour, rainy_dusk, foggy_morning, hopeful_dawn,
  overcast_school, night_street, warm_interior, cold_room`
* `apply_mood(scene, mood, practical_locations=(), particles="auto",
  fog_multiplier=1.0, sun_override=None)`
* `setup_render(scene, samples, denoise=True, device="GPU")` – Cycles, fällt
  selbstständig auf CPU zurück, wenn kein GPU-Gerät gefunden wird.
* `add_vignette(scene, strength)`, `enable_motion_blur(scene, shutter)`.

### `fluid_camera` – Kamera
* `CAMERA_MOVES`: `slow_push_in, pull_out, crane_reveal, orbit_arc,
  tracking_follow, over_shoulder, rack_focus, dolly_left, dolly_right,
  tilt_up_reveal, spline_drift, handheld_walk`
* `FORBIDDEN_MOVES`: `static, still, fixed, none` – wird von `validate_film`
  als Fehler gemeldet.
* `frame_distance(subject_height, focal_mm, fill)` – Abstand, bei dem die Figur
  `fill` der Bildhöhe ausfüllt (0.15–2.0, geklemmt).
* `project_to_screen(cam_pos, aim, point, focal_mm)` – echte Lochkamera
  (36 mm Sensorhöhe, geklemmt) für Kompositionschecks.
* `SAFE_ZONE` in Pixeln (links 54, rechts 890, oben 110, unten 1580),
  `inside_safe_zone(x, y, margin=0)`.
* `CameraRig(scene, (width, height), fps)` – baut Kamera und Keyframes.

### `text_and_signs`
* `make_sign(world, name, position, text, size=…, color=…, font=…)`,
  `make_text3d(...)`, `make_counter(...)`.
* Fonts über `tools.font_manager` (Google Fonts, OFL/Apache): `bebas, anton,
  oswald, inter, poppins, roboto, lora, playfair, abril, caveat, patrick,
  shadows, marker, typewriter, spacemono, luckiest, chalk, bangers`.
  Download passiert beim ersten Bedarf und wird in `assets_cache/fonts`
  zwischengespeichert; offline greift DejaVu. Ohne Netz und ohne Cache bleibt
  Text auf Standardschrift – Schilder trotzdem bauen.

### `scene_builder` – Shots rendern
```
python -m 1_system.blender_engine.scene_builder --list-shots
python -m 1_system.blender_engine.scene_builder --shots 1-4 --quality preview
python -m 1_system.blender_engine.scene_builder --preview-storyboard --shots all
python -m 1_system.blender_engine.scene_builder --shots 7 --force
```
Optionen: `--film-dir`, `--timeline`, `--shots`, `--out-dir`, `--samples`,
`--quality {preview,high,max}`, `--device {GPU,CPU}`, `--still`,
`--preview-storyboard`, `--manifest`, `--force`, `--list-shots`.
`preview` = 540×960/8 Samples, `high` = 1080×1920/96, `max` = 1080×1920/320.
Der Builder ist wiederaufsetzbar: fertige Shots aus dem Manifest werden
übersprungen (außer `--force`). Aufruf über
`blender -b -P 1_system/blender_engine/scene_builder.py -- …` funktioniert
ebenfalls (Kaggle-Kernel nutzt das).

---

## 3. Roblox-API (`1_system/roblox_api/`)

### `open_cloud`
* `RobloxClient(api_key=None, user_id=None, cache_dir="assets_cache/roblox",
  calls_per_minute=120, offline=False)`
  * `search_creator_store(query, limit=10, category=None, max_price=0.0)`
  * `search_catalog(query, …)`
  * `asset_info(asset_id)` → `AssetInfo(name, asset_type_id, creator,
    creator_id, description, …)`
  * `asset_content(asset_id)` → `(bytes, content_type)` (folgt CDN-Redirects)
  * `download_asset(asset_id, target, force=False, expected=None)`
  * `thumbnail_url()`, `download_thumbnail()`, `threed_thumbnail()` (OBJ)
  * `verify()` → Prüfbericht (Suche, Metadaten, Download, Thumbnails)
* `check_license(name, creator_id=0, description="", asset_type="",
  category="")` → `(ok, Begründung)`; lehnt ~30 Marken ab, blockt Audio.
* `RobloxApiError.status` + `.hint` (401/403/404/429) – Hints in Meldungen
  übernehmen, sie sind für Menschen geschrieben.
* Nötige Key-Rechte: `legacy-asset:manage` (Download) und `asset:read`
  (Metadaten), `thumbnail:read` für Vorschaubilder.

### `rbxm_parser`
* `RbxmParser().parse_file(path)` / `.parse_bytes(data)` → `RbxmModel`
  (`parts`, `meshes`, `instances`, `bounds()`, `summary()`).
* Liest binäres `.rbxm` (nach rbx-dom-Spezifikation: Byte-Interleaving,
  Zigzag-Ints, Roblox-Floats, CFrame-Sonderfälle, LZ4/ZSTD), `.rbxmx`,
  FileMesh 1.00–5.00, OBJ, glTF/GLB.
* `import_into_blender(model, collection, offset, scale, material_factory)`.
* `RbxmPart(name, class_name, size, position, rotation_matrix, color, material,
  transparency, mesh_id, mesh_scale, attachments)`.

### `animation_loader`
* `AnimationLoader(client, cache_dir="assets_cache/animations").load(asset_id)`
  → `AnimationData(name, looped, frames, duration_seconds, summary())`.
  Zweistufig: Emote/Animation-Asset → `AnimationId` → KeyframeSequence.
* `animation_to_clip(anim)`, `register_clip(library, anim, name=…)` – danach wie
  ein eingebauter Clip in den Shots nutzbar.
* `parse_animation_bytes(bytes)` für lokale `.rbxmx`-Animationen.

### `asset_inspector`
```
python -m 1_system.roblox_api.asset_inspector --assets 123,456 --out assets_cache/inspect
python -m 1_system.roblox_api.asset_inspector --search "street lamp" --tryon
```
Liefert `report.md`, `report.json`, `kontaktabzug.png` (Thumbnails + Lizenzstatus)
und mit `--tryon` ein Render am R15-Avatar (540×960, EEVEE).
`inspect_asset(client, asset_id, out_dir, try_on=False)`, `inspect_many(...)`,
`build_contact_sheet(reports, path)`, `render_tryon(asset_id, out_dir, png,
slot=…)`.

### `prepare_assets`
```
python -m 1_system.roblox_api.prepare_assets --assets 123,456 --out assets/models
```
Lädt, prüft die Lizenz, konvertiert nach GLB (Blender) und schreibt
`assets/models/assets.json`. Danach in `characters.py` eintragen:
```python
"accessories": [{"id": 123, "path": "assets/models/123.glb",
                 "slot": "HatAttachment", "scale": 1.0}]
```

---

## 4. Kaggle-Brücke (`1_system/kaggle_bridge/`)

* `kaggle_client.KaggleClient` – Hülle um `kaggle`-CLI:
  `push_kernel(dir)`, `kernel_status(slug)`, `wait_for_kernel(slug,
  timeout_minutes, poll_seconds)`, `download_output(slug, target)`,
  `create_dataset/version_dataset/dataset_exists`, `quota()`, `verify()`.
* `dataset_sync` – `build_dataset_folder(session_dir, target_dir, slug,
  include_audio=False)`, `publish(client, folder)`, `stage_session(...)`,
  `prepared_slug(username, run_id)`.
* `kernel_builder` – `build_kernel(out_dir, kernel_slug, repo_url, commit,
  dataset_slug, shots, samples, quality, workers, callback, username)`.
  Erzeugt `main.py` (klont Commit, installiert `bpy`, teilt Shots auf zwei
  T4-Worker, mergt Manifeste, ruft optional `workflow_dispatch` auf) und
  `kernel-metadata.json` mit `machine_shape: NvidiaTeslaT4`, `is_private: true`,
  `enable_internet: true`.
* `parallel_render` – `start(...)`, `check(slug)`, `download(slug, out_dir)`,
  `merge_manifests(...)`, `flatten_shots(...)`.
  CLI: `python -m 1_system.kaggle_bridge.parallel_render start|check|download`.
* `fallback_watchdog` – `decide(runs, …)`, `watchdog(...)`, CLI
  `python -m 1_system.kaggle_bridge.fallback_watchdog --state-dir render_output`.

---

## 5. Werkzeuge (`1_system/tools/`)

| Modul | Aufgabe |
|---|---|
| `film_loader` | `load_film(film_dir)`, `read_yaml`, `exec_python_file`, `load_rules`; `Film`-Objekt mit `config, script, voices, characters, objects, shots, models, animations, modules` |
| `validate_film` | `validate_report(film_dir, allow_unconfigured=False)` → `ValidationReport` (`.errors`, `.warnings`, `.info`); CLI `--strict`, `--json`, `--allow-unconfigured` |
| `assemble_final` | `collect_clips`, `build_ffmpeg_command`, `assemble(timeline, manifest, audio, output, subtitles=…, storyboard=…, report=…)`, `make_storyboard`, CLI mit `--subtitles auto|true|false` |
| `mix_audio` | Master-Ton + Untertiteldatei: `python -m 1_system.tools.mix_audio` |
| `check_shots` | vergleicht Timeline und Manifest, meldet fehlende Shots |
| `preview_storyboard` | Raster aus Standbildern, `build_storyboard(shots_dir, out, …)` |
| `font_manager` | `resolve(name)`, `fonts_dir()`; Download nur wenn erlaubt |
| `render_local` | kompletter Lauf auf dem eigenen Rechner (Audio → Shots → Schnitt) |

---

## 6. Was validiert wird (harte Regeln)

* Format 1080×1920 @ 24 fps; `subtitles` muss `true` oder `false` sein.
* Genau 1 Hauptfigur, mindestens 2 Nebenfiguren (Statisten optional).
* Mindestens 3 Sprechsegmente, mindestens 3 Shots, für jedes Segment ein Shot.
* Jeder Shot: erlaubte Kamerabewegung (nie statisch), Brennweite 14–120 mm,
  `fill` 0.2–1.1, bekannte Lichtstimmung, Figuren aus `characters.py`, Füße auf
  z = 0, bekannte Animationen/Gesichter/SFX, Trigger-Wort muss im Segmenttext
  vorkommen.
* Map: mindestens 25 Objekte, organischer Boden, Straße, mindestens 8 Details,
  mindestens 2 Schilder mit Text, bekannte Texturen/Formen, keine schwebenden
  oder versunkenen Blöcke (Warnung).
* `custom_models.py`: jeder Eintrag ist eine aufrufbare Funktion; jedes
  `custom_model` in der Map existiert dort.
* `custom_animations.py`: `register(lib)` läuft ohne Fehler, Clips sind gültig.

"""Baut aus ``2_aktueller_film/`` echte 9:16-Blender-Shots und rendert sie.

Der Scene-Builder ist die einzige Stelle, die Figuren, Map, Licht, Kamera und
Animationen zusammenbringt. Er laeuft:

* **lokal** ueber ``python -m 1_system.blender_engine.scene_builder ...``
* **auf Kaggle** fuer jeden Shot in einem eigenen Blender-Prozess (eine GPU pro Prozess)

Beispiele
---------
Schnelle Vorschau aller Shots (1 Bild pro Shot, 540x960, 8 Samples)::

    python -m 1_system.blender_engine.scene_builder --preview-storyboard --out-dir preview/

Finale Shots 3 und 4 in 1080x1920 mit 128 Samples::

    python -m 1_system.blender_engine.scene_builder --shots 3,4 --samples 128 --out-dir out/shots

Der Builder schreibt ``render_manifest.json`` mit Frames, Pfaden und Kamera-Daten.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import bpy  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    HAS_BPY = False

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

rig_r15 = importlib.import_module("1_system.blender_engine.rig_r15")
animations = importlib.import_module("1_system.blender_engine.custom_animations")
primitives = importlib.import_module("1_system.blender_engine.primitives_and_map")
lighting = importlib.import_module("1_system.blender_engine.lighting_and_style")
camera_engine = importlib.import_module("1_system.blender_engine.fluid_camera")
roblox_textures = importlib.import_module("1_system.blender_engine.roblox_textures")
text_and_signs = importlib.import_module("1_system.blender_engine.text_and_signs")
timeline_sync = importlib.import_module("1_system.audio.timeline_sync")
film_loader = importlib.import_module("1_system.tools.film_loader")

QUALITY_PRESETS = {
    "preview": dict(width=540, height=960, samples=8, denoise=True),
    "high": dict(width=1080, height=1920, samples=96, denoise=True),
    "max": dict(width=1080, height=1920, samples=320, denoise=True),
}


def log(message: str) -> None:
    print(f"[scene_builder] {message}", flush=True)


class SceneBuilder:
    """Ein Film, viele Shots: baut und rendert, was die Timeline vorgibt."""

    def __init__(self, film, timeline: dict, width: int = 1080, height: int = 1920,
                 samples: int = 96, device: str = "GPU", seed: int = 2026,
                 force: bool = False):
        self.film = film
        self.timeline = timeline
        self.width = width
        self.height = height
        self.samples = samples
        self.device = device
        self.seed = seed
        self.force = force
        self.shots = timeline.get("shots") or []
        self.specs = {int(shot["id"]): shot for shot in film.shots}

    # -- Szene ----------------------------------------------------------- #
    def reset_scene(self) -> None:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.render.resolution_x = self.width
        scene.render.resolution_y = self.height
        scene.render.resolution_percentage = 100
        scene.render.fps = int(self.timeline.get("fps", 24))
        scene.render.use_persistent_data = True
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "HIGH"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
        scene.render.ffmpeg.audio_codec = "NONE"
        scene.render.film_transparent = False
        lighting.setup_render(scene, self.samples, True, self.device)
        return scene

    # -- Figuren --------------------------------------------------------- #
    def _character_colors(self, spec: dict) -> dict:
        skin = spec.get("skin") or spec.get("skin_color") or "fair"
        if skin in roblox_textures.SKIN_COLORS:
            skin = roblox_textures.SKIN_COLORS[skin]
        return {
            "skin_color": skin,
            "shirt_color": spec.get("shirt") or spec.get("shirt_color") or "#0D69AC",
            "pants_color": spec.get("pants") or spec.get("pants_color") or "#1B2A35",
        }

    def build_characters(self, shot_spec: dict, collection) -> dict[str, dict]:
        """Baut alle Figuren, die im Shot vorkommen (plus Kamera-Ziele)."""
        placed: dict[str, dict] = {}
        entries = list(shot_spec.get("characters") or [])
        target = (shot_spec.get("camera") or {}).get("target")
        if isinstance(target, str) and target not in [c.get("id") for c in entries]:
            entries.append({"id": target, "at": [0, 0, 0], "hidden": True})
        used_ids = {str(entry.get("id")) for entry in entries}
        for spec in self.film.characters:
            if str(spec.get("id")) not in used_ids:
                continue
            entry = next(e for e in entries if str(e.get("id")) == str(spec.get("id")))
            colors = self._character_colors(spec)
            at = entry.get("at") or [0.0, 0.0, 0.0]
            scale = float(spec.get("height_scale", spec.get("scale", 1.0)))
            face = entry.get("face") or spec.get("face") or "neutral"
            character = rig_r15.build_r15(
                name=str(spec.get("name") or spec.get("id")),
                skin_color=colors["skin_color"],
                shirt_color=colors["shirt_color"],
                pants_color=colors["pants_color"],
                face=face,
                height_scale=scale,
                collection=collection,
                location=(float(at[0]), float(at[1]), float(at[2])),
                rotation_z_deg=float(entry.get("facing", spec.get("facing", 0.0))),
                face_texture_path=spec.get("face_texture"),
                shirt_texture_path=spec.get("shirt_texture"),
                pants_texture_path=spec.get("pants_texture"),
            )
            character["_location"] = (float(at[0]), float(at[1]), float(at[2]))
            character["spec"] = spec
            character["shot_entry"] = entry
            if entry.get("hidden"):
                character["root"].hide_render = True
            placed[str(spec.get("id"))] = character
            combined_accessories = list(spec.get("accessories") or []) + list(entry.get("accessories") or [])
            if combined_accessories:
                self._attach_accessories(character, combined_accessories, collection)
        return placed

    def _attach_accessories(self, character: dict, accessories: list, collection) -> None:
        """Haengt Katalog-/Creator-Store-Artikel an Standard-Attachments."""
        for accessory in accessories:
            resolved = primitives.resolve_roblox_asset_path(accessory)
            slot = accessory.get("slot", "HatAttachment")
            if resolved is None:
                log(f"Hinweis: Accessoire ohne Datei uebersprungen ({accessory.get('id', '?')})")
                continue
            world = primitives.WorldBuilder(collection)
            obj = world.import_model(f"{character['name']}_{accessory.get('id', 'acc')}",
                                     resolved, pos=(0, 0, 0), scale=1.0)
            if obj is not None:
                rig_r15.attach_to_slot(character, slot, obj,
                                       float(accessory.get("scale", 1.0)),
                                       tuple(accessory.get("offset", (0, 0, 0))))

    # -- Map ------------------------------------------------------------- #
    def build_map(self, shot_spec: dict, collection):
        """Baut die Stadt und gibt den WorldBuilder zurueck (fuer Schilder/Zaehler)."""
        config = self.film.config or {}
        era = str(config.get("look_era") or shot_spec.get("era") or "mix")
        quality = str(config.get("qualitaet", "high")).lower()
        library = primitives.TextureLibrary(preview=quality == "preview")
        world = primitives.WorldBuilder(collection, library,
                                        era="classic" if era == "classic" else "modern",
                                        preview=quality == "preview")
        world.custom_models = self.film.models
        shot_id = int(shot_spec.get("id", 0))
        entries = []
        for entry in self.film.objects:
            allowed = entry.get("shots") or entry.get("only_in")
            if allowed and shot_id not in [int(s) for s in allowed]:
                continue
            entries.append(entry)
        # individuelle Map-Erweiterung des Shots
        entries.extend(shot_spec.get("extra_objects") or [])
        try:
            primitives.build_spec(entries, world)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Map-Aufbau fehlgeschlagen in Shot {shot_id}: {exc}") from exc
        map_mod = self.film.modules.get("map_and_props")
        if map_mod is not None:
            optional_build = getattr(map_mod, "OPTIONAL_MAP_BUILD", None)
            if isinstance(optional_build, str):
                optional_build = getattr(map_mod, optional_build, None)
            if callable(optional_build):
                optional_build(world)
        build_hook = shot_spec.get("map_hook")
        if build_hook and map_mod is not None:
            function = getattr(map_mod, str(build_hook), None)
            if callable(function):
                function(world)
        return world

    # -- Animation ------------------------------------------------------- #
    def animate_characters(self, characters: dict[str, dict], shot_spec: dict,
                           frames: int) -> dict:
        info: dict[str, list] = {}
        for character_id, character in characters.items():
            entry = character.get("shot_entry") or {}
            if character.get("root") is not None and character["root"].hide_render:
                continue
            anim_name = entry.get("anim") or "idle_breath"
            library = self.film.animations or animations.library()
            try:
                clip = library.get(anim_name) if library.has(anim_name) else animations.library().get(anim_name)
            except KeyError:
                raise KeyError(
                    f"Shot {shot_spec.get('id')}: Animation '{anim_name}' existiert nicht "
                    f"(Figur {character_id}). Verfuegbar: {', '.join(library.names())}")
            speed = max(0.25, float(entry.get("speed", 1.0)))
            duration = max(4, int(round(frames / speed)))
            applied = animations.apply_clip(
                character, clip, start_frame=1, duration=duration,
                alive=bool(entry.get("alive", True)),
                seed=abs(hash(character_id)) % 1000 + self.seed % 97)
            info.setdefault(character_id, []).append(applied)
            for extra in entry.get("extra_anims") or []:
                extra_clip = (library.get(extra["name"]) if library.has(extra["name"])
                              else animations.library().get(extra["name"]))
                animations.apply_clip(character, extra_clip,
                                      start_frame=int(extra.get("start_frame", 1)),
                                      duration=int(extra.get("duration", extra_clip.duration)),
                                      alive=False)
            face = entry.get("face")
            if face:
                animations.key_face(character, str(face), 1)
            if entry.get("talking"):
                rig_r15.set_talking(character, 1, frames, seed=abs(hash(character_id)) % 17)
            counter = entry.get("counter") or (character.get("spec") or {}).get("counter")
            if counter:
                value = counter.get("start") if isinstance(counter, dict) else counter
                label = counter.get("label", "") if isinstance(counter, dict) else ""
                text = f"{value} {label}".strip()
                text_and_signs.make_billboard_counter(
                    character, text, collection=character.get("collection"),
                    camera=bpy.context.scene.camera)
        return info

    # -- Trigger --------------------------------------------------------- #
    def apply_triggers(self, shot_spec: dict, characters: dict[str, dict],
                       timeline_shot: dict, world) -> list[dict]:
        """Fuehrt Wort-Trigger des Shots aus (Gesicht, Zaehler, Kamera, Emote...)."""
        triggers = shot_spec.get("triggers") or []
        executed: list[dict] = []
        segment_id = int(timeline_shot["segment_id"])
        segment = next((s for s in self.timeline["segments"]
                        if int(s["segment_id"]) == segment_id), None)
        if segment is None:
            return executed
        for trigger in triggers:
            word = str(trigger.get("on_word", ""))
            frame = self._frame_for_word(segment, word, int(trigger.get("occurrence", 0)))
            if frame is None:
                raise ValueError(f"Shot {shot_spec.get('id')}: Wort-Trigger '{word}' "
                                 "kommt im Segment nicht vor")
            frame = max(1, frame - int(timeline_shot["start_frame"]))
            action = str(trigger.get("action", ""))
            value = trigger.get("value")
            character = characters.get(str(trigger.get("character") or shot_spec.get("camera", {}).get("target") or ""))
            if action == "face" and character:
                animations.key_face(character, str(value), frame)
            elif action == "counter" and character:
                for handle in character.get("counters", []):
                    text_and_signs.update_counter(handle, str(value), frame)
            elif action == "anim" and character:
                library = self.film.animations or animations.library()
                clip = library.get(str(value)) if library.has(str(value)) else animations.library().get(str(value))
                animations.apply_clip(character, clip, start_frame=frame,
                                      duration=int(trigger.get("duration", clip.duration)))
            elif action == "statue" and character:
                rig_r15.set_stone(character, True, frame=frame)
            elif action == "camera_focal":
                camera = bpy.context.scene.camera
                camera.data.lens = float(value)
                camera.data.keyframe_insert("lens", frame=frame)
            elif action == "camera_focus":
                camera = bpy.context.scene.camera
                camera.data.dof.focus_distance = float(value)
                camera.data.dof.keyframe_insert("focus_distance", frame=frame)
            elif action in ("sfx", "music", "shake"):
                pass  # Audio-Trigger werden beim Mastering ausgewertet
            else:
                log(f"Warnung: Trigger-Aktion '{action}' unbekannt (Shot {shot_spec.get('id')})")
                continue
            executed.append({"action": action, "word": word, "frame": frame,
                             "value": value, "character": trigger.get("character")})
        return executed

    @staticmethod
    def _frame_for_word(segment: dict, word: str, occurrence: int = 0) -> Optional[int]:
        target = timeline_sync.clean_word(word)
        seen = 0
        for entry in segment.get("words", []):
            if timeline_sync.clean_word(entry["word"]) == target:
                if seen == occurrence:
                    return int(entry["start_frame"])
                seen += 1
        return None

    # -- ein Shot -------------------------------------------------------- #
    def build_shot(self, shot_id: int, output_path: Path, still: bool = False,
                   still_frame: Optional[int] = None, frames_override: Optional[int] = None) -> dict:
        """Baut und rendert einen Shot. Gibt einen Manifest-Eintrag zurueck."""
        require_bpy_ready()
        spec = self.specs.get(int(shot_id))
        if spec is None:
            raise KeyError(f"Shot {shot_id} fehlt in shots.py")
        timeline_shot = next((s for s in self.shots if int(s["id"]) == int(shot_id)), None)
        if timeline_shot is None:
            raise KeyError(f"Shot {shot_id} fehlt in der aufgeloesten Timeline")
        frames = int(frames_override or timeline_shot["frames"])
        if frames < 2 and not still:
            raise ValueError(f"Shot {shot_id} ist kuerzer als 2 Frames")

        started = time.time()
        scene = self.reset_scene()
        scene.frame_start, scene.frame_end = 1, max(2, frames)
        collection = bpy.data.collections.new(f"Shot_{shot_id}")
        scene.collection.children.link(collection)

        characters = self.build_characters(spec, collection)
        world = self.build_map(spec, collection)

        mood = str(spec.get("lighting") or "golden_hour")
        effects = spec.get("effects") or {}
        lighting.apply_mood(
            scene, mood,
            practical_locations=spec.get("practical_lights") or [],
            particles=effects.get("particles", "auto"),
            fog_multiplier=float(effects.get("fog", 1.0)),
            sun_override=spec.get("sun"),
        )
        if spec.get("vignette", True):
            lighting.add_vignette(scene, float(spec.get("vignette_strength", 0.35)))
        if spec.get("motion_blur"):
            lighting.enable_motion_blur(scene, float(spec.get("motion_blur")))

        # Kamera zuerst, damit Zaehler sie als Billboard nutzen koennen
        rig = camera_engine.CameraRig(scene, (self.width, self.height),
                                      int(self.timeline.get("fps", 24)))
        subjects = characters
        tracking = spec.get("camera", {}).get("move") in ("tracking_follow", "handheld_walk")
        subject_positions = None
        if tracking:
            target_id = (spec.get("camera") or {}).get("target")
            subject = characters.get(str(target_id))

            def subject_positions(frame_index: int) -> tuple[float, float, float]:
                if subject is None:
                    return (0.0, 0.0, 2.0)
                location = subject["root"].location
                return (location.x, location.y, location.z + 2.0)
        camera_info = rig.build(spec.get("camera") or {}, max(2, frames), subjects,
                                subject_positions)

        animation_info = self.animate_characters(characters, spec, max(2, frames))
        trigger_info = self.apply_triggers(spec, characters, timeline_shot, world)

        for name in spec.get("set_frame_lights") or []:
            log(f"Shot {shot_id}: Zusatzlicht {name}")

        scene.frame_set(1)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        scene.render.filepath = str(output_path)
        if still:
            scene.render.image_settings.file_format = "PNG"
            scene.frame_set(int(still_frame or max(1, frames // 2)))
            bpy.ops.render.render(write_still=True)
        else:
            scene.render.use_file_extension = True
            bpy.ops.render.render(animation=True)

        # Blender haengt bei FFMPEG selbst die Endung an
        produced = output_path
        if not still and not produced.is_file():
            candidate = output_path.with_suffix(".mp4")
            if candidate.is_file():
                produced = candidate
            elif output_path.with_name(output_path.name + ".mp4").is_file():
                produced = output_path.with_name(output_path.name + ".mp4")
        if not produced.is_file():
            raise RuntimeError(f"Blender hat keinen Output erzeugt: {output_path}")

        entry = {
            "id": int(shot_id),
            "segment_id": int(timeline_shot["segment_id"]),
            "title": str(spec.get("title") or timeline_shot.get("title") or f"Shot {shot_id}"),
            "frames": frames,
            "start_frame": int(timeline_shot["start_frame"]),
            "end_frame": int(timeline_shot["end_frame"]),
            "path": str(produced),
            "still": bool(still),
            "lighting": mood,
            "camera": camera_engine.camera_report(camera_info),
            "characters": sorted(characters),
            "animations": {k: [a["clip"] for a in v] for k, v in animation_info.items()},
            "triggers": trigger_info,
            "render_seconds": round(time.time() - started, 2),
            "width": self.width, "height": self.height, "samples": self.samples,
        }
        log(f"Shot {shot_id}: {frames} Frames in {entry['render_seconds']} s -> {produced.name}")
        return entry


def require_bpy_ready() -> None:
    if not HAS_BPY:
        raise RuntimeError("Scene-Builder braucht Blender. Auf GitHub laeuft er im "
                           "Blender-Schritt, lokal mit 'pip install bpy==4.2.0'.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_shots(value: str, available: list[int]) -> list[int]:
    if value in ("", "all", "alle"):
        return sorted(available)
    selected: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            low, high = part.split("-", 1)
            selected.extend(range(int(low), int(high) + 1))
        else:
            selected.append(int(part))
    unknown = [s for s in selected if s not in available]
    if unknown:
        raise SystemExit(f"Shots {unknown} existieren nicht. Verfuegbar: {available}")
    return sorted(dict.fromkeys(selected))


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        # Aufruf ueber "blender -b -P scene_builder.py -- ..." ueberspringt das "--"
        argv = list(sys.argv[1:])
        if "--" in argv:
            argv = argv[argv.index("--") + 1:]
    parser = argparse.ArgumentParser(description="9:16-Shots aus dem aktuellen Film bauen")
    parser.add_argument("--film-dir", type=Path, default=film_loader.FILM_DIR_DEFAULT)
    parser.add_argument("--timeline", type=Path, default=Path("render_session/timeline_resolved.json"))
    parser.add_argument("--shots", default="all", help="z. B. '1,3,4' oder '2-5' oder 'all'")
    parser.add_argument("--out-dir", type=Path, default=Path("render_output/shots"))
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--height", type=int, default=1920)
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--quality", choices=sorted(QUALITY_PRESETS), default=None)
    parser.add_argument("--device", default=os.environ.get("RENDER_DEVICE", "GPU"))
    parser.add_argument("--still", action="store_true", help="nur ein Standbild pro Shot")
    parser.add_argument("--preview-storyboard", action="store_true",
                        help="1 Standbild pro Shot in Vorschauqualitaet")
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--list-shots", action="store_true")
    args = parser.parse_args(argv)

    if args.quality:
        preset = QUALITY_PRESETS[args.quality]
        args.width, args.height = preset["width"], preset["height"]
        args.samples = preset["samples"]
    if args.preview_storyboard:
        args.width, args.height, args.samples, args.still = 540, 960, 8, True
    if args.width * 16 != args.height * 9:
        raise SystemExit(f"Aufloesung {args.width}x{args.height} ist nicht 9:16")

    film = film_loader.load_film(args.film_dir)
    if args.timeline.is_file():
        timeline = timeline_sync.load_timeline(args.timeline)
    else:
        # Standbilder ohne Audio: alle Shots mit fester Laenge
        timeline = {"fps": film.fps, "width": args.width, "height": args.height,
                    "total_frames": 24 * 5, "total_seconds": 5.0, "word_cues": [],
                    "segments": [], "shots": [
                        {"id": int(shot["id"]), "segment_id": int(shot["segment_id"]),
                         "start_frame": 0, "end_frame": 24 * 5, "frames": 24 * 5,
                         "title": shot.get("title", "")}
                        for shot in film.shots]}
        if not args.still and not args.preview_storyboard and not args.list_shots:
            raise SystemExit("Ohne Timeline sind nur Standbilder moeglich "
                             "(--still / --preview-storyboard)")

    available = [int(s["id"]) for s in timeline.get("shots", [])]
    if args.list_shots:
        for shot in timeline.get("shots", []):
            print(f"Shot {shot['id']:>2} | Segment {shot['segment_id']} | "
                  f"{shot['frames']:>4} Frames ({shot['frames'] / timeline['fps']:.2f} s) | "
                  f"{shot.get('title', '')}")
        return 0
    selected = _parse_shots(args.shots, available)
    if not HAS_BPY:
        print(json.dumps({"error": "bpy fehlt", "shots": selected}, ensure_ascii=False))
        return 2

    builder = SceneBuilder(film, timeline, args.width, args.height, args.samples,
                           args.device, force=args.force)
    manifest_path = args.manifest or (args.out_dir / "render_manifest.json")
    entries: list[dict] = []
    if manifest_path.is_file():
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8")).get("shots", [])
        except ValueError:
            entries = []
    done = {int(entry["id"]) for entry in entries if Path(entry.get("path", "")).is_file()}
    for shot_id in selected:
        if shot_id in done and not args.force:
            log(f"Shot {shot_id} existiert bereits - uebersprungen")
            continue
        suffix = ".png" if args.still else ".mp4"
        output = args.out_dir / f"shot_{shot_id:03d}{suffix}"
        entry = builder.build_shot(shot_id, output, still=args.still)
        entries = [e for e in entries if int(e["id"]) != shot_id] + [entry]
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(
            {"shots": sorted(entries, key=lambda e: int(e["id"])),
             "fps": timeline.get("fps", 24), "width": args.width, "height": args.height,
             "film": film.title}, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Fertig: {len(selected)} Shot(s), Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

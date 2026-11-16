"""Strenge Vorabpruefung des aktuellen Films - lieber jetzt meckern als nach dem Render.

Geprueft wird unter anderem
---------------------------
* Pflichtdateien, Python-Syntax, YAML-Struktur
* festes Format 9:16 / 1080x1920 / 24 fps und **ausdrueckliches** ``subtitles: true|false``
* mindestens 3 Figuren (1 Hauptfigur + mindestens 2 Nebenfiguren), gueltige Farben/Gesichter
* Sprechtext: Segmente, Sprecher mit voice_id, Laenge 140-3.200 Zeichen, Pausen plausibel
* Shots: lueckenlos je Segment, keine statische Kamera, gueltige Bewegung/Brennweite/Licht,
  bekannte Figuren/Animationen/SFX, Wort-Trigger existieren wirklich im Sprechtext
* Map: erlaubte Formen, gueltige Texturen/BrickColors, nichts schwebt, Mindestdetail
  (organischer Boden, Strasse, Laternen/Kabel, Baeume, Schilder) und Hochformat-Details
* Hochformat-Komposition: Kopf im sicheren Bereich, nicht in der TikTok-UI-Zone

Die Pruefung ist bewusst streng: Ein Fehler verhindert den Renderstart (Exitcode 1).
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

film_loader = importlib.import_module("1_system.tools.film_loader")
roblox_textures = importlib.import_module("1_system.blender_engine.roblox_textures")
primitives = importlib.import_module("1_system.blender_engine.primitives_and_map")
camera_engine = importlib.import_module("1_system.blender_engine.fluid_camera")
lighting = importlib.import_module("1_system.blender_engine.lighting_and_style")
rig_r15 = importlib.import_module("1_system.blender_engine.rig_r15")
animations = importlib.import_module("1_system.blender_engine.custom_animations")
sound_design = importlib.import_module("1_system.audio.sound_design")

VALID_ROLES = {"hauptfigur", "nebenfigur", "statist"}
RELATION_WORDS = ("mutter", "vater", "bruder", "schwester", "oma", "opa", "grossmutter",
                  "grossvater", "großmutter", "großvater", "gross", "groß", "tochter",
                  "sohn", "enkel", "enkelin", "freund", "freundin", "nachbar", "nachbarin",
                  "lehrer", "lehrerin", "mitschueler", "mitschuelerin", "mitschüler",
                  "mitschülerin", "schueler", "schüler", "kollege", "kollegin", "cousine",
                  "cousin", "tante", "onkel", "ich-erzähler", "erzähler")
TRIGGER_ACTIONS = {"face", "counter", "anim", "statue", "camera_focal", "camera_focus",
                   "sfx", "music", "shake"}
MIN_MAP_OBJECTS = 25
MAX_SPEECH_CHARS = 3200
MIN_SPEECH_CHARS = 140


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def add(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings,
                "info": self.info}

    def summary_markdown(self) -> str:
        lines = ["## Film-Validierung", ""]
        lines.append(f"**Ergebnis:** {'BESTANDEN' if self.ok else 'FEHLGESCHLAGEN'} "
                     f"({len(self.errors)} Fehler, {len(self.warnings)} Hinweise)")
        if self.info:
            lines += ["", "| Kennzahl | Wert |", "|---|---|"]
            for key, value in self.info.items():
                lines.append(f"| {key} | {value} |")
        if self.errors:
            lines += ["", "### Fehler (muessen behoben werden)", ""]
            lines += [f"- {error}" for error in self.errors]
        if self.warnings:
            lines += ["", "### Hinweise (freiwillig verbessern)", ""]
            lines += [f"- {warning}" for warning in self.warnings]
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Einzelpruefungen
# --------------------------------------------------------------------------- #
def _check_config(film, report: ValidationReport) -> None:
    config = film.config
    fmt = config.get("format") or {}
    for key, expected in (("width", 1080), ("height", 1920), ("fps", 24)):
        if int(fmt.get(key, -1)) != expected:
            report.add(f"film_config.yaml: format.{key} muss {expected} sein "
                       f"(9:16, 24 fps) - gefunden: {fmt.get(key, 'fehlt')}")
    if not isinstance(config.get("subtitles"), bool):
        report.add("film_config.yaml: 'subtitles' muss ausdruecklich true oder false sein "
                   "(der Betreiber entscheidet das pro Film)")
    if not str(config.get("titel") or config.get("title") or "").strip():
        report.add("film_config.yaml: 'titel' fehlt")
    quality = str(config.get("qualitaet", "high")).lower()
    if quality not in ("preview", "high", "max"):
        report.add("film_config.yaml: qualitaet muss preview, high oder max sein")
    music = config.get("musik") or {}
    if music and str(music.get("mood", "melancholisch")).lower() not in sound_design.MUSIC_MOODS:
        report.add(f"film_config.yaml: unbekannte Musikstimmung '{music.get('mood')}'. "
                   f"Erlaubt: {', '.join(sound_design.MUSIC_MOODS)}")
    safe = config.get("safe_zone") or {}
    if safe.get("bottom_px", 340) < 260:
        report.warn("safe_zone.bottom_px ist kleiner als 260 px - Untertitel koennten "
                    "in der TikTok-Caption-Zone liegen")


def _check_characters(film, report: ValidationReport) -> dict[str, dict]:
    characters: dict[str, dict] = {}
    if len(film.characters) < 3:
        report.add(f"Es sind nur {len(film.characters)} Figuren definiert - verlangt sind "
                   "mindestens 3 (1 Hauptfigur + mindestens 2 Nebenfiguren)")
    roles: dict[str, int] = {}
    for index, character in enumerate(film.characters):
        identifier = str(character.get("id") or "").strip()
        if not identifier:
            report.add(f"characters.py: Figur {index + 1} ohne 'id'")
            continue
        if identifier in characters:
            report.add(f"characters.py: doppelte Figuren-ID '{identifier}'")
            continue
        characters[identifier] = character
        role = str(character.get("role") or "nebenfigur").strip()
        roles[role] = roles.get(role, 0) + 1
        if role not in VALID_ROLES:
            report.add(f"Figur '{identifier}': unbekannte Rolle '{role}' "
                       f"(erlaubt: {', '.join(sorted(VALID_ROLES))})")
        face = str(character.get("face") or "neutral")
        if face not in rig_r15.FACE_NAMES:
            report.add(f"Figur '{identifier}': Gesicht '{face}' unbekannt "
                       f"(erlaubt: {', '.join(rig_r15.FACE_NAMES)})")
        for color_key in ("skin", "skin_color", "shirt", "shirt_color", "pants", "pants_color"):
            value = character.get(color_key)
            if value is None:
                continue
            if isinstance(value, str) and value.lower() not in roblox_textures.SKIN_COLORS:
                rgb = roblox_textures.brickcolor(value, default="")
                if rgb == roblox_textures.brickcolor("", default=""):
                    report.warn(f"Figur '{identifier}': Farbe '{value}' ist keine bekannte "
                                "BrickColor und kein Hex-Wert - es wird Grau benutzt")
        scale = float(character.get("height_scale", character.get("scale", 1.0)))
        if not 0.6 <= scale <= 1.5:
            report.add(f"Figur '{identifier}': height_scale {scale} ist unplausibel (0.6-1.5)")
        relation = str(character.get("relation") or character.get("beziehung") or "")
        if not relation:
            report.warn(f"Figur '{identifier}': keine Beziehung zur Hauptfigur angegeben "
                        "(z. B. 'Mutter', 'Mitschueler') - wichtig fuer die Story")
        elif not any(word in relation.lower() for word in RELATION_WORDS):
            report.warn(f"Figur '{identifier}': Beziehung '{relation}' ist ungewoehnlich")
    if roles.get("hauptfigur", 0) != 1:
        report.add(f"Es braucht genau 1 Hauptfigur, gefunden: {roles.get('hauptfigur', 0)}")
    if roles.get("nebenfigur", 0) < 2:
        report.add(f"Es brauchen mindestens 2 Nebenfiguren, gefunden: {roles.get('nebenfigur', 0)}")
    report.info["Figuren"] = (f"{len(characters)} (Hauptfigur {roles.get('hauptfigur', 0)}, "
                              f"Nebenfiguren {roles.get('nebenfigur', 0)}, "
                              f"Statisten {roles.get('statist', 0)})")
    return characters


def _check_script(film, report: ValidationReport, allow_unconfigured: bool = False) -> None:
    segments = film.segments()
    if len(segments) < 3:
        report.add(f"Nur {len(segments)} Sprechsegmente - ein 60-120-s-Film braucht mindestens 3")
    speakers = film.speaker_entries()
    main_voice = (speakers.get("haupt_erzaehler") or {}).get("voice_id")
    if not main_voice:
        message = ("3_regeln/empfohlene_elevenlabs_stimmen.yaml: haupt_erzaehler.voice_id fehlt")
        report.warn(message) if allow_unconfigured else report.add(message)
    seen_ids: set[int] = set()
    total = 0
    for index, segment in enumerate(segments, start=1):
        segment_id = int(segment.get("id", 0)) if str(segment.get("id", "")).isdigit() else index
        if segment_id in seen_ids:
            report.add(f"script_and_voices.yaml: Segment-ID {segment_id} doppelt")
        seen_ids.add(segment_id)
        text = str(segment.get("text") or "").strip()
        if len(text) < 2:
            report.add(f"Segment {segment_id}: kein Sprechtext")
        total += len(text)
        speaker = str(segment.get("speaker") or "haupt_erzaehler")
        if speaker not in speakers:
            message = (f"Segment {segment_id}: Sprecher '{speaker}' fehlt in "
                       "empfohlene_elevenlabs_stimmen.yaml")
            report.warn(message) if allow_unconfigured else report.add(message)
        elif not (speakers[speaker] or {}).get("voice_id"):
            message = f"Segment {segment_id}: Sprecher '{speaker}' hat keine voice_id"
            report.warn(message) if allow_unconfigured else report.add(message)
        pause = float(segment.get("pause_after", 0.0) or 0.0)
        if not 0 <= pause <= 6:
            report.add(f"Segment {segment_id}: pause_after {pause}s unplausibel")
    if total < MIN_SPEECH_CHARS:
        report.add(f"Sprechtext hat nur {total} Zeichen - zu kurz (Ziel 1.800-2.200, "
                   f"Minimum {MIN_SPEECH_CHARS})")
    if total > MAX_SPEECH_CHARS:
        report.add(f"Sprechtext hat {total} Zeichen - zu lang (Maximum {MAX_SPEECH_CHARS})")
    whisper_lines = sum(1 for s in segments if str(s.get("speaker")) != "haupt_erzaehler")
    if whisper_lines > 3:
        report.add(f"{whisper_lines} Nebenstimmen-Zeilen - erlaubt sind hoechstens 3 kurze "
                   "Einwuerfe im ganzen Film")
    for segment in segments:
        if str(segment.get("speaker")) != "haupt_erzaehler" and len(str(segment.get("text", ""))) > 90:
            report.warn(f"Segment {segment.get('id')}: Nebenstimme ist mit "
                        f"{len(str(segment.get('text', '')))} Zeichen recht lang - "
                        "Nebenstimmen sollen kurze, emotionale Einzel saetze sein")
    report.info["Sprechtext"] = f"{total} Zeichen, {len(segments)} Segmente"
    words = sum(len(str(s.get("text", "")).split()) for s in segments)
    if not 100 <= words <= 330:
        report.warn(f"Der Text hat {words} Woerter; fuer 60-120 s sind ~140-290 ideal")
    else:
        report.info["Woerter"] = words


def _check_shots(film, characters: dict[str, dict], report: ValidationReport) -> None:
    shots = film.shots
    if len(shots) < 3:
        report.add(f"Es sind nur {len(shots)} Shots definiert - zu wenig fuer einen Film")
    segment_ids = {int(s.get("id", i)) for i, s in enumerate(film.segments(), start=1)}
    library = film.animations or animations.library()
    builtin = set(animations.builtin_names())
    known_animations = set(library.names()) | builtin
    shot_ids: set[int] = set()
    per_segment: dict[int, int] = {}
    for shot in shots:
        shot_id = int(shot.get("id", 0))
        if shot_id in shot_ids:
            report.add(f"shots.py: doppelte Shot-ID {shot_id}")
        shot_ids.add(shot_id)
        segment_id = int(shot.get("segment_id", 0))
        if segment_id not in segment_ids:
            report.add(f"Shot {shot_id}: segment_id {segment_id} existiert nicht im Sprechtext")
        per_segment[segment_id] = per_segment.get(segment_id, 0) + 1
        camera = shot.get("camera") or {}
        move = str(camera.get("move", ""))
        if move in camera_engine.FORBIDDEN_MOVES or not move:
            report.add(f"Shot {shot_id}: Kamera ist statisch ('{move or 'leer'}') - "
                       "jeder Shot braucht eine Bewegung")
        elif move not in camera_engine.CAMERA_MOVES:
            report.add(f"Shot {shot_id}: unbekannte Kamerabewegung '{move}'. Erlaubt: "
                       f"{', '.join(camera_engine.CAMERA_MOVES)}")
        focal = float(camera.get("focal", 40))
        if not 14 <= focal <= 120:
            report.add(f"Shot {shot_id}: Brennweite {focal} mm ist unplausibel (14-120)")
        fill = float(camera.get("fill", 0.8))
        if not 0.2 <= fill <= 1.1:
            report.add(f"Shot {shot_id}: fill {fill} unplausibel (0.2-1.1)")
        target = camera.get("target")
        if isinstance(target, str) and target not in characters:
            report.add(f"Shot {shot_id}: Kamera-Ziel '{target}' ist keine Figur aus characters.py")
        mood = str(shot.get("lighting") or "")
        if mood not in lighting.MOODS:
            report.add(f"Shot {shot_id}: Lichtstimmung '{mood}' unbekannt. Erlaubt: "
                       f"{', '.join(lighting.MOOD_NAMES)}")
        entries = shot.get("characters") or []
        if not entries:
            report.add(f"Shot {shot_id}: keine Figuren im Bild")
        for entry in entries:
            identifier = str(entry.get("id") or "")
            if identifier not in characters:
                report.add(f"Shot {shot_id}: Figur '{identifier}' fehlt in characters.py")
            at = entry.get("at") or [0, 0, 0]
            if not isinstance(at, (list, tuple)) or len(at) < 2:
                report.add(f"Shot {shot_id}: 'at' von '{identifier}' muss [x, y, z] sein")
            elif len(at) >= 3 and abs(float(at[2])) > 0.01:
                report.add(f"Shot {shot_id}: Figur '{identifier}' steht bei z={at[2]} - "
                           "Figuren muessen mit den Fuessen auf dem Boden stehen (z=0)")
            anim = entry.get("anim")
            if anim and str(anim) not in known_animations:
                report.add(f"Shot {shot_id}: Animation '{anim}' unbekannt. Verfuegbar: "
                           f"{', '.join(sorted(known_animations)[:12])} ...")
            face = entry.get("face")
            if face and str(face) not in rig_r15.FACE_NAMES:
                report.add(f"Shot {shot_id}: Gesicht '{face}' unbekannt")
            for extra in entry.get("extra_anims") or []:
                if str(extra.get("name")) not in known_animations:
                    report.add(f"Shot {shot_id}: Zusatz-Animation '{extra.get('name')}' unbekannt")
        for sfx in shot.get("sfx") or []:
            kind = sfx if isinstance(sfx, str) else (sfx or {}).get("kind")
            if str(kind) not in sound_design.SFX_KINDS:
                report.add(f"Shot {shot_id}: SFX '{kind}' unbekannt. Erlaubt: "
                           f"{', '.join(sound_design.SFX_KINDS)}")
        segment = next((s for s in film.segments()
                        if int(s.get("id", 0)) == segment_id), None)
        segment_words = {timeline_word for timeline_word in
                         (str(w).strip(".,!?;:\"'\u201e\u201c()").casefold()
                          for w in str((segment or {}).get("text", "")).split())}
        for trigger in shot.get("triggers") or []:
            action = str(trigger.get("action") or "")
            if action not in TRIGGER_ACTIONS:
                report.add(f"Shot {shot_id}: Trigger-Aktion '{action}' unbekannt. Erlaubt: "
                           f"{', '.join(sorted(TRIGGER_ACTIONS))}")
            word = str(trigger.get("on_word") or "")
            if not word:
                report.add(f"Shot {shot_id}: Trigger ohne 'on_word'")
            elif word.strip(".,!?;:\"'\u201e\u201c()").casefold() not in segment_words:
                report.add(f"Shot {shot_id}: Trigger-Wort '{word}' kommt in Segment "
                           f"{segment_id} nicht vor")
            if action == "anim" and str(trigger.get("value")) not in known_animations:
                report.add(f"Shot {shot_id}: Trigger-Animation '{trigger.get('value')}' unbekannt")
        effects = shot.get("effects") or {}
        particles = effects.get("particles")
        if particles not in (None, "auto", "rain", "dust", "leaves", "mist"):
            report.add(f"Shot {shot_id}: Partikel '{particles}' unbekannt")
    missing = sorted(segment_ids - set(per_segment))
    if missing:
        report.add(f"Fuer diese Sprechsegmente fehlt ein Shot: {missing}")
    too_many = {seg: count for seg, count in per_segment.items() if count > 6}
    if too_many:
        report.warn(f"Sehr viele Shots pro Segment: {too_many} - kurze Shots wirken hektisch")
    report.info["Shots"] = len(shots)


def _check_map(film, report: ValidationReport) -> None:
    objects = film.objects
    if len(objects) < MIN_MAP_OBJECTS:
        report.add(f"Die Map hat nur {len(objects)} Objekte - verlangt sind mindestens "
                   f"{MIN_MAP_OBJECTS} (organische, detailreiche Stadt)")
    types: dict[str, int] = {}
    grounded = 0
    for index, entry in enumerate(objects, start=1):
        shape = str(entry.get("type") or "").strip()
        name = str(entry.get("name") or f"#{index}")
        if shape not in primitives.SHAPE_TYPES:
            report.add(f"Map-Objekt '{name}': unbekannte Form '{shape}'")
            continue
        types[shape] = types.get(shape, 0) + 1
        texture = entry.get("texture") or entry.get("top_texture") or entry.get("side_texture")
        if texture and str(texture) not in roblox_textures.TEXTURE_CATALOG:
            report.add(f"Map-Objekt '{name}': Textur '{texture}' unbekannt")
        for key in ("top_texture", "bottom_texture", "side_texture"):
            value = entry.get(key)
            if value and str(value) not in roblox_textures.TEXTURE_CATALOG:
                report.add(f"Map-Objekt '{name}': {key} '{value}' unbekannt")
        color = entry.get("color")
        if color and isinstance(color, str) and not color.startswith("#"):
            if roblox_textures.brickcolor(color, default="") == roblox_textures.brickcolor("", default=""):
                report.warn(f"Map-Objekt '{name}': Farbe '{color}' unbekannt (wird Grau)")
        pos = entry.get("pos")
        if pos is not None:
            if not isinstance(pos, (list, tuple)) or len(pos) != 3:
                report.add(f"Map-Objekt '{name}': pos muss [x, y, z] sein")
            elif not all(isinstance(v, (int, float)) for v in pos):
                report.add(f"Map-Objekt '{name}': pos enthaelt keine Zahlen")
            else:
                grounded += 1
        if shape in ("block", "cylinder", "ball", "wedge", "cone", "truss") and pos:
            size = entry.get("size")
            if shape == "block" and size and len(size) == 3:
                bottom = float(pos[2]) - float(size[2]) / 2
                if bottom > 0.35:
                    report.warn(f"Map-Objekt '{name}': schwebt {bottom:.2f} Studs ueber dem "
                                "Boden - Absicht (z. B. Schild) oder Fehler?")
                    continue
                if bottom < -0.6:
                    report.add(f"Map-Objekt '{name}': steckt {abs(bottom):.2f} Studs im Boden")
        if shape == "custom_model":
            model = entry.get("model")
            if model not in (film.models or {}):
                report.add(f"Map-Objekt '{name}': custom_model '{model}' fehlt in custom_models.py "
                           f"(vorhanden: {sorted(film.models or {})})")
    if not types.get("organic_ground"):
        report.add("Map braucht einen organischen Boden (type 'organic_ground')")
    if not (types.get("curved_road") or types.get("block")):
        report.add("Map braucht eine Strasse (type 'curved_road')")
    detail_shapes = ("tree", "bush", "street_lamp", "hanging_cable", "bench", "fence",
                     "grass_tuft", "stone", "bicycle", "mailbox", "trash_can", "puddle")
    detail_count = sum(types.get(shape, 0) for shape in detail_shapes)
    if detail_count < 8:
        report.add(f"Zu wenig Alltagsdetails ({detail_count}) - Laternen, Baeume, Kabel, "
                   "Buesche, Pfuetzen, Baenke machen die Stadt lebendig")
    signs = types.get("sign", 0) + types.get("text3d", 0)
    if signs < 2:
        report.add(f"Nur {signs} Schild(er) mit Text - mindestens 2 sind Pflicht "
                   "(Ortsschild, Ladenfront, Tafel, Briefkasten)")
    tall = sum(1 for entry in objects
               if entry.get("type") in ("block", "gable_roof", "cylinder")
               and isinstance(entry.get("size"), (list, tuple)) and len(entry["size"]) == 3
               and float(entry["size"][2]) >= 4.0)
    if tall < 3:
        report.warn(f"Wenig vertikale Architektur ({tall} hohe Objekte) - im 9:16-Format "
                    "tragen Haeuser, Tuerme und Treppen die Bildkomposition")
    report.info["Map-Objekte"] = f"{len(objects)} ({detail_count} Details, {signs} Schilder)"
    report.info["Formen"] = ", ".join(f"{k}:{v}" for k, v in sorted(types.items()))[:300]


def _check_composition(film, characters: dict[str, dict], report: ValidationReport) -> None:
    """Grobe Hochformat-Pruefung: Kopf im sicheren Bereich, Fuesse sichtbar."""
    for shot in film.shots:
        camera = shot.get("camera") or {}
        target_id = camera.get("target")
        entries = {str(e.get("id")): e for e in shot.get("characters") or []}
        if isinstance(target_id, str) and target_id in characters:
            entry = entries.get(target_id) or {"at": [0, 0, 0]}
            at = entry.get("at") or [0, 0, 0]
            scale = float((characters[target_id] or {}).get("height_scale", 1.0))
            height = 6.7 * scale
            focal = float(camera.get("focal", 40))
            fill = float(camera.get("fill", 0.8))
            distance = camera_engine.frame_distance(height, focal, fill)
            azimuth = math.radians(float(camera.get("azimuth", 0.0)))
            cam_pos = (float(at[0]) + math.cos(azimuth) * distance,
                       float(at[1]) + math.sin(azimuth) * distance,
                       float(camera.get("height", height * 0.6)))
            aim = (float(at[0]), float(at[1]), float(at[2]) + height * 0.62)
            head = camera_engine.project_to_screen(cam_pos, aim,
                                                  (float(at[0]), float(at[1]),
                                                   float(at[2]) + height * 0.9), focal)
            feet = camera_engine.project_to_screen(cam_pos, aim,
                                                  (float(at[0]), float(at[1]),
                                                   float(at[2]) + 0.1), focal)
            if not camera_engine.inside_safe_zone(head[0], head[1], margin=-10):
                report.warn(f"Shot {shot.get('id')}: Kopf liegt rechnerisch ausserhalb der "
                            f"Safe-Zone ({head[0]:.0f},{head[1]:.0f} px) - pruefe die "
                            "Komposition im Storyboard")
            if feet[1] < camera_engine.SAFE_ZONE["safe_top"]:
                report.warn(f"Shot {shot.get('id')}: Fuesse sind nicht im Bild "
                            "(fill zu gross oder height zu niedrig)")


def _check_python(film, report: ValidationReport) -> None:
    for name in ("characters.py", "map_and_props.py", "shots.py",
                 "custom_models.py", "custom_animations.py"):
        path = Path(film.directory) / name
        if not path.is_file():
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            report.add(f"{name}: Syntaxfehler Zeile {exc.lineno}: {exc.msg}")


def _check_models(film, report: ValidationReport) -> None:
    for name, function in (film.models or {}).items():
        if not callable(function):
            report.add(f"custom_models.py: '{name}' ist keine Funktion")
    animation_problems = []
    if film.animations is not None:
        animation_problems = film.animations.validate()
    for problem in animation_problems:
        report.add(f"custom_animations.py: {problem}")


def _check_rules(film, report: ValidationReport) -> None:
    """Prueft, ob die Empfehlungsdateien plausibel gefuellt sind."""
    voices = film.voices or {}
    main = voices.get("haupt_erzaehler") or {}
    if not main.get("voice_id"):
        report.warn("Noch keine Haupt-Erzaehlerstimme hinterlegt - der Render wird "
                    "scheitern, bis in 3_regeln/empfohlene_elevenlabs_stimmen.yaml eine "
                    "voice_id steht")
    emotes = film_loader.load_rules().get("emotes") or {}
    if not emotes.get("r15"):
        report.warn("3_regeln/empfohlene_emotes_und_animationen.yaml ist leer - "
                    "Roblox-Emotes koennen nicht geladen werden")


# --------------------------------------------------------------------------- #
# Gesamtpruefung
# --------------------------------------------------------------------------- #
def validate_report(film_dir: Path = film_loader.FILM_DIR_DEFAULT,
                    allow_unconfigured: bool = False) -> ValidationReport:
    report = ValidationReport()
    try:
        film = film_loader.load_film(film_dir)
    except film_loader.FilmLoadError as exc:
        report.add(str(exc))
        return report
    _check_python(film, report)
    _check_config(film, report)
    characters = _check_characters(film, report)
    _check_script(film, report, allow_unconfigured)
    _check_shots(film, characters, report)
    _check_map(film, report)
    _check_models(film, report)
    _check_composition(film, characters, report)
    _check_rules(film, report)
    report.info["Titel"] = film.title
    report.info["Untertitel"] = "an" if film.subtitles else ("aus" if film.subtitles is False else "FEHLT")
    report.info["Format"] = f"{film.width}x{film.height} @ {film.fps} fps"
    return report


def validate_film(film_dir: Path = film_loader.FILM_DIR_DEFAULT) -> list[str]:
    """Kompatibilitaets-API: gibt nur die Fehlerliste zurueck."""
    return validate_report(film_dir).errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Film streng validieren")
    parser.add_argument("--film-dir", type=Path, default=film_loader.FILM_DIR_DEFAULT)
    parser.add_argument("--strict", action="store_true",
                        help="auch Hinweise (Warnungen) fuehren zu Exitcode 1")
    parser.add_argument("--json", type=Path, default=None, help="Bericht als JSON speichern")
    parser.add_argument("--allow-unconfigured", action="store_true",
                        help="fehlende voice_id als Hinweis statt Fehler behandeln "
                             "(fuer Struktur-Tests ohne Secrets)")
    args = parser.parse_args(argv)
    try:
        report = validate_report(args.film_dir, args.allow_unconfigured)
    except Exception as exc:  # noqa: BLE001 - Validierung darf nie mit Traceback enden
        print(f"FEHLER: Validierung abgebrochen - {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2
    for error in report.errors:
        print(f"FEHLER: {error}", file=sys.stderr)
    for warning in report.warnings:
        print(f"HINWEIS: {warning}", file=sys.stderr)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                             encoding="utf-8")
    summary_path = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write(report.summary_markdown())
    if report.ok and (not args.strict or not report.warnings):
        print(f"Validierung bestanden: {report.info.get('Shots', 0)} Shots, "
              f"{report.info.get('Figuren', '')}, {report.info.get('Map-Objekte', '')}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

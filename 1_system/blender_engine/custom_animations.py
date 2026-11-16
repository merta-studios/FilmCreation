"""Eigene R15-Animationsbibliothek, Keyframe-Composer und Dauer-"Alive"-Layer.

Aufbau
------
Eine Animation ist ein *Clip*: Knochenspuren als Keyframes (Grad), optionale
Gesichtswechsel und Marker. Clips sind reine Python-Daten - sie lassen sich ohne
Blender erzeugen, pruefen und in der Filmvalidierung auflisten. Erst
``apply_clip()`` schreibt die Kurven in Blender.

Koordinaten
-----------
Rotationen sind Grad und werden im **Bone-Raum** gesetzt:

* ``X`` schwingt ein nach unten haengendes Glied nach vorn/hinten (Gehen, Nicken),
* ``Y`` verdreht es um die eigene Achse,
* ``Z`` bewegt es seitlich (Spreizen, Kopf neigen).

Der Composer interpoliert weich (Smoothstep) und respektiert Loop-Clips. Zusaetzlich
liegt auf jeder Figur ein "Alive"-Layer: Atmen, Mikro-Kopfbewegungen, Blickdrift,
Gewichtsverlagerung und Blinzeln. Dadurch steht niemals eine Figur wirklich still -
auch dann nicht, wenn im Shot keine Animation angegeben ist.

Filme erweitern die Bibliothek in ``2_aktueller_film/custom_animations.py``::

    def register(lib):
        lib.new("winken_scheu", duration=36, loop=True)
        lib.key("RightUpperArm", {0: (0, 0, 0), 12: (0, 0, -70), 24: (0, 0, -30), 36: (0, 0, 0)})
        lib.key("Head", {0: (0, 0, 0), 18: (6, 0, 8)})
"""
from __future__ import annotations

import importlib
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # macht das Modul unabhaengig vom Aufrufpfad
    sys.path.insert(0, str(_ROOT))

_rig = importlib.import_module("1_system.blender_engine.rig_r15")
BONE_NAMES = _rig.BONE_NAMES
FACES = _rig.FACES
require_bpy = _rig.require_bpy

FPS_ANIM = 24
DEFAULT_BLEND_FRAMES = 8


# --------------------------------------------------------------------------- #
# Clip-Daten
# --------------------------------------------------------------------------- #
@dataclass
class Clip:
    """Eine Animation als Keyframe-Daten (Grad, Frames ab Clipstart)."""

    name: str
    duration: int = 24
    loop: bool = False
    description: str = ""
    rotation: dict[str, dict[int, tuple[float, float, float]]] = field(default_factory=dict)
    location: dict[str, dict[int, tuple[float, float, float]]] = field(default_factory=dict)
    faces: dict[int, str] = field(default_factory=dict)
    markers: dict[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.duration < 2:
            raise ValueError(f"Clip '{self.name}': Dauer muss mindestens 2 Frames sein")
        for bone in list(self.rotation) + list(self.location):
            if bone not in BONE_NAMES:
                raise ValueError(
                    f"Clip '{self.name}': Bone '{bone}' existiert nicht. "
                    f"Erlaubt: {', '.join(BONE_NAMES)}")
        for frame, face in self.faces.items():
            if face not in FACES:
                raise ValueError(f"Clip '{self.name}': Gesicht '{face}' unbekannt "
                                 f"(erlaubt: {', '.join(FACES)})")
            if not 0 <= frame <= self.duration:
                raise ValueError(f"Clip '{self.name}': Gesichts-Key bei Frame {frame} "
                                 "liegt ausserhalb der Clip-Dauer")

    # -- Sampling -------------------------------------------------------- #
    def _sample_track(self, keys: dict[int, tuple[float, float, float]],
                      frame: int) -> tuple[float, float, float]:
        if not keys:
            return (0.0, 0.0, 0.0)
        local = frame % self.duration if self.loop else min(max(frame, 0), self.duration)
        frames = sorted(keys)
        if local <= frames[0]:
            return tuple(keys[frames[0]])
        if local >= frames[-1]:
            return tuple(keys[frames[-1]])
        for a, b in zip(frames, frames[1:]):
            if a <= local <= b:
                span = max(1, b - a)
                t = (local - a) / span
                smooth = t * t * (3 - 2 * t)
                return tuple(keys[a][i] + (keys[b][i] - keys[a][i]) * smooth for i in range(3))
        return tuple(keys[frames[-1]])

    def sample(self, frame: int) -> dict[str, tuple[float, float, float]]:
        return {bone: self._sample_track(keys, frame) for bone, keys in self.rotation.items()}

    def sample_offsets(self, frame: int) -> dict[str, tuple[float, float, float]]:
        return {bone: self._sample_track(keys, frame) for bone, keys in self.location.items()}

    def face_at(self, frame: int) -> Optional[str]:
        chosen = None
        for key_frame in sorted(self.faces):
            if key_frame <= frame:
                chosen = self.faces[key_frame]
        return chosen

    def validate(self) -> list[str]:
        problems = []
        for bone, keys in self.rotation.items():
            if not keys:
                problems.append(f"{self.name}: Bone {bone} ohne Keys")
            elif min(keys) < 0 or max(keys) > self.duration:
                problems.append(f"{self.name}: Keys fuer {bone} ausserhalb 0..{self.duration}")
        if self.loop and self.rotation:
            for bone, keys in self.rotation.items():
                if 0 in keys and self.duration in keys and tuple(keys[0]) != tuple(keys[self.duration]):
                    problems.append(
                        f"{self.name}: Loop-Clip endet fuer {bone} nicht auf dem Startwert")
        return problems


# --------------------------------------------------------------------------- #
# Composer
# --------------------------------------------------------------------------- #
class AnimationBuilder:
    """Bequeme Schreib-API fuer Clips (auch von Filmdateien genutzt)."""

    def __init__(self) -> None:
        self.clips: dict[str, Clip] = {}
        self._current: Optional[Clip] = None

    def new(self, name: str, duration: int = 24, loop: bool = False,
            description: str = "") -> Clip:
        if name in self.clips:
            raise ValueError(f"Animation '{name}' existiert bereits")
        clip = Clip(name=name, duration=int(duration), loop=bool(loop),
                    description=description)
        self.clips[name] = clip
        self._current = clip
        return clip

    def _target(self, name: Optional[str]) -> Clip:
        if name:
            if name not in self.clips:
                raise KeyError(f"Animation '{name}' nicht angelegt (zuerst new() aufrufen)")
            return self.clips[name]
        if self._current is None:
            raise RuntimeError("Noch keine Animation mit new() angelegt")
        return self._current

    def key(self, bone: str, keys: dict[int, tuple[float, float, float]],
            clip: Optional[str] = None) -> Clip:
        """Setzt Rotations-Keys eines Bones: ``{frame: (x, y, z)}`` in Grad."""
        target = self._target(clip)
        target.rotation.setdefault(bone, {}).update(
            {int(frame): tuple(float(v) for v in value) for frame, value in keys.items()})
        return target

    def move(self, bone: str, keys: dict[int, tuple[float, float, float]],
             clip: Optional[str] = None) -> Clip:
        """Setzt Positions-Keys (Studs) - sparsam nutzen, meist reicht Rotation."""
        target = self._target(clip)
        target.location.setdefault(bone, {}).update(
            {int(frame): tuple(float(v) for v in value) for frame, value in keys.items()})
        return target

    def face(self, frame: int, name: str, clip: Optional[str] = None) -> Clip:
        target = self._target(clip)
        target.faces[int(frame)] = str(name)
        return target

    def marker(self, frame: int, label: str, clip: Optional[str] = None) -> Clip:
        target = self._target(clip)
        target.markers[int(frame)] = str(label)
        return target

    # -- Abfragen -------------------------------------------------------- #
    def names(self) -> list[str]:
        return sorted(self.clips)

    def has(self, name: str) -> bool:
        return name in self.clips

    def get(self, name: str) -> Clip:
        if name not in self.clips:
            raise KeyError(f"Animation '{name}' unbekannt. Verfuegbar: {', '.join(self.names())}")
        return self.clips[name]

    def validate(self) -> list[str]:
        problems: list[str] = []
        for clip in self.clips.values():
            problems.extend(clip.validate())
        return problems


class AnimationLibrary(AnimationBuilder):
    """Wie AnimationBuilder, aber mit allen eingebauten Story-Animationen."""

    def __init__(self) -> None:
        super().__init__()
        _register_builtins(self)


# --------------------------------------------------------------------------- #
# Eingebaute Bibliothek
# --------------------------------------------------------------------------- #
def _register_builtins(lib: AnimationBuilder) -> None:
    """Registriert die Story-Animationen (weiche Kurven, 24 fps)."""

    def clip(name: str, duration: int, loop: bool, description: str) -> Clip:
        return lib.new(name, duration=duration, loop=loop, description=description)

    # --- Gangarten ------------------------------------------------------ #
    clip("walk_sad", 48, True, "Langsamer, gebeugter Gang mit haengendem Kopf")
    lib.key("LeftUpperLeg", {0: (18, 0, 0), 12: (0, 0, 0), 24: (-18, 0, 0), 36: (0, 0, 0), 48: (18, 0, 0)})
    lib.key("RightUpperLeg", {0: (-18, 0, 0), 12: (0, 0, 0), 24: (18, 0, 0), 36: (0, 0, 0), 48: (-18, 0, 0)})
    lib.key("LeftLowerLeg", {0: (8, 0, 0), 12: (26, 0, 0), 24: (2, 0, 0), 36: (12, 0, 0), 48: (8, 0, 0)})
    lib.key("RightLowerLeg", {0: (2, 0, 0), 12: (12, 0, 0), 24: (8, 0, 0), 36: (26, 0, 0), 48: (2, 0, 0)})
    lib.key("LeftFoot", {0: (-6, 0, 0), 24: (10, 0, 0), 48: (-6, 0, 0)})
    lib.key("RightFoot", {0: (10, 0, 0), 24: (-6, 0, 0), 48: (10, 0, 0)})
    lib.key("LeftUpperArm", {0: (-6, 0, 4), 24: (8, 0, 4), 48: (-6, 0, 4)})
    lib.key("RightUpperArm", {0: (8, 0, -4), 24: (-6, 0, -4), 48: (8, 0, -4)})
    lib.key("UpperTorso", {0: (4, 0, 0), 24: (6, 0, 1.5), 48: (4, 0, 0)})
    lib.key("Head", {0: (10, 0, -2), 24: (13, 0, 2), 48: (10, 0, -2)})

    clip("walk_hurry", 32, True, "Schneller, angespannter Gang mit Vorneigung")
    lib.key("LeftUpperLeg", {0: (32, 0, 0), 8: (0, 0, 0), 16: (-30, 0, 0), 24: (0, 0, 0), 32: (32, 0, 0)})
    lib.key("RightUpperLeg", {0: (-30, 0, 0), 8: (0, 0, 0), 16: (32, 0, 0), 24: (0, 0, 0), 32: (-30, 0, 0)})
    lib.key("LeftLowerLeg", {0: (4, 0, 0), 8: (46, 0, 0), 16: (6, 0, 0), 24: (18, 0, 0), 32: (4, 0, 0)})
    lib.key("RightLowerLeg", {0: (6, 0, 0), 8: (18, 0, 0), 16: (4, 0, 0), 24: (46, 0, 0), 32: (6, 0, 0)})
    lib.key("LeftUpperArm", {0: (26, 0, 6), 16: (-24, 0, 6), 32: (26, 0, 6)})
    lib.key("RightUpperArm", {0: (-24, 0, -6), 16: (26, 0, -6), 32: (-24, 0, -6)})
    lib.key("LeftLowerArm", {0: (24, 0, 0), 16: (14, 0, 0), 32: (24, 0, 0)})
    lib.key("RightLowerArm", {0: (14, 0, 0), 16: (24, 0, 0), 32: (14, 0, 0)})
    lib.key("UpperTorso", {0: (10, 0, 0), 16: (12, 0, 0), 32: (10, 0, 0)})

    clip("run_scared", 24, True, "Hektisches Rennen mit rudernden Armen")
    lib.key("LeftUpperLeg", {0: (42, 0, 0), 6: (10, 0, 0), 12: (-38, 0, 0), 18: (10, 0, 0), 24: (42, 0, 0)})
    lib.key("RightUpperLeg", {0: (-38, 0, 0), 6: (10, 0, 0), 12: (42, 0, 0), 18: (10, 0, 0), 24: (-38, 0, 0)})
    lib.key("LeftLowerLeg", {0: (10, 0, 0), 6: (58, 0, 0), 12: (18, 0, 0), 18: (34, 0, 0), 24: (10, 0, 0)})
    lib.key("RightLowerLeg", {0: (18, 0, 0), 6: (34, 0, 0), 12: (10, 0, 0), 18: (58, 0, 0), 24: (18, 0, 0)})
    lib.key("LeftUpperArm", {0: (-48, 0, 14), 12: (44, 0, 14), 24: (-48, 0, 14)})
    lib.key("RightUpperArm", {0: (44, 0, -14), 12: (-48, 0, -14), 24: (44, 0, -14)})
    lib.key("UpperTorso", {0: (14, 0, 0), 12: (16, 0, 0), 24: (14, 0, 0)})
    lib.key("Head", {0: (-4, 0, 0), 12: (-2, 0, 4), 24: (-4, 0, 0)})

    # --- Stehen / Reaktionen -------------------------------------------- #
    clip("stand_shy", 60, True, "Scheues Stehen, Haende vor dem Koerper")
    lib.key("LeftUpperArm", {0: (10, 0, 18), 30: (12, 0, 16), 60: (10, 0, 18)})
    lib.key("RightUpperArm", {0: (12, 0, -16), 30: (10, 0, -18), 60: (12, 0, -16)})
    lib.key("LeftLowerArm", {0: (34, 0, 0), 30: (38, 0, 0), 60: (34, 0, 0)})
    lib.key("RightLowerArm", {0: (36, 0, 0), 30: (40, 0, 0), 60: (36, 0, 0)})
    lib.key("Head", {0: (12, 0, 4), 30: (14, 0, -2), 60: (12, 0, 4)})
    lib.key("UpperTorso", {0: (2, 0, 0), 30: (3, 0, 0), 60: (2, 0, 0)})

    clip("look_up_wonder", 96, False, "Kopf heben, Augen weit, Hoffnung")
    lib.key("Head", {0: (0, 0, 0), 24: (-26, 0, 0), 72: (-30, 0, 2), 96: (-24, 0, 0)})
    lib.key("UpperTorso", {0: (0, 0, 0), 40: (-6, 0, 0), 96: (-4, 0, 0)})
    lib.key("LeftUpperArm", {0: (0, 0, 0), 40: (-8, 0, 12), 96: (-6, 0, 10)})
    lib.key("RightUpperArm", {0: (0, 0, 0), 40: (-8, 0, -12), 96: (-6, 0, -10)})
    lib.face(0, "neutral")
    lib.face(30, "hopeful")

    clip("step_back_scared", 36, False, "Erschrockenes Zurueckweichen")
    lib.key("UpperTorso", {0: (0, 0, 0), 10: (-10, 0, 0), 36: (-4, 0, 0)})
    lib.key("LeftUpperLeg", {0: (0, 0, 0), 12: (-22, 0, 0), 36: (-6, 0, 0)})
    lib.key("RightUpperLeg", {0: (0, 0, 0), 12: (18, 0, 0), 36: (2, 0, 0)})
    lib.key("LeftUpperArm", {0: (0, 0, 0), 12: (-40, 0, 26), 36: (-16, 0, 18)})
    lib.key("RightUpperArm", {0: (0, 0, 0), 12: (-40, 0, -26), 36: (-16, 0, -18)})
    lib.key("Head", {0: (0, 0, 0), 10: (-14, 0, 0), 36: (-6, 0, 0)})
    lib.face(0, "surprised")
    lib.face(24, "sad")

    clip("cover_eyes", 48, False, "Haende vor die Augen")
    lib.key("LeftUpperArm", {0: (0, 0, 0), 18: (-92, 0, 12), 48: (-96, 0, 10)})
    lib.key("RightUpperArm", {0: (0, 0, 0), 18: (-92, 0, -12), 48: (-96, 0, -10)})
    lib.key("LeftLowerArm", {0: (0, 0, 0), 18: (86, 0, 0), 48: (90, 0, 0)})
    lib.key("RightLowerArm", {0: (0, 0, 0), 18: (86, 0, 0), 48: (90, 0, 0)})
    lib.key("Head", {0: (0, 0, 0), 18: (16, 0, 0), 48: (18, 0, 0)})
    lib.face(0, "sad")
    lib.face(20, "crying")

    clip("cry_cover_face", 72, True, "Weinen mit Haenden vors Gesicht und Schluchzen")
    lib.key("LeftUpperArm", {0: (-88, 0, 14), 18: (-92, 0, 12), 36: (-86, 0, 15), 54: (-92, 0, 12), 72: (-88, 0, 14)})
    lib.key("RightUpperArm", {0: (-88, 0, -14), 18: (-92, 0, -12), 36: (-86, 0, -15), 54: (-92, 0, -12), 72: (-88, 0, -14)})
    lib.key("LeftLowerArm", {0: (92, 0, 0), 36: (96, 0, 0), 72: (92, 0, 0)})
    lib.key("RightLowerArm", {0: (92, 0, 0), 36: (96, 0, 0), 72: (92, 0, 0)})
    lib.key("UpperTorso", {0: (10, 0, 0), 18: (13, 0, 1.5), 36: (10, 0, 0), 54: (13, 0, -1.5), 72: (10, 0, 0)})
    lib.key("Head", {0: (18, 0, 0), 18: (21, 0, 2), 36: (18, 0, 0), 54: (21, 0, -2), 72: (18, 0, 0)})
    lib.face(0, "crying")

    clip("wipe_tears", 60, False, "Traenen wegwischen, dann aufblicken")
    lib.key("RightUpperArm", {0: (0, 0, 0), 14: (-80, 0, -8), 26: (-84, 0, -4), 40: (-30, 0, -6), 60: (0, 0, 0)})
    lib.key("RightLowerArm", {0: (0, 0, 0), 14: (74, 0, 0), 26: (80, 0, 12), 40: (30, 0, 0), 60: (0, 0, 0)})
    lib.key("Head", {0: (16, 0, 0), 26: (14, 0, -8), 44: (0, 0, 0), 60: (-6, 0, 0)})
    lib.face(0, "crying")
    lib.face(34, "sad")
    lib.face(52, "hopeful")

    clip("fall_to_knees", 60, False, "In die Knie sinken")
    lib.key("LeftUpperLeg", {0: (0, 0, 0), 30: (-72, 0, 0), 60: (-78, 0, 0)})
    lib.key("RightUpperLeg", {0: (0, 0, 0), 30: (26, 0, 0), 60: (30, 0, 0)})
    lib.key("LeftLowerLeg", {0: (0, 0, 0), 30: (78, 0, 0), 60: (82, 0, 0)})
    lib.key("RightLowerLeg", {0: (0, 0, 0), 30: (14, 0, 0), 60: (16, 0, 0)})
    lib.key("UpperTorso", {0: (0, 0, 0), 30: (18, 0, 0), 60: (22, 0, 0)})
    lib.key("LeftUpperArm", {0: (0, 0, 0), 30: (18, 0, 10), 60: (24, 0, 8)})
    lib.key("RightUpperArm", {0: (0, 0, 0), 30: (18, 0, -10), 60: (24, 0, -8)})
    lib.key("Head", {0: (0, 0, 0), 30: (22, 0, 0), 60: (28, 0, 0)})
    lib.face(0, "sad")
    lib.face(36, "crying")

    clip("freeze_as_statue", 48, False, "Erstarren wie eine Statue (fuer Stadt-Regeln)")
    lib.key("UpperTorso", {0: (4, 0, 0), 8: (6, 0, 0), 48: (6, 0, 0)})
    lib.key("Head", {0: (6, 0, 0), 8: (8, 0, 0), 48: (8, 0, 0)})
    lib.key("LeftUpperArm", {0: (4, 0, 6), 48: (4, 0, 6)})
    lib.key("RightUpperArm", {0: (4, 0, -6), 48: (4, 0, -6)})
    lib.face(0, "surprised")
    lib.face(10, "neutral")

    # --- Interaktion ---------------------------------------------------- #
    clip("hug_a", 72, False, "Umarmung - Gebende Person")
    lib.key("LeftUpperArm", {0: (0, 0, 0), 24: (-64, 0, 26), 72: (-70, 0, 24)})
    lib.key("RightUpperArm", {0: (0, 0, 0), 24: (-64, 0, -26), 72: (-70, 0, -24)})
    lib.key("LeftLowerArm", {0: (0, 0, 0), 24: (54, 0, 10), 72: (58, 0, 10)})
    lib.key("RightLowerArm", {0: (0, 0, 0), 24: (54, 0, -10), 72: (58, 0, -10)})
    lib.key("UpperTorso", {0: (0, 0, 0), 24: (6, 0, 0), 72: (8, 0, 0)})
    lib.key("Head", {0: (0, 0, 0), 24: (8, 0, 6), 72: (10, 0, 8)})
    lib.face(0, "sad")
    lib.face(20, "hopeful")

    clip("hug_b", 72, False, "Umarmung - Empfangende Person")
    lib.key("LeftUpperArm", {0: (0, 0, 0), 20: (-58, 0, 30), 72: (-62, 0, 28)})
    lib.key("RightUpperArm", {0: (0, 0, 0), 20: (-58, 0, -30), 72: (-62, 0, -28)})
    lib.key("LeftLowerArm", {0: (0, 0, 0), 20: (60, 0, 12), 72: (64, 0, 12)})
    lib.key("RightLowerArm", {0: (0, 0, 0), 20: (60, 0, -12), 72: (64, 0, -12)})
    lib.key("UpperTorso", {0: (0, 0, 0), 20: (10, 0, 0), 72: (12, 0, 0)})
    lib.key("Head", {0: (0, 0, 0), 20: (14, 0, -6), 72: (16, 0, -8)})
    lib.face(0, "crying")
    lib.face(36, "happy")

    clip("comfort_shoulder", 96, False, "Hand auf die Schulter legen")
    lib.key("RightUpperArm", {0: (0, 0, 0), 24: (-60, 0, -18), 72: (-62, 0, -16), 96: (-30, 0, -10)})
    lib.key("RightLowerArm", {0: (0, 0, 0), 24: (48, 0, 0), 72: (50, 0, 0), 96: (24, 0, 0)})
    lib.key("UpperTorso", {0: (0, 0, 0), 30: (4, 0, -3), 96: (2, 0, 0)})
    lib.key("Head", {0: (0, 0, 0), 30: (6, 0, -8), 96: (2, 0, -4)})
    lib.face(0, "sad")
    lib.face(48, "hopeful")

    clip("hand_over_object", 48, False, "Etwas ueberreichen")
    lib.key("RightUpperArm", {0: (0, 0, 0), 18: (-54, 0, -6), 48: (-56, 0, -4)})
    lib.key("RightLowerArm", {0: (0, 0, 0), 18: (44, 0, 0), 48: (46, 0, 0)})
    lib.key("UpperTorso", {0: (0, 0, 0), 18: (5, 0, -4), 48: (5, 0, -4)})
    lib.key("Head", {0: (0, 0, 0), 18: (8, 0, -6), 48: (8, 0, -6)})

    clip("receive_object", 48, False, "Etwas entgegennehmen")
    lib.key("LeftUpperArm", {0: (0, 0, 0), 16: (-50, 0, 12), 48: (-48, 0, 10)})
    lib.key("LeftLowerArm", {0: (0, 0, 0), 16: (46, 0, 0), 48: (48, 0, 0)})
    lib.key("Head", {0: (0, 0, 0), 16: (10, 0, 4), 48: (10, 0, 4)})
    lib.face(0, "shy")
    lib.face(30, "hopeful")

    clip("point_and_laugh", 60, True, "Auf jemanden zeigen und lachen")
    lib.key("RightUpperArm", {0: (-70, 0, -14), 20: (-74, 0, -12), 40: (-68, 0, -16), 60: (-70, 0, -14)})
    lib.key("RightLowerArm", {0: (8, 0, 0), 30: (14, 0, 0), 60: (8, 0, 0)})
    lib.key("UpperTorso", {0: (0, 0, 0), 15: (-6, 0, 0), 30: (2, 0, 0), 45: (-5, 0, 0), 60: (0, 0, 0)})
    lib.key("Head", {0: (-4, 0, 0), 20: (-12, 0, -4), 40: (-6, 0, 2), 60: (-4, 0, 0)})
    lib.face(0, "angry")
    lib.face(18, "happy")

    clip("nod", 32, False, "Nicken")
    lib.key("Head", {0: (0, 0, 0), 8: (18, 0, 0), 16: (2, 0, 0), 24: (14, 0, 0), 32: (0, 0, 0)})

    clip("head_shake", 36, False, "Kopf schuetteln")
    lib.key("Head", {0: (0, 0, 0), 9: (0, 0, 16), 18: (0, 0, -16), 27: (0, 0, 10), 36: (0, 0, 0)})

    clip("wave_goodbye_sad", 72, False, "Traurig zum Abschied winken")
    lib.key("RightUpperArm", {0: (-40, 0, -30), 18: (-46, 0, -34), 36: (-40, 0, -28), 54: (-46, 0, -34), 72: (-20, 0, -16)})
    lib.key("RightLowerArm", {0: (30, 0, 0), 18: (38, 0, 0), 36: (30, 0, 0), 54: (38, 0, 0), 72: (16, 0, 0)})
    lib.key("Head", {0: (6, 0, 0), 36: (10, 0, -4), 72: (12, 0, 0)})
    lib.face(0, "sad")
    lib.face(40, "hopeful")

    # --- Sitz- und Alltagsposen ---------------------------------------- #
    clip("sit_wheelchair", 48, True, "Im Rollstuhl sitzen (Beine angewinkelt)")
    lib.key("LeftUpperLeg", {0: (-82, 0, 4), 24: (-84, 0, 4), 48: (-82, 0, 4)})
    lib.key("RightUpperLeg", {0: (-82, 0, -4), 24: (-84, 0, -4), 48: (-82, 0, -4)})
    lib.key("LeftLowerLeg", {0: (84, 0, 0), 24: (86, 0, 0), 48: (84, 0, 0)})
    lib.key("RightLowerLeg", {0: (84, 0, 0), 24: (86, 0, 0), 48: (84, 0, 0)})
    lib.key("UpperTorso", {0: (6, 0, 0), 24: (7, 0, 0), 48: (6, 0, 0)})
    lib.key("LeftUpperArm", {0: (-6, 0, 10), 24: (-8, 0, 10), 48: (-6, 0, 10)})
    lib.key("RightUpperArm", {0: (-6, 0, -10), 24: (-8, 0, -10), 48: (-6, 0, -10)})

    clip("push_wheelchair", 48, True, "Rollstuhl schieben")
    lib.key("LeftUpperArm", {0: (-56, 0, 12), 24: (-62, 0, 10), 48: (-56, 0, 12)})
    lib.key("RightUpperArm", {0: (-56, 0, -12), 24: (-62, 0, -10), 48: (-56, 0, -12)})
    lib.key("LeftLowerArm", {0: (18, 0, 0), 24: (22, 0, 0), 48: (18, 0, 0)})
    lib.key("RightLowerArm", {0: (18, 0, 0), 24: (22, 0, 0), 48: (18, 0, 0)})
    lib.key("UpperTorso", {0: (6, 0, 0), 24: (7, 0, 0), 48: (6, 0, 0)})
    lib.key("LeftUpperLeg", {0: (12, 0, 0), 24: (-10, 0, 0), 48: (12, 0, 0)})
    lib.key("RightUpperLeg", {0: (-10, 0, 0), 24: (12, 0, 0), 48: (-10, 0, 0)})

    clip("sit_desk_write", 64, True, "Am Tisch sitzen und schreiben")
    lib.key("LeftUpperLeg", {0: (-86, 0, 6), 32: (-86, 0, 6), 64: (-86, 0, 6)})
    lib.key("RightUpperLeg", {0: (-86, 0, -6), 32: (-86, 0, -6), 64: (-86, 0, -6)})
    lib.key("LeftLowerLeg", {0: (86, 0, 0), 64: (86, 0, 0)})
    lib.key("RightLowerLeg", {0: (86, 0, 0), 64: (86, 0, 0)})
    lib.key("LeftUpperArm", {0: (-66, 0, 14), 32: (-68, 0, 14), 64: (-66, 0, 14)})
    lib.key("RightUpperArm", {0: (-62, 0, -14), 16: (-56, 0, -14), 32: (-62, 0, -14), 48: (-56, 0, -14), 64: (-62, 0, -14)})
    lib.key("LeftLowerArm", {0: (56, 0, 0), 64: (56, 0, 0)})
    lib.key("RightLowerArm", {0: (60, 0, 0), 32: (68, 0, 0), 64: (60, 0, 0)})
    lib.key("UpperTorso", {0: (10, 0, 0), 32: (11, 0, 0), 64: (10, 0, 0)})
    lib.key("Head", {0: (16, 0, 0), 32: (18, 0, -2), 64: (16, 0, 0)})

    clip("lie_in_bed", 96, True, "Im Bett liegen (Decke separat modellieren)")
    lib.key("UpperTorso", {0: (0, 0, 0), 48: (2, 0, 0), 96: (0, 0, 0)})
    lib.key("Head", {0: (4, 0, 0), 48: (6, 0, 3), 96: (4, 0, 0)})
    lib.key("LeftUpperArm", {0: (-10, 0, 20), 48: (-12, 0, 20), 96: (-10, 0, 20)})
    lib.key("RightUpperArm", {0: (-10, 0, -20), 48: (-12, 0, -20), 96: (-10, 0, -20)})
    lib.key("LeftUpperLeg", {0: (18, 0, 4), 48: (20, 0, 4), 96: (18, 0, 4)})
    lib.key("RightUpperLeg", {0: (18, 0, -4), 48: (20, 0, -4), 96: (18, 0, -4)})

    clip("open_door_slowly", 72, False, "Tuer langsam oeffnen")
    lib.key("RightUpperArm", {0: (0, 0, 0), 20: (-58, 0, -10), 48: (-66, 0, -4), 72: (-30, 0, -8)})
    lib.key("RightLowerArm", {0: (0, 0, 0), 20: (26, 0, 0), 48: (52, 0, 0), 72: (20, 0, 0)})
    lib.key("UpperTorso", {0: (0, 0, 0), 30: (7, 0, 0), 72: (2, 0, 0)})
    lib.key("Head", {0: (0, 0, 0), 30: (8, 0, 0), 72: (2, 0, 0)})

    clip("kneel_pray", 120, True, "Knien und beten/hoffen")
    lib.key("LeftUpperLeg", {0: (-72, 0, 2), 60: (-74, 0, 2), 120: (-72, 0, 2)})
    lib.key("RightUpperLeg", {0: (-72, 0, -2), 60: (-74, 0, -2), 120: (-72, 0, -2)})
    lib.key("LeftLowerLeg", {0: (84, 0, 0), 120: (84, 0, 0)})
    lib.key("RightLowerLeg", {0: (84, 0, 0), 120: (84, 0, 0)})
    lib.key("LeftUpperArm", {0: (-72, 0, 8), 60: (-74, 0, 6), 120: (-72, 0, 8)})
    lib.key("RightUpperArm", {0: (-72, 0, -8), 60: (-74, 0, -6), 120: (-72, 0, -8)})
    lib.key("LeftLowerArm", {0: (72, 0, 0), 120: (72, 0, 0)})
    lib.key("RightLowerArm", {0: (72, 0, 0), 120: (72, 0, 0)})
    lib.key("Head", {0: (22, 0, 0), 60: (24, 0, 0), 120: (22, 0, 0)})

    clip("hold_hands", 48, True, "Haende halten")
    lib.key("LeftUpperArm", {0: (-24, 0, 26), 24: (-26, 0, 26), 48: (-24, 0, 26)})
    lib.key("RightUpperArm", {0: (-24, 0, -8), 24: (-26, 0, -8), 48: (-24, 0, -8)})
    lib.key("LeftLowerArm", {0: (34, 0, 0), 48: (34, 0, 0)})
    lib.key("RightLowerArm", {0: (30, 0, 0), 48: (30, 0, 0)})

    clip("idle_breath", 96, True, "Ruhiges Atmen im Stand")
    lib.key("UpperTorso", {0: (0, 0, 0), 48: (-1.6, 0, 0), 96: (0, 0, 0)})
    lib.key("Head", {0: (0, 0, 0), 48: (1.2, 0, 0), 96: (0, 0, 0)})
    lib.key("LeftUpperArm", {0: (0, 0, 0), 48: (0, 0, 1.6), 96: (0, 0, 0)})
    lib.key("RightUpperArm", {0: (0, 0, 0), 48: (0, 0, -1.6), 96: (0, 0, 0)})

    clip("turn_away", 48, False, "Sich abwenden")
    lib.key("UpperTorso", {0: (0, 0, -26), 48: (0, 0, -30)})
    lib.key("Head", {0: (0, 0, -14), 48: (4, 0, -18)})
    lib.key("LeftUpperArm", {0: (0, 0, 2), 48: (6, 0, 4)})
    lib.key("RightUpperArm", {0: (0, 0, -2), 48: (6, 0, -4)})

    clip("sit_ground", 48, True, "Auf dem Boden sitzen, Knie angezogen")
    lib.key("LeftUpperLeg", {0: (-96, 0, 6), 48: (-96, 0, 6)})
    lib.key("RightUpperLeg", {0: (-96, 0, -6), 48: (-96, 0, -6)})
    lib.key("LeftLowerLeg", {0: (72, 0, 0), 24: (74, 0, 0), 48: (72, 0, 0)})
    lib.key("RightLowerLeg", {0: (72, 0, 0), 24: (74, 0, 0), 48: (72, 0, 0)})
    lib.key("UpperTorso", {0: (16, 0, 0), 24: (17, 0, 0), 48: (16, 0, 0)})
    lib.key("LeftUpperArm", {0: (-40, 0, 22), 48: (-40, 0, 22)})
    lib.key("RightUpperArm", {0: (-40, 0, -22), 48: (-40, 0, -22)})


# --------------------------------------------------------------------------- #
# Bibliothek mit Emote-Mix
# --------------------------------------------------------------------------- #
def library() -> AnimationLibrary:
    """Frische Bibliothek mit allen eingebauten Animationen."""
    return AnimationLibrary()


def builtin_names() -> list[str]:
    return library().names()


# --------------------------------------------------------------------------- #
# Sampling inkl. Blending und Alive-Layer
# --------------------------------------------------------------------------- #
def _alive_pose(frame: int, seed: float) -> dict[str, tuple[float, float, float]]:
    """Mikrobewegungen, damit keine Figur je exakt stillsteht."""
    t = frame / FPS_ANIM
    breath = math.sin(t * 2 * math.pi / 4.2 + seed)
    sway = math.sin(t * 2 * math.pi / 7.3 + seed * 1.7)
    drift = math.sin(t * 2 * math.pi / 11.0 + seed * 0.6)
    return {
        "UpperTorso": (breath * 0.9, 0.0, sway * 0.7),
        "Head": (breath * 0.5 + drift * 0.6, drift * 1.6, drift * 2.4 + sway * 0.8),
        "LeftUpperArm": (0.0, 0.0, breath * 0.9 + 0.8),
        "RightUpperArm": (0.0, 0.0, -breath * 0.9 - 0.8),
        "LowerTorso": (0.0, 0.0, sway * 0.5),
    }


def sample_combined(clips: Iterable[tuple[Clip, float]], frame: int,
                    alive: bool = True, seed: float = 0.0) -> dict[str, tuple[float, float, float]]:
    """Summiert mehrere gewichtete Clips plus optional den Alive-Layer."""
    pose: dict[str, list[float]] = {}
    for clip, weight in clips:
        if weight <= 0:
            continue
        for bone, rotation in clip.sample(frame).items():
            pose.setdefault(bone, [0.0, 0.0, 0.0])
            for i in range(3):
                pose[bone][i] += rotation[i] * weight
    if alive:
        for bone, rotation in _alive_pose(frame, seed).items():
            pose.setdefault(bone, [0.0, 0.0, 0.0])
            for i in range(3):
                pose[bone][i] += rotation[i]
    return {bone: (values[0], values[1], values[2]) for bone, values in pose.items()}


def blink_frames(start: int, end: int, seed: float = 0.0,
                 average_gap: int = 96) -> list[int]:
    """Deterministische Blinzel-Frames (ca. alle 3,5-5 s, leicht variierend)."""
    frames: list[int] = []
    frame = start + int(24 + (seed * 37) % 40)
    while frame < end:
        frames.append(frame)
        frame += average_gap + int((math.sin(frame * 0.37 + seed) + 1) * 18)
    return frames


# --------------------------------------------------------------------------- #
# Anwendung in Blender
# --------------------------------------------------------------------------- #
def apply_clip(character: dict, clip: Clip, start_frame: int, *,
               duration: Optional[int] = None, blend_frames: int = DEFAULT_BLEND_FRAMES,
               alive: bool = True, seed: float = 0.0, extra_clips: Optional[list[tuple[Clip, float]]] = None,
               sample_step: int = 4) -> dict:
    """Schreibt einen Clip (plus optionale Misch-Clips und Alive-Layer) als Keyframes.

    ``duration`` begrenzt die Wiedergabe (z. B. Shot-Laenge); Loop-Clips laufen weiter,
    Nicht-Loop-Clips halten ihre Endpose. Rueckgabe: Info-Dict fuer Logs/Tests.
    """
    require_bpy()
    import math as _math

    end_frame = start_frame + int(duration if duration is not None else clip.duration)
    clips: list[tuple[Clip, float]] = [(clip, 1.0)]
    if extra_clips:
        clips.extend(extra_clips)

    bones = character["bones"]
    for pose_bone in bones.values():
        pose_bone.rotation_mode = "XYZ"

    written = 0
    frames = list(range(start_frame, end_frame + 1, max(1, sample_step)))
    if frames[-1] != end_frame:
        frames.append(end_frame)
    for frame in frames:
        local = frame - start_frame
        pose = sample_combined(clips, local, alive=alive, seed=seed)
        for bone_name, rotation in pose.items():
            pose_bone = bones.get(bone_name)
            if pose_bone is None:
                continue
            pose_bone.rotation_euler = tuple(_math.radians(v) for v in rotation)
            pose_bone.keyframe_insert("rotation_euler", frame=frame)
            written += 1

    # Gesichtswechsel des Clips anwenden
    face_events = 0
    for key_frame in sorted(clip.faces):
        if key_frame > (duration if duration is not None else clip.duration):
            continue
        face_name = clip.faces[key_frame]
        key_face(character, face_name, start_frame + key_frame)
        face_events += 1

    return {
        "clip": clip.name, "start_frame": start_frame, "end_frame": end_frame,
        "keyframes": written, "face_events": face_events,
        "blend_frames": blend_frames, "alive": alive,
    }


def key_face(character: dict, face_name: str, frame: int) -> None:
    """Setzt ein Gesicht und keyframed alle sichtbaren Gesichtsteile."""
    require_bpy()
    set_face = _rig.set_face

    if face_name not in FACES:
        raise KeyError(f"Gesicht '{face_name}' unbekannt")
    set_face(character, face_name)
    for eye in character.get("eyes") or []:
        eye.keyframe_insert("scale", frame=frame)
        eye.keyframe_insert("location", frame=frame)
    mouth = character.get("mouth")
    if mouth is not None:
        mouth.keyframe_insert("scale", frame=frame)
        mouth.keyframe_insert("location", frame=frame)
        mouth.keyframe_insert("rotation_euler", frame=frame)
    for brow in character.get("brows") or []:
        brow.keyframe_insert("rotation_euler", frame=frame)
    for tear in character.get("tears") or []:
        tear.keyframe_insert("hide_render", frame=frame)
        tear.keyframe_insert("hide_viewport", frame=frame)


def add_alive_layer(character: dict, start_frame: int, end_frame: int,
                    seed: float = 0.0, sample_step: int = 4,
                    blinks: bool = True) -> None:
    """Legt Atmen/Blickdrift/Blinzeln auf eine Figur, die sonst keine Animation hat."""
    require_bpy()
    import math as _math
    blink = _rig.blink

    bones = character["bones"]
    frame = start_frame
    while frame <= end_frame:
        pose = _alive_pose(frame, seed)
        for bone_name, rotation in pose.items():
            pose_bone = bones.get(bone_name)
            if pose_bone is None:
                continue
            pose_bone.rotation_mode = "XYZ"
            existing = pose_bone.rotation_euler
            pose_bone.rotation_euler = (
                existing.x + _math.radians(rotation[0]),
                existing.y + _math.radians(rotation[1]),
                existing.z + _math.radians(rotation[2]),
            )
            pose_bone.keyframe_insert("rotation_euler", frame=frame)
            pose_bone.rotation_euler = existing
        frame += max(1, sample_step)
    if blinks:
        for blink_frame in blink_frames(start_frame, end_frame, seed):
            blink(character, blink_frame)


def list_animations(lib: Optional[AnimationLibrary] = None) -> list[dict]:
    """Metadaten aller Animationen (fuer Doku, Filmliste und Validierung)."""
    lib = lib or library()
    return [
        {"name": clip.name, "duration_frames": clip.duration, "loop": clip.loop,
         "duration_seconds": round(clip.duration / FPS_ANIM, 2),
         "bones": len(clip.rotation), "faces": sorted(set(clip.faces.values())),
         "description": clip.description}
        for clip in lib.clips.values()
    ]

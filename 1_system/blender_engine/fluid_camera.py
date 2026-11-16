"""Kamera-Engine fuer TikTok-Hochformat (1080x1920) - die Kamera steht NIE still.

Jeder Shot bekommt eine echte Bewegung plus organisches "Atmen" auf jedem Frame.
Die Bewegungstypen sind so gebaut, dass sie im 9:16-Format funktionieren:
vertikale Architektur, viel Himmel, Gesichter im oberen Drittel und freie
Ränder rechts/unten fuer die TikTok-UI.

Bewegungen
----------
``slow_push_in``   langsame Fahrt auf das Gesicht zu (Emotion)
``pull_out``       von der Figur weg, zeigt die Stadt (Einsamkeit)
``crane_reveal``   Kran von unten nach oben, enthüllt Haeuser/Himmel
``orbit_arc``      Bogen um die Figur (Distanz bleibt, Perspektive aendert sich)
``tracking_follow`` laeuft seitlich mit der Figur mit
``over_shoulder``  ueber die Schulter einer zweiten Figur
``rack_focus``     Fokus zieht von Vordergrund auf Hintergrund (oder umgekehrt)
``dolly_left`` / ``dolly_right``  seitliche Fahrt
``tilt_up_reveal`` Neigung von Boden zu Himmel
``spline_drift``   freie Bezier-Fahrt durch eigene Punkte
``handheld_walk``  handgefuehrtes Gehen (Doku-Gefuehl)

Sicherheitszone
---------------
``SAFE_ZONE`` beschreibt die TikTok-UI-Bereiche in Pixeln. ``frame_distance()``
und ``project_to_screen()`` rechnen ohne Blender, damit die Filmvalidierung
pruefen kann, ob Koepfe und Schilder im sicheren Bereich liegen.
"""
from __future__ import annotations

import importlib
import math
import random
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

try:
    import bpy  # type: ignore
    from mathutils import Vector, Euler  # type: ignore
    HAS_BPY = True
except ImportError:  # pragma: no cover
    bpy = None  # type: ignore
    Vector = Euler = None  # type: ignore
    HAS_BPY = False

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: Erlaubte Bewegungen (Validierung schlaegt bei allem anderen fehl)
CAMERA_MOVES = (
    "slow_push_in", "pull_out", "crane_reveal", "orbit_arc", "tracking_follow",
    "over_shoulder", "rack_focus", "dolly_left", "dolly_right", "tilt_up_reveal",
    "spline_drift", "handheld_walk",
)

#: Verbotene Werte - eine statische Kamera ist im System nicht erlaubt
FORBIDDEN_MOVES = ("static", "still", "fixed", "none")

#: TikTok-Sicherheitszonen in Pixeln bei 1080x1920
SAFE_ZONE = {
    "right_ui_px": 190,     # Like-/Kommentar-/Share-Spalte rechts
    "bottom_ui_px": 340,    # Caption + Musikzeile unten
    "top_ui_px": 110,       # Statusleiste/For You
    "left_margin_px": 54,
    "safe_left": 54, "safe_right": 1080 - 190,
    "safe_top": 110, "safe_bottom": 1920 - 340,
}

FPS = 24
SENSOR_HEIGHT_MM = 36.0


def require_bpy() -> None:
    if not HAS_BPY:
        raise RuntimeError("Kamera-Aufbau braucht Blender (bpy).")


# --------------------------------------------------------------------------- #
# Reine Geometrie (auch fuer Validierung ohne Blender)
# --------------------------------------------------------------------------- #
def vertical_fov_deg(focal_mm: float, sensor_height_mm: float = SENSOR_HEIGHT_MM) -> float:
    return math.degrees(2 * math.atan(sensor_height_mm / (2 * max(1.0, float(focal_mm)))))


def frame_distance(subject_height: float, focal_mm: float, fill: float = 0.82) -> float:
    """Kameraabstand, damit eine Figur ``fill`` der Bildhoehe einnimmt.

    ``fill = 0.8`` heisst: die Figur fuellt 80 % der Bildhoehe, es bleibt Luft
    oben und unten. ``fill = 1.0`` = formatfuellend, ``fill > 1`` = Beschnitt.
    """
    fov = math.radians(vertical_fov_deg(focal_mm))
    fill = max(0.15, min(2.0, float(fill)))
    half_frame = max(0.05, (subject_height / fill) / 2.0)
    return half_frame / math.tan(fov / 2)


def look_at_euler(position, target) -> tuple[float, float, float]:
    """Euler-Winkel (XYZ, Radiant) fuer eine Kamera, die ``target`` anschaut."""
    dx, dy, dz = (target[0] - position[0], target[1] - position[1], target[2] - position[2])
    yaw = math.atan2(dy, dx) + math.pi / 2
    horizontal = math.hypot(dx, dy)
    pitch = math.atan2(dz, horizontal) + math.pi / 2
    return (pitch, 0.0, yaw)


def project_to_screen(camera_position, target, point, focal_mm: float = 40.0,
                      resolution: tuple[int, int] = (1080, 1920)) -> tuple[float, float]:
    """Projiziert einen Weltpunkt in Bildpixel (Pinhole mit vertikalem Sensor).

    Die Kamera schaut von ``camera_position`` auf ``target``; die Bildhoehe
    entspricht einem 36-mm-Sensor (``sensor_fit = VERTICAL``). Punkte hinter der
    Kamera werden auf den Bildrand geklemmt, damit Aufrufer immer Zahlen bekommen.
    """
    width, height = resolution
    fx = float(target[0]) - float(camera_position[0])
    fy = float(target[1]) - float(camera_position[1])
    fz = float(target[2]) - float(camera_position[2])
    norm = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
    fx, fy, fz = fx / norm, fy / norm, fz / norm
    # right = forward x up(0,0,1)
    rx, ry, rz = fy * 1.0 - fz * 0.0, fz * 0.0 - fx * 1.0, 0.0
    rnorm = math.sqrt(rx * rx + ry * ry) or 1.0
    rx, ry = rx / rnorm, ry / rnorm
    # up_cam = right x forward
    ux = ry * fz - 0.0 * fy
    uy = 0.0 * fx - rx * fz
    uz = rx * fy - ry * fx
    dx = float(point[0]) - float(camera_position[0])
    dy = float(point[1]) - float(camera_position[1])
    dz = float(point[2]) - float(camera_position[2])
    depth = dx * fx + dy * fy + dz * fz
    tan_v = math.tan(math.radians(vertical_fov_deg(focal_mm)) / 2)
    tan_h = tan_v * (width / height) if height else tan_v
    if depth <= 0.05:
        return (width / 2, height / 2)
    x_ndc = ((dx * rx + dy * ry) / depth) / tan_h
    y_ndc = ((dx * ux + dy * uy + dz * uz) / depth) / tan_v
    x = width / 2 * (1.0 + max(-4.0, min(4.0, x_ndc)))
    y = height / 2 * (1.0 - max(-4.0, min(4.0, y_ndc)))
    return (x, y)


def inside_safe_zone(x: float, y: float, margin: float = 0.0) -> bool:
    return (SAFE_ZONE["safe_left"] + margin <= x <= SAFE_ZONE["safe_right"] - margin
            and SAFE_ZONE["safe_top"] + margin <= y <= SAFE_ZONE["safe_bottom"] - margin)


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _breathing(frame: int, seed: float = 0.0, amplitude: float = 1.0) -> tuple[float, float, float, float, float, float]:
    """Deterministisches Mikro-Wackeln (Position + Rotation) fuer echte Kamera-Haptik."""
    t = frame / FPS
    ax = 0.010 * amplitude * math.sin(t * 1.37 + seed)
    ay = 0.008 * amplitude * math.sin(t * 1.11 + seed * 1.9 + 0.7)
    az = 0.006 * amplitude * math.sin(t * 0.93 + seed * 2.7 + 1.3)
    rx = 0.10 * amplitude * math.sin(t * 1.61 + seed * 3.1)
    ry = 0.07 * amplitude * math.sin(t * 1.19 + seed * 1.3)
    rz = 0.09 * amplitude * math.sin(t * 1.43 + seed * 2.3 + 0.5)
    return ax, ay, az, rx, ry, rz


# --------------------------------------------------------------------------- #
# Kamera-Rig
# --------------------------------------------------------------------------- #
class CameraRig:
    """Baut und animiert die Kamera fuer einen Shot."""

    def __init__(self, scene, resolution=(1080, 1920), fps: int = FPS,
                 subject_height: float = 6.7):
        require_bpy()
        self.scene = scene
        self.resolution = resolution
        self.fps = fps
        self.subject_height = subject_height
        camera_data = bpy.data.cameras.new("Kamera")
        camera_data.sensor_fit = "VERTICAL"
        camera_data.sensor_height = SENSOR_HEIGHT_MM
        camera_data.sensor_width = 36.0
        camera_data.clip_start = 0.05
        camera_data.clip_end = 400.0
        self.camera = bpy.data.objects.new("Kamera", camera_data)
        scene.collection.objects.link(self.camera)
        scene.camera = self.camera
        scene.render.resolution_x, scene.render.resolution_y = resolution
        scene.render.resolution_percentage = 100
        scene.render.fps = fps

    # -- Zielpunkte ------------------------------------------------------ #
    def resolve_target(self, spec: dict, subjects: dict) -> tuple[float, float, float]:
        target = spec.get("target", "center")
        if isinstance(target, (list, tuple)) and len(target) >= 3:
            return (float(target[0]), float(target[1]), float(target[2]))
        if target in subjects:
            return _subject_aim_point(subjects[target], spec.get("target_part", "chest"))
        return (0.0, 0.0, self.subject_height * 0.55)

    def build(self, spec: dict, frames: int, subjects: dict,
              subject_positions: Optional[Callable[[int], tuple]] = None) -> dict:
        """Animiert die Kamera ueber ``frames`` Frames entsprechend der Shot-Spec."""
        require_bpy()
        move = str(spec.get("move", "slow_push_in"))
        if move in FORBIDDEN_MOVES:
            raise ValueError("Statische Kamera ist nicht erlaubt - bitte eine Bewegung waehlen")
        if move not in CAMERA_MOVES:
            raise ValueError(f"Unbekannte Kamerabewegung '{move}'. Erlaubt: {', '.join(CAMERA_MOVES)}")
        focal = float(spec.get("focal", 40.0))
        fill = float(spec.get("fill", 0.8))
        target = self.resolve_target(spec, subjects)
        distance = float(spec.get("distance") or frame_distance(self.subject_height, focal, fill))
        height = float(spec.get("height", target[2] + 0.35))
        azimuth = float(spec.get("azimuth", 0.0))
        seed = float(spec.get("seed", 0.0))
        breath = float(spec.get("breathing", 1.0))
        fstop = float(spec.get("fstop", 2.8))
        shift_y = float(spec.get("shift_y", 0.0))
        camera = self.camera
        camera.data.lens = focal
        camera.data.shift_y = shift_y
        camera.data.dof.use_dof = True
        camera.data.dof.aperture_fstop = max(0.7, fstop)

        def base_position(frame_index: int) -> tuple[float, float, float]:
            t = frame_index / max(1, frames - 1)
            eased = _smoothstep(t)
            centre = target
            if subject_positions is not None and move in ("tracking_follow", "over_shoulder",
                                                          "handheld_walk"):
                try:
                    centre = subject_positions(frame_index)
                except (KeyError, TypeError, IndexError):
                    centre = target
            if move == "slow_push_in":
                d = distance * (1.08 - 0.28 * eased)
                h = height
                a = azimuth + 4.0 * eased
            elif move == "pull_out":
                d = distance * (0.82 + 0.55 * eased)
                h = height + 0.5 * eased
                a = azimuth - 6.0 * eased
            elif move == "crane_reveal":
                d = distance * (1.02 - 0.12 * eased)
                h = height - self.subject_height * 0.32 + self.subject_height * 0.62 * eased
                a = azimuth + 12.0 * eased
            elif move == "orbit_arc":
                arc = float(spec.get("arc_degrees", 28.0))
                d = distance
                h = height + 0.12 * math.sin(eased * math.pi)
                a = azimuth - arc / 2 + arc * eased
            elif move == "tracking_follow":
                d = distance * (1.0 + 0.06 * eased)
                h = height
                a = azimuth + 8.0 * eased
                centre = (centre[0], centre[1], centre[2])
            elif move == "over_shoulder":
                d = distance * 0.72
                h = height + 0.15
                a = azimuth + 18.0 + 8.0 * eased
            elif move == "rack_focus":
                d = distance * (1.0 - 0.10 * eased)
                h = height
                a = azimuth + 3.0 * eased
            elif move == "dolly_left":
                d = distance
                h = height - 0.1 * eased
                a = azimuth - 16.0 * eased
            elif move == "dolly_right":
                d = distance
                h = height + 0.1 * eased
                a = azimuth + 16.0 * eased
            elif move == "tilt_up_reveal":
                d = distance * (1.0 + 0.06 * eased)
                h = height - self.subject_height * 0.45 + self.subject_height * 0.5 * eased
                a = azimuth + 5.0 * eased
            elif move == "spline_drift":
                d = distance * (1.0 + 0.10 * math.sin(eased * math.pi))
                h = height + 0.35 * math.sin(eased * math.pi * 1.2)
                a = azimuth + 22.0 * eased
            else:  # handheld_walk
                d = distance * (1.0 + 0.04 * math.sin(eased * math.pi * 2))
                h = height + 0.05 * math.sin(eased * math.pi * 3)
                a = azimuth + 6.0 * eased
            angle = math.radians(a)
            x = centre[0] + math.cos(angle) * d
            y = centre[1] + math.sin(angle) * d
            z = max(0.25, h)
            return (x, y, z)

        def focus_target_for(frame_index: int) -> float:
            if move == "rack_focus":
                near = float(spec.get("focus_near", distance * 0.5))
                far = float(spec.get("focus_far", distance * 1.8))
                t = _smoothstep(frame_index / max(1, frames - 1))
                return near + (far - near) * t
            return max(0.5, math.dist(base_position(frame_index), target))

        positions: list[tuple[float, float, float]] = []
        for frame_index in range(frames):
            px, py, pz = base_position(frame_index)
            if move == "handheld_walk":
                walk = 0.05 * math.sin(frame_index * 0.55) + 0.03 * math.sin(frame_index * 1.7 + 1.1)
                pz += walk
            bx, by, bz, rx, ry, rz = _breathing(frame_index, seed, breath)
            positions.append((px + bx, py + by, pz + bz))

        key_step = 1 if move in ("tracking_follow", "handheld_walk", "rack_focus") else 2
        focus_points = []
        for frame_index in range(0, frames, key_step):
            position = positions[frame_index]
            # Ziel leicht ueber der Bildmitte halten: Gesicht im oberen Drittel
            aim = (target[0], target[1], target[2] + 0.12)
            euler = look_at_euler(position, aim)
            _, _, _, rx, ry, rz = _breathing(frame_index, seed, breath)
            camera.location = position
            camera.rotation_mode = "XYZ"
            camera.rotation_euler = (euler[0] + math.radians(rx),
                                     euler[1] + math.radians(ry),
                                     euler[2] + math.radians(rz))
            camera.keyframe_insert("location", frame=frame_index + 1)
            camera.keyframe_insert("rotation_euler", frame=frame_index + 1)
            focus = focus_target_for(frame_index)
            camera.data.dof.focus_distance = focus
            camera.data.dof.keyframe_insert("focus_distance", frame=frame_index + 1)
            focus_points.append(focus)
        if frames > 1:
            for fcurve in camera.animation_data.action.fcurves:
                for keyframe in fcurve.keyframe_points:
                    keyframe.interpolation = "BEZIER"
                    keyframe.easing = "EASE_IN_OUT"
        return {
            "camera": camera, "move": move, "frames": frames, "focal": focal,
            "target": target, "distance": distance, "positions": positions,
            "focus_distance": focus_points[-1] if focus_points else distance,
            "total_travel": sum(math.dist(positions[i], positions[i - 1])
                                for i in range(1, len(positions))),
        }


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #
def _subject_aim_point(character: dict, part: str = "chest") -> tuple[float, float, float]:
    """Weltpunkt einer Figur (Kopf/Brust/Fuesse) ohne Blender-Abhaengigkeit."""
    meta = character.get("meta", {}) if isinstance(character, dict) else {}
    location = character.get("_location") or meta.get("base_location") or (0.0, 0.0, 0.0)
    scale = float(character.get("scale", 1.0) or 1.0)
    heights = {"feet": 0.2, "chest": 4.6, "head": 6.1, "eyes": 6.15, "hand": 2.6}
    z = heights.get(part, 4.6) * scale
    return (float(location[0]), float(location[1]), float(location[2]) + z)


def register_subject(character: dict, location, scale: Optional[float] = None) -> dict:
    """Aktualisiert die Weltposition einer Figur fuer die Kamera."""
    character["_location"] = tuple(float(v) for v in location)
    if scale is not None:
        character["scale"] = float(scale)
    return character


def camera_report(rig_result: dict) -> dict:
    """Kurzbericht fuer Logs: Bewegung, Brennweite, zurueckgelegter Weg."""
    return {
        "move": rig_result["move"],
        "focal_mm": rig_result["focal"],
        "frames": rig_result["frames"],
        "travel_studs": round(rig_result["total_travel"], 3),
        "static": rig_result["total_travel"] < 0.02,
    }


def suggest_distance(subject_height: float = 6.7, focal: float = 40.0) -> float:
    """Bequemer Standardabstand fuer eine Einzelportrait-Einstellung."""
    return round(frame_distance(subject_height, focal, 0.82), 2)


if __name__ == "__main__":  # pragma: no cover
    print("Bewegungen:", ", ".join(CAMERA_MOVES))
    print("vFOV bei 40 mm:", round(vertical_fov_deg(40), 2), "Grad")
    print("Abstand fuer 6,7 Studs bei 40 mm:", suggest_distance())
    print("Projektion Kopf:", [round(v) for v in project_to_screen((0, -12, 4), (0, 0, 3), (0, 0, 6.1))])

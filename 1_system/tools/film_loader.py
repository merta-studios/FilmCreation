"""Laedt alle Dateien eines Films aus ``2_aktueller_film/`` in pruefbare Objekte.

Der Loader ist bewusst ohne Blender und ohne Netzwerk nutzbar. Darauf bauen
``validate_film.py``, ``generate_timeline.py``, ``prepare_bundle.py`` und der
Kaggle-Worker auf - so pruefen alle denselben Vertrag.

Vertrag der Filmdateien (Kurzfassung, ausfuehrlich in ``3_regeln/02_BAUKASTEN_HANDBUCH.md``)
-------------------------------------------------------------------------------------------
film_config.yaml
    titel, slug, format{width,height,fps}, qualitaet, subtitles, musik, sfx, safe_zone
script_and_voices.yaml
    segments: [{id, speaker, text, pause_after, emotion}]
characters.py       CHARACTERS = [ ... ]
map_and_props.py    OBJECTS = [ ... ], optional OPTIONAL_MAP_BUILD = "funktion"
custom_models.py    MODELS = {"name": funktion(api, pos, rotation)}
custom_animations.py def register(lib): ...
shots.py            SHOTS = [ {id, segment_id, title, camera, lighting, characters, sfx, triggers} ]
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FILM_DIR_DEFAULT = REPO_ROOT / "2_aktueller_film"
RULES_DIR = REPO_ROOT / "3_regeln"
VOICES_FILE = RULES_DIR / "empfohlene_elevenlabs_stimmen.yaml"
EMOTES_FILE = RULES_DIR / "empfohlene_emotes_und_animationen.yaml"
AVATAR_FILE = RULES_DIR / "empfohlene_avatar_artikel.yaml"
MAP_ASSETS_FILE = RULES_DIR / "empfohlene_map_assets_und_texturen.yaml"

REQUIRED_FILES = (
    "film_config.yaml",
    "script_and_voices.yaml",
    "characters.py",
    "map_and_props.py",
    "shots.py",
)
OPTIONAL_FILES = ("custom_models.py", "custom_animations.py")

REQUIRED_FORMAT = {"width": 1080, "height": 1920, "fps": 24}


class FilmLoadError(ValueError):
    """Sammelfehler mit klarer Liste, damit der Agent alles auf einmal beheben kann."""


@dataclass
class Film:
    """Geladener, noch nicht inhaltlich gepruefter Film."""

    directory: Path
    config: dict
    script: dict
    voices: dict
    characters: list[dict]
    objects: list[dict]
    shots: list[dict]
    models: dict[str, Any] = field(default_factory=dict)
    animations: Any = None
    modules: dict[str, ModuleType] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # -- Bequeme Ableitungen --------------------------------------------- #
    @property
    def title(self) -> str:
        return str(self.config.get("titel") or self.config.get("title") or "Ohne Titel")

    @property
    def slug(self) -> str:
        raw = str(self.config.get("slug") or "film")
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in raw.lower())
        return safe.strip("-") or "film"

    @property
    def subtitles(self) -> Optional[bool]:
        value = self.config.get("subtitles")
        return value if isinstance(value, bool) else None

    @property
    def fps(self) -> int:
        return int((self.config.get("format") or {}).get("fps", 24))

    @property
    def width(self) -> int:
        return int((self.config.get("format") or {}).get("width", 1080))

    @property
    def height(self) -> int:
        return int((self.config.get("format") or {}).get("height", 1920))

    def segments(self) -> list[dict]:
        return list(self.script.get("segments") or [])

    def speaker_entries(self) -> dict[str, dict]:
        entries: dict[str, dict] = {}
        main = self.voices.get("haupt_erzaehler") or {}
        if isinstance(main, dict):
            entries["haupt_erzaehler"] = main
        for key, value in (self.voices.get("nebenstimmen") or {}).items():
            if isinstance(value, dict):
                entries[str(key)] = value
        return entries

    def voice_for(self, speaker: str) -> dict:
        entries = self.speaker_entries()
        if speaker in entries:
            return entries[speaker]
        # Erzaehler ist Standard, wenn nur ein Sprecher konfiguriert ist.
        if "haupt_erzaehler" in entries:
            return entries["haupt_erzaehler"]
        raise FilmLoadError(f"Sprecher '{speaker}' hat keine Stimme in {VOICES_FILE.name}")

    def character_by_id(self, character_id: str) -> Optional[dict]:
        for character in self.characters:
            if str(character.get("id")) == str(character_id):
                return character
        return None

    def speech_text(self) -> str:
        return " ".join(str(s.get("text", "")).strip() for s in self.segments())

    def speech_characters(self) -> int:
        return sum(len(str(s.get("text", "")).strip()) for s in self.segments())


# --------------------------------------------------------------------------- #
# YAML / Python laden
# --------------------------------------------------------------------------- #
def read_yaml(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise FilmLoadError(f"Datei fehlt: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FilmLoadError(f"{path.name}: YAML ist fehlerhaft - {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise FilmLoadError(f"{path.name}: oberste YAML-Ebene muss ein Mapping sein")
    return data


def exec_python_file(path: Path, extra_globals: Optional[dict] = None) -> ModuleType:
    """Fuehrt eine Film-Python-Datei als Modul aus (ohne bpy, ohne Seiteneffekte)."""
    path = Path(path)
    if not path.is_file():
        raise FilmLoadError(f"Datei fehlt: {path}")
    name = f"film_module_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FilmLoadError(f"{path.name} kann nicht geladen werden")
    module = importlib.util.module_from_spec(spec)
    if extra_globals:
        for key, value in extra_globals.items():
            setattr(module, key, value)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except SyntaxError as exc:
        raise FilmLoadError(f"{path.name}: Syntaxfehler in Zeile {exc.lineno}: {exc.msg}") from exc
    except Exception as exc:  # noqa: BLE001 - Fehler soll mit Dateiname ankommen
        raise FilmLoadError(f"{path.name}: Fehler beim Ausfuehren - {type(exc).__name__}: {exc}") from exc
    finally:
        if previous is not None:
            sys.modules[name] = previous
    return module


def literal_assignment(path: Path, name: str) -> Any:
    """Liest eine Zuweisung wie ``SHOTS = [...]`` ohne die Datei auszufuehren."""
    path = Path(path)
    if not path.is_file():
        raise FilmLoadError(f"Datei fehlt: {path}")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise FilmLoadError(f"{path.name}: Syntaxfehler in Zeile {exc.lineno}: {exc.msg}") from exc
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError as exc:
                        raise FilmLoadError(
                            f"{path.name}: '{name}' muss ein reines Python-Literal sein "
                            f"(keine Funktionsaufrufe) - {exc}") from exc
    raise FilmLoadError(f"{path.name}: Zuweisung '{name}' nicht gefunden")


# --------------------------------------------------------------------------- #
# Film laden
# --------------------------------------------------------------------------- #
def load_film(film_dir: Path = FILM_DIR_DEFAULT, *, require_files: bool = True) -> Film:
    """Laedt alle Filmdaten; sammelt Fehler in einer verstaendlichen Meldung."""
    film_dir = Path(film_dir)
    if not film_dir.is_dir():
        raise FilmLoadError(f"Filmordner fehlt: {film_dir}")
    missing = [name for name in REQUIRED_FILES if not (film_dir / name).is_file()]
    if missing and require_files:
        raise FilmLoadError("Es fehlen Pflichtdateien in 2_aktueller_film/: " + ", ".join(missing))

    config = read_yaml(film_dir / "film_config.yaml")
    script = read_yaml(film_dir / "script_and_voices.yaml")

    characters_mod = exec_python_file(film_dir / "characters.py")
    characters = list(getattr(characters_mod, "CHARACTERS", []) or [])

    map_mod = exec_python_file(film_dir / "map_and_props.py")
    objects = list(getattr(map_mod, "OBJECTS", []) or [])

    shots_mod = exec_python_file(film_dir / "shots.py")
    shots = list(getattr(shots_mod, "SHOTS", []) or [])

    models: dict[str, Any] = {}
    modules = {
        "characters": characters_mod, "map_and_props": map_mod, "shots": shots_mod,
    }
    if (film_dir / "custom_models.py").is_file():
        models_mod = exec_python_file(film_dir / "custom_models.py")
        models = dict(getattr(models_mod, "MODELS", {}) or {})
        modules["custom_models"] = models_mod

    animations = None
    if (film_dir / "custom_animations.py").is_file():
        from importlib import import_module

        anim_mod = import_module("1_system.blender_engine.custom_animations")
        library = anim_mod.AnimationLibrary()
        film_anim_mod = exec_python_file(film_dir / "custom_animations.py",
                                         {"AnimationBuilder": anim_mod.AnimationBuilder})
        register = getattr(film_anim_mod, "register", None)
        if callable(register):
            try:
                register(library)
            except Exception as exc:  # noqa: BLE001
                raise FilmLoadError(
                    f"custom_animations.py: register() ist abgestuerzt - "
                    f"{type(exc).__name__}: {exc}") from exc
        animations = library
        modules["custom_animations"] = film_anim_mod

    voices = read_yaml(VOICES_FILE) if Path(VOICES_FILE).is_file() else {}
    return Film(
        directory=film_dir,
        config=config,
        script=script,
        voices=voices,
        characters=characters,
        objects=objects,
        shots=shots,
        models=models,
        animations=animations,
        modules=modules,
    )


def load_rules() -> dict:
    """Laedt die Empfehlungsdateien aus ``3_regeln/`` (fehlende Dateien = leer)."""
    rules = {}
    for key, path in (("voices", VOICES_FILE), ("emotes", EMOTES_FILE),
                      ("avatar", AVATAR_FILE), ("map_assets", MAP_ASSETS_FILE)):
        rules[key] = read_yaml(path) if Path(path).is_file() else {}
    return rules


def read_notes() -> list[tuple[str, str]]:
    """Liest alle Dateien aus ``3_regeln/eigene_notizen/`` (Notizen des Betreibers)."""
    notes: list[tuple[str, str]] = []
    folder = RULES_DIR / "eigene_notizen"
    if not folder.is_dir():
        return notes
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".yaml", ".yml"}:
            notes.append((str(path.relative_to(RULES_DIR)), path.read_text(encoding="utf-8")))
    return notes

"""Schriften besorgen: freie Google-/OFL-Fonts automatisch laden und cachen.

Warum ein eigener Font-Loader?
------------------------------
Roblox-Schilder, Kreidetafeln, Strassenschilder und TikTok-Untertitel wirken nur
dann echt, wenn die Schrift passt. Blender bringt nur eine Standardschrift mit.
Dieser Loader holt deshalb freie Schriften (OFL/Apache) direkt aus dem
offiziellen Google-Fonts-Repository, prueft die Lizenzdatei und legt sie in
``assets_cache/fonts`` ab. Danach sind sie offline verfuegbar:

* ``resolve("bebas")`` -> lokaler Pfad zur .ttf (oder ``None``, wenn offline)
* ``resolve("/pfad/eigene.ttf")`` -> eigener Font, unveraendert zurueck
* ``ensure(["bebas", "caveat"])`` -> mehrere Fonts in einem Rutsch
* ``list_local()`` -> was schon im Cache liegt

Die Funktionen sind absichtlich fehlertolerant: Ohne Internet (z. B. im
Blender-Render ohne Netz) faellt das System auf Blenders Standardschrift bzw.
DejaVu zurueck, statt abzubrechen.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(os.environ.get("FONT_CACHE_DIR", "assets_cache/fonts"))
MANIFEST = CACHE_DIR / "fonts_manifest.json"
API_ROOT = "https://api.github.com/repos/google-fonts/google-fonts/contents"
RAW_ROOT = "https://github.com/google-fonts/google-fonts/raw/main"
USER_AGENT = "FilmCreation-FontLoader/1.0 (+https://github.com/merta-studios/FilmCreation)"

#: Stilname -> (Familie, Ordner im Google-Fonts-Repo, Beschreibung)
FONT_FAMILIES: dict[str, tuple[str, str, str]] = {
    "bebas": ("Bebas Neue", "ofl/bebasneue", "Plakat/Hook-Schrift, sehr schmal"),
    "anton": ("Anton", "ofl/anton", "fette Headline fuer Schilder"),
    "oswald": ("Oswald", "ofl/oswald", "Strassenschild/Kondensiert"),
    "inter": ("Inter", "ofl/inter", "neutraler Sans fuer Untertitel"),
    "poppins": ("Poppins", "ofl/poppins", "freundlicher Sans"),
    "roboto": ("Roboto", "apache/roboto", "Standard-Sans fuer UI-Texte"),
    "lora": ("Lora", "ofl/lora", "ruhige Serif fuer erzaehlende Schilder"),
    "playfair": ("Playfair Display", "ofl/playfairdisplay", "elegante Serif"),
    "abril": ("Abril Fatface", "ofl/abrilfatface", "plakative Display-Serif"),
    "caveat": ("Caveat", "ofl/caveat", "Handschrift fuer Notizen"),
    "patrick": ("Patrick Hand", "ofl/patrickhand", "comichafte Handschrift"),
    "shadows": ("Shadows Into Light", "ofl/shadowsintolight", "zarte Handschrift"),
    "marker": ("Permanent Marker", "ofl/permanentmarker", "Filzstift/Ladenfront"),
    "typewriter": ("Courier Prime", "ofl/courierprime", "Schreibmaschine/Brief"),
    "spacemono": ("Space Mono", "ofl/spacemono", "Monospace fuer Digital-Zaehler"),
    "luckiest": ("Luckiest Guy", "ofl/luckiestguy", "verspielte Roblox-Schrift"),
    "chalk": ("Gloria Hallelujah", "ofl/gloriahallelujah", "Kreide auf Schultafel"),
    "bangers": ("Bangers", "ofl/bangers", "Comic-Sound-Effekt"),
}

#: Standard-Set, das sich das System bei Bedarf zieht
DEFAULT_SET = ("inter", "bebas", "caveat", "spacemono")


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _request_json(url: str, timeout: int = 30):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (festes Host-Ziel)
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, target: Path, timeout: int = 60) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        target.write_bytes(response.read())
    if target.stat().st_size < 2000:
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Download zu klein: {url}")
    return target


def _pick_ttf(files: list[dict]) -> Optional[str]:
    candidates = [f for f in files
                  if isinstance(f.get("name"), str) and f["name"].lower().endswith((".ttf", ".otf"))]
    if not candidates:
        return None

    def score(entry: dict) -> tuple[int, int, int]:
        name = entry["name"].lower()
        penalty = 0
        if "italic" in name or "oblique" in name:
            penalty += 100
        if "thin" in name or "extralight" in name or "light" in name:
            penalty += 20
        if "black" in name:
            penalty += 5
        bold_bonus = -10 if ("bold" in name or "semibold" in name) else 0
        variable = 5 if "[" in name else 0
        return (penalty + variable, bold_bonus, len(name))

    return sorted(candidates, key=score)[0]["name"]


def fetch_font(family_key: str, force: bool = False) -> Optional[Path]:
    """Laedt eine Schrift (falls noetig) und gibt den lokalen Pfad zurueck."""
    if family_key not in FONT_FAMILIES:
        return None
    family, folder, _description = FONT_FAMILIES[family_key]
    target = CACHE_DIR / f"{_slug(family)}.ttf"
    if target.is_file() and not force and target.stat().st_size > 2000:
        return target
    try:
        files = _request_json(f"{API_ROOT}/{folder}")
        chosen = _pick_ttf(files)
        if not chosen:
            return None
        url = f"{RAW_ROOT}/{folder}/{chosen}".replace(" ", "%20")
        _download(url, target)
        # Lizenz mitnehmen (OFL.txt / LICENSE.txt), damit die Herkunft dokumentiert ist
        for entry in files:
            if str(entry.get("name", "")).upper().startswith(("OFL", "LICENSE")):
                try:
                    _download(f"{RAW_ROOT}/{folder}/{entry['name']}",
                              CACHE_DIR / f"{_slug(family)}_{entry['name']}")
                except (urllib.error.URLError, RuntimeError):
                    pass
                break
        _update_manifest(family, folder, target.name, chosen)
        return target
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError, KeyError):
        return None


def _update_manifest(family: str, folder: str, filename: str, original: str) -> None:
    data = {}
    if MANIFEST.is_file():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data[family] = {"folder": folder, "file": filename, "original": original,
                    "source": f"{RAW_ROOT}/{folder}/{original}"}
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve(name_or_path: Optional[str], allow_download: bool = True) -> Optional[Path]:
    """Loest Stilnamen (``"bebas"``, ``"Bebas Neue"``) oder Pfade zu einer Font-Datei auf."""
    if not name_or_path:
        return None
    raw = str(name_or_path).strip()
    candidate = Path(raw)
    if candidate.suffix.lower() in (".ttf", ".otf") and candidate.is_file():
        return candidate
    key = _slug(raw.replace(" ", ""))
    alias = {
        "bebasneue": "bebas", "inter_": "inter", "playfairdisplay": "playfair",
        "courierprime": "typewriter", "space_mono": "spacemono",
        "permanentmarker": "marker", "luckiestguy": "luckiest",
        "gloriahallelujah": "chalk", "shadowsintolight": "shadows",
        "patrickhand": "patrick", "abrilfatface": "abril",
    }
    key = alias.get(key, key)
    if key in FONT_FAMILIES:
        cached = CACHE_DIR / f"{_slug(FONT_FAMILIES[key][0])}.ttf"
        if cached.is_file():
            return cached
        return fetch_font(key) if allow_download else None
    # Fallback: Datei im Cache mit aehnlichem Namen suchen
    if CACHE_DIR.is_dir():
        for path in CACHE_DIR.glob("*.ttf"):
            if key and key in _slug(path.stem):
                return path
    return None


def ensure(families: Optional[list[str]] = None) -> dict[str, Optional[str]]:
    """Stellt sicher, dass die genannten (oder Standard-)Schriften lokal sind."""
    result: dict[str, Optional[str]] = {}
    for key in families or list(DEFAULT_SET):
        path = resolve(key)
        result[key] = str(path) if path else None
    return result


def list_local() -> dict[str, dict]:
    if not MANIFEST.is_file():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def font_family_for_ass(style: str = "inter") -> str:
    """Familienname fuer libass (Untertitel) - mit DejaVu-Fallback."""
    path = resolve(style, allow_download=False)
    if path:
        return path.stem.split("[")[0].replace("_", " ")
    return "DejaVu Sans"


def fonts_dir() -> Path:
    """Ordner fuer ``ffmpeg -vf ass=...:fontsdir=...``."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Freie Schriften cachen")
    parser.add_argument("families", nargs="*", default=None,
                        help=f"Stilnamen, z. B. {', '.join(FONT_FAMILIES)}")
    parser.add_argument("--list", action="store_true", help="nur Cache anzeigen")
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(list_local(), ensure_ascii=False, indent=2))
        return 0
    result = ensure(args.families or list(DEFAULT_SET))
    for key, path in result.items():
        print(f"{key:12s} -> {path or 'NICHT VERFUEGBAR (offline?)'}")
    return 0 if all(result.values()) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

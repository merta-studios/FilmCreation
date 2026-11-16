"""Roblox Open Cloud: Katalog-Suche, Asset-Download, 3D-Thumbnails, Cache, Rechte-Filter.

Was die Roblox-APIs wirklich hergeben (Stand der offiziellen Doku)
------------------------------------------------------------------
* **Creator Store / Toolbox:** ``GET https://apis.roblox.com/toolbox-service/v2/assets``
  mit ``search``, ``maxPageSize``, ``pageToken``. Braucht einen Open-Cloud-Key.
  Liefert Metadaten (ID, Name, Creator, Asset-Typ), **nicht** die Modelldatei.
* **Asset-Metadaten:** ``GET https://apis.roblox.com/assets/v1/assets/{assetId}``
  (Scope ``asset:read``).
* **Asset-Inhalt:** ``GET https://apis.roblox.com/asset-delivery-api/v1/assetId/{assetId}``
  (Scope ``legacy-asset:manage``) - liefert entweder direkt die Datei oder ein JSON
  mit ``location`` (CDN-URL), die dann geladen wird.
* **2D-Vorschau:** ``GET https://thumbnails.roblox.com/v1/assets?assetIds=...``
  (oeffentlich, kein Key noetig).
* **3D-Vorschau:** ``GET https://thumbnails.roblox.com/v1/assets-thumbnail-3d?assetId=...``
  liefert eine OBJ-Datei - praktisch, wenn ein Mesh nicht direkt ladbar ist.

Sicherheit
----------
* Der API-Key wird nie geloggt und nie in Fehlermeldungen geschrieben.
* Rate-Limiting mit Backoff (429/``Retry-After``), harte Obergrenze pro Minute.
* Ergebnisse werden gecacht (Metadaten + Dateien), damit ein zweiter Lauf keine
  einzige Anfrage braucht.
* **Rechte- und Markenfilter:** Fremde UGC-Artikel, Markenlogos und nicht-freie
  Modelle werden aussortiert (``license_safe``). Offizielle Roblox-Artikel
  (``CreatorTargetId=1``) sind erlaubt, fremde Marken nicht.

Beispiel
--------
    client = RobloxClient()
    hits = client.search_creator_store("street lamp", limit=8)
    client.download_asset(hits[0]["id"], Path("assets/street_lamp.rbxm"))
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

ROBLOX_API = "https://apis.roblox.com"
THUMBNAIL_API = "https://thumbnails.roblox.com"
ASSET_DELIVERY = f"{ROBLOX_API}/asset-delivery-api/v1/assetId"
ASSETS_API = f"{ROBLOX_API}/assets/v1/assets"
TOOLBOX_SEARCH = f"{ROBLOX_API}/toolbox-service/v2/assets:search"
CACHE_DIR_DEFAULT = Path("assets_cache/roblox")

#: Marken und Franchises, die aus rechtlichen Gruenden nie eingebaut werden
BLOCKED_BRANDS = (
    "nike", "adidas", "gucci", "puma", "louis vuitton", "supreme", "balenciaga",
    "disney", "mickey", "marvel", "spider-man", "spiderman", "batman", "pokemon",
    "pikachu", "minecraft", "among us", "squid game", "fortnite", "naruto",
    "dragon ball", "one piece", "hello kitty", "sanrio", "barbie", "harry potter",
    "star wars", "ferrari", "lamborghini", "bmw", "mercedes", "coca-cola", "pepsi",
    "mcdonald", "netflix", "tiktok", "instagram", "youtube", "roblox admin",
)

#: Kategorien, die wir nie automatisch einbauen (Audio/Tech mit unbekannter Lizenz)
BLOCKED_CATEGORIES = ("audio", "plugin", "font?")

#: Offizieller Roblox-Creator (alle offiziellen Avatar-Artikel)
ROBLOX_CREATOR_IDS = {1}


class RobloxApiError(RuntimeError):
    """API-Fehler mit Statuscode und verstaendlichem Hinweis."""

    def __init__(self, message: str, status: int = 0, url: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url

    @property
    def hint(self) -> str:
        if self.status == 401:
            return "ROBLOX_API_KEY ist ungueltig oder abgelaufen."
        if self.status == 403:
            return ("Dem Key fehlen Rechte. Fuer Downloads braucht er "
                    "'legacy-asset:manage', fuer Metadaten 'asset:read'.")
        if self.status == 404:
            return "Asset existiert nicht (oder ist nicht fuer dich freigegeben)."
        if self.status == 429:
            return "Rate-Limit: bitte kurz warten (der Client versucht es automatisch)."
        return ""


@dataclass
class AssetInfo:
    asset_id: int
    name: str = ""
    asset_type: str = ""
    asset_type_id: int = 0
    creator: str = ""
    creator_id: int = 0
    is_free: bool = True
    price: float = 0.0
    description: str = ""
    license_safe: bool = True
    license_note: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.asset_id, "name": self.name, "asset_type": self.asset_type,
            "asset_type_id": self.asset_type_id, "creator": self.creator,
            "creator_id": self.creator_id, "is_free": self.is_free, "price": self.price,
            "license_safe": self.license_safe, "license_note": self.license_note,
        }


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return "(nicht gesetzt)"
    return value[:4] + "****" + value[-2:] if len(value) > 8 else "****"


def check_license(name: str, creator_id: int = 0, description: str = "",
                  asset_type: str = "", category: str = "") -> tuple[bool, str]:
    """Prueft Namen/Beschreibung/Creator auf Marken- und Lizenzrisiken."""
    text = f"{name} {description}".lower()
    for brand in BLOCKED_BRANDS:
        if brand in text:
            return False, f"Marken-/Franchise-Begriff '{brand}' erkannt - nicht verwenden"
    if category and any(blocked in category.lower() for blocked in BLOCKED_CATEGORIES):
        return False, f"Kategorie '{category}' wird nicht automatisch eingebaut"
    if asset_type.lower() in ("audio", "sound"):
        return False, "Audio-Assets haben oft unklare Rechte - besser prozedurale SFX"
    if creator_id and creator_id not in ROBLOX_CREATOR_IDS:
        return True, (f"Creator {creator_id} ist nicht Roblox - Free-Model nur nach "
                      "eigener Sichtpruefung verwenden")
    return True, "offizieller Roblox-Creator" if creator_id in ROBLOX_CREATOR_IDS else "kein Markenrisiko erkannt"


class RateLimiter:
    """Einfache gleitende Fenster-Begrenzung mit Mindestabstand."""

    def __init__(self, calls_per_minute: int = 120):
        self.calls_per_minute = max(1, int(calls_per_minute))
        self.timestamps: list[float] = []

    def wait(self) -> None:
        now = time.monotonic()
        self.timestamps = [t for t in self.timestamps if now - t < 60.0]
        if len(self.timestamps) >= self.calls_per_minute:
            sleep_for = 60.0 - (now - self.timestamps[0]) + 0.05
            if sleep_for > 0:
                time.sleep(min(sleep_for, 30.0))
            self.timestamps = [t for t in self.timestamps if time.monotonic() - t < 60.0]
        self.timestamps.append(time.monotonic())
        if len(self.timestamps) > 1:
            gap = 60.0 / self.calls_per_minute
            elapsed = time.monotonic() - self.timestamps[-2]
            if elapsed < gap * 0.5:
                time.sleep(gap * 0.5 - elapsed)


class RobloxClient:
    """Kleiner, robuster Client fuer die Roblox-APIs, die wir wirklich brauchen."""

    def __init__(self, api_key: Optional[str] = None, user_id: Optional[int] = None,
                 cache_dir: Path = CACHE_DIR_DEFAULT, calls_per_minute: int = 120,
                 session: Optional[requests.Session] = None, timeout: int = 45,
                 offline: bool = False):
        self.api_key = api_key if api_key is not None else os.environ.get("ROBLOX_API_KEY", "")
        raw_user = user_id if user_id is not None else os.environ.get("ROBLOX_USER_ID", "")
        try:
            self.user_id = int(raw_user) if raw_user else 0
        except (TypeError, ValueError):
            self.user_id = 0
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "FilmCreation/1.0 (+github.com/merta-studios/FilmCreation)",
            "Accept": "application/json",
        })
        self.limiter = RateLimiter(calls_per_minute)
        self.timeout = timeout
        self.offline = offline
        self.stats = {"requests": 0, "cache_hits": 0, "downloads": 0, "errors": 0}

    # -- Basis ----------------------------------------------------------- #
    def _headers(self, auth: bool = True) -> dict:
        headers = {}
        if auth and self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _request(self, method: str, url: str, *, params: Optional[dict] = None,
                 json_body: Optional[dict] = None,
                 auth: bool = True, stream: bool = False) -> requests.Response:
        if self.offline:
            raise RobloxApiError("Offline-Modus aktiv", 0, url)
        last_error: Optional[Exception] = None
        for attempt in range(4):
            self.limiter.wait()
            try:
                self.stats["requests"] += 1
                response = self.session.request(method, url, params=params,
                                                headers=self._headers(auth),
                                                timeout=self.timeout, stream=stream,
                                                json=json_body, allow_redirects=True)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after or "").replace(".", "", 1).isdigit() else 2.0 * (attempt + 1)
                time.sleep(min(wait, 20.0))
                continue
            if response.status_code in (401, 403, 404):
                self.stats["errors"] += 1
                raise RobloxApiError(
                    f"Roblox-API antwortet {response.status_code} auf {url.split('?')[0]}",
                    response.status_code, url)
            if response.status_code >= 400:
                self.stats["errors"] += 1
                raise RobloxApiError(f"Roblox-API-Fehler {response.status_code}: "
                                     f"{response.text[:200]}", response.status_code, url)
            return response
        self.stats["errors"] += 1
        raise RobloxApiError(f"Roblox-API nicht erreichbar: {last_error}")

    def _cache_path(self, key: str, suffix: str = ".json") -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        folder = self.cache_dir / ("meta" if suffix == ".json" else "files")
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{digest}{suffix}"

    def _cached_json(self, key: str, producer) -> Any:
        path = self._cache_path(key)
        if path.is_file():
            try:
                self.stats["cache_hits"] += 1
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        data = producer()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    # -- Suche ----------------------------------------------------------- #
    def search_creator_store(self, query: str, limit: int = 10,
                             category: Optional[str] = None,
                             max_price: float = 0.0,
                             page_token: str = "") -> list[dict]:
        """Sucht freie Modelle im Creator Store und filtert Rechte-Risiken."""
        if not query.strip():
            raise ValueError("Suchbegriff fehlt")
        limit = max(1, min(50, int(limit)))
        params = {"query": query.strip(), "maxPageSize": limit,
                  "searchCategoryType": category or "Model",
                  "maxPriceCents": max(0, int(max_price * 100))}
        if page_token:
            params["pageToken"] = page_token

        def fetch() -> dict:
            response = self._request("POST", TOOLBOX_SEARCH, json_body=params)
            try:
                return response.json()
            except ValueError as exc:
                raise RobloxApiError("Creator-Store-Antwort ist kein JSON") from exc

        data = self._cached_json(f"toolbox-v2:{query}:{category}:{limit}:{page_token}:{max_price}", fetch)
        results: list[dict] = []
        for item in data.get("creatorStoreAssets") or data.get("assets") or data.get("data") or []:
            asset_id = item.get("id") or item.get("assetId") or item.get("asset", {}).get("id")
            if not asset_id:
                continue
            info = self._parse_catalog_entry(item, int(asset_id))
            if info.price > max_price:
                continue
            results.append({**info.to_dict(), "search_query": query})
        return results

    def _parse_catalog_entry(self, item: dict, asset_id: int) -> AssetInfo:
        name = str(item.get("name") or item.get("asset", {}).get("name") or "")
        creator = item.get("creator") or {}
        creator_id = int(creator.get("id") or creator.get("creatorTargetId") or
                         creator.get("userId") or creator.get("groupId") or 0)
        creator_name = str(creator.get("name") or "")
        asset = item.get("asset") or {}
        asset_type = str(item.get("assetType") or item.get("type") or "")
        description = str(item.get("description") or asset.get("description") or "")
        price = float(item.get("price") or 0.0)
        safe, note = check_license(name, creator_id, description, asset_type)
        return AssetInfo(asset_id=asset_id, name=name, asset_type=asset_type,
                         creator=creator_name, creator_id=creator_id,
                         is_free=price <= 0, price=price, description=description[:400],
                         license_safe=safe, license_note=note, raw=item)

    def search_catalog(self, query: str, limit: int = 10) -> list[dict]:
        """Kurzform fuer die Katalog-Suche (Alias auf search_creator_store)."""
        return self.search_creator_store(query, limit=limit)

    # -- Metadaten ------------------------------------------------------- #
    def asset_info(self, asset_id: int) -> AssetInfo:
        if asset_id <= 0:
            raise ValueError("asset_id muss positiv sein")

        def fetch() -> dict:
            response = self._request("GET", f"{ASSETS_API}/{asset_id}")
            try:
                return response.json()
            except ValueError as exc:
                raise RobloxApiError("Asset-Metadaten sind kein JSON") from exc

        data = self._cached_json(f"asset:{asset_id}", fetch)
        creator = data.get("creationContext", {}).get("creator", {}) or {}
        name = str(data.get("displayName") or data.get("name") or "")
        description = str(data.get("description") or "")
        creator_id = int(creator.get("targetId") or 0)
        safe, note = check_license(name, creator_id, description,
                                   str(data.get("assetType") or ""))
        return AssetInfo(
            asset_id=asset_id, name=name,
            asset_type=str(data.get("assetType") or ""),
            asset_type_id=int(data.get("assetTypeId") or 0),
            creator=str(creator.get("name") or ""), creator_id=creator_id,
            is_free=True, description=description[:400],
            license_safe=safe, license_note=note, raw=data)

    # -- Download -------------------------------------------------------- #
    def asset_content(self, asset_id: int) -> tuple[bytes, str]:
        """Laedt den echten Dateiinhalt eines Assets (mit CDN-Redirect)."""
        response = self._request("GET", f"{ASSET_DELIVERY}/{asset_id}", stream=True)
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                payload = response.json()
            except ValueError as exc:
                raise RobloxApiError("Asset-Delivery liefert unlesbares JSON") from exc
            location = payload.get("location") or payload.get("url")
            if not location:
                raise RobloxApiError("Asset-Delivery liefert keine Download-URL")
            cdn = self._request("GET", location, auth=False, stream=True)
            return cdn.content, cdn.headers.get("Content-Type", "")
        return response.content, content_type

    def download_asset(self, asset_id: int, target: Path, force: bool = False,
                       expected: Optional[Iterable[str]] = None) -> Path:
        """Laedt ein Asset in eine Datei; erkennt die Endung am Inhalt."""
        target = Path(target)
        if target.is_file() and target.stat().st_size > 0 and not force:
            self.stats["cache_hits"] += 1
            return target
        data, content_type = self.asset_content(asset_id)
        if len(data) < 40:
            raise RobloxApiError(f"Asset {asset_id}: Download ist leer")
        suffix = target.suffix.lower()
        if not suffix:
            suffix = self._guess_suffix(data, content_type)
            target = target.with_suffix(suffix)
        allowed = set(expected or (".rbxm", ".rbxmx", ".obj", ".gltf", ".glb", ".png", ".jpg",
                                   ".jpeg", ".tga"))
        if suffix not in allowed:
            raise RobloxApiError(f"Asset {asset_id}: Dateityp {suffix} ist nicht erlaubt "
                                 f"(erlaubt: {', '.join(sorted(allowed))})")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.stats["downloads"] += 1
        return target

    @staticmethod
    def _guess_suffix(data: bytes, content_type: str) -> str:
        # Binaeres RBXM beginnt mit der Magic inkl. Signaturbytes, XML mit "<?xml"/"<roblox"
        if data.startswith(b"<roblox!\x89\xff\r\n\x1a\n"):
            return ".rbxm"
        if data.lstrip().startswith((b"<?xml", b"<roblox")):
            return ".rbxmx"
        if data[:4] == b"\x89PNG":
            return ".png"
        if data[:2] == b"\xff\xd8":
            return ".jpg"
        if data[:4] == b"glTF":
            return ".glb"
        if b"version" in data[:32] and data[:7] == b"version":
            return ".mesh"
        if content_type.startswith("text/plain"):
            return ".obj"
        if data[:1] in (b"{", b"["):
            return ".json"
        return ".rbxm"

    # -- Thumbnails ------------------------------------------------------ #
    def thumbnail_url(self, asset_id: int, size: str = "420x420") -> Optional[str]:
        def fetch() -> dict:
            response = self._request("GET", f"{THUMBNAIL_API}/v1/assets",
                                     params={"assetIds": asset_id, "size": size,
                                             "format": "Png", "isCircular": "false"},
                                     auth=False)
            return response.json()

        data = self._cached_json(f"thumb:{asset_id}:{size}", fetch)
        entries = data.get("data") or []
        if not entries:
            return None
        entry = entries[0]
        if entry.get("state") != "Completed":
            return None
        return entry.get("imageUrl")

    def download_thumbnail(self, asset_id: int, target: Path,
                           size: str = "420x420") -> Optional[Path]:
        target = Path(target)
        if target.is_file() and target.stat().st_size > 100:
            self.stats["cache_hits"] += 1
            return target
        url = self.thumbnail_url(asset_id, size)
        if not url:
            return None
        response = self._request("GET", url, auth=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target

    def threed_thumbnail(self, asset_id: int, target: Path) -> Optional[Path]:
        """3D-Vorschau (OBJ) eines Assets - Fallback, wenn das Modell nicht ladbar ist."""
        target = Path(target)
        if target.is_file() and target.stat().st_size > 100:
            return target

        def fetch() -> dict:
            response = self._request("GET", f"{THUMBNAIL_API}/v1/assets-thumbnail-3d",
                                     params={"assetId": asset_id}, auth=False)
            return response.json()

        try:
            data = self._cached_json(f"thumb3d:{asset_id}", fetch)
        except RobloxApiError:
            return None
        url = data.get("imageUrl")
        if not url:
            return None
        response = self._request("GET", url, auth=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return target

    # -- Verbindungstest ------------------------------------------------- #
    def verify(self) -> dict:
        """Prueft Key und Grundfunktionen ohne etwas zu veraendern."""
        report = {"key": mask_secret(self.api_key), "user_id": self.user_id,
                  "search_ok": False, "metadata_ok": False, "delivery_ok": False,
                  "thumbnails_ok": False, "errors": []}
        if not self.api_key:
            report["errors"].append("ROBLOX_API_KEY fehlt")
            return report
        try:
            hits = self.search_creator_store("street lamp", limit=1)
            report["search_ok"] = bool(hits)
            report["sample"] = hits[0]["name"] if hits else ""
        except RobloxApiError as exc:
            report["errors"].append(f"Creator-Store: {exc} {exc.hint}")
        try:
            self.asset_info(1818)  # bekanntes altes Asset (Haar)
            report["metadata_ok"] = True
        except RobloxApiError as exc:
            report["errors"].append(f"Asset-Metadaten: {exc} {exc.hint}")
        try:
            data, _ = self.asset_content(1818)
            report["delivery_ok"] = len(data) > 100
        except RobloxApiError as exc:
            report["errors"].append(f"Asset-Delivery: {exc} {exc.hint}")
        try:
            report["thumbnails_ok"] = bool(self.thumbnail_url(1818))
        except (RobloxApiError, requests.RequestException) as exc:
            report["errors"].append(f"Thumbnails: {exc}")
        return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Roblox Open Cloud testen und Assets laden")
    parser.add_argument("--search", default=None, help="Creator-Store-Suche")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--asset", type=int, action="append", default=None)
    parser.add_argument("--out", type=Path, default=Path("assets_cache/roblox/files"))
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    client = RobloxClient()
    output: dict[str, Any] = {}
    if args.verify:
        output["verify"] = client.verify()
        print(json.dumps(output["verify"], ensure_ascii=False, indent=2))
    if args.search:
        hits = client.search_creator_store(args.search, args.limit)
        output["search"] = hits
        for hit in hits:
            flag = "OK " if hit["license_safe"] else "RISIKO"
            print(f"[{flag}] {hit['id']:>12}  {hit['name'][:48]:<48} "
                  f"von {hit['creator'][:18]:<18} {hit['license_note'][:40]}")
    for asset_id in args.asset or []:
        info = client.asset_info(asset_id)
        path = client.download_asset(asset_id, args.out / f"{asset_id}")
        output.setdefault("assets", []).append({**info.to_dict(), "path": str(path)})
        print(f"Asset {asset_id}: {info.name} -> {path} ({path.stat().st_size} Bytes)")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not output.get("verify", {}).get("errors") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

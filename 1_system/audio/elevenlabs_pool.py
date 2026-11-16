"""ElevenLabs-Pool: mehrere Accounts/Keys, Guthaben-Pruefung, TTS mit Wort-Timestamps.

Was dieses Modul leistet
------------------------
* Sammelt Keys aus ``ELEVENLABS_API_KEYS`` (Komma, Semikolon oder Zeilenumbruch)
  und aus ``ELEVENLABS_API_KEY_1`` ... ``ELEVENLABS_API_KEY_10``; Duplikate fliegen raus.
* Keys duerfen optional ein Konto-Label tragen: ``familie:sk_abc123``. Damit weiss
  der Pool, welche Keys zum selben ElevenLabs-Account gehoeren (Guthaben wird pro
  Konto nur EINMAL gezaehlt). Ohne Label wird ein Fingerprint aus dem
  Subscription-Objekt gebildet; identische Werte gelten als dasselbe Konto.
* Prueft ``GET /v1/user/subscription`` pro Key, maskiert alle Secrets in Ausgaben.
* Waehlt beim Sprechen automatisch den Key mit dem meisten Restguthaben, wechselt bei
  ``quota_exceeded`` / 401 / 429 auf den naechsten und merkt sich verbrauchte Zeichen.
* Ruft ``POST /v1/text-to-speech/{voice_id}/with-timestamps`` auf und liefert Audio
  (Base64-dekodiert) plus Zeichen-Alignment fuer die wortgenaue Timeline.
* Prueft optional pro Account, ob die gewuenschte Stimme dort wirklich existiert
  (eine Voice-ID ist nicht automatisch auf jedem Account verfuegbar).

Sicherheit: Keys werden niemals geloggt, niemals in Fehlermeldungen geschrieben und
niemals in Artefakte gepackt. Ausgegeben wird immer nur ``abcd****yz``.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
TIMEOUT = 90
MAX_KEYS = 10


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #
def mask_key(key: str) -> str:
    """Maskiert einen Key so, dass er in Logs/Screenshots unbrauchbar ist."""
    raw = key.split(":", 1)[-1] if ":" in key else key
    raw = raw.strip()
    if not raw:
        return "(leer)"
    if len(raw) <= 8:
        return raw[:2] + "****"
    return raw[:4] + "****" + raw[-2:]


def split_key_entry(entry: str) -> tuple[Optional[str], str]:
    """``label:sk_...`` -> ("label", "sk_..."); ohne Label -> (None, key)."""
    entry = entry.strip()
    if not entry:
        return None, ""
    for sep in (":", "|"):
        if sep in entry:
            label, key = entry.split(sep, 1)
            label, key = label.strip(), key.strip()
            if label and key and len(key) >= 8:
                return label, key
    return None, entry


def collect_api_keys() -> list[str]:
    """Sammelt alle Keys (Rohform inkl. optionalem Label), Duplikate entfernt."""
    raw_entries: list[str] = []
    combined = os.environ.get("ELEVENLABS_API_KEYS", "")
    if combined:
        raw_entries.extend(part for part in combined.replace(";", ",").replace("\n", ",").split(","))
    for i in range(1, MAX_KEYS + 1):
        raw_entries.append(os.environ.get(f"ELEVENLABS_API_KEY_{i}", ""))
    keys: list[str] = []
    seen_secrets: set[str] = set()
    for entry in raw_entries:
        label, secret = split_key_entry(entry)
        if not secret or secret in seen_secrets:
            continue
        seen_secrets.add(secret)
        keys.append(f"{label}:{secret}" if label else secret)
    return keys


def _secret(entry: str) -> str:
    return split_key_entry(entry)[1]


def _label(entry: str) -> Optional[str]:
    return split_key_entry(entry)[0]


# --------------------------------------------------------------------------- #
# Datenklassen
# --------------------------------------------------------------------------- #
@dataclass
class KeyStatus:
    key_masked: str
    ok: bool
    account: str = ""
    tier: str = ""
    characters_used: int = 0
    characters_limit: int = 0
    characters_remaining: int = 0
    reset_at: Optional[str] = None
    voice_ids: set[str] = field(default_factory=set)
    voice_checked: bool = False
    has_voice: bool = True
    error: str = ""

    @property
    def usable(self) -> bool:
        return self.ok and self.characters_remaining > 0 and self.has_voice

    def to_dict(self) -> dict:
        return {
            "key": self.key_masked,
            "ok": self.ok,
            "account": self.account,
            "tier": self.tier,
            "characters_used": self.characters_used,
            "characters_limit": self.characters_limit,
            "characters_remaining": self.characters_remaining,
            "reset_at": self.reset_at,
            "voice_ok": self.has_voice,
            "error": self.error,
        }


@dataclass
class CreditReport:
    keys: list[KeyStatus] = field(default_factory=list)
    estimated_chars: int = 0
    required_voice_id: Optional[str] = None

    @property
    def accounts(self) -> dict[str, list[KeyStatus]]:
        grouped: dict[str, list[KeyStatus]] = {}
        for status in self.keys:
            grouped.setdefault(status.account or status.key_masked, []).append(status)
        return grouped

    @property
    def account_remaining(self) -> dict[str, int]:
        """Restguthaben pro Konto (mehrere Keys desselben Kontos zaehlen einmal).

        Das Guthaben mehrerer *verschiedener* Konten ist addierbar, weil jedes Konto
        seinen eigenen Zeichen-Zaehler hat. Innerhalb eines Kontos nehmen wir das
        Maximum der Key-Abfragen (gleiche Zahl, unterschiedliche Cache-Staende).
        """
        out: dict[str, int] = {}
        for account, statuses in self.accounts.items():
            values = [s.characters_remaining for s in statuses if s.ok]
            if values:
                out[account] = max(values)
        return out

    @property
    def total_remaining(self) -> int:
        return sum(self.account_remaining.values())

    @property
    def usable_keys(self) -> int:
        return sum(1 for s in self.keys if s.usable)

    @property
    def ok(self) -> bool:
        """Harte Freigabe: mindestens ein brauchbarer Key UND genug Guthaben."""
        if not self.keys or self.usable_keys == 0:
            return False
        if self.required_voice_id:
            supported = [s for s in self.keys if s.usable and s.has_voice]
            if not supported:
                return False
        return self.total_remaining >= self.estimated_chars

    def summary(self) -> str:
        lines = [
            f"ElevenLabs-Guthaben: {self.total_remaining} Zeichen ueber "
            f"{len(self.account_remaining)} Konto(en), Bedarf {self.estimated_chars} "
            f"(inkl. Puffer)",
            "",
        ]
        for account, statuses in self.accounts.items():
            best = max((s.characters_remaining for s in statuses if s.ok), default=0)
            lines.append(f"  Konto '{account}': {best} Zeichen frei")
            for status in statuses:
                if status.ok:
                    voice_flag = ""
                    if self.required_voice_id and status.voice_checked:
                        voice_flag = " | Stimme: " + ("vorhanden" if status.has_voice else "FEHLT")
                    lines.append(
                        f"    {status.key_masked}: {status.characters_remaining}/"
                        f"{status.characters_limit} frei, Tarif {status.tier or '?'}, "
                        f"Reset {status.reset_at or 'unbekannt'}{voice_flag}")
                else:
                    lines.append(f"    {status.key_masked}: FEHLER - {status.error}")
        lines.append("")
        lines.append("Status: AUSREICHEND - Start erlaubt" if self.ok
                     else "Status: NICHT AUSREICHEND - HARTER STOPP")
        return "\n".join(lines)

    def summary_markdown(self) -> str:
        out = [
            f"**Verfuegbar:** {self.total_remaining} Zeichen ueber "
            f"{len(self.account_remaining)} Konto(en) - **Bedarf:** {self.estimated_chars} Zeichen",
            "",
            "| Konto | Key | Restzeichen | Limit | Tarif | Reset |",
            "|---|---|---|---|---|---|",
        ]
        for account, statuses in self.accounts.items():
            for status in statuses:
                if status.ok:
                    out.append(
                        f"| {account} | {status.key_masked} | {status.characters_remaining} | "
                        f"{status.characters_limit} | {status.tier or '-'} | {status.reset_at or '-'} |")
                else:
                    out.append(f"| {account} | {status.key_masked} | - | - | - | {status.error} |")
        out.append("")
        out.append("**Ergebnis:** " + ("AUSREICHEND - Start erlaubt" if self.ok
                                       else "NICHT AUSREICHEND - HARTER STOPP"))
        if self.required_voice_id:
            out.append("")
            out.append(f"**Stimme `{self.required_voice_id}`:** " +
                       ("auf mindestens einem Konto vorhanden" if self.ok else "nicht nutzbar"))
        out.append("")
        out.append("_Hinweis: Guthaben verschiedener Konten wird addiert, mehrfach "
                   "hinterlegte Keys desselben Kontos nur einmal gezaehlt._")
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "estimated_chars": self.estimated_chars,
            "required_voice_id": self.required_voice_id,
            "total_remaining": self.total_remaining,
            "usable_keys": self.usable_keys,
            "ok": self.ok,
            "keys": [k.to_dict() for k in self.keys],
        }


@dataclass
class SynthesisResult:
    audio_bytes: bytes
    alignment: dict
    duration_seconds: float
    key_used: str
    account: str = ""
    characters: int = 0
    output_format: str = DEFAULT_OUTPUT_FORMAT

    @property
    def word_count(self) -> int:
        chars = self.alignment.get("characters", [])
        return sum(1 for i, c in enumerate(chars)
                   if not c.isspace() and (i == 0 or chars[i - 1].isspace()))


class ElevenLabsError(RuntimeError):
    """Fachlicher Fehler mit maschinenlesbarem `code` (quota_exceeded, invalid_api_key...)."""

    def __init__(self, message: str, code: str = "error", status_code: int = 0):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# --------------------------------------------------------------------------- #
# Pool
# --------------------------------------------------------------------------- #
class ElevenLabsPool:
    """Verwaltet mehrere Keys inkl. Rotation, Guthaben und Stimmen-Verfuegbarkeit."""

    def __init__(self, keys: Optional[list[str]] = None, model_id: str = DEFAULT_MODEL_ID,
                 output_format: str = DEFAULT_OUTPUT_FORMAT,
                 voice_settings: Optional[dict] = None,
                 session: Optional[requests.Session] = None):
        self.keys = keys if keys is not None else collect_api_keys()
        self.model_id = model_id
        self.output_format = output_format
        self.voice_settings = voice_settings or {
            "stability": 0.45, "similarity_boost": 0.8, "style": 0.25,
            "use_speaker_boost": True,
        }
        self.session = session or requests.Session()
        self._remaining: dict[str, int] = {}
        self._dead: set[str] = set()
        self._voice_cache: dict[tuple[str, str], bool] = {}

    # -- intern ---------------------------------------------------------- #
    def _headers(self, entry: str) -> dict:
        return {"xi-api-key": _secret(entry), "Content-Type": "application/json",
                "Accept": "application/json"}

    def _account_of(self, entry: str, data: dict) -> str:
        label = _label(entry)
        if label:
            return label
        fingerprint = (
            data.get("character_limit"), data.get("character_count"),
            data.get("next_character_count_reset_unix"),
        )
        readable = "konto-" + str(hash(fingerprint) % 100_000).zfill(5)
        return readable

    @staticmethod
    def _reset_iso(value) -> Optional[str]:
        if value in (None, "", 0, "0"):
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            except (OverflowError, OSError, ValueError):
                return None
        return str(value)

    def _parse_error(self, response: requests.Response) -> ElevenLabsError:
        code, message = "http_error", f"HTTP {response.status_code}"
        try:
            payload = response.json()
            detail = payload.get("detail", payload)
            if isinstance(detail, dict):
                code = str(detail.get("status") or detail.get("code") or code)
                message = str(detail.get("message") or code)
            elif isinstance(detail, str):
                message = detail
            elif isinstance(detail, list) and detail:
                first = detail[0]
                code = str(first.get("status", code)) if isinstance(first, dict) else code
                message = str(first.get("msg", first)) if isinstance(first, dict) else str(first)
        except ValueError:
            message = (response.text or message)[:300]
        return ElevenLabsError(f"ElevenLabs: {message} ({code})", code, response.status_code)

    # -- Guthaben -------------------------------------------------------- #
    def check_key(self, entry: str, required_voice_id: Optional[str] = None) -> KeyStatus:
        masked = mask_key(entry)
        try:
            response = self.session.get(f"{BASE_URL}/user/subscription",
                                        headers={"xi-api-key": _secret(entry)}, timeout=TIMEOUT)
        except requests.RequestException:
            return KeyStatus(masked, False, error="Netzwerkfehler bei Guthaben-Abfrage")
        if response.status_code == 401:
            try:
                detail = response.json().get("detail", {})
                missing_permissions = isinstance(detail, dict) and detail.get("status") == "missing_permissions"
            except (ValueError, AttributeError):
                missing_permissions = False
            if missing_permissions:
                return KeyStatus(masked, False, error="Key hat keine Berechtigung fuer die Guthaben-Abfrage (401)")
            return KeyStatus(masked, False, error="Key abgelehnt (401); Key und Berechtigungen pruefen")
        if response.status_code == 429:
            return KeyStatus(masked, False, error="Rate-Limit (429) - spaeter erneut versuchen")
        if response.status_code != 200:
            return KeyStatus(masked, False, error=f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            return KeyStatus(masked, False, error="Antwort der Guthaben-API ist kein JSON")
        used = int(data.get("character_count", 0) or 0)
        limit = int(data.get("character_limit", 0) or 0)
        remaining = max(0, limit - used)
        status = KeyStatus(
            key_masked=masked,
            ok=True,
            account=self._account_of(entry, data),
            tier=str(data.get("tier") or data.get("status") or ""),
            characters_used=used,
            characters_limit=limit,
            characters_remaining=remaining,
            reset_at=self._reset_iso(data.get("next_character_count_reset_unix")
                                     or data.get("next_invoice_date")),
        )
        self._remaining[entry] = remaining
        if required_voice_id:
            status.voice_checked = True
            status.has_voice = self.has_voice(entry, required_voice_id)
        return status

    def check_credits(self, estimated_chars: int = 0,
                      required_voice_id: Optional[str] = None) -> CreditReport:
        if estimated_chars < 0:
            raise ValueError("Zeichenbedarf darf nicht negativ sein")
        statuses = [self.check_key(entry, required_voice_id) for entry in self.keys]
        return CreditReport(statuses, estimated_chars, required_voice_id)

    # -- Stimmen --------------------------------------------------------- #
    def list_voices(self, entry: Optional[str] = None) -> list[dict]:
        entry = entry or (self.keys[0] if self.keys else "")
        if not entry:
            return []
        try:
            response = self.session.get(f"{BASE_URL}/voices",
                                        headers={"xi-api-key": _secret(entry)}, timeout=TIMEOUT)
        except requests.RequestException:
            return []
        if response.status_code != 200:
            return []
        try:
            return list(response.json().get("voices", []))
        except ValueError:
            return []

    def has_voice(self, entry: str, voice_id: str) -> bool:
        cache_key = (entry, voice_id)
        if cache_key in self._voice_cache:
            return self._voice_cache[cache_key]
        try:
            response = self.session.get(f"{BASE_URL}/voices/{voice_id}",
                                        headers={"xi-api-key": _secret(entry)}, timeout=TIMEOUT)
            available = response.status_code == 200
            # 401/403/429 sagen nichts ueber die Stimme aus -> nicht als "fehlt" werten
            if response.status_code in (401, 403, 429):
                available = True
        except requests.RequestException:
            available = True
        self._voice_cache[cache_key] = available
        return available

    # -- Auswahl --------------------------------------------------------- #
    def _usable_entries(self) -> list[str]:
        return [e for e in self.keys if e not in self._dead and self._remaining.get(e, 1) > 0]

    def select_key(self) -> str:
        if not self.keys:
            raise ElevenLabsError("Keine ElevenLabs-Keys konfiguriert", "no_keys")
        usable = self._usable_entries()
        if not usable:
            raise ElevenLabsError("Alle ElevenLabs-Keys sind aufgebraucht oder gesperrt",
                                  "all_keys_exhausted")
        return max(usable, key=lambda e: self._remaining.get(e, 0))

    def mark_exhausted(self, entry: str) -> None:
        self._dead.add(entry)
        self._remaining[entry] = 0

    # -- Sprechen -------------------------------------------------------- #
    def _request_speech(self, entry: str, text: str, voice_id: str,
                        previous_text: str, next_text: str,
                        voice_settings: Optional[dict]) -> SynthesisResult:
        payload = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": voice_settings or self.voice_settings,
            "apply_text_normalization": "auto",
        }
        if previous_text:
            payload["previous_text"] = previous_text
        if next_text:
            payload["next_text"] = next_text
        try:
            response = self.session.post(
                f"{BASE_URL}/text-to-speech/{voice_id}/with-timestamps",
                params={"output_format": self.output_format},
                headers=self._headers(entry), json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ElevenLabsError(f"Netzwerkfehler bei TTS: {type(exc).__name__}", "network") from exc
        if response.status_code != 200:
            raise self._parse_error(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise ElevenLabsError("TTS-Antwort ist kein JSON", "bad_response") from exc
        audio_b64 = data.get("audio_base64") or ""
        alignment = data.get("alignment") or data.get("normalized_alignment") or {}
        if not audio_b64:
            raise ElevenLabsError("Antwort ohne Audio", "empty_audio")
        if not alignment or not alignment.get("characters"):
            raise ElevenLabsError(
                "Antwort ohne Wort-Timestamps - Modell/Format unterstuetzt kein Alignment",
                "no_alignment")
        try:
            audio = base64.b64decode(audio_b64)
        except (ValueError, TypeError) as exc:
            raise ElevenLabsError("Audio-Base64 ist beschaedigt", "bad_audio") from exc
        if len(audio) < 1000:
            raise ElevenLabsError("Audio ist auffaellig klein", "bad_audio")
        duration = float(alignment["character_end_times_seconds"][-1])
        consumed = len(text)
        self._remaining[entry] = max(0, self._remaining.get(entry, 0) - consumed)
        return SynthesisResult(audio, alignment, duration, mask_key(entry),
                               _label(entry) or "", consumed, self.output_format)

    def synthesize_segment(self, text: str, voice_id: str, output_path: Path,
                           previous_text: str = "", next_text: str = "",
                           voice_settings: Optional[dict] = None,
                           max_attempts: int = 6) -> SynthesisResult:
        """Synthetisiert ein Segment und rotiert bei Limit-Fehlern ueber die Keys."""
        text = text.strip()
        if not text:
            raise ValueError("Leerer Sprechtext")
        if not voice_id:
            raise ValueError("Keine voice_id uebergeben")
        if not self.keys:
            raise ElevenLabsError("Keine ElevenLabs-Keys konfiguriert", "no_keys")
        if not self._remaining:
            # Ohne vorherige Guthaben-Abfrage zumindest grob wissen, was da ist.
            for entry in self.keys:
                self.check_key(entry)

        last_error: Optional[ElevenLabsError] = None
        excluded: set[str] = set()
        for attempt in range(max_attempts):
            candidates = [e for e in self._usable_entries() if e not in excluded]
            if not candidates:
                break
            entry = max(candidates, key=lambda e: self._remaining.get(e, 0))
            try:
                result = self._request_speech(entry, text, voice_id,
                                              previous_text, next_text, voice_settings)
            except ElevenLabsError as exc:
                last_error = exc
                retryable = exc.code in {
                    "quota_exceeded", "invalid_api_key", "rate_limit_exceeded",
                    "too_many_concurrent_requests", "network", "http_error",
                } or exc.status_code in (401, 402, 429, 500, 502, 503, 504)
                if exc.code == "quota_exceeded" or exc.status_code == 401:
                    self.mark_exhausted(entry)
                else:
                    excluded.add(entry)
                if not retryable:
                    raise
                time.sleep(min(2.0 * (attempt + 1), 8.0))
                continue
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(result.audio_bytes)
            return result
        raise ElevenLabsError(
            f"Kein Key konnte das Segment sprechen. Letzter Fehler: {last_error}", "all_failed")

    # -- Bequemlichkeit -------------------------------------------------- #
    def remaining_snapshot(self) -> dict[str, int]:
        return {mask_key(k): v for k, v in self._remaining.items()}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _write_summary(report: CreditReport) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write("## ElevenLabs-Credit-Check\n\n" + report.summary_markdown() + "\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"remaining={report.total_remaining}\n")
            stream.write(f"ok={'true' if report.ok else 'false'}\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="ElevenLabs-Guthaben und Stimmen pruefen")
    parser.add_argument("--estimated-chars", type=int, default=0,
                        help="Bedarf inkl. Puffer (Standard: 0 = nur Kontostand zeigen)")
    parser.add_argument("--voice-id", default="", help="Stimme pruefen (Verfuegbarkeit pro Konto)")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--list-voices", action="store_true")
    args = parser.parse_args(argv)
    if args.estimated_chars < 0:
        parser.error("Zeichenbedarf darf nicht negativ sein")

    pool = ElevenLabsPool()
    if args.list_voices:
        for voice in pool.list_voices():
            print(f"{voice.get('voice_id')}  {voice.get('name')}  "
                  f"[{voice.get('category', '?')}]  {voice.get('labels', {})}")
        return 0
    if not pool.keys:
        print("FEHLER: Keine ElevenLabs-Keys gefunden (ELEVENLABS_API_KEYS oder "
              "ELEVENLABS_API_KEY_1..10 setzen).", file=sys.stderr)
        return 2
    report = pool.check_credits(args.estimated_chars, args.voice_id or None)
    print(report.summary())
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    _write_summary(report)
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

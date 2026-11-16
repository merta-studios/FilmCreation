"""ElevenLabs Multi-Key-Pool: Credit-Pruefung, TTS mit Wort-Timestamps, Rotation."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://api.elevenlabs.io/v1"
MODEL_ID = "eleven_multilingual_v2"
TIMEOUT = 60


def _mask_key(key: str) -> str:
    if not key:
        return "(leer)"
    if len(key) <= 8:
        return key[:2] + "****"
    return key[:4] + "****" + key[-2:]


def collect_api_keys() -> list[str]:
    """Sammelt Keys aus ELEVENLABS_API_KEYS + ELEVENLABS_API_KEY_1..10, Duplikate entfernen."""
    keys: list[str] = []
    combined = os.environ.get("ELEVENLABS_API_KEYS", "")
    if combined:
        for part in combined.replace("\n", ",").split(","):
            k = part.strip()
            if k and k not in keys:
                keys.append(k)
    for i in range(1, 11):
        k = os.environ.get(f"ELEVENLABS_API_KEY_{i}", "").strip()
        if k and k not in keys:
            keys.append(k)
    return keys


@dataclass
class KeyStatus:
    key_masked: str
    ok: bool
    characters_used: int = 0
    characters_limit: int = 0
    characters_remaining: int = 0
    reset_at: Optional[str] = None
    error: str = ""


@dataclass
class CreditReport:
    keys: list[KeyStatus] = field(default_factory=list)
    estimated_chars: int = 0

    @property
    def total_remaining(self) -> int:
        return max((k.characters_remaining for k in self.keys if k.ok), default=0)

    @property
    def ok(self) -> bool:
        return bool(self.keys) and all(k.ok for k in self.keys) and self.total_remaining >= self.estimated_chars

    def summary(self) -> str:
        lines = [f"ElevenLabs-Credits: mindestens {self.total_remaining} Zeichen sicher verfügbar (bester einzelner Key) "
                 f"(Bedarf geschaetzt: {self.estimated_chars})"]
        for k in self.keys:
            if k.ok:
                lines.append(f"  {k.key_masked}: {k.characters_remaining}/"
                             f"{k.characters_limit} frei, Reset: {k.reset_at or 'unbekannt'}")
            else:
                lines.append(f"  {k.key_masked}: FEHLER – {k.error}")
        lines.append("Status: " + ("AUSREICHEND" if self.ok else "NICHT AUSREICHEND – STOPP"))
        return "\n".join(lines)

    def summary_markdown(self) -> str:
        lines = [f"**Sicher verfügbar (bester einzelner Key):** {self.total_remaining} Zeichen (Bedarf: {self.estimated_chars})",
                 "", "| Key | Status | Rest | Reset |", "|---|---|---|---|"]
        for k in self.keys:
            if k.ok:
                lines.append(f"| {k.key_masked} | OK | {k.characters_remaining} | {k.reset_at or '-'} |")
            else:
                lines.append(f"| {k.key_masked} | FEHLER: {k.error} | - | - |")
        lines.append("")
        lines.append("**Ergebnis:** " + ("AUSREICHEND" if self.ok else "NICHT AUSREICHEND"))
        return "\n".join(lines)


@dataclass
class SynthesisResult:
    audio_bytes: bytes
    alignment: dict
    duration_seconds: float
    key_used: str


class ElevenLabsPool:
    """Verwaltet mehrere ElevenLabs-Keys mit Rotation und automatischem Fallback."""

    def __init__(self, keys: Optional[list[str]] = None):
        self.keys = keys if keys is not None else collect_api_keys()
        self._key_index = 0

    def _headers(self, key: str) -> dict:
        return {"xi-api-key": key, "Content-Type": "application/json",
                "Accept": "audio/mpeg"}

    def check_key(self, key: str) -> KeyStatus:
        masked = _mask_key(key)
        try:
            r = requests.get(f"{BASE_URL}/user/subscription",
                             headers={"xi-api-key": key}, timeout=TIMEOUT)
            if r.status_code == 401:
                return KeyStatus(masked, False, error="Ungueltiger Key (401)")
            if r.status_code == 429:
                return KeyStatus(masked, False, error="Rate-Limit (429)")
            if r.status_code != 200:
                return KeyStatus(masked, False, error=f"HTTP {r.status_code}")
            data = r.json()
            used = int(data.get("character_count", 0))
            limit = int(data.get("character_limit", 0))
            remaining = max(0, limit - used)
            reset = data.get("next_character_count_reset_unix") or data.get("next_invoice_date") or data.get("reset_at")
            if isinstance(reset, (int, float)):
                from datetime import datetime, timezone
                reset = datetime.fromtimestamp(reset, timezone.utc).isoformat()
            return KeyStatus(masked, True, used, limit, remaining,
                             str(reset) if reset else None)
        except requests.RequestException as e:
            return KeyStatus(masked, False, error="Netzwerkfehler bei Credit-Pruefung")

    def check_credits(self, estimated_chars: int = 0) -> CreditReport:
        statuses = [self.check_key(k) for k in self.keys]
        return CreditReport(keys=statuses, estimated_chars=estimated_chars)

    def _synthesize_once(self, key: str, text: str, voice_id: str,
                         previous_text: str, next_text: str) -> SynthesisResult:
        payload = {
            "text": text,
            "model_id": MODEL_ID,
            "previous_text": previous_text,
            "next_text": next_text,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                               "style": 0.0, "use_speaker_boost": True},
        }
        r = requests.post(f"{BASE_URL}/text-to-speech/{voice_id}/with-timestamps",
                          headers=self._headers(key), json=payload, timeout=TIMEOUT)
        if r.status_code == 429:
            raise RuntimeError("quota_exceeded (429)")
        if r.status_code == 401:
            raise RuntimeError("Ungueltiger Key (401)")
        if r.status_code == 404:
            raise RuntimeError(f"Stimme {voice_id} nicht gefunden (404)")
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs HTTP {r.status_code}")
        data = r.json()
        audio_b64 = data.get("audio_base64", "")
        alignment = data.get("alignment", {})
        import base64
        audio_bytes = base64.b64decode(audio_b64) if audio_b64 else b""
        duration = 0.0
        ends = alignment.get("character_end_times_seconds", [])
        if ends:
            duration = float(ends[-1])
        return SynthesisResult(audio_bytes, alignment, duration, _mask_key(key))

    def synthesize_segment(self, text: str, voice_id: str, output_path: Path,
                           previous_text: str = "", next_text: str = "",
                           max_retries: int = 3) -> SynthesisResult:
        """Synthesiert ein Segment, rotiert bei 429/401 automatisch auf den naechsten Key."""
        if not self.keys:
            raise RuntimeError("Keine ElevenLabs-Keys konfiguriert.")
        last_error: Optional[Exception] = None
        for attempt in range(max_retries * max(1, len(self.keys))):
            key = self.keys[self._key_index % len(self.keys)]
            try:
                result = self._synthesize_once(key, text, voice_id,
                                               previous_text, next_text)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(result.audio_bytes)
                return result
            except RuntimeError as e:
                last_error = e
                msg = str(e)
                if "quota_exceeded" in msg or "Ungueltiger" in msg or "429" in msg or "nicht gefunden" in msg:
                    self._key_index += 1
                    time.sleep(1.0)
                    continue
                raise
            except requests.RequestException as e:
                last_error = e
                self._key_index += 1
                time.sleep(1.0)
        raise RuntimeError(f"Alle Keys erschoepft. Letzter Fehler: {last_error}")

    def list_voices(self) -> list[dict]:
        if not self.keys:
            return []
        r = requests.get(f"{BASE_URL}/voices", headers={"xi-api-key": self.keys[0]},
                         timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        return r.json().get("voices", [])


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ElevenLabs Guthaben sicher pruefen")
    parser.add_argument("--estimated-chars", type=int, required=True)
    args = parser.parse_args()
    if args.estimated_chars < 0:
        parser.error("Zeichenbedarf darf nicht negativ sein")
    report = ElevenLabsPool().check_credits(args.estimated_chars)
    print(report.summary())
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("## ElevenLabs-Credit-Check\n\n" + report.summary_markdown() + "\n")
    return 0 if report.ok else 1

if __name__ == "__main__":
    raise SystemExit(main())

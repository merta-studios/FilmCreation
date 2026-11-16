"""Kaggle-CLI-Bindung: Kernel und Datasets hochladen, Status abfragen, Output holen.

Warum die CLI und nicht die Web-API?
------------------------------------
Kaggle hat keine dokumentierte oeffentliche REST-API fuer Kernel-Pushes. Der
offizielle Weg ist das ``kaggle``-CLI (``pip install kaggle``), das intern die
Web-Endpunkte benutzt. Genau dieses CLI rufen wir hier auf - mit klaren Fehlern,
Zeitlimits und ohne interaktive Rueckfragen.

Zugangsdaten
------------
* ``KAGGLE_USERNAME`` und ``KAGGLE_KEY`` (GitHub-Secrets) - daraus schreiben wir
  bei Bedarf ``~/.kaggle/kaggle.json`` mit Rechten 600.
* Alternativ ein vorhandenes ``KAGGLE_CONFIG_DIR``/``~/.kaggle/kaggle.json``.

Wichtige Befehle (verifiziert):
* ``kaggle kernels push -p DIR``            - Kernel aus ``kernel-metadata.json`` starten
* ``kaggle kernels status USER/SLUG``       - Status (``KernelWorkerStatus.COMPLETE`` ...)
* ``kaggle kernels output USER/SLUG -p DIR``- Ergebnisdateien herunterladen
* ``kaggle datasets create|version -p DIR`` - Datasets anlegen/aktualisieren
* ``kaggle quota``                          - verbleibende GPU-Stunden
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

#: Statuswerte, die das CLI fuer Kernel ausgibt
RUNNING_STATES = ("QUEUED", "RUNNING")
DONE_OK_STATES = ("COMPLETE",)
DONE_ERROR_STATES = ("ERROR", "CANCELED", "CANCELLED", "FAILED")

DEFAULT_TIMEOUT_MINUTES = 300


class KaggleError(RuntimeError):
    """Fehler aus dem Kaggle-CLI mit verstaendlichem Hinweis."""

    def __init__(self, message: str, output: str = ""):
        super().__init__(message)
        self.output = output

    @property
    def hint(self) -> str:
        text = self.output.lower()
        if "401" in text or "unauthorized" in text or "username and api key" in text:
            return ("Kaggle-Zugang fehlt: KAGGLE_USERNAME und KAGGLE_KEY als "
                    "GitHub-Secrets setzen (Kaggle -> Account -> Create New Token).")
        if "403" in text or "forbidden" in text:
            return ("Kaggle verweigert den Zugriff. Meist fehlt die Telefon-Verifizierung "
                    "im Kaggle-Konto (Settings -> Phone Verification) oder der Key ist alt.")
        if "quota" in text or "exceeded" in text:
            return ("Kaggle-GPU-Quota erschoepft (30 h/Woche). Warte auf den Reset "
                    "(Montag 00:00 UTC) oder rendere lokal." )
        if "not found" in text or "404" in text:
            return "Kernel/Dataset existiert nicht - Name (USER/SLUG) pruefen."
        if "no such file" in text and "kaggle" in text:
            return "Kaggle-CLI fehlt: pip install kaggle"
        return "Details siehe Ausgabe oben."


@dataclass
class CliResult:
    """Ergebnis eines CLI-Aufrufs (stdout und stderr zusammen als ``output``)."""
    returncode: int
    stdout: str = ""
    output: str = ""


@dataclass
class KernelState:
    slug: str
    status: str
    raw: str = ""

    @property
    def finished(self) -> bool:
        upper = self.status.upper()
        return any(state in upper for state in DONE_OK_STATES + DONE_ERROR_STATES)

    @property
    def ok(self) -> bool:
        upper = self.status.upper()
        return any(state in upper for state in DONE_OK_STATES)


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return "(nicht gesetzt)"
    return value[:4] + "****" + value[-2:] if len(value) > 8 else "****"


class KaggleClient:
    """Duenne, testbare Huelle um das ``kaggle``-CLI."""

    def __init__(self, username: Optional[str] = None, key: Optional[str] = None,
                 cli: Optional[str] = None, config_dir: Optional[Path] = None,
                 dry_run: bool = False):
        self.username = (username if username is not None
                         else os.environ.get("KAGGLE_USERNAME", "")).strip()
        self.key = (key if key is not None
                    else os.environ.get("KAGGLE_KEY", "") or os.environ.get("KAGGLE_API_TOKEN", "")).strip()
        self.cli = cli or shutil.which("kaggle") or "kaggle"
        self.config_dir = Path(config_dir) if config_dir else None
        self.dry_run = dry_run

    # -- Basis ----------------------------------------------------------- #
    def _env(self) -> dict:
        env = dict(os.environ)
        if self.config_dir is not None:
            env["KAGGLE_CONFIG_DIR"] = str(self.config_dir)
        if self.key.startswith("KGAT_"):
            env["KAGGLE_API_TOKEN"] = self.key
            env.pop("KAGGLE_KEY", None)
            env.pop("KAGGLE_USERNAME", None)
        return env

    def ensure_credentials(self) -> Optional[Path]:
        """Legacy-Key-Datei anlegen; API-Tokens nur im Prozess-Environment verwenden."""
        if self.key.startswith("KGAT_"):
            return None
        if self.config_dir is not None:
            target_dir = Path(self.config_dir)
        else:
            target_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR")
                              or Path.home() / ".kaggle")
        target = target_dir / "kaggle.json"
        if target.is_file():
            return target
        if not self.username or not self.key:
            raise KaggleError(
                "Kaggle-Zugang fehlt: KAGGLE_USERNAME/KAGGLE_KEY nicht gesetzt")
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"username": self.username, "key": self.key}),
                          encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:  # pragma: no cover - Windows
            pass
        return target

    def _run(self, args: list[str], timeout: int = 600, check: bool = True) -> CliResult:
        if not Path(self.cli).exists() and shutil.which(self.cli) is None:
            raise KaggleError("Kaggle-CLI nicht gefunden", "kaggle: command not found")
        command = [self.cli, *args]
        if self.dry_run:
            print("[dry-run] " + " ".join(command))
            return CliResult(0)
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    timeout=timeout, env=self._env())
        except subprocess.TimeoutExpired as exc:
            raise KaggleError(f"Kaggle-CLI Zeitlimit ({timeout}s): {' '.join(args[:3])}") from exc
        output = (result.stdout or "") + (result.stderr or "")
        if check and result.returncode != 0:
            raise KaggleError(f"Kaggle-CLI Fehler: {' '.join(args[:3])}", output)
        return CliResult(result.returncode, result.stdout or "", output)

    # -- Kernel ---------------------------------------------------------- #
    def push_kernel(self, folder: Path) -> str:
        """Startet einen Kernel aus ``kernel-metadata.json``; gibt den Slug zurueck."""
        folder = Path(folder)
        meta_path = folder / "kernel-metadata.json"
        if not meta_path.is_file():
            raise KaggleError(f"kernel-metadata.json fehlt in {folder}")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        slug = str(metadata.get("id") or "")
        if not slug:
            raise KaggleError("kernel-metadata.json ohne 'id' (USER/SLUG)")
        self.ensure_credentials()
        self._run(["kernels", "push", "-p", str(folder)], timeout=900)
        return slug

    def kernel_status(self, slug: str) -> KernelState:
        result = self._run(["kernels", "status", slug], timeout=120, check=False)
        text = result.output.strip()
        if result.returncode != 0:
            if "not found" in text.lower():
                raise KaggleError(f"Kernel {slug} nicht gefunden", text)
            return KernelState(slug=slug, status="UNKNOWN", raw=text)
        match = re.search(r"status[:\s\"']+([A-Za-z._]+)", text)
        status = match.group(1) if match else text.splitlines()[-1][:80]
        return KernelState(slug=slug, status=status, raw=text)

    def wait_for_kernel(self, slug: str, timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
                        poll_seconds: int = 60,
                        on_poll: Optional[Callable[[KernelState], None]] = None) -> KernelState:
        deadline = time.time() + timeout_minutes * 60
        state = KernelState(slug=slug, status="UNKNOWN")
        while time.time() < deadline:
            state = self.kernel_status(slug)
            if on_poll is not None:
                on_poll(state)
            else:
                print(f"[kaggle] {slug}: {state.status}", flush=True)
            if state.finished:
                return state
            time.sleep(poll_seconds)
        raise KaggleError(f"Kernel {slug} nach {timeout_minutes} Minuten nicht fertig "
                          f"(Status: {state.status})")

    def download_output(self, slug: str, target: Path) -> Path:
        target = Path(target)
        target.mkdir(parents=True, exist_ok=True)
        self._run(["kernels", "output", slug, "-p", str(target)], timeout=1800)
        return target

    # -- Datasets -------------------------------------------------------- #
    def create_dataset(self, folder: Path) -> str:
        folder = Path(folder)
        meta_path = folder / "dataset-metadata.json"
        if not meta_path.is_file():
            raise KaggleError(f"dataset-metadata.json fehlt in {folder}")
        slug = str(json.loads(meta_path.read_text(encoding="utf-8")).get("id") or "")
        self.ensure_credentials()
        self._run(["datasets", "create", "-p", str(folder)], timeout=1800)
        return slug

    def version_dataset(self, folder: Path, message: str = "Update") -> str:
        folder = Path(folder)
        slug = str(json.loads((folder / "dataset-metadata.json").read_text(encoding="utf-8"))
                   .get("id") or "")
        self.ensure_credentials()
        self._run(["datasets", "version", "-p", str(folder), "-m", message[:100]], timeout=1800)
        return slug

    def dataset_exists(self, slug: str) -> bool:
        result = self._run(["datasets", "files", "-d", slug], timeout=120, check=False)
        return result.returncode == 0

    # -- Kontingent ------------------------------------------------------ #
    def quota(self) -> dict:
        """Liest die verbleibenden Kaggle-GPU-Stunden (Web-UI-Zahl in Stunden)."""
        result = self._run(["quota"], timeout=120, check=False)
        text = result.output
        hours = 0.0
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:hours|h)\b", text, re.I)
        if match:
            hours = float(match.group(1).replace(",", "."))
        else:
            match = re.search(r"remaining[^0-9]*(\d+(?:[.,]\d+)?)", text, re.I)
            if match:
                hours = float(match.group(1).replace(",", "."))
        return {"ok": result.returncode == 0, "hours": hours, "raw": text.strip()[:500]}

    # -- Diagnose -------------------------------------------------------- #
    def verify(self) -> dict:
        report = {"cli": self.cli, "username": self.username or "(nicht gesetzt)",
                  "key": mask_secret(self.key), "auth_ok": False, "quota": None,
                  "errors": []}
        if not self.username or not self.key:
            report["errors"].append("KAGGLE_USERNAME/KAGGLE_KEY fehlen")
            return report
        try:
            self.ensure_credentials()
            result = self._run(["kernels", "list", "-m"], timeout=180, check=False)
            report["auth_ok"] = result.returncode == 0
            if not report["auth_ok"]:
                report["errors"].append(KaggleError("Kernels-Liste fehlgeschlagen",
                                                    result.output).hint)
        except KaggleError as exc:
            report["errors"].append(exc.hint or str(exc))
        report["quota"] = self.quota()
        if report["quota"]["ok"] and report["quota"]["hours"] == 0.0:
            report["errors"].append("Keine freien GPU-Stunden gemeldet (Quota pruefen)")
        return report


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Kaggle-Zugang pruefen")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--status", default=None, help="Kernel-Slug USER/SLUG")
    parser.add_argument("--quota", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    client = KaggleClient()
    if args.status:
        state = client.kernel_status(args.status)
        print(json.dumps({"slug": state.slug, "status": state.status,
                          "finished": state.finished, "ok": state.ok}, indent=2))
        return 0
    if args.quota:
        print(json.dumps(client.quota(), indent=2))
        return 0
    report = client.verify()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Kaggle-CLI: {report['cli']}")
        print(f"Benutzer:   {report['username']}")
        print(f"Key:        {report['key']}")
        print(f"Zugang:     {'OK' if report['auth_ok'] else 'FEHLER'}")
        if report["quota"]:
            print(f"GPU-Stunden:{report['quota']['hours']:.2f}")
        for error in report["errors"]:
            print(f"  - {error}")
    return 0 if report["auth_ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

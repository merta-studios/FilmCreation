"""Notfall-Waechter: haengende oder gescheiterte Render-Laeufe uebernehmen.

Der Workflow ``check-kaggle-fallback.yml`` laeuft alle 15 Minuten und ruft dieses
Modul auf. Es beantwortet genau eine Frage: *Muss ich jetzt eingreifen?*

Regeln
------
1. Es gibt keinen offenen Render-Lauf -> **nichts tun** (der Cron ist damit
   selbst-begrenzend: kein Lauf, keine Arbeit, kein Verbrauch).
2. Ein Lauf wartet laenger als ``max_queue_minutes`` in der Warteschlange ->
   Lauf abbrechen und direkt auf GitHub neu starten.
3. Ein Lauf rendert laenger als ``max_run_minutes`` -> Kaggle-Kernel pruefen:
   ist er tot (ERROR/CANCELED/UNKNOWN) oder haengt, dann restliche Shots auf
   GitHub rendern (``1-start-render`` mit ``render_target=github``).
4. Der Kernel ist fertig, aber der Schnitt wurde nicht gestartet ->
   ``2-finish-film`` starten.
5. Ein Lauf ist gerade erfolgreich durchgelaufen -> nichts tun.

Alle Entscheidungen werden als ``actions``-Liste zurueckgegeben und im
Step-Summary protokolliert - so ist im Nachhinein nachvollziehbar, warum der
Waechter eingegriffen hat.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if __package__ in (None, ""):  # pragma: no cover - direkter Aufruf
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from importlib import import_module  # noqa: E402

kaggle_client = import_module("1_system.kaggle_bridge.kaggle_client")

RENDER_WORKFLOW = "1-start-render.yml"
FINISH_WORKFLOW = "2-finish-film.yml"

DEFAULT_MAX_RUN_MINUTES = 240
DEFAULT_MAX_QUEUE_MINUTES = 45


@dataclass
class RunInfo:
    run_id: int
    status: str
    conclusion: str
    created_at: datetime
    display_title: str = ""

    @property
    def in_progress(self) -> bool:
        return self.status.lower() in ("in_progress", "queued", "waiting", "pending")

    @property
    def queued(self) -> bool:
        return self.status.lower() in ("queued", "waiting", "pending")


@dataclass
class Action:
    kind: str            # "dispatch", "cancel", "none"
    workflow: str = ""
    reason: str = ""
    inputs: dict = field(default_factory=dict)
    run_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "workflow": self.workflow, "reason": self.reason,
                "inputs": self.inputs, "run_id": self.run_id}


class GitHubCli:
    """Duenne Huelle um ``gh`` (injizierbar fuer Tests)."""

    def __init__(self, cli: str = "gh", repo: Optional[str] = None, timeout: int = 120):
        self.cli = cli
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
        self.timeout = timeout

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        command = [self.cli, *args]
        if self.repo:
            command += ["--repo", self.repo]
        return subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)

    def runs(self, workflow: str, limit: int = 10) -> list[RunInfo]:
        result = self._run(["run", "list", "--workflow", workflow, "--limit", str(limit),
                            "--json", "databaseId,status,conclusion,createdAt,displayTitle"])
        if result.returncode != 0:
            raise RuntimeError(f"gh run list fehlgeschlagen: {result.stderr[:300]}")
        payload = json.loads(result.stdout or "[]")
        runs: list[RunInfo] = []
        for item in payload:
            try:
                created = datetime.fromisoformat(
                    str(item.get("createdAt", "")).replace("Z", "+00:00"))
            except ValueError:
                created = datetime.now(timezone.utc)
            runs.append(RunInfo(run_id=int(item["databaseId"]),
                                status=str(item.get("status", "")),
                                conclusion=str(item.get("conclusion") or ""),
                                created_at=created,
                                display_title=str(item.get("displayTitle") or "")))
        return runs

    def download_artifact(self, run_id: int, name: str, target: Path) -> bool:
        target = Path(target)
        target.mkdir(parents=True, exist_ok=True)
        result = self._run(["run", "download", str(run_id), "-n", name, "-D", str(target)])
        return result.returncode == 0

    def dispatch(self, workflow: str, inputs: dict, ref: Optional[str] = None) -> bool:
        args = ["workflow", "run", workflow]
        for key, value in inputs.items():
            args += ["-f", f"{key}={value}"]
        if ref:
            args += ["--ref", ref]
        result = self._run(args)
        return result.returncode == 0

    def cancel(self, run_id: int) -> bool:
        result = self._run(["run", "cancel", str(run_id)])
        return result.returncode == 0

    def variable(self, name: str) -> str:
        result = self._run(["variable", "get", name])
        return result.stdout.strip() if result.returncode == 0 else ""

    def disable_workflow(self, workflow: str) -> bool:
        return self._run(["workflow", "disable", workflow]).returncode == 0


def _age_minutes(created_at: datetime, now: datetime) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (now - created_at).total_seconds() / 60.0


def read_kaggle_state(folder: Path) -> dict:
    """Liest ``kaggle_status.json`` (Artifact ``kaggle-state`` aus Workflow 1)."""
    for candidate in (Path(folder) / "kaggle_status.json",
                      Path(folder) / "render_output" / "kaggle_status.json"):
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except ValueError:
                return {}
    return {}


def decide(runs: list[RunInfo], now: Optional[datetime] = None,
           state: Optional[dict] = None, kernel_status: str = "",
           kaggle_available: bool = True,
           max_run_minutes: int = DEFAULT_MAX_RUN_MINUTES,
           max_queue_minutes: int = DEFAULT_MAX_QUEUE_MINUTES) -> list[Action]:
    """Reine Entscheidungslogik (ohne Seiteneffekte) - so gut testbar."""
    now = now or datetime.now(timezone.utc)
    state = state or {}
    actions: list[Action] = []
    open_runs = [run for run in runs if run.in_progress]
    if not open_runs:
        return [Action(kind="none", reason="kein offener Render-Lauf")]
    for run in open_runs:
        age = _age_minutes(run.created_at, now)
        if run.queued and age > max_queue_minutes:
            actions.append(Action("cancel", reason=f"Lauf {run.run_id} wartet {age:.0f} min",
                                  run_id=run.run_id))
            actions.append(Action("dispatch", RENDER_WORKFLOW,
                                  reason="Warteschlange haengt - direkt auf GitHub rendern",
                                  inputs={"render_target": "github", "quality": "preview",
                                          "subtitles": "auto"}))
            continue
        if age <= max_run_minutes:
            actions.append(Action("none",
                                  reason=f"Lauf {run.run_id} laeuft seit {age:.0f} min - abwarten"))
            continue
        status_upper = (kernel_status or "").upper()
        kernel_dead = any(word in status_upper for word in
                          ("ERROR", "CANCELED", "CANCELLED", "FAILED", "UNKNOWN"))
        kernel_done = "COMPLETE" in status_upper
        if kernel_done and not state.get("finish_started"):
            actions.append(Action("dispatch", FINISH_WORKFLOW,
                                  reason=f"Kernel fertig, Schnitt fehlt (Lauf {run.run_id})",
                                  inputs={"run_id": run.run_id,
                                          "kaggle_kernel": state.get("kernel", "")}))
        elif kernel_dead or not kaggle_available:
            shots = ",".join(str(s) for s in state.get("missing", []) or []) or "all"
            actions.append(Action("cancel", reason=f"Lauf {run.run_id} haengt "
                                                   f"({age:.0f} min), Kernel tot",
                                  run_id=run.run_id))
            actions.append(Action("dispatch", RENDER_WORKFLOW,
                                  reason="Kaggle ausgefallen - GitHub-Fallback",
                                  inputs={"render_target": "github", "quality": "preview",
                                          "shots": shots, "subtitles": "auto"}))
        else:
            actions.append(Action("none",
                                  reason=f"Kernel laeuft noch ({kernel_status or 'unbekannt'}), "
                                         f"Lauf {age:.0f} min"))
    return actions


def watchdog(repo_state_dir: Path = Path("render_output"), max_run_minutes: int = DEFAULT_MAX_RUN_MINUTES,
             max_queue_minutes: int = DEFAULT_MAX_QUEUE_MINUTES, execute: bool = True,
             gh: Optional[GitHubCli] = None, kaggle: Optional["kaggle_client.KaggleClient"] = None) -> dict:
    """Fuehrt die Entscheidung aus und liefert einen Bericht."""
    gh = gh or GitHubCli()
    report: dict = {"checked_at": datetime.now(timezone.utc).isoformat(),
                    "actions": [], "executed": []}
    if gh.variable("KAGGLE_FALLBACK_ACTIVE").lower() == "false":
        report["actions"].append({"kind": "none",
                                  "reason": "KAGGLE_FALLBACK_ACTIVE=false - Waechter deaktiviert"})
        return report
    try:
        runs = gh.runs(RENDER_WORKFLOW, limit=10)
    except RuntimeError as exc:
        report["error"] = str(exc)
        return report
    open_runs = [run for run in runs if run.in_progress]
    if not open_runs:
        report["actions"] = [Action("none", reason="kein offener Render-Lauf").to_dict()]
        return report

    state: dict = {}
    for run in open_runs:
        if gh.download_artifact(run.run_id, "kaggle-state", repo_state_dir / "state"):
            state = read_kaggle_state(repo_state_dir / "state")
            break
    kernel_status = ""
    kaggle_available = True
    slug = state.get("kernel") or ""
    if slug:
        kaggle = kaggle or kaggle_client.KaggleClient()
        try:
            kernel_status = kaggle.kernel_status(slug).status
        except kaggle_client.KaggleError as exc:
            kernel_status = "UNKNOWN"
            kaggle_available = False
            report["kaggle_error"] = str(exc)

    actions = decide(runs, state=state, kernel_status=kernel_status,
                     kaggle_available=kaggle_available,
                     max_run_minutes=max_run_minutes,
                     max_queue_minutes=max_queue_minutes)
    report["actions"] = [action.to_dict() for action in actions]
    for action in actions:
        if not execute:
            continue
        if action.kind == "dispatch" and action.workflow:
            ok = gh.dispatch(action.workflow, action.inputs)
            report["executed"].append({"action": action.to_dict(), "ok": ok})
        elif action.kind == "cancel" and action.run_id:
            ok = gh.cancel(action.run_id)
            report["executed"].append({"action": action.to_dict(), "ok": ok})
    return report


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Haengende Render-Laeufe uebernehmen")
    parser.add_argument("--max-run-minutes", type=int, default=DEFAULT_MAX_RUN_MINUTES)
    parser.add_argument("--max-queue-minutes", type=int, default=DEFAULT_MAX_QUEUE_MINUTES)
    parser.add_argument("--state-dir", type=Path, default=Path("render_output"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--disable-after-takeover", action="store_true",
                        help="Waechter-Workflow nach erfolgreichem Eingreifen abschalten")
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = watchdog(args.state_dir, args.max_run_minutes, args.max_queue_minutes,
                      execute=not args.dry_run)
    if args.disable_after_takeover and any(
            item.get("ok") for item in report.get("executed", [])):
        gh = GitHubCli()
        disabled = gh.disable_workflow("check-kaggle-fallback.yml")
        report["self_disabled"] = disabled
        print("Hinweis: Waechter-Workflow wurde abgeschaltet "
              f"({'ok' if disabled else 'fehlgeschlagen'}). Zum Wiedereinschalten: "
              "gh workflow enable check-kaggle-fallback.yml")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as stream:
            stream.write("## Kaggle-Waechter\n\n")
            for action in report.get("actions", []):
                stream.write(f"* **{action.get('kind')}** "
                             f"{action.get('workflow') or ''} - {action.get('reason')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

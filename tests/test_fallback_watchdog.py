"""Tests fuer den Kaggle-Notfall-Waechter (reine Entscheidungslogik + Ausfuehrung)."""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

watchdog_mod = importlib.import_module("1_system.kaggle_bridge.fallback_watchdog")
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def run(status="in_progress", minutes_ago=30, run_id=42, base=None):
    return watchdog_mod.RunInfo(run_id=run_id, status=status, conclusion="",
                                created_at=(base or NOW) - timedelta(minutes=minutes_ago))


def kinds(actions):
    return [(action.kind, action.workflow) for action in actions]


def test_no_open_run_does_nothing():
    actions = watchdog_mod.decide([], now=NOW)
    assert kinds(actions) == [("none", "")]


def test_fresh_run_waits():
    actions = watchdog_mod.decide([run(minutes_ago=20)], now=NOW)
    assert kinds(actions) == [("none", "")]


def test_queued_run_is_restarted_on_github():
    actions = watchdog_mod.decide([run(status="queued", minutes_ago=90)], now=NOW)
    assert kinds(actions) == [("cancel", ""), ("dispatch", watchdog_mod.RENDER_WORKFLOW)]
    assert actions[-1].inputs["render_target"] == "github"


def test_dead_kernel_triggers_fallback_with_missing_shots():
    actions = watchdog_mod.decide([run(minutes_ago=300)], now=NOW,
                                  state={"kernel": "u/k", "missing": [7, 8]},
                                  kernel_status="KernelWorkerStatus.ERROR")
    assert kinds(actions) == [("cancel", ""), ("dispatch", watchdog_mod.RENDER_WORKFLOW)]
    assert actions[-1].inputs["shots"] == "7,8"


def test_finished_kernel_starts_finish_workflow():
    actions = watchdog_mod.decide([run(minutes_ago=300)], now=NOW,
                                  state={"kernel": "u/k", "finish_started": False},
                                  kernel_status="KernelWorkerStatus.COMPLETE")
    assert kinds(actions) == [("dispatch", watchdog_mod.FINISH_WORKFLOW)]
    assert actions[0].inputs["run_id"] == 42


def test_running_kernel_is_left_alone():
    actions = watchdog_mod.decide([run(minutes_ago=300)], now=NOW,
                                  kernel_status="KernelWorkerStatus.RUNNING")
    assert kinds(actions) == [("none", "")]


class FakeGh:
    def __init__(self, runs=None, variable="", artifact=None):
        self._runs = runs or []
        self._variable = variable
        self.artifact = artifact or {}
        self.dispatched: list[tuple[str, dict]] = []
        self.cancelled: list[int] = []

    def variable(self, name):
        return self._variable

    def runs(self, workflow, limit=10):
        return self._runs

    def download_artifact(self, run_id, name, target):
        target = Path(target)
        target.mkdir(parents=True, exist_ok=True)
        if self.artifact:
            (target / "kaggle_status.json").write_text(json.dumps(self.artifact))
            return True
        return False

    def dispatch(self, workflow, inputs, ref=None):
        self.dispatched.append((workflow, inputs))
        return True

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        return True


class FakeKaggle:
    def __init__(self, status):
        self.status = status

    def kernel_status(self, slug):
        return watchdog_mod.kaggle_client.KernelState(slug=slug, status=self.status)


def test_watchdog_respects_disable_variable(tmp_path):
    gh = FakeGh(variable="false", runs=[run(minutes_ago=500)])
    report = watchdog_mod.watchdog(tmp_path, gh=gh, kaggle=FakeKaggle("RUNNING"))
    assert "deaktiviert" in report["actions"][0]["reason"]
    assert gh.dispatched == []


def test_watchdog_executes_fallback(tmp_path):
    from datetime import datetime as real_datetime
    gh = FakeGh(runs=[run(minutes_ago=300, base=real_datetime.now(timezone.utc))],
                artifact={"kernel": "u/k", "missing": [3]})
    report = watchdog_mod.watchdog(tmp_path, gh=gh, kaggle=FakeKaggle("KernelWorkerStatus.ERROR"))
    assert gh.cancelled == [42]
    assert gh.dispatched and gh.dispatched[0][0] == watchdog_mod.RENDER_WORKFLOW
    assert gh.dispatched[0][1]["shots"] == "3"
    assert report["executed"]


def test_watchdog_without_open_runs(tmp_path):
    gh = FakeGh(runs=[])
    report = watchdog_mod.watchdog(tmp_path, gh=gh)
    assert report["actions"][0]["kind"] == "none"
    assert gh.dispatched == []

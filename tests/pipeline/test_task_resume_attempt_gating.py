from __future__ import annotations

import types
from pathlib import Path

import quantaalpha.pipeline.factor_mining as fm


class _DummyLoop:
    def __init__(self, *args, **kwargs):
        self._ran = 0
        self.user_initial_direction = None
        self._hyp = None
        self._exp = None
        self._fb = None

    @classmethod
    def load(cls, path, use_local: bool = True, stop_event=None):
        inst = cls()
        inst._loaded_from = str(path)
        return inst

    def run(self, step_n: int, stop_event=None):
        self._ran += int(step_n)

    def _get_trajectory_data(self):
        # Always produce empty experiment so factor_count=0.
        return {"experiment": None, "hypothesis": None, "feedback": None}


def test_task_resume_only_first_attempt(tmp_path, monkeypatch):
    # Ensure _run_evolution_task will execute attempt=2 (max_empty_retries=1).
    task = {
        "phase": fm.RoundPhase.ORIGINAL,
        "direction_id": 0,
        "parent_trajectories": [],
        "strategy_suffix": "",
        "round_idx": 0,
    }

    # Redirect logs to tmp branch directory.
    log_root = tmp_path / "logroot"
    log_root.mkdir()
    branch_log = log_root / "original_00_00"
    (branch_log / "__session__").mkdir(parents=True)
    snap = branch_log / "__session__" / "0" / "0_factor_propose"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_bytes(b"x")  # existence only; load is monkeypatched.

    monkeypatch.setattr(fm, "AlphaAgentLoop", _DummyLoop)

    # Force resume path to be found on attempt 1.
    monkeypatch.setattr(
        fm,
        "_count_experiment_factors",
        lambda _exp: 0,
    )

    # Patch helpers in quantaalpha.utils.workflow.
    import quantaalpha.utils.workflow as wf

    monkeypatch.setattr(wf, "find_latest_session_snapshot", lambda _p: snap)
    monkeypatch.setattr(wf, "count_steps_done", lambda _s: 5)  # completed

    # Run with 5 steps per task; attempt 1 will "resume" and run 0 steps,
    # attempt 2 must NOT resume and must run 5 steps fresh.
    out = fm._run_evolution_task(
        task=task,
        directions=["dir0"],
        step_n=5,
        use_local=True,
        user_direction="u",
        log_root=str(log_root),
        stop_event=None,
        quality_gate_cfg={},
        max_empty_retries=1,
    )
    assert out.get("attempt") == 2


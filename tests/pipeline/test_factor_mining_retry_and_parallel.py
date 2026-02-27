from types import SimpleNamespace

from quantaalpha.pipeline import factor_mining
from quantaalpha.pipeline.evolution import RoundPhase


def test_run_evolution_task_retries_until_non_empty(monkeypatch):
    init_calls = {"count": 0}

    class FakeLoop:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            init_calls["count"] += 1
            self._idx = init_calls["count"]

        def run(self, step_n, stop_event):  # noqa: ARG002
            return None

        def _get_trajectory_data(self):
            if self._idx == 1:
                return {"experiment": SimpleNamespace(sub_tasks=[])}
            return {"experiment": SimpleNamespace(sub_tasks=[object()])}

    monkeypatch.setattr(factor_mining, "AlphaAgentLoop", FakeLoop)
    monkeypatch.setattr(
        factor_mining.StrategyTrajectory,
        "generate_id",
        staticmethod(lambda direction_id, round_idx, phase: f"{direction_id}-{round_idx}-{phase.value}"),
    )

    task = {
        "phase": RoundPhase.ORIGINAL,
        "direction_id": 0,
        "round_idx": 0,
        "strategy_suffix": "",
        "parent_trajectories": [],
    }
    result = factor_mining._run_evolution_task(
        task=task,
        directions=["d0"],
        step_n=5,
        use_local=True,
        user_direction="u0",
        log_root="",
        stop_event=None,
        quality_gate_cfg={},
        max_empty_retries=1,
    )

    assert init_calls["count"] == 2
    assert result["attempt"] == 2
    assert result["factor_count"] == 1


def test_run_evolution_task_sets_default_skip_reason_after_retry(monkeypatch):
    class FakeLoop:
        def __init__(self, *args, **kwargs):  # noqa: ARG002
            pass

        def run(self, step_n, stop_event):  # noqa: ARG002
            return None

        def _get_trajectory_data(self):
            return {"experiment": SimpleNamespace(sub_tasks=[])}

    monkeypatch.setattr(factor_mining, "AlphaAgentLoop", FakeLoop)
    monkeypatch.setattr(
        factor_mining.StrategyTrajectory,
        "generate_id",
        staticmethod(lambda direction_id, round_idx, phase: f"{direction_id}-{round_idx}-{phase.value}"),
    )

    task = {
        "phase": RoundPhase.ORIGINAL,
        "direction_id": 0,
        "round_idx": 0,
        "strategy_suffix": "",
        "parent_trajectories": [],
    }
    result = factor_mining._run_evolution_task(
        task=task,
        directions=["d0"],
        step_n=5,
        use_local=True,
        user_direction="u0",
        log_root="",
        stop_event=None,
        quality_gate_cfg={},
        max_empty_retries=1,
    )

    assert result["attempt"] == 2
    assert result["factor_count"] == 0
    assert result["skip_reason"] == "zero_factors_after_retry"


def test_run_tasks_parallel_respects_worker_cap_and_retry_budget(monkeypatch):
    started = {"count": 0}
    first_get_started = {"count": None}
    observed_retry_budgets = []

    class FakeQueue:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

        def get(self):
            if first_get_started["count"] is None:
                first_get_started["count"] = started["count"]
            return self.items.pop(0)

    class FakeProcess:
        def __init__(self, target, args):
            self.target = target
            self.args = args
            self._alive = False

        def start(self):
            started["count"] += 1
            self._alive = True
            self.target(*self.args)
            self._alive = False

        def join(self, timeout=5):  # noqa: ARG002
            return None

        def is_alive(self):
            return self._alive

        def terminate(self):
            self._alive = False

    def fake_worker(
        task,
        directions,
        step_n,
        use_local,
        user_direction,
        log_root,
        result_queue,
        task_idx,
        max_empty_retries,
        quality_gate_cfg,
    ):  # noqa: ARG001
        observed_retry_budgets.append(max_empty_retries)
        result_queue.put(
            {
                "success": True,
                "task_idx": task_idx,
                "task": task,
                "traj_data": {"experiment": SimpleNamespace(sub_tasks=[object()])},
            }
        )

    monkeypatch.setattr(factor_mining, "Queue", FakeQueue)
    monkeypatch.setattr(factor_mining, "Process", FakeProcess)
    monkeypatch.setattr(factor_mining, "_parallel_task_worker", fake_worker)

    tasks = [
        {"phase": RoundPhase.ORIGINAL, "direction_id": i, "round_idx": 0, "parent_trajectories": []}
        for i in range(3)
    ]
    results = factor_mining._run_tasks_parallel(
        tasks=tasks,
        directions=["d0", "d1", "d2"],
        step_n=5,
        use_local=True,
        user_direction="u0",
        log_root="",
        quality_gate_cfg={},
        max_parallel_workers=2,
        max_empty_retries=4,
    )

    assert len(results) == 3
    assert observed_retry_budgets == [4, 4, 4]
    assert first_get_started["count"] == 2

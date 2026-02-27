from __future__ import annotations

import os

from quantaalpha.log import logger
from quantaalpha.utils.workflow import LoopBase, LoopMeta, count_steps_done, find_latest_session_snapshot


class DummyLoop(LoopBase, metaclass=LoopMeta):
    def __init__(self):
        self.value = 0
        super().__init__()

    def step_a(self, prev_out):
        self.value += 1
        return self.value

    def step_b(self, prev_out):
        self.value += 1
        return self.value


def test_find_latest_session_snapshot_and_count_steps_done(tmp_path, monkeypatch):
    logger.set_trace_path(tmp_path)
    monkeypatch.setenv("SESSION_DUMP_TXT", "true")

    loop = DummyLoop()
    loop.run(step_n=1)

    snap = find_latest_session_snapshot(tmp_path)
    assert snap is not None
    assert snap.exists()
    assert not str(snap).endswith(".txt")

    loaded = DummyLoop.load(snap)
    assert count_steps_done(loaded) == 1
    assert getattr(loaded, "value", None) == 1

    loaded.run(step_n=1)
    assert count_steps_done(loaded) == 2
    assert getattr(loaded, "value", None) == 2


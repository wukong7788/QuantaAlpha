"""
This is a class that try to store/resume/traceback the workflow session


Postscripts:
- Originally, I want to implement it in a more general way with python generator.
  However, Python generator is not picklable (dill does not support pickle as well)

"""

import datetime
import os
import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tqdm.auto import tqdm

from quantaalpha.core.exception import CoderError
from quantaalpha.log import logger
import threading

class LoopMeta(type):
    @staticmethod
    def _get_steps(bases):
        """
        Recursively get all the `steps` from the base classes and combine them into a single list.

        Args:
            bases (tuple): A tuple of base classes.

        Returns:
            List[Callable]: A list of steps combined from all base classes.
        """
        # import pdb; pdb.set_trace()
        steps = []
        for base in bases:
            for step in LoopMeta._get_steps(base.__bases__) + getattr(base, "steps", []):
                if step not in steps:
                    steps.append(step)
        return steps

    def __new__(cls, clsname, bases, attrs):
        """
        Create a new class with combined steps from base classes and current class.

        Args:
            clsname (str): Name of the new class.
            bases (tuple): Base classes.
            attrs (dict): Attributes of the new class.

        Returns:
            LoopMeta: A new instance of LoopMeta.
        """
        steps = LoopMeta._get_steps(bases)  # all the base classes of parents
        for name, attr in attrs.items():
            # Skip methods whose names start with underscore (private/protected)
            if not name.startswith("_") and isinstance(attr, Callable):
                if name not in steps:
                    # NOTE: if we override the step in the subclass
                    # Then it is not the new step. So we skip it.
                    steps.append(name)
        attrs["steps"] = steps
        return super().__new__(cls, clsname, bases, attrs)


@dataclass
class LoopTrace:
    start: datetime.datetime  # the start time of the trace
    end: datetime.datetime  # the end time of the trace
    # TODO: more information about the trace


class LoopBase:
    steps: list[Callable]  # a list of steps to work on
    loop_trace: dict[int, list[LoopTrace]]

    skip_loop_error: tuple[Exception] = field(
        default_factory=tuple
    )  # you can define a list of error that will skip current loop

    def __init__(self):
        self.loop_idx = 0  # current loop index
        self.step_idx = 0  # the index of next step to be run
        self.loop_prev_out = {}  # the step results of current loop
        self.loop_trace = defaultdict(list[LoopTrace])  # the key is the number of loop
        self.session_folder = logger.log_trace_path / "__session__"

    def run(self, step_n: int | None = None, stop_event: threading.Event = None):
        """

        Parameters
        ----------
        step_n : int | None
            How many steps to run;
            `None` indicates to run forever until error or KeyboardInterrupt
        """
        with tqdm(total=len(self.steps), desc="Workflow Progress", unit="step") as pbar:
            while True:
                if step_n is not None:
                    if step_n <= 0:
                        break
                    step_n -= 1

                li, si = self.loop_idx, self.step_idx

                start = datetime.datetime.now(datetime.timezone.utc)

                name = self.steps[si]
                func = getattr(self, name)
                try:
                    self.loop_prev_out[name] = func(self.loop_prev_out)
                    
                    # TODO: Fix the error logger.exception(f"Skip loop {li} due to {e}")
                except self.skip_loop_error as e:
                    logger.warning(f"Skip loop {li} due to {e}")
                    self.loop_idx += 1
                    self.step_idx = 0
                    continue
                except CoderError as e:
                    logger.warning(f"Traceback loop {li} due to {e}")
                    self.step_idx = 0
                    continue

                end = datetime.datetime.now(datetime.timezone.utc)

                self.loop_trace[li].append(LoopTrace(start, end))

                # Update tqdm progress bar
                pbar.set_postfix(loop_index=li, step_index=si, step_name=name)
                pbar.update(1)

                # index increase and save session
                self.step_idx = (self.step_idx + 1) % len(self.steps)
                if self.step_idx == 0:  # reset to step 0 in next round
                    self.loop_idx += 1
                    self.loop_prev_out = {}
                    pbar.reset()  # reset the progress bar for the next loop
                self.dump(self.session_folder / f"{li}" / f"{si}_{name}")  # save a snapshot after the session
                
                if stop_event is not None and stop_event.is_set():
                    # break
                    raise Exception("Mining stopped by user")
                    
                
    def dump(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self, f)
        self._dump_text_snapshot(path)

    @staticmethod
    def _env_truthy(name: str, default: str = "false") -> bool:
        v = os.getenv(name, default)
        return str(v).strip().lower() in {"1", "true", "yes", "on"}

    def _dump_text_snapshot(self, path: Path) -> None:
        """
        Optional text snapshot for easier manual inspection.
        Controlled by env `SESSION_DUMP_TXT` (default: false).
        """
        if not self._env_truthy("SESSION_DUMP_TXT", "false"):
            return

        lines = []
        lines.append("Loop Session Snapshot")
        lines.append(f"saved_at_utc={datetime.datetime.now(datetime.timezone.utc).isoformat()}")
        lines.append(f"loop_idx={self.loop_idx}")
        lines.append(f"step_idx={self.step_idx}")
        lines.append(f"steps={self.steps}")

        if self.loop_prev_out:
            lines.append("loop_prev_out:")
            for k, v in self.loop_prev_out.items():
                lines.append(f"  - {k}: {type(v).__name__}")
        else:
            lines.append("loop_prev_out: <empty>")

        if self.loop_trace:
            lines.append("loop_trace_summary:")
            for li in sorted(self.loop_trace.keys()):
                traces = self.loop_trace[li]
                durations = [(t.end - t.start).total_seconds() for t in traces]
                lines.append(
                    f"  - loop={li}, steps={len(traces)}, total_sec={sum(durations):.2f}, "
                    f"durations_sec={[round(x, 2) for x in durations]}"
                )
        else:
            lines.append("loop_trace_summary: <empty>")

        txt_path = Path(str(path) + ".txt")
        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path):
        path = Path(path)
        with path.open("rb") as f:
            session = pickle.load(f)
        logger.set_trace_path(session.session_folder.parent)

        max_loop = max(session.loop_trace.keys())
        logger.storage.truncate(time=session.loop_trace[max_loop][-1].end)
        return session


def count_steps_done(session: "LoopBase") -> int:
    """
    Return total executed steps for a session.

    LoopBase maintains:
    - loop_idx: number of fully completed loops
    - step_idx: index of the next step to execute within the current loop
    """
    try:
        steps_per_loop = len(getattr(session, "steps", []) or [])
    except Exception:
        steps_per_loop = 0
    if steps_per_loop <= 0:
        return 0
    try:
        loop_idx = int(getattr(session, "loop_idx", 0) or 0)
    except Exception:
        loop_idx = 0
    try:
        step_idx = int(getattr(session, "step_idx", 0) or 0)
    except Exception:
        step_idx = 0
    return max(0, loop_idx) * steps_per_loop + max(0, step_idx)


def find_latest_session_snapshot(trace_path: str | Path) -> Path | None:
    """
    Find the latest workflow session snapshot under <trace_path>/__session__/**.

    Returns:
        Path to a pickle snapshot file, or None if no snapshot exists.
    """
    base = Path(trace_path) / "__session__"
    if not base.exists() or not base.is_dir():
        return None

    best: Path | None = None
    best_mtime = -1.0
    for root, _dirs, files in os.walk(base):
        for fn in files:
            if fn.endswith(".txt"):
                continue
            fp = Path(root) / fn
            try:
                if not fp.is_file():
                    continue
                mtime = fp.stat().st_mtime
            except Exception:
                continue
            if mtime > best_mtime:
                best = fp
                best_mtime = mtime
    return best

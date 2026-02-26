"""
Factor workflow with session control and evolution support.

Supports three round phases:
- Original: Initial exploration in each direction
- Mutation: Orthogonal exploration from parent trajectories
- Crossover: Hybrid strategies from multiple parents

Supports parallel execution within each phase when enabled.
"""

from typing import Any
from pathlib import Path
import fire
import signal
import sys
import threading
from multiprocessing import Process, Queue
from functools import wraps
import time
import ctypes
import os
import pickle
from quantaalpha.pipeline.settings import ALPHA_AGENT_FACTOR_PROP_SETTING
from quantaalpha.pipeline.planning import generate_parallel_directions
from quantaalpha.pipeline.planning import load_run_config
from quantaalpha.pipeline.loop import AlphaAgentLoop
from quantaalpha.pipeline.evolution import (
    EvolutionController, 
    EvolutionConfig,
    StrategyTrajectory,
    RoundPhase,
)
from quantaalpha.core.exception import FactorEmptyError
from quantaalpha.log import logger
from quantaalpha.log.time import measure_time
from quantaalpha.llm.config import LLM_SETTINGS


def _is_no_space_error(err: Exception | str) -> bool:
    """Whether an exception/text indicates disk-full (errno 28)."""
    if isinstance(err, OSError) and getattr(err, "errno", None) == 28:
        return True
    text = str(err).lower()
    return (
        "no space left on device" in text
        or "errno 28" in text
        or "[errno 28]" in text
    )


def _is_truthy(value: Any) -> bool:
    """Parse env/config flags robustly."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}




def force_timeout():
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            seconds = LLM_SETTINGS.factor_mining_timeout
            def handle_timeout(signum, frame):
                logger.error(f"Process terminated: timeout exceeded ({seconds}s)")
                sys.exit(1)

            signal.signal(signal.SIGALRM, handle_timeout)
            signal.alarm(seconds)

            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
            return result
        return wrapper
    return decorator


def _run_branch(
    direction: str | None,
    step_n: int,
    use_local: bool,
    idx: int,
    log_root: str,
    log_prefix: str,
    quality_gate_cfg: dict = None,
):
    if log_root:
        branch_name = f"{log_prefix}_{idx:02d}"
        branch_log = Path(log_root) / branch_name
        branch_log.mkdir(parents=True, exist_ok=True)
        logger.set_trace_path(branch_log)
    model_loop = AlphaAgentLoop(
        ALPHA_AGENT_FACTOR_PROP_SETTING,
        potential_direction=direction,
        stop_event=None,
        use_local=use_local,
        quality_gate_config=quality_gate_cfg or {},
    )
    model_loop.user_initial_direction = direction
    model_loop.run(step_n=step_n, stop_event=None)


def _count_experiment_factors(experiment: Any) -> int:
    """Safely count generated factors from an experiment object."""
    if experiment is None:
        return 0
    sub_tasks = getattr(experiment, "sub_tasks", None)
    if not sub_tasks:
        return 0
    try:
        return len(sub_tasks)
    except Exception:
        return 0


def _run_evolution_task(
    task: dict[str, Any],
    directions: list[str],
    step_n: int,
    use_local: bool,
    user_direction: str | None,
    log_root: str,
    stop_event: threading.Event | None,
    quality_gate_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run a single evolution task (one small loop).

    Args:
        task: Evolution task descriptor
        directions: List of original directions
        step_n: Steps per round
        use_local: Use local backtest
        user_direction: User initial direction
        log_root: Log root directory
        stop_event: Stop event
        quality_gate_cfg: Quality gate config

    Returns:
        Dict containing trajectory data
    """
    phase = task["phase"]
    direction_id = task["direction_id"]
    strategy_suffix = task.get("strategy_suffix", "")
    round_idx = task["round_idx"]
    parent_trajectories = task.get("parent_trajectories", [])
    
    # Resolve direction by phase
    if phase == RoundPhase.ORIGINAL:
        direction = directions[direction_id] if direction_id < len(directions) else None
    elif phase == RoundPhase.MUTATION:
        direction = directions[direction_id] if direction_id < len(directions) else None
    else:  # CROSSOVER
        direction = None

    parent_ids = [p.trajectory_id for p in parent_trajectories]

    if log_root:
        branch_name = f"{phase.value}_{round_idx:02d}_{direction_id:02d}"
        branch_log = Path(log_root) / branch_name
        branch_log.mkdir(parents=True, exist_ok=True)
        logger.set_trace_path(branch_log)

    logger.info(f"Starting evolution task: phase={phase.value}, round={round_idx}, direction={direction_id}")

    max_empty_retries = 1
    last_traj_data: dict[str, Any] | None = None

    for attempt in range(1, max_empty_retries + 2):
        if attempt > 1:
            logger.warning(
                f"Task retry due to empty factors: phase={phase.value}, round={round_idx}, "
                f"direction={direction_id}, attempt={attempt}/{max_empty_retries + 1}"
            )

        trajectory_id = StrategyTrajectory.generate_id(direction_id, round_idx, phase)

        model_loop = AlphaAgentLoop(
            ALPHA_AGENT_FACTOR_PROP_SETTING,
            potential_direction=direction,
            stop_event=stop_event,
            use_local=use_local,
            strategy_suffix=strategy_suffix,
            evolution_phase=phase.value,
            trajectory_id=trajectory_id,
            parent_trajectory_ids=parent_ids,
            direction_id=direction_id,
            round_idx=round_idx,
            quality_gate_config=quality_gate_cfg or {},
        )
        model_loop.user_initial_direction = user_direction

        # Run one small loop (5 steps)
        model_loop.run(step_n=step_n, stop_event=stop_event)

        traj_data = model_loop._get_trajectory_data()
        factor_count = _count_experiment_factors(traj_data.get("experiment"))
        traj_data["task"] = task
        traj_data["factor_count"] = factor_count
        traj_data["attempt"] = attempt
        last_traj_data = traj_data

        if factor_count > 0:
            return traj_data

        logger.warning(
            f"Empty factor branch detected: phase={phase.value}, round={round_idx}, "
            f"direction={direction_id}, attempt={attempt}/{max_empty_retries + 1}"
        )

    assert last_traj_data is not None
    last_traj_data["skip_reason"] = "zero_factors_after_retry"
    return last_traj_data


def _parallel_task_worker(
    task: dict[str, Any],
    directions: list[str],
    step_n: int,
    use_local: bool,
    user_direction: str | None,
    log_root: str,
    result_queue: Queue,
    task_idx: int,
):
    """
    Worker for parallel evolution tasks. Runs one evolution task in a separate process and puts result in queue.
    Args: task, directions, step_n, use_local, user_direction, log_root, result_queue, task_idx.
    """
    try:
        from quantaalpha.core.conf import RD_AGENT_SETTINGS
        RD_AGENT_SETTINGS.use_file_lock = False
        RD_AGENT_SETTINGS.pickle_cache_folder_path_str = str(
            Path(log_root) / f"pickle_cache_{task_idx}"
        )

        traj_data = _run_evolution_task(
            task=task,
            directions=directions,
            step_n=step_n,
            use_local=use_local,
            user_direction=user_direction,
            log_root=log_root,
            stop_event=None,
        )
        result_queue.put({
            "success": True,
            "task_idx": task_idx,
            "task": task,
            "traj_data": traj_data,
        })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        result_queue.put({
            "success": False,
            "task_idx": task_idx,
            "task": task,
            "error": str(e),
            "traceback": tb,
            "fatal_no_space": _is_no_space_error(e) or _is_no_space_error(tb),
        })


def _serialize_task_for_parallel(task: dict[str, Any]) -> dict[str, Any]:
    """Serialize task for use in child process (parent_trajectories are complex objects)."""
    serialized = task.copy()
    
    # RoundPhase -> string
    if "phase" in serialized and isinstance(serialized["phase"], RoundPhase):
        serialized["phase"] = serialized["phase"]
    
    # Convert parent_trajectories to serializable info
    if "parent_trajectories" in serialized:
        serialized["parent_trajectory_ids"] = [
            p.trajectory_id for p in serialized.get("parent_trajectories", [])
        ]
        # Child process does not need full trajectory objects; strategy_suffix has required info
        serialized["parent_trajectories"] = []
    
    return serialized


def _run_tasks_parallel(
    tasks: list[dict[str, Any]],
    directions: list[str],
    step_n: int,
    use_local: bool,
    user_direction: str | None,
    log_root: str,
) -> list[dict[str, Any]]:
    """
    Run multiple evolution tasks in parallel.
    Returns list of results, each with task and traj_data.
    """
    if not tasks:
        return []
    
    result_queue = Queue()
    processes = []
    
    logger.info(f"Starting {len(tasks)} parallel evolution tasks")

    for idx, task in enumerate(tasks):
        serialized_task = _serialize_task_for_parallel(task)
        
        p = Process(
            target=_parallel_task_worker,
            args=(
                serialized_task,
                directions,
                step_n,
                use_local,
                user_direction,
                log_root,
                result_queue,
                idx,
            ),
        )
        p.start()
        processes.append(p)
        logger.info(f"Started task {idx}: phase={task['phase'].value}, direction={task['direction_id']}")

    results = []
    fatal_no_space_result = None
    for _ in range(len(tasks)):
        result = result_queue.get()
        if result["success"]:
            original_task = tasks[result["task_idx"]]
            result["task"] = original_task
            result["traj_data"]["task"] = original_task
            results.append(result)
            logger.info(f"Task {result['task_idx']} completed")
        else:
            logger.error(f"Task {result['task_idx']} failed: {result['error']}")
            logger.error(result.get('traceback', ''))
            if result.get("fatal_no_space", False):
                fatal_no_space_result = result
                logger.error(
                    "Fatal disk error detected in parallel task "
                    f"{result['task_idx']} (No space left on device)."
                )
                break

    if fatal_no_space_result is not None:
        for p in processes:
            if p.is_alive():
                p.terminate()
        for p in processes:
            p.join(timeout=5)
        raise OSError(
            28,
            f"No space left on device during parallel task {fatal_no_space_result['task_idx']}: "
            f"{fatal_no_space_result.get('error', '')}",
        )

    for p in processes:
        p.join()

    logger.info(f"Parallel tasks done: {len(results)}/{len(tasks)} succeeded")
    
    return results


def run_evolution_loop(
    initial_direction: str | None,
    evolution_cfg: dict[str, Any],
    exec_cfg: dict[str, Any],
    planning_cfg: dict[str, Any],
    stop_event: threading.Event | None = None,
    quality_gate_cfg: dict[str, Any] | None = None,
):
    """
    Run evolution loop: Original -> Mutation -> Crossover -> Mutation -> ...
    Supports parallel execution per phase.
    """
    quality_gate_cfg = quality_gate_cfg or {}
    from quantaalpha.core.conf import RD_AGENT_SETTINGS
    RD_AGENT_SETTINGS.use_file_lock = False
    logger.info("Evolution mode: file lock disabled to avoid deadlock")

    # Parse config
    num_directions = int(planning_cfg.get("num_directions", 2))
    max_rounds = int(evolution_cfg.get("max_rounds", 10))
    crossover_size = int(evolution_cfg.get("crossover_size", 2))
    crossover_n = int(evolution_cfg.get("crossover_n", 3))
    steps_per_loop = int(exec_cfg.get("steps_per_loop", 5))
    use_local = bool(exec_cfg.get("use_local", True))
    
    mutation_enabled = bool(evolution_cfg.get("mutation_enabled", True))
    crossover_enabled = bool(evolution_cfg.get("crossover_enabled", True))
    parent_selection_strategy = str(evolution_cfg.get("parent_selection_strategy", "best"))
    top_percent_threshold = float(evolution_cfg.get("top_percent_threshold", 0.3))
    log_root = str(logger.log_trace_path)
    parallel_enabled = bool(evolution_cfg.get("parallel_enabled", False))
    fresh_start = bool(evolution_cfg.get("fresh_start", True))
    cleanup_on_finish = bool(evolution_cfg.get("cleanup_on_finish", False))
    relay_enabled = _is_truthy(evolution_cfg.get("relay_enabled", False)) or _is_truthy(
        os.getenv("QUANTA_ENABLE_RELAY", "0")
    )
    relay_mode = str(
        os.getenv("QUANTA_RELAY_MODE", evolution_cfg.get("relay_mode", "relay"))
    ).strip().lower()
    if relay_mode not in {"relay", "resume"}:
        if relay_enabled:
            logger.warning(f"Invalid relay mode={relay_mode!r}, fallback to 'relay'")
        relay_mode = "relay"
    relay_chunk_rounds = int(evolution_cfg.get("relay_chunk_rounds", 5))
    relay_chunk_rounds_env = os.getenv("QUANTA_RELAY_CHUNK_ROUNDS")
    if relay_chunk_rounds_env is not None:
        try:
            relay_chunk_rounds = int(relay_chunk_rounds_env)
        except ValueError:
            logger.warning(
                f"Invalid QUANTA_RELAY_CHUNK_ROUNDS={relay_chunk_rounds_env!r}, "
                f"fallback to {relay_chunk_rounds}"
            )
    if relay_chunk_rounds <= 0:
        logger.warning(f"Invalid relay chunk rounds={relay_chunk_rounds}, force to 1")
        relay_chunk_rounds = 1
    if relay_enabled and fresh_start:
        logger.info("Relay mode enabled: overriding evolution.fresh_start=true -> false")
        fresh_start = False

    state_path = Path(log_root) / "evolution_state.json"
    pool_save_path = Path(log_root) / "trajectory_pool.json"
    mutation_prompt_path = Path(__file__).parent / "prompts" / "evolution_prompts.yaml"
    force_relay_resume = _is_truthy(os.getenv("QUANTA_FORCE_RELAY_RESUME", "0"))
    resume_state_data: dict[str, Any] | None = None
    restored_directions: list[Any] | None = None
    saved_run_control: dict[str, Any] | None = None
    if relay_enabled and relay_mode == "resume" and not state_path.exists():
        raise ValueError(
            "Resume mode requires existing evolution_state.json, "
            f"but state file not found: {state_path}. "
            "Use relay mode to start the first leg."
        )
    if relay_enabled and state_path.exists():
        import json

        with open(state_path, "r", encoding="utf-8") as state_file:
            loaded_state = json.load(state_file)
        if isinstance(loaded_state, dict):
            resume_state_data = loaded_state
            maybe_run_control = loaded_state.get("run_control")
            if isinstance(maybe_run_control, dict):
                saved_run_control = maybe_run_control
            saved_directions = loaded_state.get("directions")
            if isinstance(saved_directions, list) and saved_directions:
                restored_directions = saved_directions
                logger.info(
                    f"{relay_mode.title()} mode: restored {len(restored_directions)} directions from saved state"
                )
            else:
                has_progress = bool(loaded_state.get("directions_completed")) or int(
                    loaded_state.get("current_round", 0) or 0
                ) > 0
                if has_progress and not force_relay_resume:
                    raise ValueError(
                        "Saved state missing directions for an in-progress run; "
                        "cannot safely resume without direction drift. "
                        "Set QUANTA_FORCE_RELAY_RESUME=1 to bypass this check."
                    )
                if has_progress:
                    logger.warning(
                        "Saved state missing directions for in-progress run. "
                        "Proceeding due to QUANTA_FORCE_RELAY_RESUME=1."
                    )
                else:
                    logger.warning(
                        "Saved state has no directions yet; regenerate directions for round-0 start."
                    )

    # Generate initial directions (or restore from relay state)
    planning_enabled = bool(planning_cfg.get("enabled", False))
    prompt_file = planning_cfg.get("prompt_file") or "planning_prompts.yaml"
    prompt_path = Path(__file__).parent / "prompts" / str(prompt_file)

    if restored_directions is not None:
        directions = restored_directions
        logger.info(f"Using restored directions ({len(directions)}) for state resume")
    elif planning_enabled and initial_direction:
        directions = generate_parallel_directions(
            initial_direction=initial_direction,
            n=num_directions,
            prompt_file=prompt_path,
            max_attempts=int(planning_cfg.get("max_attempts", 5)),
            use_llm=bool(planning_cfg.get("use_llm", True)),
            allow_fallback=bool(planning_cfg.get("allow_fallback", True)),
        )
    elif planning_enabled:
        directions = [None] * num_directions
    else:
        directions = [initial_direction] if initial_direction else [None]

    logger.info(f"Generated {len(directions)} exploration directions")
    for i, d in enumerate(directions):
        logger.info(f"  Direction {i}: {d}")
    
    logger.info(f"Trajectory pool path: {pool_save_path} (fresh_start={fresh_start})")

    config = EvolutionConfig(
        num_directions=len(directions),
        steps_per_loop=steps_per_loop,
        max_rounds=max_rounds,
        mutation_enabled=mutation_enabled,
        crossover_enabled=crossover_enabled,
        crossover_size=crossover_size,
        crossover_n=crossover_n,
        prefer_diverse_crossover=True,
        parent_selection_strategy=parent_selection_strategy,
        top_percent_threshold=top_percent_threshold,
        parallel_enabled=parallel_enabled,
        pool_save_path=str(pool_save_path),
        mutation_prompt_path=str(mutation_prompt_path) if mutation_prompt_path.exists() else None,
        crossover_prompt_path=str(mutation_prompt_path) if mutation_prompt_path.exists() else None,
        fresh_start=fresh_start,
    )

    if relay_enabled and isinstance(resume_state_data, dict):
        saved_cfg = resume_state_data.get("config")
        if isinstance(saved_cfg, dict):
            current_cfg = {
                "num_directions": len(directions),
                "max_rounds": max_rounds,
                "mutation_enabled": mutation_enabled,
                "crossover_enabled": crossover_enabled,
                "crossover_size": crossover_size,
                "crossover_n": crossover_n,
                "prefer_diverse_crossover": True,
                "parent_selection_strategy": parent_selection_strategy,
                "top_percent_threshold": top_percent_threshold,
                "parallel_enabled": parallel_enabled,
            }
            mismatch_items: list[str] = []
            for key, current_val in current_cfg.items():
                if key not in saved_cfg:
                    continue
                if saved_cfg.get(key) != current_val:
                    mismatch_items.append(
                        f"{key}: saved={saved_cfg.get(key)!r}, current={current_val!r}"
                    )
            if mismatch_items:
                mismatch_msg = (
                    "State resume config mismatch detected: " + "; ".join(mismatch_items)
                )
                if force_relay_resume:
                    logger.warning(
                        mismatch_msg + " (continue due to QUANTA_FORCE_RELAY_RESUME=1)"
                    )
                else:
                    raise ValueError(
                        mismatch_msg
                        + ". Set QUANTA_FORCE_RELAY_RESUME=1 to force resume."
                    )

    controller = EvolutionController(config)
    relay_pending_stop_round: int | None = None
    relay_leg_index = 0
    if relay_enabled:
        run_mode_name = "Relay" if relay_mode == "relay" else "Resume"
        logger.info(f"{run_mode_name} mode enabled: state_path={state_path}")
        if state_path.exists():
            state_data = controller.load_state(state_path) or {}
            meta = state_data.get("meta") if isinstance(state_data, dict) else {}
            if not isinstance(meta, dict):
                meta = {}
            maybe_run_control = state_data.get("run_control") if isinstance(state_data, dict) else None
            if isinstance(maybe_run_control, dict):
                saved_run_control = maybe_run_control
            prev_experiment_id = meta.get("experiment_id") or "unknown"
            prev_saved_at = meta.get("saved_at_utc") or "unknown"
            prev_log_trace = meta.get("log_trace_path") or str(state_path.parent)
            logger.info(
                f"{run_mode_name} resume source: "
                f"previous_experiment_id={prev_experiment_id}, "
                f"state_saved_at_utc={prev_saved_at}, "
                f"previous_log_trace_path={prev_log_trace}"
            )
            logger.info(f"{run_mode_name} resume state loaded successfully")
        else:
            existing_trajs = len(controller.pool.get_all())
            if existing_trajs > 0:
                logger.warning(
                    f"{run_mode_name} mode found existing trajectory pool but no evolution_state.json; "
                    "continuing from round 0."
                )
            else:
                logger.info(
                    f"{run_mode_name} mode: no existing state found, starting from round 0"
                )

        state_round_raw = controller.get_current_state().get("round", 0)
        try:
            relay_start_round = int(state_round_raw or 0)
        except Exception:
            relay_start_round = 0

        prev_pending_stop_round: int | None = None
        prev_leg_index = 0
        if isinstance(saved_run_control, dict):
            try:
                pending_raw = saved_run_control.get("pending_stop_round")
                if pending_raw is not None:
                    prev_pending_stop_round = int(pending_raw)
            except Exception:
                prev_pending_stop_round = None
            try:
                prev_leg_index = int(saved_run_control.get("leg_index", 0) or 0)
            except Exception:
                prev_leg_index = 0

        if relay_mode == "resume":
            relay_pending_stop_round = max_rounds
            relay_leg_index = max(prev_leg_index, 1)
            if relay_start_round >= max_rounds:
                logger.info(
                    "Resume target already complete: "
                    f"current_round={relay_start_round}, max_rounds={max_rounds}"
                )
            else:
                logger.info(
                    "Resume target: "
                    f"current_round={relay_start_round}, "
                    f"pending_stop_round={relay_pending_stop_round}, max_rounds={max_rounds}"
                )
        elif relay_start_round >= max_rounds:
            relay_pending_stop_round = max_rounds
            relay_leg_index = max(prev_leg_index, 1)
            logger.info(
                "Relay target already complete: "
                f"current_round={relay_start_round}, max_rounds={max_rounds}"
            )
        elif (
            prev_pending_stop_round is not None
            and relay_start_round < prev_pending_stop_round <= max_rounds
        ):
            relay_pending_stop_round = prev_pending_stop_round
            relay_leg_index = max(prev_leg_index, 1)
            logger.info(
                "Relay continue unfinished leg: "
                f"leg={relay_leg_index}, current_round={relay_start_round}, "
                f"pending_stop_round={relay_pending_stop_round}, max_rounds={max_rounds}"
            )
        else:
            relay_leg_index = max(prev_leg_index, 0) + 1
            if relay_start_round <= 0:
                relay_pending_stop_round = min(relay_chunk_rounds, max_rounds)
                logger.info(
                    "Relay plan first leg: "
                    f"leg={relay_leg_index}, current_round={relay_start_round}, "
                    f"chunk_rounds={relay_chunk_rounds}, "
                    f"pending_stop_round={relay_pending_stop_round}, max_rounds={max_rounds}"
                )
            else:
                relay_pending_stop_round = max_rounds
                logger.info(
                    "Relay plan final leg: "
                    f"leg={relay_leg_index}, current_round={relay_start_round}, "
                    f"pending_stop_round={relay_pending_stop_round}, max_rounds={max_rounds}"
                )

    def _build_relay_run_control() -> dict[str, Any]:
        if not relay_enabled:
            return {}
        state_round_raw = controller.get_current_state().get("round", 0)
        try:
            current_round = int(state_round_raw or 0)
        except Exception:
            current_round = 0
        return {
            "mode": relay_mode,
            "relay_schedule": (
                "first_leg_chunk_then_finish"
                if relay_mode == "relay"
                else "resume_to_target"
            ),
            "relay_chunk_rounds": relay_chunk_rounds,
            "target_max_rounds": max_rounds,
            "pending_stop_round": relay_pending_stop_round,
            "leg_index": relay_leg_index,
            "current_round_at_save": current_round,
        }

    def _should_stop_for_relay() -> bool:
        if not relay_enabled or relay_pending_stop_round is None:
            return False
        state_round_raw = controller.get_current_state().get("round", 0)
        try:
            current_round = int(state_round_raw or 0)
        except Exception:
            current_round = 0
        if current_round >= relay_pending_stop_round:
            run_mode_name = "Relay" if relay_mode == "relay" else "Resume"
            logger.info(
                f"{run_mode_name} planned stop reached: "
                f"current_round={current_round}, "
                f"pending_stop_round={relay_pending_stop_round}, max_rounds={max_rounds}"
            )
            return True
        return False

    def _save_relay_checkpoint(reason: str) -> None:
        if not relay_enabled:
            return
        try:
            controller.save_state(
                state_path,
                extra_state={
                    "directions": directions,
                    "run_control": _build_relay_run_control(),
                },
            )
            logger.info(f"Run checkpoint saved: {reason}")
        except Exception as checkpoint_err:
            logger.warning(f"Run checkpoint save failed ({reason}): {checkpoint_err}")

    logger.info("="*60)
    logger.info("Starting evolution loop")
    logger.info(f"Config: directions={len(directions)}, max_rounds={max_rounds}, "
               f"crossover_size={crossover_size}, crossover_n={crossover_n}")
    logger.info(f"Phases: mutation={'on' if mutation_enabled else 'off'}, "
               f"crossover={'on' if crossover_enabled else 'off'}")
    if mutation_enabled and not crossover_enabled:
        logger.info("Mode: mutation only (Original -> Mutation -> ...)")
    elif crossover_enabled and not mutation_enabled:
        logger.info("Mode: crossover only (Original -> Crossover -> ...)")
    elif mutation_enabled and crossover_enabled:
        logger.info("Mode: full evolution (Original -> Mutation -> Crossover -> ...)")
    else:
        logger.info("Mode: original only (no evolution)")
    logger.info(f"Parent selection: {parent_selection_strategy}" +
               (f" (top_percent={top_percent_threshold})" if parent_selection_strategy == "top_percent_plus_random" else ""))
    logger.info(f"Parallel execution: {'on' if parallel_enabled else 'off'}")
    if relay_enabled:
        control_items = [
            f"mode={relay_mode}",
            f"schedule={'first_leg_chunk_then_finish' if relay_mode == 'relay' else 'resume_to_target'}",
            f"leg={relay_leg_index}",
            f"pending_stop_round={relay_pending_stop_round}",
            f"target_max_rounds={max_rounds}",
        ]
        if relay_mode == "relay":
            control_items.insert(1, f"chunk_rounds={relay_chunk_rounds}")
        logger.info("Run control: " + ", ".join(control_items))
    logger.info("="*60)

    if parallel_enabled:
        while not controller.is_complete():
            if stop_event and stop_event.is_set():
                logger.info("Stop signal received, ending evolution loop")
                break
            if _should_stop_for_relay():
                break

            tasks = controller.get_all_tasks_for_current_phase()
            if not tasks:
                logger.info("Evolution complete: no more tasks")
                break

            current_phase = tasks[0]["phase"]
            current_round = tasks[0]["round_idx"]
            logger.info(f"Parallel phase: phase={current_phase.value}, round={current_round}, tasks={len(tasks)}")

            results = _run_tasks_parallel(
                tasks=tasks,
                directions=directions,
                step_n=steps_per_loop,
                use_local=use_local,
                user_direction=initial_direction,
                log_root=log_root,
            )
            
            completed_tasks = []
            for result in results:
                if result["success"]:
                    task = result["task"]
                    traj_data = result["traj_data"]
                    raw_count = traj_data.get("factor_count", 0)
                    try:
                        factor_count = int(raw_count)
                    except Exception:
                        factor_count = 0
                    trajectory = controller.create_trajectory_from_loop_result(
                        task=task,
                        hypothesis=traj_data.get("hypothesis"),
                        experiment=traj_data.get("experiment"),
                        feedback=traj_data.get("feedback"),
                    )
                    if factor_count <= 0:
                        trajectory.extra_info["status"] = "skipped"
                        trajectory.extra_info["skip_reason"] = traj_data.get(
                            "skip_reason", "zero_factors"
                        )
                        trajectory.extra_info["factor_count"] = 0
                        logger.warning(
                            f"Task skipped after retry: phase={task['phase'].value}, "
                            f"round={task['round_idx']}, direction={task['direction_id']}, "
                            f"reason={trajectory.extra_info['skip_reason']}"
                        )
                    controller.report_task_complete(task, trajectory)
                    _save_relay_checkpoint(
                        f"task_done phase={task['phase'].value} round={task['round_idx']} direction={task['direction_id']}"
                    )
                    completed_tasks.append(task)
                    if factor_count > 0:
                        logger.info(
                            f"Trajectory done: {trajectory.trajectory_id}, "
                            f"RankIC={trajectory.get_primary_metric()}"
                        )

            controller.advance_phase_after_parallel_completion(completed_tasks)
            _save_relay_checkpoint(
                f"phase_advance phase={current_phase.value} round={current_round}"
            )

    else:
        while not controller.is_complete():
            if stop_event and stop_event.is_set():
                logger.info("Stop signal received, ending evolution loop")
                break
            if _should_stop_for_relay():
                break

            task = controller.get_next_task()
            if task is None:
                logger.info("Evolution complete: no more tasks")
                break

            logger.info(f"Running task: phase={task['phase'].value}, round={task['round_idx']}, direction={task['direction_id']}")

            try:
                traj_data = _run_evolution_task(
                    task=task,
                    directions=directions,
                    step_n=steps_per_loop,
                    use_local=use_local,
                    user_direction=initial_direction,
                    log_root=log_root,
                    stop_event=stop_event,
                    quality_gate_cfg=quality_gate_cfg,
                )
                raw_count = traj_data.get("factor_count", 0)
                try:
                    factor_count = int(raw_count)
                except Exception:
                    factor_count = 0
                trajectory = controller.create_trajectory_from_loop_result(
                    task=task,
                    hypothesis=traj_data.get("hypothesis"),
                    experiment=traj_data.get("experiment"),
                    feedback=traj_data.get("feedback"),
                )
                if factor_count <= 0:
                    trajectory.extra_info["status"] = "skipped"
                    trajectory.extra_info["skip_reason"] = traj_data.get(
                        "skip_reason", "zero_factors"
                    )
                    trajectory.extra_info["factor_count"] = 0
                    logger.warning(
                        f"Task skipped after retry: phase={task['phase'].value}, "
                        f"round={task['round_idx']}, direction={task['direction_id']}, "
                        f"reason={trajectory.extra_info['skip_reason']}"
                    )
                controller.report_task_complete(task, trajectory)
                _save_relay_checkpoint(
                    f"task_done phase={task['phase'].value} round={task['round_idx']} direction={task['direction_id']}"
                )
                if factor_count > 0:
                    logger.info(
                        f"Task done: trajectory_id={trajectory.trajectory_id}, "
                        f"RankIC={trajectory.get_primary_metric()}"
                    )
            except Exception as e:
                logger.error(f"Task failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                if _is_no_space_error(e):
                    logger.error(
                        "Fatal disk error detected (No space left on device), "
                        "aborting evolution loop immediately."
                    )
                    raise
                continue

    final_extra_state: dict[str, Any] = {"directions": directions}
    if relay_enabled:
        final_extra_state["run_control"] = _build_relay_run_control()
    controller.save_state(state_path, extra_state=final_extra_state)
    best_trajs = controller.get_best_trajectories(top_n=5)
    logger.info("="*60)
    logger.info(f"Evolution complete. Top {len(best_trajs)} trajectories:")
    for i, t in enumerate(best_trajs):
        metric = t.get_primary_metric()
        metric_str = f"{metric:.4f}" if metric is not None else "N/A"
        logger.info(f"  {i+1}. {t.trajectory_id}: phase={t.phase.value}, RankIC={metric_str}")
    logger.info(f"Pool stats: {controller.pool.get_statistics()}")
    logger.info("="*60)
    if cleanup_on_finish:
        logger.info("Cleaning up trajectory pool file...")
        controller.pool.cleanup_file()


@force_timeout()
def main(path=None, step_n=100, direction=None, stop_event=None, config_path=None, evolution_mode=None):
    """
    Autonomous alpha factor mining with optional evolution support.

    Args:
        path: Session path (for resume)
        step_n: Number of steps (default 100 = 20 loops * 5 steps/loop)
        direction: Initial direction
        stop_event: Stop event
        config_path: Run config file path
        evolution_mode: Enable evolution (None=from config, True/False=override)

    Evolution flow: Original -> Mutation -> Crossover -> Mutation -> ...

    You can continue running session by

    .. code-block:: python

        quantaalpha mine --direction "[Initial Direction]" --config_path configs/experiment.yaml

    """
    try:
        from quantaalpha.core.conf import RD_AGENT_SETTINGS
        logger.info("="*60)
        logger.info("Experiment config")
        logger.info(f"  Workspace: {RD_AGENT_SETTINGS.workspace_path}")
        logger.info(f"  Cache dir: {RD_AGENT_SETTINGS.pickle_cache_folder_path_str}")
        logger.info(f"  Cache enabled: {RD_AGENT_SETTINGS.cache_with_pickle}")
        logger.info("="*60)

        # Config file default: project_root/configs/
        _project_root = Path(__file__).resolve().parents[2]
        config_default = _project_root / "configs" / "experiment.yaml"
        config_file = Path(config_path) if config_path else config_default
        run_cfg = load_run_config(config_file)
        planning_cfg = (run_cfg.get("planning") or {}) if isinstance(run_cfg, dict) else {}
        exec_cfg = (run_cfg.get("execution") or {}) if isinstance(run_cfg, dict) else {}
        evolution_cfg = (run_cfg.get("evolution") or {}) if isinstance(run_cfg, dict) else {}
        quality_gate_cfg = (run_cfg.get("quality_gate") or {}) if isinstance(run_cfg, dict) else {}

        if evolution_mode is not None:
            use_evolution = evolution_mode
        else:
            use_evolution = bool(evolution_cfg.get("enabled", False))

        if step_n is None or step_n == 100:
            if exec_cfg.get("step_n") is not None:
                step_n = exec_cfg.get("step_n")
            else:
                max_loops = int(exec_cfg.get("max_loops", 10))
                steps_per_loop = int(exec_cfg.get("steps_per_loop", 5))
                step_n = max_loops * steps_per_loop

        use_local = os.getenv("USE_LOCAL", "True").lower()
        use_local = True if use_local in ["true", "1"] else False
        if exec_cfg.get("use_local") is not None:
            use_local = bool(exec_cfg.get("use_local"))
        exec_cfg["use_local"] = use_local
        
        logger.info(f"Use {'Local' if use_local else 'Docker container'} to execute factor backtest")
        
        if use_evolution and path is None:
            logger.info("="*60)
            logger.info("Evolution mode: Original -> Mutation -> Crossover loop")
            logger.info("="*60)
            
            run_evolution_loop(
                initial_direction=direction,
                evolution_cfg=evolution_cfg,
                exec_cfg=exec_cfg,
                planning_cfg=planning_cfg,
                stop_event=stop_event,
                quality_gate_cfg=quality_gate_cfg,
            )
        
        elif path is None:
            planning_enabled = bool(planning_cfg.get("enabled", False))
            n_dirs = int(planning_cfg.get("num_directions", 1))
            max_attempts = int(planning_cfg.get("max_attempts", 5))
            use_llm = bool(planning_cfg.get("use_llm", True))
            allow_fallback = bool(planning_cfg.get("allow_fallback", True))
            prompt_file = planning_cfg.get("prompt_file") or "planning_prompts.yaml"
            prompt_path = Path(__file__).parent / "prompts" / str(prompt_file)
            if planning_enabled and direction:
                directions = generate_parallel_directions(
                    initial_direction=direction,
                    n=n_dirs,
                    prompt_file=prompt_path,
                    max_attempts=max_attempts,
                    use_llm=use_llm,
                    allow_fallback=allow_fallback,
                )
            else:
                directions = [direction] if direction else [None]

            log_root = exec_cfg.get("branch_log_root") or "log"
            log_prefix = exec_cfg.get("branch_log_prefix") or "branch"
            use_branch_logs = planning_enabled and len(directions) > 1
            parallel_execution = bool(exec_cfg.get("parallel_execution", False))

            if parallel_execution and len(directions) > 1:
                procs: list[Process] = []
                for idx, dir_text in enumerate(directions, start=1):
                    if dir_text:
                        logger.info(f"[Planning] Branch {idx}/{len(directions)} direction: {dir_text}")
                    p = Process(
                        target=_run_branch,
                        args=(dir_text, step_n, use_local, idx, log_root if use_branch_logs else "", log_prefix),
                    )
                    p.start()
                    procs.append(p)
                for p in procs:
                    p.join()
            else:
                for idx, dir_text in enumerate(directions, start=1):
                    if dir_text:
                        logger.info(f"[Planning] Branch {idx}/{len(directions)} direction: {dir_text}")
                    if use_branch_logs:
                        branch_name = f"{log_prefix}_{idx:02d}"
                        branch_log = Path(log_root) / branch_name
                        branch_log.mkdir(parents=True, exist_ok=True)
                        logger.set_trace_path(branch_log)
                    model_loop = AlphaAgentLoop(
                        ALPHA_AGENT_FACTOR_PROP_SETTING,
                        potential_direction=dir_text,
                        stop_event=stop_event,
                        use_local=use_local,
                        quality_gate_config=quality_gate_cfg,
                    )
                    model_loop.user_initial_direction = direction
                    model_loop.run(step_n=step_n, stop_event=stop_event)
        else:
            model_loop = AlphaAgentLoop.load(path, use_local=use_local)
            model_loop.run(step_n=step_n, stop_event=stop_event)
    except Exception as e:
        logger.error(f"Error during execution: {str(e)}")
        raise
    finally:
        logger.info("Run finished or terminated")

if __name__ == "__main__":
    fire.Fire(main)

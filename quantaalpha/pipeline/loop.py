"""
Model workflow with session control.
"""

import time
import pandas as pd
from typing import Any
import json
import os

from quantaalpha.pipeline.settings import BaseFacSetting
from quantaalpha.core.developer import Developer
from quantaalpha.core.proposal import (
    Hypothesis2Experiment,
    HypothesisExperiment2Feedback,
    HypothesisGen,  
    Trace,
)
from quantaalpha.core.scenario import Scenario
from quantaalpha.core.utils import import_class
from quantaalpha.log import logger
from quantaalpha.log.time import measure_time
from quantaalpha.utils.workflow import LoopBase, LoopMeta
from quantaalpha.core.exception import FactorEmptyError
import threading


import datetime
import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tqdm.auto import tqdm

from quantaalpha.core.exception import CoderError
from quantaalpha.log import logger
from functools import wraps

# Decorator: check stop_event before invoking the function

STOP_EVENT: threading.Event | None = None

def stop_event_check(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if STOP_EVENT is not None and STOP_EVENT.is_set():
            raise Exception("Operation stopped due to stop_event flag.")
        return func(self, *args, **kwargs)
    return wrapper


class AlphaAgentLoop(LoopBase, metaclass=LoopMeta):
    skip_loop_error = (FactorEmptyError,)
    
    @measure_time
    def __init__(
        self, 
        PROP_SETTING: BaseFacSetting, 
        potential_direction, 
        stop_event: threading.Event, 
        use_local: bool = True,
        strategy_suffix: str = "",
        evolution_phase: str = "original",
        trajectory_id: str = "",
        parent_trajectory_ids: list = None,
        direction_id: int = 0,
        round_idx: int = 0,
        quality_gate_config: dict = None,
    ):
        with logger.tag("init"):
            self.use_local = use_local
            # Store initial direction for factor provenance
            self.potential_direction = potential_direction

            # Evolution-related attributes
            self.strategy_suffix = strategy_suffix
            self.evolution_phase = evolution_phase  # original / mutation / crossover
            self.trajectory_id = trajectory_id
            self.parent_trajectory_ids = parent_trajectory_ids or []
            self.direction_id = direction_id
            self.round_idx = round_idx  # 0=original, 1=mutation, 2=crossover, ...

            # Quality gate config
            self.quality_gate_config = quality_gate_config or {}

            # For trajectory collection
            self._last_hypothesis = None
            self._last_experiment = None
            self._last_feedback = None
            self._last_skip_reason = None
            self._seen_expressions_cache: set[str] | None = None
            
            logger.info(f"Initialized AlphaAgentLoop, backtest in {'local' if use_local else 'Docker'}")
            if potential_direction:
                logger.info(f"Initial direction: {potential_direction}")
            if evolution_phase != "original":
                logger.info(f"Evolution phase: {evolution_phase}, round: {round_idx}, trajectory_id: {trajectory_id}")

            consistency_enabled = self.quality_gate_config.get("consistency_enabled", False)
            complexity_enabled = self.quality_gate_config.get("complexity_enabled", True)
            redundancy_enabled = self.quality_gate_config.get("redundancy_enabled", True)
            cheap_filter_enabled = self.quality_gate_config.get("cheap_filter_enabled", True)
            cheap_filter_require_acceptable = self.quality_gate_config.get("cheap_filter_require_acceptable", True)
            max_construct_failures_per_branch = self.quality_gate_config.get(
                "max_construct_failures_per_branch",
                2,
            )
            max_json_parse_failures_per_branch = self.quality_gate_config.get(
                "max_json_parse_failures_per_branch",
                2,
            )
            self.cheap_filter_enabled = bool(cheap_filter_enabled)
            self.cheap_filter_require_acceptable = bool(cheap_filter_require_acceptable)
            logger.info(f"Quality gate: consistency={'on' if consistency_enabled else 'off'}, "
                       f"complexity={'on' if complexity_enabled else 'off'}, "
                       f"redundancy={'on' if redundancy_enabled else 'off'}, "
                       f"cheap_filter={'on' if self.cheap_filter_enabled else 'off'}")
                
            scen: Scenario = import_class(PROP_SETTING.scen)(use_local=use_local)
            logger.log_object(scen, tag="scenario")

            # If strategy suffix is set, append it to the direction
            effective_direction = potential_direction
            if strategy_suffix:
                effective_direction = (potential_direction or "") + "\n" + strategy_suffix
            
            self.hypothesis_generator: HypothesisGen = import_class(PROP_SETTING.hypothesis_gen)(scen, effective_direction)
            logger.log_object(self.hypothesis_generator, tag="hypothesis generator")

            # Pass consistency check config into factor constructor
            self.factor_constructor: Hypothesis2Experiment = import_class(PROP_SETTING.hypothesis2experiment)(
                consistency_enabled=consistency_enabled,
                max_construct_failures_per_branch=max_construct_failures_per_branch,
                max_json_parse_failures_per_branch=max_json_parse_failures_per_branch,
            )
            logger.log_object(self.factor_constructor, tag="experiment generation")

            self.coder: Developer = import_class(PROP_SETTING.coder)(scen)
            logger.log_object(self.coder, tag="coder")
            
            self.runner: Developer = import_class(PROP_SETTING.runner)(scen)
            logger.log_object(self.runner, tag="runner")

            self.summarizer: HypothesisExperiment2Feedback = import_class(PROP_SETTING.summarizer)(scen)
            logger.log_object(self.summarizer, tag="summarizer")
            self.trace = Trace(scen=scen)
            
            global STOP_EVENT
            STOP_EVENT = stop_event
            super().__init__()

    @classmethod
    def load(
        cls,
        path,
        use_local: bool = True,
        stop_event: threading.Event | None = None,
    ):
        """Load existing session."""
        instance = super().load(path)
        instance.use_local = use_local
        global STOP_EVENT
        STOP_EVENT = stop_event
        logger.info(f"Loaded AlphaAgentLoop, backtest in {'local' if use_local else 'Docker'}")
        return instance

    @measure_time
    @stop_event_check
    def factor_propose(self, prev_out: dict[str, Any]):
        """Propose hypothesis as the basis for factor construction."""
        with logger.tag("r"):  
            idea = self.hypothesis_generator.gen(self.trace)
            logger.log_object(idea, tag="hypothesis generation")
            self._last_hypothesis = idea
        return idea

    @measure_time
    @stop_event_check
    def factor_construct(self, prev_out: dict[str, Any]):
        """Construct multiple factors from the hypothesis."""
        with logger.tag("r"): 
            # New loop may run after previous feedback already saved fresh factors.
            # Invalidate seen-expression cache so duplicate filter can observe latest library/pool state.
            self._seen_expressions_cache = None
            factor = self.factor_constructor.convert(prev_out["factor_propose"], self.trace)
            logger.log_object(factor.sub_tasks, tag="experiment generation")
            self._last_skip_reason = None
        return factor

    def _collect_factor_tasks(self, experiment: Any) -> list[Any]:
        tasks = getattr(experiment, "sub_tasks", None)
        if tasks is None:
            tasks = getattr(experiment, "tasks", None)
        return list(tasks or [])

    def _assign_factor_tasks(self, experiment: Any, tasks: list[Any]) -> None:
        if hasattr(experiment, "sub_tasks"):
            experiment.sub_tasks = tasks
        if hasattr(experiment, "tasks"):
            experiment.tasks = tasks

    @staticmethod
    def _normalize_expression(expr: str) -> str:
        if not isinstance(expr, str):
            return ""
        return " ".join(expr.strip().split())

    @staticmethod
    def _safe_load_json(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_seen_expressions(self) -> set[str]:
        cached = getattr(self, "_seen_expressions_cache", None)
        if cached is not None:
            return set(cached)

        seen: set[str] = set()
        project_root = Path(__file__).resolve().parent.parent.parent

        # 1) Existing factor library expressions (cross-run, same suffix).
        library_suffix = os.environ.get("FACTOR_LIBRARY_SUFFIX", "")
        if library_suffix:
            library_filename = f"all_factors_library_{library_suffix}.json"
        else:
            library_filename = "all_factors_library.json"
        library_path = project_root / "data" / "factorlib" / library_filename
        if library_path.exists():
            payload = self._safe_load_json(library_path)
            factors = payload.get("factors", {})
            if isinstance(factors, dict):
                for finfo in factors.values():
                    if not isinstance(finfo, dict):
                        continue
                    expr = self._normalize_expression(str(finfo.get("factor_expression", "")))
                    if expr:
                        seen.add(expr)

        # 2) Current experiment trajectory pool expressions (cross-round in same run).
        trace_path = Path(str(logger.log_trace_path))
        pool_candidates = [
            trace_path / "trajectory_pool.json",
            trace_path.parent / "trajectory_pool.json",
            trace_path.parent.parent / "trajectory_pool.json",
        ]
        loaded_pool = False
        for pool_path in pool_candidates:
            if not pool_path.exists():
                continue
            payload = self._safe_load_json(pool_path)
            trajectories = payload.get("trajectories", {})
            if not isinstance(trajectories, dict):
                continue
            loaded_pool = True
            for traj in trajectories.values():
                if not isinstance(traj, dict):
                    continue
                factors = traj.get("factors", [])
                if not isinstance(factors, list):
                    continue
                for finfo in factors:
                    if not isinstance(finfo, dict):
                        continue
                    expr = finfo.get("expression", finfo.get("factor_expression", ""))
                    expr = self._normalize_expression(str(expr))
                    if expr:
                        seen.add(expr)
            break

        self._seen_expressions_cache = set(seen)
        logger.info(
            f"Exact-duplicate prefilter loaded {len(seen)} seen expressions "
            f"(library={'yes' if library_path.exists() else 'no'}, trajectory_pool={'yes' if loaded_pool else 'no'})."
        )
        return set(seen)

    def _apply_precalc_quality_gate(self, experiment: Any) -> Any:
        if not self.cheap_filter_enabled:
            return experiment

        regulator = getattr(self.factor_constructor, "factor_regulator", None)
        if regulator is None:
            logger.warning("Cheap filter enabled but no factor_regulator found; skipping pre-calc quality gate.")
            return experiment

        tasks = self._collect_factor_tasks(experiment)
        if not tasks:
            self._last_skip_reason = "cheap_filter_empty_tasks"
            raise FactorEmptyError("Cheap filter: no factor tasks to evaluate.")

        seen_expressions = self._load_seen_expressions()
        accepted_expressions: set[str] = set()
        valid_tasks: list[Any] = []
        rejected_reasons: list[str] = []
        for task in tasks:
            factor_name = getattr(task, "factor_name", "unknown")
            expr = getattr(task, "factor_expression", "")
            if not isinstance(expr, str) or not expr.strip():
                rejected_reasons.append(f"{factor_name}:empty_expression")
                continue

            normalized_expr = self._normalize_expression(expr)
            if normalized_expr in seen_expressions or normalized_expr in accepted_expressions:
                rejected_reasons.append(f"{factor_name}:duplicate_exact")
                continue

            style_ok, style_feedback = regulator.validate_expression_style(expr)
            if not style_ok:
                rejected_reasons.append(f"{factor_name}:style:{style_feedback}")
                continue

            if not regulator.is_parsable(expr):
                rejected_reasons.append(f"{factor_name}:parse_failed")
                continue

            success, eval_dict = regulator.evaluate(expr)
            if not success:
                rejected_reasons.append(f"{factor_name}:evaluate_failed")
                continue

            if self.cheap_filter_require_acceptable and not regulator.is_expression_acceptable(eval_dict):
                rejected_reasons.append(f"{factor_name}:quality_gate_failed")
                continue

            valid_tasks.append(task)
            accepted_expressions.add(normalized_expr)

        if rejected_reasons:
            logger.warning(
                "Pre-calc cheap gate rejected factors: "
                f"{len(rejected_reasons)}/{len(tasks)}. "
                f"samples={rejected_reasons[:3]}"
            )

        if not valid_tasks:
            if rejected_reasons and all(r.endswith(":duplicate_exact") for r in rejected_reasons):
                self._last_skip_reason = "duplicate_exact"
                raise FactorEmptyError(
                    "Cheap filter removed all candidate factors before calculate/backtest (duplicate_exact)."
                )
            self._last_skip_reason = "cheap_filter_no_valid_factors"
            raise FactorEmptyError("Cheap filter removed all candidate factors before calculate/backtest.")

        if len(valid_tasks) < len(tasks):
            logger.info(f"Cheap filter retained {len(valid_tasks)}/{len(tasks)} factors for calculation.")
            self._assign_factor_tasks(experiment, valid_tasks)

        return experiment

    @measure_time
    @stop_event_check
    def factor_calculate(self, prev_out: dict[str, Any]):
        """Compute factor values from factor expressions."""
        with logger.tag("d"):  # develop
            filtered_experiment = self._apply_precalc_quality_gate(prev_out["factor_construct"])
            factor = self.coder.develop(filtered_experiment)
            logger.log_object(factor.sub_workspace_list, tag="coder result")
        return factor
    

    @measure_time
    @stop_event_check
    def factor_backtest(self, prev_out: dict[str, Any]):
        """Run backtest for factors."""
        with logger.tag("ef"):  # evaluate and feedback
            logger.info(f"Start factor backtest (Local: {self.use_local})")
            exp = self.runner.develop(prev_out["factor_calculate"], use_local=self.use_local)
            if exp is None:
                logger.error(f"Factor extraction failed.")
                raise FactorEmptyError("Factor extraction failed.")
            logger.log_object(exp, tag="runner result")
            self._last_experiment = exp
        return exp

    @measure_time
    @stop_event_check
    def feedback(self, prev_out: dict[str, Any]):
        feedback = self.summarizer.generate_feedback(prev_out["factor_backtest"], prev_out["factor_propose"], self.trace)
        with logger.tag("ef"):  # evaluate and feedback
            logger.log_object(feedback, tag="feedback")
        self.trace.hist.append((prev_out["factor_propose"], prev_out["factor_backtest"], feedback))
        
        self._last_feedback = feedback

        # Auto-save factors to unified factor library
        try:
            import os
            from pathlib import Path
            from quantaalpha.factors.library import FactorLibraryManager
            
            # Project root: loop.py -> pipeline/ -> quantaalpha/ -> project_root/
            project_root = Path(__file__).resolve().parent.parent.parent

            experiment_id = "unknown"
            if hasattr(self, 'session_folder') and self.session_folder:
                parts = Path(self.session_folder).parts
                for part in parts:
                    if part.startswith("202") and len(part) > 10:
                        experiment_id = part
                        break

            round_number = self.round_idx

            hypothesis_text = None
            if prev_out.get("factor_propose"):
                hypothesis_text = str(prev_out["factor_propose"])

            planning_direction = getattr(self, 'potential_direction', None)
            user_initial_direction = getattr(self, 'user_initial_direction', None)

            evolution_phase = getattr(self, 'evolution_phase', 'original')
            trajectory_id = getattr(self, 'trajectory_id', '')
            parent_trajectory_ids = getattr(self, 'parent_trajectory_ids', [])

            # Factor library filename can be customized via env FACTOR_LIBRARY_SUFFIX
            library_suffix = os.environ.get('FACTOR_LIBRARY_SUFFIX', '')
            if library_suffix:
                library_filename = f"all_factors_library_{library_suffix}.json"
            else:
                library_filename = "all_factors_library.json"
            factorlib_dir = project_root / "data" / "factorlib"
            factorlib_dir.mkdir(parents=True, exist_ok=True)
            library_path = factorlib_dir / library_filename
            manager = FactorLibraryManager(str(library_path))
            manager.add_factors_from_experiment(
                experiment=prev_out["factor_backtest"],
                experiment_id=experiment_id,
                round_number=round_number,
                hypothesis=hypothesis_text,
                feedback=feedback,
                initial_direction=planning_direction,
                user_initial_direction=user_initial_direction,
                planning_direction=planning_direction,
                evolution_phase=evolution_phase,
                trajectory_id=trajectory_id,
                parent_trajectory_ids=parent_trajectory_ids,
            )
            logger.info(f"Saved factors to library: {library_path} (phase={evolution_phase})")
        except Exception as e:
            logger.warning(f"Failed to save factors to library: {e}")
    
    def _get_trajectory_data(self) -> dict[str, Any]:
        """
        Get trajectory data for the current round (used by evolution controller).
        Method name is prefixed with underscore so the workflow system does not treat it as a step.
        Returns:
            Dict with hypothesis, experiment, feedback, etc.
        """
        return {
            "hypothesis": self._last_hypothesis,
            "experiment": self._last_experiment,
            "feedback": self._last_feedback,
            "skip_reason": self._last_skip_reason,
            "direction_id": self.direction_id,
            "evolution_phase": self.evolution_phase,
            "trajectory_id": self.trajectory_id,
            "parent_trajectory_ids": self.parent_trajectory_ids,
            "loop_idx": self.loop_idx,
            "round_idx": self.round_idx,
        }




class BacktestLoop(LoopBase, metaclass=LoopMeta):
    skip_loop_error = (FactorEmptyError,)
    @measure_time
    def __init__(self, PROP_SETTING: BaseFacSetting, factor_path=None):
        with logger.tag("init"):

            self.factor_path = factor_path

            scen: Scenario = import_class(PROP_SETTING.scen)()
            logger.log_object(scen, tag="scenario")

            self.hypothesis_generator: HypothesisGen = import_class(PROP_SETTING.hypothesis_gen)(scen)
            logger.log_object(self.hypothesis_generator, tag="hypothesis generator")

            self.factor_constructor: Hypothesis2Experiment = import_class(PROP_SETTING.hypothesis2experiment)(factor_path=factor_path)
            logger.log_object(self.factor_constructor, tag="experiment generation")

            self.coder: Developer = import_class(PROP_SETTING.coder)(scen, with_feedback=False, with_knowledge=False, knowledge_self_gen=False)
            logger.log_object(self.coder, tag="coder")
            
            self.runner: Developer = import_class(PROP_SETTING.runner)(scen)
            logger.log_object(self.runner, tag="runner")

            self.summarizer: HypothesisExperiment2Feedback = import_class(PROP_SETTING.summarizer)(scen)
            logger.log_object(self.summarizer, tag="summarizer")
            self.trace = Trace(scen=scen)
            super().__init__()

    def factor_propose(self, prev_out: dict[str, Any]):
        """
        Market hypothesis on which factors are built
        """
        with logger.tag("r"):  
            idea = self.hypothesis_generator.gen(self.trace)
            logger.log_object(idea, tag="hypothesis generation")
        return idea
        

    @measure_time
    def factor_construct(self, prev_out: dict[str, Any]):
        """
        Construct a variety of factors that depend on the hypothesis
        """
        with logger.tag("r"): 
            factor = self.factor_constructor.convert(prev_out["factor_propose"], self.trace)
            logger.log_object(factor.sub_tasks, tag="experiment generation")
        return factor

    @measure_time
    def factor_calculate(self, prev_out: dict[str, Any]):
        """
        Debug factors and calculate their values
        """
        with logger.tag("d"):  # develop
            factor = self.coder.develop(prev_out["factor_construct"])
            logger.log_object(factor.sub_workspace_list, tag="coder result")
        return factor
    

    @measure_time
    def factor_backtest(self, prev_out: dict[str, Any]):
        """
        Conduct Backtesting
        """
        with logger.tag("ef"):  # evaluate and feedback
            exp = self.runner.develop(prev_out["factor_calculate"])
            if exp is None:
                logger.error(f"Factor extraction failed.")
                raise FactorEmptyError("Factor extraction failed.")
            logger.log_object(exp, tag="runner result")
        return exp

    @measure_time
    def stop(self, prev_out: dict[str, Any]):
        exit(0)

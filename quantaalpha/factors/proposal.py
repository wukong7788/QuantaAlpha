import json
from pathlib import Path
from typing import List, Tuple

from jinja2 import Environment, StrictUndefined

from quantaalpha.factors.coder.factor import FactorExperiment, FactorTask
from quantaalpha.components.proposal import FactorHypothesis2Experiment, FactorHypothesisGen
from quantaalpha.core.prompts import Prompts
from quantaalpha.core.proposal import Hypothesis, Scenario, Trace
from quantaalpha.core.experiment import Experiment
from quantaalpha.factors.experiment import QlibFactorExperiment
from quantaalpha.llm.client import APIBackend, robust_json_parse
import os
import pandas as pd
from quantaalpha.log import logger
from quantaalpha.factors.regulator.factor_regulator import FactorRegulator
from quantaalpha.core.exception import FactorEmptyError

DEFAULT_HISTORY_LIMIT = 4
MIN_HISTORY_LIMIT = 1
MAX_RETRY_SUMMARY_ITEMS = 3
MAX_RETRY_BAD_EXAMPLE_CHARS = 180


def render_hypothesis_and_feedback(prompt_dict, trace: Trace, history_limit: int = DEFAULT_HISTORY_LIMIT) -> str:
    """Render hypothesis_and_feedback with configurable history limit."""
    if len(trace.hist) > 0:
        limited_trace = Trace(scen=trace.scen)
        limited_trace.hist = trace.hist[-history_limit:] if history_limit > 0 else trace.hist
        return (
            Environment(undefined=StrictUndefined)
            .from_string(prompt_dict["hypothesis_and_feedback"])
            .render(trace=limited_trace)
        )
    else:
        return "No previous hypothesis and feedback available since it's the first round."


def is_input_length_error(error_msg: str) -> bool:
    """Check if error is due to input length limit."""
    error_indicators = [
        "input length",
        "context length", 
        "maximum context",
        "token limit",
        "InvalidParameter",
        "Range of input length",
        "max_tokens",
        "too long"
    ]
    error_str = str(error_msg).lower()
    return any(indicator.lower() in error_str for indicator in error_indicators)


def build_retry_summary(retry_items: list[dict[str, str]]) -> str:
    """Build compact retry feedback to avoid prompt bloat on repeated failures."""
    if not retry_items:
        return ""

    recent_items = retry_items[-MAX_RETRY_SUMMARY_ITEMS:]
    lines = []
    for idx, item in enumerate(reversed(recent_items), 1):
        bad_example = (item.get("bad_example") or "").strip()
        if len(bad_example) > MAX_RETRY_BAD_EXAMPLE_CHARS:
            bad_example = bad_example[:MAX_RETRY_BAD_EXAMPLE_CHARS] + "..."
        lines.append(
            f"{idx}. error_type={item.get('error_type', 'unknown')}; "
            f"fix={item.get('fix_instruction', '')}; "
            f"counter_example={bad_example}"
        )

    return (
        "Recent failed attempts summary (latest first):\n"
        + "\n".join(lines)
        + "\nRegenerate strictly following the fixes above."
    )


QlibFactorHypothesis = Hypothesis
qa_prompt_dict = Prompts(file_path=Path(__file__).parent / "prompts" / "proposal.yaml")

class AlphaAgentHypothesis(Hypothesis):
    """
    AlphaAgentHypothesis extends the Hypothesis class to include a potential_direction,
    which represents the initial idea or starting point for the hypothesis.
    """

    def __init__(
        self,
        hypothesis: str,
        concise_observation: str,
        concise_justification: str,
        concise_knowledge: str,
        concise_specification: str
    ) -> None:
        super().__init__(
            hypothesis,
            "",
            "",
            concise_observation,
            concise_justification,
            concise_knowledge,
        )
        self.concise_specification = concise_specification
        
    def __str__(self) -> str:
        return f"""Hypothesis: {self.hypothesis}
                Concise Observation: {self.concise_observation}
                Concise Justification: {self.concise_justification}
                Concise Knowledge: {self.concise_knowledge}
                concise Specification: {self.concise_specification}
                """

base_prompt_dict = Prompts(file_path=Path(__file__).parent / "prompts" / "prompts.yaml")

class QlibFactorHypothesisGen(FactorHypothesisGen):
    def __init__(self, scen: Scenario) -> Tuple[dict, bool]:
        super().__init__(scen)

    def prepare_context(self, trace: Trace) -> Tuple[dict, bool]:
        hypothesis_and_feedback = (
            (
                Environment(undefined=StrictUndefined)
                .from_string(base_prompt_dict["hypothesis_and_feedback"])
                .render(trace=trace)
            )
            if len(trace.hist) > 0
            else "No previous hypothesis and feedback available since it's the first round."
        )
        context_dict = {
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "RAG": None,
            "hypothesis_output_format": base_prompt_dict["hypothesis_output_format"],
            "hypothesis_specification": base_prompt_dict["factor_hypothesis_specification"],
        }
        return context_dict, True

    def convert_response(self, response: str) -> Hypothesis:
        response_dict = robust_json_parse(response)
        hypothesis = QlibFactorHypothesis(
            hypothesis=response_dict.get("hypothesis", ""),
            reason=response_dict.get("reason", ""),
            concise_reason=response_dict.get("concise_reason", ""),
            concise_observation=response_dict.get("concise_observation", ""),
            concise_justification=response_dict.get("concise_justification", ""),
            concise_knowledge=response_dict.get("concise_knowledge", ""),
        )
        return hypothesis


class QlibFactorHypothesis2Experiment(FactorHypothesis2Experiment):
    def prepare_context(self, hypothesis: Hypothesis, trace: Trace) -> Tuple[dict | bool]:
        scenario = trace.scen.get_scenario_all_desc()
        experiment_output_format = base_prompt_dict["factor_experiment_output_format"]

        hypothesis_and_feedback = (
            (
                Environment(undefined=StrictUndefined)
                .from_string(base_prompt_dict["hypothesis_and_feedback"])
                .render(trace=trace)
            )
            if len(trace.hist) > 0
            else "No previous hypothesis and feedback available since it's the first round."
        )

        experiment_list: List[FactorExperiment] = [t[1] for t in trace.hist]

        factor_list = []
        for experiment in experiment_list:
            factor_list.extend(experiment.sub_tasks)

        return {
            "target_hypothesis": str(hypothesis),
            "scenario": scenario,
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "experiment_output_format": experiment_output_format,
            "target_list": factor_list,
            "RAG": None,
        }, True

    def convert_response(self, response: str, trace: Trace) -> FactorExperiment:
        response_dict = robust_json_parse(response)
        tasks = []

        for factor_name in response_dict:
            factor_data = response_dict.get(factor_name, {})
            if not isinstance(factor_data, dict):
                continue
            description = factor_data.get("description", "")
            formulation = factor_data.get("formulation", "")
            # expression = factor_data.get("expression", "")
            variables = factor_data.get("variables", {})
            tasks.append(
                FactorTask(
                    factor_name=factor_name,
                    factor_description=description,
                    factor_formulation=formulation,
                    # factor_expression=expression,
                    variables=variables,
                )
            )

        exp = QlibFactorExperiment(tasks)
        exp.based_experiments = [QlibFactorExperiment(sub_tasks=[])] + [t[1] for t in trace.hist if t[2]]

        unique_tasks = []

        for task in tasks:
            duplicate = False
            for based_exp in exp.based_experiments:
                for sub_task in based_exp.sub_tasks:
                    if task.factor_name == sub_task.factor_name:
                        duplicate = True
                        break
                if duplicate:
                    break
            if not duplicate:
                unique_tasks.append(task)

        exp.tasks = unique_tasks
        return exp



qa_prompt_dict = Prompts(file_path=Path(__file__).parent / "prompts" / "prompts.yaml")

# prompt_dict not as attribute: class instance is pickled later, prompt_dict cannot be pickled
class AlphaAgentHypothesisGen(FactorHypothesisGen):
    def __init__(self, scen: Scenario, potential_direction: str=None) -> Tuple[dict, bool]:
        super().__init__(scen)
        self.potential_direction = potential_direction

    def prepare_context(self, trace: Trace, history_limit: int = DEFAULT_HISTORY_LIMIT) -> Tuple[dict, bool]:
        
        if len(trace.hist) > 0:
            hypothesis_and_feedback = render_hypothesis_and_feedback(
                qa_prompt_dict, trace, history_limit
            )
            
        elif self.potential_direction is not None: 
            hypothesis_and_feedback = (
                Environment(undefined=StrictUndefined)
                .from_string(qa_prompt_dict["potential_direction_transformation"])
                .render(potential_direction=self.potential_direction)
            ) # 
        else:
            hypothesis_and_feedback = "No previous hypothesis and feedback available since it's the first round. You are encouraged to propose an innovative hypothesis that diverges significantly from existing perspectives."
            
        context_dict = {
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "RAG": None,
            "hypothesis_output_format": qa_prompt_dict["hypothesis_output_format"],
            "hypothesis_specification": qa_prompt_dict["factor_hypothesis_specification"],
        }
        return context_dict, True

    def convert_response(self, response: str) -> AlphaAgentHypothesis:
        """
        Convert LLM JSON to AlphaAgentHypothesis; use default empty string for missing fields to avoid KeyError.
        """
        response_dict = robust_json_parse(response)
        # Use get to avoid KeyError on missing fields
        hypothesis = AlphaAgentHypothesis(
            hypothesis=response_dict.get("hypothesis", ""),
            concise_observation=response_dict.get("concise_observation", ""),
            concise_knowledge=response_dict.get("concise_knowledge", ""),
            concise_justification=response_dict.get("concise_justification", ""),
            concise_specification=response_dict.get("concise_specification", ""),
        )
        return hypothesis
    
    def gen(self, trace: Trace) -> AlphaAgentHypothesis:
        """Generate hypothesis; supports dynamic history limit for input length."""
        history_limit = DEFAULT_HISTORY_LIMIT
        
        while history_limit >= MIN_HISTORY_LIMIT:
            try:
                context_dict, json_flag = self.prepare_context(trace, history_limit)
                system_prompt = (
                    Environment(undefined=StrictUndefined)
                    .from_string(qa_prompt_dict["hypothesis_gen"]["system_prompt"])
                    .render(
                        targets=self.targets,
                        scenario=self.scen.get_scenario_all_desc(filtered_tag="hypothesis_and_experiment"),
                        hypothesis_output_format=context_dict["hypothesis_output_format"],
                        hypothesis_specification=context_dict["hypothesis_specification"],
                    )
                )
                user_prompt = (
                    Environment(undefined=StrictUndefined)
                    .from_string(qa_prompt_dict["hypothesis_gen"]["user_prompt"])
                    .render(
                        targets=self.targets,
                        hypothesis_and_feedback=context_dict["hypothesis_and_feedback"],
                        RAG=context_dict["RAG"],
                        round=len(trace.hist)
                    )
                )

                resp = APIBackend().build_messages_and_create_chat_completion(user_prompt, system_prompt, json_mode=json_flag)
                hypothesis = self.convert_response(resp)
                return hypothesis
            
            except Exception as e:
                if is_input_length_error(str(e)) and history_limit > MIN_HISTORY_LIMIT:
                    history_limit -= 1
                    logger.warning(f"Input length exceeded, retrying with history_limit={history_limit}...")
                else:
                    raise
        
        # Last attempt with minimum history limit
        context_dict, json_flag = self.prepare_context(trace, MIN_HISTORY_LIMIT)
        system_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(qa_prompt_dict["hypothesis_gen"]["system_prompt"])
            .render(
                targets=self.targets,
                scenario=self.scen.get_scenario_all_desc(filtered_tag="hypothesis_and_experiment"),
                hypothesis_output_format=context_dict["hypothesis_output_format"],
                hypothesis_specification=context_dict["hypothesis_specification"],
            )
        )
        user_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(qa_prompt_dict["hypothesis_gen"]["user_prompt"])
            .render(
                targets=self.targets,
                hypothesis_and_feedback=context_dict["hypothesis_and_feedback"],
                RAG=context_dict["RAG"],
                round=len(trace.hist)
            )
        )
        resp = APIBackend().build_messages_and_create_chat_completion(user_prompt, system_prompt, json_mode=json_flag)
        hypothesis = self.convert_response(resp)
        return hypothesis
    
    

class EmptyHypothesisGen(FactorHypothesisGen):
    def __init__(self, scen: Scenario) -> Tuple[dict, bool]:
        super().__init__(scen)
        
    def convert_response(self, *args, **kwargs) -> AlphaAgentHypothesis: 
        return super().convert_response(*args, **kwargs)  
    
    def prepare_context(self, *args, **kwargs) -> Tuple[dict | bool]:
        return super().prepare_context(*args, **kwargs)

    def gen(self, trace: Trace) -> AlphaAgentHypothesis:

        hypothesis = AlphaAgentHypothesis(
            hypothesis="",
            concise_observation="",
            concise_justification="",
            concise_knowledge="",
            concise_specification=""
        )

        return hypothesis




class AlphaAgentHypothesis2FactorExpression(FactorHypothesis2Experiment):
    def __init__(
        self,
        *args,
        consistency_enabled: bool = False,
        max_construct_failures_per_branch: int = 2,
        max_json_parse_failures_per_branch: int = 2,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # Initialize FactorRegulator with config settings
        from quantaalpha.factors.coder.config import FACTOR_COSTEER_SETTINGS
        self.factor_regulator = FactorRegulator(
            factor_zoo_path=FACTOR_COSTEER_SETTINGS.factor_zoo_path,
            duplication_threshold=FACTOR_COSTEER_SETTINGS.duplication_threshold
        )
        self.max_construct_failures_per_branch = max(1, int(max_construct_failures_per_branch))
        self.max_json_parse_failures_per_branch = max(1, int(max_json_parse_failures_per_branch))
        
        # Initialize consistency checker if enabled
        self.consistency_enabled = consistency_enabled
        self._quality_gate = None
        
    @property
    def quality_gate(self):
        """Lazy-load FactorQualityGate."""
        if self._quality_gate is None and self.consistency_enabled:
            try:
                from quantaalpha.factors.regulator.consistency_checker import FactorQualityGate
                self._quality_gate = FactorQualityGate(
                    consistency_enabled=self.consistency_enabled,
                    complexity_enabled=True,
                    redundancy_enabled=True
                )
            except ImportError as e:
                logger.warning(f"Could not load consistency checker: {e}")
                self._quality_gate = None
        return self._quality_gate
        
    def prepare_context(self, hypothesis: Hypothesis, trace: Trace, history_limit: int = DEFAULT_HISTORY_LIMIT) -> Tuple[dict | bool]:
        scenario = trace.scen.get_scenario_all_desc()
        experiment_output_format = qa_prompt_dict["factor_experiment_output_format"]
        function_lib_description = qa_prompt_dict['function_lib_description']
        hypothesis_and_feedback = render_hypothesis_and_feedback(
            qa_prompt_dict, trace, history_limit
        )

        experiment_list: List[FactorExperiment] = [t[1] for t in trace.hist]

        factor_list = []
        for experiment in experiment_list:
            factor_list.extend(experiment.sub_tasks)

        return {
            "target_hypothesis": str(hypothesis),
            "scenario": scenario,
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "function_lib_description": function_lib_description,
            "experiment_output_format": experiment_output_format,
            "target_list": factor_list,
            "RAG": None,
        }, True
        
    def convert(self, hypothesis: Hypothesis, trace: Trace) -> Experiment:
        """Convert hypothesis to factor expressions; supports dynamic history limit."""
        history_limit = DEFAULT_HISTORY_LIMIT
        
        while history_limit >= MIN_HISTORY_LIMIT:
            try:
                return self._convert_with_history_limit(hypothesis, trace, history_limit)
            except Exception as e:
                if is_input_length_error(str(e)) and history_limit > MIN_HISTORY_LIMIT:
                    history_limit -= 1
                    logger.warning(f"Input length exceeded, retrying with history_limit={history_limit}...")
                else:
                    raise
        
        # Last attempt with minimum history limit
        return self._convert_with_history_limit(hypothesis, trace, MIN_HISTORY_LIMIT)
    
    def _convert_with_history_limit(self, hypothesis: Hypothesis, trace: Trace, history_limit: int) -> Experiment:
        """Convert with given history limit."""
        context, json_flag = self.prepare_context(hypothesis, trace, history_limit)
        system_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(qa_prompt_dict["hypothesis2experiment"]["system_prompt"])
            .render(
                targets=self.targets,
                scenario=trace.scen.background, # get_scenario_all_desc(filtered_tag="hypothesis_and_experiment"),
                experiment_output_format=context["experiment_output_format"],
            )
        )
        user_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(qa_prompt_dict["hypothesis2experiment"]["user_prompt"])
            .render(
                targets=self.targets,
                target_hypothesis=context["target_hypothesis"],
                hypothesis_and_feedback=context["hypothesis_and_feedback"],
                function_lib_description=context["function_lib_description"],
                target_list=context["target_list"],
                RAG=context["RAG"], 
                expression_duplication=None
            )
        )
        
        # Detect duplicated sub-expressions and expression style violations.
        flag = False
        expression_duplication_prompt = None
        retry_summary_items: list[dict[str, str]] = []
        construct_failures = 0
        json_parse_failures = 0

        def _append_retry_feedback(
            error_type: str,
            fix_instruction: str,
            bad_example: str,
        ) -> None:
            nonlocal expression_duplication_prompt, user_prompt
            retry_summary_items.append(
                {
                    "error_type": error_type,
                    "fix_instruction": fix_instruction,
                    "bad_example": bad_example,
                }
            )
            expression_duplication_prompt = build_retry_summary(retry_summary_items)

            user_prompt = (
                Environment(undefined=StrictUndefined)
                .from_string(qa_prompt_dict["hypothesis2experiment"]["user_prompt"])
                .render(
                    targets=self.targets,
                    target_hypothesis=context["target_hypothesis"],
                    hypothesis_and_feedback=context["hypothesis_and_feedback"],
                    function_lib_description=context["function_lib_description"],
                    target_list=context["target_list"],
                    RAG=context["RAG"],
                    expression_duplication=expression_duplication_prompt,
                )
            )

        while True:
            if flag:
                break
                
            resp = APIBackend().build_messages_and_create_chat_completion(user_prompt, system_prompt, json_mode=json_flag)
            try:
                response_dict = robust_json_parse(resp)
                json_parse_failures = 0
            except json.JSONDecodeError as e:
                json_parse_failures += 1
                logger.warning(
                    f"JSON parse failed ({json_parse_failures}/{self.max_json_parse_failures_per_branch}): {e}, retrying..."
                )
                if json_parse_failures >= self.max_json_parse_failures_per_branch:
                    raise FactorEmptyError(
                        "construct_stop_loss: JSON parse failure budget exceeded"
                    )
                continue
            proposed_names = []
            proposed_exprs = []
            retry_required = False
            
            for i, factor_name in enumerate(response_dict):
                factor_data = response_dict.get(factor_name, {})
                if not isinstance(factor_data, dict):
                    continue
                expr = factor_data.get("expression", "")
                description = factor_data.get("description", "")
                formulation = factor_data.get("formulation", "")
                variables = factor_data.get("variables", {})

                style_ok, style_feedback = self.factor_regulator.validate_expression_style(expr)
                if not style_ok:
                    logger.warning(f"Expression style validation failed: {style_feedback}. expr={expr}")
                    _append_retry_feedback(
                        error_type="expression_style",
                        fix_instruction=style_feedback,
                        bad_example=expr,
                    )
                    retry_required = True
                    break

                # Check if expression is parsable
                if not self.factor_regulator.is_parsable(expr):
                    logger.info(f"Failed to parse expr: {expr}, retrying...")
                    _append_retry_feedback(
                        error_type="syntax_error",
                        fix_instruction=(
                            "Expression parsing failed. Use only allowed functions, operators '+ - * /', "
                            "and consistently '$'-prefixed base variables."
                        ),
                        bad_example=expr,
                    )
                    retry_required = True
                    break
                
                success, eval_dict = self.factor_regulator.evaluate(expr)
                if not success:
                    retry_required = True
                    break
                
                # Consistency check (if enabled)
                if self.consistency_enabled and self.quality_gate is not None:
                    try:
                        passed, feedback, results = self.quality_gate.evaluate(
                            hypothesis=str(hypothesis),
                            factor_name=factor_name,
                            factor_description=description,
                            factor_formulation=formulation,
                            factor_expression=expr,
                            variables=variables
                        )
                        
                        # Use corrected expression from consistency check if provided
                        if results.get("corrected_expression") and results["corrected_expression"] != expr:
                            logger.info(f"Consistency check corrected expression: {expr} -> {results['corrected_expression']}")
                            expr = results["corrected_expression"]
                            factor_data["expression"] = expr
                            response_dict[factor_name] = factor_data

                            style_ok, style_feedback = self.factor_regulator.validate_expression_style(expr)
                            if not style_ok:
                                logger.warning(
                                    f"Corrected expression style validation failed: {style_feedback}. expr={expr}"
                                )
                                _append_retry_feedback(
                                    error_type="expression_style",
                                    fix_instruction=style_feedback,
                                    bad_example=expr,
                                )
                                retry_required = True
                                break

                            # Re-check corrected expression
                            if not self.factor_regulator.is_parsable(expr):
                                logger.warning(f"Corrected expression could not be parsed: {expr}")
                                _append_retry_feedback(
                                    error_type="syntax_error",
                                    fix_instruction=(
                                        "Corrected expression is still unparsable. Use canonical operator form "
                                        "and '$'-prefixed base variables only."
                                    ),
                                    bad_example=expr,
                                )
                                retry_required = True
                                break
                            success, eval_dict = self.factor_regulator.evaluate(expr)
                            if not success:
                                retry_required = True
                                break
                        
                        if not passed:
                            logger.warning(f"Consistency check failed: {factor_name}, feedback: {feedback}")
                    except Exception as e:
                        logger.warning(f"Consistency check error: {e}")
                
                # If expression has problems, regenerate with feedback
                if not self.factor_regulator.is_expression_acceptable(eval_dict):
                    # Get symbol length and base features count for complexity feedback
                    symbol_length = eval_dict.get('symbol_length', 0)
                    num_base_features = eval_dict.get('num_base_features', 0)
                    symbol_length_threshold = self.factor_regulator.symbol_length_threshold
                    base_features_threshold = self.factor_regulator.base_features_threshold

                    fix_instruction = (
                        "Expression quality gate failed. Reduce duplicated subtree size, control free args ratio, "
                        "and keep symbol/base-feature complexity within thresholds."
                    )
                    if symbol_length > symbol_length_threshold:
                        fix_instruction += f" symbol_length={symbol_length} exceeds threshold={symbol_length_threshold}."
                    if num_base_features > base_features_threshold:
                        fix_instruction += (
                            f" base_features={num_base_features} exceeds threshold={base_features_threshold}."
                        )
                    if eval_dict["duplicated_subtree_size"] > self.factor_regulator.duplication_threshold:
                        fix_instruction += (
                            " duplicated subtree is too large relative to duplication threshold."
                        )

                    _append_retry_feedback(
                        error_type="quality_gate",
                        fix_instruction=fix_instruction,
                        bad_example=expr,
                    )
                    retry_required = True
                    break
                else:
                    proposed_names.append(factor_name)
                    proposed_exprs.append(expr)
                    if i == len(response_dict) - 1:
                        flag = True
                    else:
                        continue

            if not flag and not retry_required:
                _append_retry_feedback(
                    error_type="empty_or_invalid_output",
                    fix_instruction=(
                        "Returned JSON has no valid factor entries. "
                        "Provide at least one factor with non-empty expression/description/formulation."
                    ),
                    bad_example=str(response_dict),
                )
                retry_required = True

            if retry_required:
                construct_failures += 1
                logger.warning(
                    "Construct failure budget usage: "
                    f"{construct_failures}/{self.max_construct_failures_per_branch}"
                )
                if construct_failures >= self.max_construct_failures_per_branch:
                    raise FactorEmptyError(
                        "construct_stop_loss: construct failure budget exceeded"
                    )
            elif flag:
                construct_failures = 0
        

        # Add valid factors to the factor regulator
        self.factor_regulator.add_factor(proposed_names, proposed_exprs)

        return self.convert_response(json.dumps(response_dict, ensure_ascii=False), trace)
    

    def convert_response(self, response: str, trace: Trace) -> FactorExperiment:
        response_dict = robust_json_parse(response)
        tasks = []

        for factor_name in response_dict:
            factor_data = response_dict.get(factor_name, {})
            if not isinstance(factor_data, dict):
                continue
            description = factor_data.get("description", "")
            formulation = factor_data.get("formulation", "")
            expression = factor_data.get("expression", "")
            variables = factor_data.get("variables", {})
            tasks.append(
                FactorTask(
                    factor_name=factor_name,
                    factor_description=description,
                    factor_formulation=formulation,
                    factor_expression=expression,
                    variables=variables,
                )
            )
            
        exp = QlibFactorExperiment(tasks)
        exp.based_experiments = [QlibFactorExperiment(sub_tasks=[])] + [t[1] for t in trace.hist if t[2]]

        unique_tasks = []

        for task in tasks:
            duplicate = False
            for based_exp in exp.based_experiments:
                for sub_task in based_exp.sub_tasks:
                    if task.factor_name == sub_task.factor_name:
                        duplicate = True
                        break
                if duplicate:
                    break
            if not duplicate:
                unique_tasks.append(task)

        exp.tasks = unique_tasks
        return exp



class BacktestHypothesis2FactorExpression(FactorHypothesis2Experiment):
    def __init__(self, factor_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.factor_path = factor_path
        
    def convert_response(self, *args, **kwargs) -> FactorExperiment:
        return super().convert_response(*args, **kwargs)
        
    def prepare_context(self, *args, **kwargs) -> Tuple[dict | bool]:
        return super().prepare_context(*args, **kwargs)
        
    def convert(self, hypothesis: Hypothesis, trace: Trace) -> FactorExperiment:
        if os.path.exists(self.factor_path):
            tasks = []
            factor_df = pd.read_csv(self.factor_path, usecols=["factor_name", "factor_expression"], index_col=None)
            for index, row in factor_df.iterrows():
                tasks.append(
                    FactorTask(
                        factor_name=row["factor_name"],
                        factor_description="",
                        factor_formulation="",
                        factor_expression=row["factor_expression"],
                        variables="",
                    )
                )
            
            exp = QlibFactorExperiment(tasks)
            exp.based_experiments = [QlibFactorExperiment(sub_tasks=[])] + [t[1] for t in trace.hist if t[2]]

            unique_tasks = []

            for task in tasks:
                duplicate = False
                for based_exp in exp.based_experiments:
                    for sub_task in based_exp.sub_tasks:
                        if task.factor_name == sub_task.factor_name:
                            duplicate = True
                            break
                    if duplicate:
                        break
                if not duplicate:
                    unique_tasks.append(task)

            exp.tasks = unique_tasks
            return exp
            
        else:
            raise ValueError(f"File {self.factor_csv_path} does not exist. ")
        
    

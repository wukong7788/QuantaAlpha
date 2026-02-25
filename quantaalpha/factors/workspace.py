"""
QuantaAlpha custom workspace.

Overrides rdagent QlibFBWorkspace: project-level factor_template overrides default YAML;
base files (read_exp_res.py, etc.) still from rdagent; init empty git repo in workspace to suppress qlib recorder git output.
"""

import subprocess
import os
import re
import sys
from pathlib import Path
from typing import Any

from rdagent.scenarios.qlib.experiment.workspace import QlibFBWorkspace as _RdagentQlibFBWorkspace
from rdagent.log import rdagent_logger as logger
import pandas as pd

from quantaalpha.factors.coder.config import FACTOR_COSTEER_SETTINGS

_CUSTOM_TEMPLATE_DIR = Path(__file__).resolve().parent / "factor_template"


class QlibFBWorkspace(_RdagentQlibFBWorkspace):
    """
    Override rdagent QlibFBWorkspace: inject project factor_template/ YAML over defaults;
    init empty git repo in workspace to avoid qlib recorder git help output.
    """

    def __init__(self, template_folder_path: Path, *args, **kwargs) -> None:
        super().__init__(template_folder_path, *args, **kwargs)
        if _CUSTOM_TEMPLATE_DIR.exists():
            self.inject_code_from_folder(_CUSTOM_TEMPLATE_DIR)
            logger.info(f"Overrode rdagent default config with project template: {_CUSTOM_TEMPLATE_DIR}")

    def before_execute(self) -> None:
        """Init empty git repo in workspace to suppress qlib recorder git warnings."""
        super().before_execute()
        git_dir = self.workspace_path / ".git"
        if not git_dir.exists():
            try:
                subprocess.run(
                    ["git", "init"],
                    cwd=str(self.workspace_path),
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass

    def _run_local_cmd(
        self,
        cmd: list[str],
        env: dict[str, str],
        timeout: int,
    ) -> tuple[str, int]:
        """Run a command in workspace and return combined stdout/stderr + exit code."""
        proc = subprocess.run(
            cmd,
            cwd=str(self.workspace_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return output, proc.returncode

    def execute(self, qlib_config_name: str = "conf.yaml", run_env: dict | None = None, *args: Any, **kwargs: Any):
        """
        Execute qlib backtest locally with explicit Python binary.
        This avoids silently failing conda-based execution when conda is unavailable.
        """
        run_env = run_env or {}
        timeout = int(kwargs.get("timeout", FACTOR_COSTEER_SETTINGS.file_based_execution_timeout))
        python_bin = (
            os.environ.get("FACTOR_CoSTEER_PYTHON_BIN")
            or sys.executable
            or FACTOR_COSTEER_SETTINGS.python_bin
            or "python"
        )
        env = {**os.environ, **run_env}

        # qrun equivalent: python -m qlib.cli.run <config>
        execute_qlib_log, qrun_code = self._run_local_cmd(
            [python_bin, "-m", "qlib.cli.run", qlib_config_name],
            env=env,
            timeout=timeout,
        )
        logger.log_object(execute_qlib_log, tag="Qlib_execute_log")
        if qrun_code != 0:
            logger.error(f"qrun failed with exit code={qrun_code}")

        execute_log, parse_code = self._run_local_cmd(
            [python_bin, "read_exp_res.py"],
            env=env,
            timeout=timeout,
        )
        if parse_code != 0:
            logger.error(f"read_exp_res.py failed with exit code={parse_code}")
            if execute_log:
                logger.error(execute_log[-2000:])

        quantitative_backtesting_chart_path = self.workspace_path / "ret.pkl"
        if quantitative_backtesting_chart_path.exists():
            ret_df = pd.read_pickle(quantitative_backtesting_chart_path)
            logger.log_object(ret_df, tag="Quantitative Backtesting Chart")
        else:
            logger.error("No result file found.")
            return None, execute_qlib_log

        qlib_res_path = self.workspace_path / "qlib_res.csv"
        if qlib_res_path.exists():
            pattern = r"(Epoch\d+: train -[0-9\.]+, valid -[0-9\.]+|best score: -[0-9\.]+ @ \d+ epoch)"
            matches = re.findall(pattern, execute_qlib_log)
            compact_log = "\n".join(matches) if matches else execute_qlib_log
            return pd.read_csv(qlib_res_path, index_col=0).iloc[:, 0], compact_log

        logger.error(f"File {qlib_res_path} does not exist.")
        return None, execute_qlib_log

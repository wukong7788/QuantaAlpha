import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_SH = REPO_ROOT / "run.sh"


def _run_with_blacklist(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RUN_SH), "--blacklist-file", str(path), "test direction"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def test_run_sh_fails_fast_when_blacklist_file_is_missing(tmp_path):
    missing_path = tmp_path / "missing_blacklist.json"

    result = _run_with_blacklist(missing_path)

    assert result.returncode != 0
    assert "subtree blacklist file not found" in result.stderr


def test_run_sh_fails_fast_when_blacklist_json_is_invalid(tmp_path):
    invalid_path = tmp_path / "invalid_blacklist.json"
    invalid_path.write_text("{not-json}", encoding="utf-8")

    result = _run_with_blacklist(invalid_path)

    assert result.returncode != 0
    assert "failed to parse subtree blacklist JSON" in result.stderr


def test_run_sh_fails_fast_when_blacklist_has_no_patterns(tmp_path):
    empty_path = tmp_path / "empty_blacklist.json"
    empty_path.write_text(json.dumps({"patterns": []}), encoding="utf-8")

    result = _run_with_blacklist(empty_path)

    assert result.returncode != 0
    assert "contains no raw patterns" in result.stderr

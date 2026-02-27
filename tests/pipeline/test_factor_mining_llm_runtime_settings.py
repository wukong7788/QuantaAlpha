import json

from quantaalpha.llm.config import LLM_SETTINGS
from quantaalpha.pipeline.factor_mining import _apply_runtime_llm_settings


def test_apply_runtime_llm_settings_maps_new_options():
    raw = {
        "max_retries": 7,
        "retry_delay": 0.5,
        "json_mode_strict": True,
        "json_mode_temperature": 0.1,
        "freeform_temperature": 0.6,
        "request_timeout_s": 45,
        "retry_backoff": "exponential",
        "retry_jitter": True,
        "retry_max_wait_seconds": 20,
        "failover_base_urls": ["https://a.example/v1", "https://b.example/v1"],
        "json_mode_response_format": "json_object",
        "json_mode_json_schema": "",
    }

    _apply_runtime_llm_settings(raw)

    assert LLM_SETTINGS.max_retry == 7
    assert LLM_SETTINGS.retry_wait_seconds == 0.5
    assert LLM_SETTINGS.json_mode_strict is True
    assert LLM_SETTINGS.json_mode_temperature == 0.1
    assert LLM_SETTINGS.freeform_temperature == 0.6
    assert LLM_SETTINGS.request_timeout_s == 45.0
    assert LLM_SETTINGS.retry_backoff == "exponential"
    assert LLM_SETTINGS.retry_jitter is True
    assert LLM_SETTINGS.retry_max_wait_seconds == 20.0
    assert json.loads(LLM_SETTINGS.failover_base_urls) == [
        "https://a.example/v1",
        "https://b.example/v1",
    ]
    assert LLM_SETTINGS.json_mode_response_format == "json_object"
    assert LLM_SETTINGS.json_mode_json_schema == ""


def test_apply_runtime_llm_settings_parses_bool_like_strings():
    raw = {
        "json_mode_strict": "false",
        "retry_jitter": "0",
    }

    _apply_runtime_llm_settings(raw)

    assert LLM_SETTINGS.json_mode_strict is False
    assert LLM_SETTINGS.retry_jitter is False

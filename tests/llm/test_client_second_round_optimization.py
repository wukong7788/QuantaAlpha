import pytest

from quantaalpha.llm.client import APIBackend
from quantaalpha.llm.config import LLM_SETTINGS


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeUsage:
    total_tokens = 1
    prompt_tokens = 1
    completion_tokens = 1


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage()


def _make_backend_with_capture(captured: dict) -> APIBackend:
    backend = APIBackend.__new__(APIBackend)
    backend.use_chat_cache = False
    backend.dump_chat_cache = False
    backend.use_llama2 = False
    backend.use_gcr_endpoint = False
    backend.chat_stream = False
    backend.chat_seed = None
    backend.reasoning_model = "fake-reasoning-model"
    backend.chat_model = "fake-chat-model"
    backend.chat_model_map = {}
    backend.request_timeout_s = 12.5

    class _FakeCompletions:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return _FakeResponse('{"ok": true}')

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeChatClient:
        chat = _FakeChat()

    backend.chat_client = _FakeChatClient()
    return backend


def test_json_mode_uses_json_temperature_and_response_format(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}
    backend = _make_backend_with_capture(captured)

    monkeypatch.setattr(LLM_SETTINGS, "json_mode_temperature", 0.0)
    monkeypatch.setattr(LLM_SETTINGS, "freeform_temperature", 0.5)
    monkeypatch.setattr(LLM_SETTINGS, "json_mode_response_format", "json_object")
    monkeypatch.setattr(LLM_SETTINGS, "json_mode_strict", True)

    output, _finish_reason = backend._create_chat_completion_inner_function(
        messages=[{"role": "user", "content": "hello"}],
        reasoning_flag=False,
        json_mode=True,
    )

    assert output == '{"ok": true}'
    assert captured["temperature"] == 0.0
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 12.5


def test_freeform_uses_freeform_temperature(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}
    backend = _make_backend_with_capture(captured)

    monkeypatch.setattr(LLM_SETTINGS, "json_mode_temperature", 0.0)
    monkeypatch.setattr(LLM_SETTINGS, "freeform_temperature", 0.7)
    monkeypatch.setattr(LLM_SETTINGS, "json_mode_response_format", "json_object")
    monkeypatch.setattr(LLM_SETTINGS, "json_mode_strict", True)

    output, _finish_reason = backend._create_chat_completion_inner_function(
        messages=[{"role": "user", "content": "hello"}],
        reasoning_flag=False,
        json_mode=False,
    )

    assert output == '{"ok": true}'
    assert captured["temperature"] == 0.7
    assert "response_format" not in captured


def test_retry_backoff_exponential_without_jitter():
    backend = APIBackend.__new__(APIBackend)
    backend.retry_wait_seconds = 1.0
    backend.retry_backoff = "exponential"
    backend.retry_jitter = False
    backend.retry_max_wait_seconds = 10.0

    assert backend._compute_retry_sleep_seconds(0) == 1.0
    assert backend._compute_retry_sleep_seconds(1) == 2.0
    assert backend._compute_retry_sleep_seconds(2) == 4.0


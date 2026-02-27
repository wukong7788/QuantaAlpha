import pytest

from quantaalpha.llm.client import APIBackend


def _make_backend_stub() -> APIBackend:
    backend = APIBackend.__new__(APIBackend)
    backend.retry_wait_seconds = 0
    return backend


def test_empty_json_response_retries_next_attempt_without_followup(monkeypatch: pytest.MonkeyPatch):
    backend = _make_backend_stub()
    attempts: list[str] = ["   ", '{"ok": true}']
    followup_calls = {"count": 0}

    def fake_auto_continue(**kwargs):  # noqa: ARG001
        return attempts.pop(0)

    def fake_followup(kwargs, attempt_idx):  # noqa: ARG001
        followup_calls["count"] += 1
        return None

    monkeypatch.setattr(backend, "_create_chat_completion_auto_continue", fake_auto_continue)
    monkeypatch.setattr(backend, "_retry_json_only_once", fake_followup)

    result = backend._try_create_chat_completion_or_embedding(
        max_retry=2,
        chat_completion=True,
        json_mode=True,
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == '{"ok": true}'
    assert followup_calls["count"] == 0


def test_json_parse_failure_uses_single_json_only_followup(monkeypatch: pytest.MonkeyPatch):
    backend = _make_backend_stub()
    calls = {"initial": 0, "followup": 0}

    def fake_auto_continue(**kwargs):  # noqa: ARG001
        calls["initial"] += 1
        return "this is not json"

    def fake_followup(kwargs, attempt_idx):  # noqa: ARG001
        calls["followup"] += 1
        assert attempt_idx == 1
        return '{"fixed": 1}'

    monkeypatch.setattr(backend, "_create_chat_completion_auto_continue", fake_auto_continue)
    monkeypatch.setattr(backend, "_retry_json_only_once", fake_followup)

    result = backend._try_create_chat_completion_or_embedding(
        max_retry=1,
        chat_completion=True,
        json_mode=True,
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == '{"fixed": 1}'
    assert calls == {"initial": 1, "followup": 1}


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


def test_reasoning_non_json_response_should_not_be_json_truncated():
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

    class _FakeCompletions:
        @staticmethod
        def create(**kwargs):  # noqa: ARG002
            return _FakeResponse("non-json prefix {not_valid_json} suffix")

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeChatClient:
        chat = _FakeChat()

    backend.chat_client = _FakeChatClient()

    output, _finish_reason = backend._create_chat_completion_inner_function(
        messages=[{"role": "user", "content": "hello"}],
        reasoning_flag=True,
        json_mode=False,
    )

    assert output == "non-json prefix {not_valid_json} suffix"


def test_json_parse_failure_should_not_trigger_failover(monkeypatch: pytest.MonkeyPatch):
    backend = _make_backend_stub()
    attempts = ["not-json", '{"ok": true}']
    failover_switch_calls = {"count": 0}

    def fake_auto_continue(**kwargs):  # noqa: ARG001
        return attempts.pop(0)

    def fake_switch(reason: str):  # noqa: ARG001
        failover_switch_calls["count"] += 1
        return True

    monkeypatch.setattr(backend, "_create_chat_completion_auto_continue", fake_auto_continue)
    monkeypatch.setattr(backend, "_retry_json_only_once", lambda kwargs, attempt_idx: None)
    monkeypatch.setattr(backend, "_switch_next_chat_base_url", fake_switch)
    monkeypatch.setattr(backend, "_compute_retry_sleep_seconds", lambda attempt_idx: 0.0)

    result = backend._try_create_chat_completion_or_embedding(
        max_retry=2,
        chat_completion=True,
        json_mode=True,
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == '{"ok": true}'
    assert failover_switch_calls["count"] == 0


def test_transport_timeout_should_trigger_failover(monkeypatch: pytest.MonkeyPatch):
    backend = _make_backend_stub()
    state = {"attempt": 0}
    failover_switch_calls = {"count": 0}

    def fake_auto_continue(**kwargs):  # noqa: ARG001
        if state["attempt"] == 0:
            state["attempt"] += 1
            raise TimeoutError("simulated timeout")
        return '{"ok": true}'

    def fake_switch(reason: str):  # noqa: ARG001
        failover_switch_calls["count"] += 1
        return True

    monkeypatch.setattr(backend, "_create_chat_completion_auto_continue", fake_auto_continue)
    monkeypatch.setattr(backend, "_switch_next_chat_base_url", fake_switch)
    monkeypatch.setattr(backend, "_compute_retry_sleep_seconds", lambda attempt_idx: 0.0)

    result = backend._try_create_chat_completion_or_embedding(
        max_retry=2,
        chat_completion=True,
        json_mode=True,
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == '{"ok": true}'
    assert failover_switch_calls["count"] == 1

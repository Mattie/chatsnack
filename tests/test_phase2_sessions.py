from types import SimpleNamespace

from chatsnack import Chat
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.runtime import ResponsesAdapter, ResponsesWebSocketAdapter


def test_responses_runtime_without_session_stays_http():
    chat = Chat(params=ChatParams(runtime="responses", session=None))
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_responses_runtime_with_inherit_selects_websocket_and_inherits_lineage(monkeypatch):
    chat = Chat(params=ChatParams(runtime="responses", session="inherit"))
    assert isinstance(chat.runtime, ResponsesWebSocketAdapter)

    async def fake_create_completion_a(messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=[]), metadata={"response_id": "r1"})

    monkeypatch.setattr(chat.runtime, "create_completion_a", fake_create_completion_a)
    next_chat = chat.chat("hello")

    assert isinstance(next_chat.runtime, ResponsesWebSocketAdapter)
    assert next_chat.runtime.session is chat.runtime.session


def test_responses_runtime_with_new_selects_websocket_and_descendants_get_new_session(monkeypatch):
    chat = Chat(params=ChatParams(runtime="responses", session="new"))

    async def fake_create_completion_a(messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=[]), metadata={"response_id": "r1"})

    monkeypatch.setattr(chat.runtime, "create_completion_a", fake_create_completion_a)
    next_chat = chat.chat("hello")

    assert isinstance(next_chat.runtime, ResponsesWebSocketAdapter)
    assert next_chat.runtime.session is not chat.runtime.session


def test_close_session_methods_delegate_to_adapter(monkeypatch):
    chat = Chat(params=ChatParams(runtime="responses", session="inherit"))
    called = {"single": 0, "all": 0}

    monkeypatch.setattr(chat.runtime, "close_session", lambda: called.__setitem__("single", called["single"] + 1))
    monkeypatch.setattr(ResponsesWebSocketAdapter, "close_all_sessions", classmethod(lambda cls: called.__setitem__("all", called["all"] + 1)))

    chat.close_session()
    Chat.close_all_sessions()

    assert called == {"single": 1, "all": 1}

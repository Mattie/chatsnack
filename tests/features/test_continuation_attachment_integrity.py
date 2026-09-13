"""Continuation must preserve the attachment bytes represented by its history."""

import base64
from contextlib import nullcontext
import json
from pathlib import Path

import httpx
import openai
import pytest

from chatsnack import Chat, ChatParams


def _response(request, number, output=None):
    """Supply a complete SDK response while keeping provider requests offline."""
    return httpx.Response(200, json={
        "id": f"resp_{number}", "object": "response", "created_at": 1,
        "status": "completed", "model": json.loads(request.content)["model"],
        "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        "output": output if output is not None else [{
            "type": "message", "id": f"msg_{number}", "role": "assistant",
            "status": "completed", "content": [{
                "type": "output_text", "text": "Read it.", "annotations": [],
            }],
        }],
    })


@pytest.mark.parametrize("attachment_kind", ["files", "images"])
@pytest.mark.asyncio
async def test_changed_local_attachment_replays_its_new_upload(tmp_path, monkeypatch, attachment_kind):
    """A saved response ID must not hide changes behind an unchanged local path."""
    requests, uploads = [], []
    path = tmp_path / ("notes.txt" if attachment_kind == "files" else "drawing.png")
    path.write_bytes(b"first version")

    def respond(request):
        """Observe the SDK payload after attachment resolution and continuation."""
        requests.append(json.loads(request.content))
        return _response(request, len(requests))

    async def upload(file_path, **kwargs):
        """Stand in for file upload while reading the real current local bytes."""
        uploads.append(Path(file_path).read_bytes())
        return f"file_{len(uploads)}"

    async with openai.AsyncOpenAI(api_key="offline", http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    )) as sdk:
        source = Chat(params=ChatParams(runtime="responses", model="test-model", responses={"store": True}))
        source.ai.aclient = sdk
        monkeypatch.setattr(source.ai, "upload_file_async", upload)
        continued = await source.chat_a("Read the attachment.", **{attachment_kind: [{"path": str(path)}]})
        path.write_bytes(b"changed second version")
        await continued.chat_a("Read it again.")

    assert uploads == [b"first version", b"changed second version"]
    assert "previous_response_id" not in requests[1]
    assert requests[1]["input"][0]["content"][1]["file_id"] == "file_2"
    assert requests[1]["input"][1]["id"] == "msg_1"


@pytest.mark.asyncio
async def test_resolved_attachment_reference_keeps_the_stored_shortcut():
    """A stable provider file ID remains safe to reuse through a stored response."""
    requests = []

    def respond(request):
        """Capture requests without uploading or contacting a provider."""
        requests.append(json.loads(request.content))
        return _response(request, len(requests))

    async with openai.AsyncOpenAI(api_key="offline", http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    )) as sdk:
        source = Chat(params=ChatParams(runtime="responses", model="test-model", responses={"store": True}))
        source.ai.aclient = sdk
        continued = await source.chat_a("Read this.", files=[{"file_id": "file_stable"}])
        await continued.chat_a("Summarize it.")

    assert requests[1]["previous_response_id"] == "resp_1"
    assert len(requests[1]["input"]) == 1


@pytest.mark.parametrize("capture_failure", ["storage-error", "invalid-image", "invalid-base64", "data-uri"])
@pytest.mark.asyncio
async def test_image_capture_failure_cannot_return_incomplete_history(monkeypatch, capture_failure):
    """A paid image response fails locally when its bytes cannot be preserved."""
    requests = []
    data = b"invalid image" if capture_failure == "invalid-image" else b"\x89PNG\r\n\x1a\nimage"
    result = base64.b64encode(data).decode("ascii")
    if capture_failure == "invalid-base64":
        result = "not-base64!"
    elif capture_failure == "data-uri":
        result = f"data:image/png;base64,{result}"

    def respond(request):
        """Return an image whose replay depends on successful local capture."""
        requests.append(json.loads(request.content))
        return _response(request, 1, [{
            "type": "image_generation_call", "id": "ig_1", "status": "completed",
            "result": result,
        }])

    if capture_failure == "storage-error":
        def unavailable(*args, **kwargs):
            """Model a full or unavailable asset store without changing the disk."""
            raise OSError("asset store unavailable")
        monkeypatch.setattr("chatsnack.chat.mixin_query.capture_asset", unavailable)

    async with openai.AsyncOpenAI(api_key="offline", http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    )) as sdk:
        source = Chat(runtime="responses", model="test-model")
        source.ai.aclient = sdk
        decode_warning = (pytest.warns(RuntimeWarning, match="Could not decode generated image")
                          if capture_failure in {"invalid-base64", "data-uri"} else nullcontext())
        with decode_warning, pytest.raises(RuntimeError, match="preserve generated image") as failure:
            await source.chat_a("Draw a snack.")

    assert failure.value.__cause__ is not None
    assert source.messages == []
    assert len(requests) == 1
    assert source.last_call_usage.response_count == 1
    assert source.last_call_usage.total.total_tokens == 3
    assert failure.value.last_call_usage is source.last_call_usage

"""Goal: a saved Astra Chat uses ordinary utensils through the real SDK offline."""

import json
import warnings

import httpx
import openai
import pytest

from chatsnack import Chat, Text, utensil


@pytest.mark.asyncio
async def test_saved_astra_chat_executes_stock_and_continues(tmp_path, monkeypatch):
    """Exercise saved authoring, SDK serialization, execution, and continuation together."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("CHATSNACK_DEFAULT_RUNTIME", "chat_completions")
    requests = []
    lookups = []

    @utensil
    def astra_stock(sku: str):
        """Look up the notebook's demo stock."""
        lookups.append(sku)
        return {"sku": sku, "available": 12}

    def respond(request):
        """Supply a provider call followed by answers, retaining the actual SDK wire body."""
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/responses"
        if len(requests) == 1:
            output = [{"type": "function_call", "id": "fc_stock", "call_id": "call_stock",
                       "name": "astra_stock", "arguments": '{"sku":"snack-box"}',
                       "status": "completed"}]
        else:
            output = [{"type": "message", "id": "msg_stock", "role": "assistant",
                       "status": "completed", "content": [{"type": "output_text",
                       "text": "12 snack boxes are available.", "annotations": [], "logprobs": []}]}]
        return httpx.Response(200, json={
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "status": "completed", "model": body["model"], "output": output,
            "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
        })

    Text(name="AstraStockStyle", content="Answer briefly from the stock result.").save()
    template = Chat(name="AstraStock", model="gpt-6-astra", runtime="responses",
                    utensils=[astra_stock])
    template.system("{text.AstraStockStyle}").user("Check stock for {sku}.")
    template.reasoning.effort = "low"
    template.reasoning.summary = "auto"
    template.save()
    loaded = Chat(name="AstraStock", utensils=[astra_stock])
    loaded.load()

    async with openai.AsyncOpenAI(
        api_key="offline-test-key", base_url="https://api.openai.com/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        loaded.ai.aclient = sdk
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            thread = await loaded.chat_a(sku="snack-box")
            continued = await thread.chat_a("How many snack boxes did you say were available?")

    assert not caught
    assert thread.last == continued.last == "12 snack boxes are available."
    assert lookups == ["snack-box"]
    assert "{sku}" in loaded.yaml
    assert "{text.AstraStockStyle}" in loaded.yaml
    assert len(requests) == 3
    assert all(body["model"] == "gpt-6-astra" for body in requests)
    assert all(body["reasoning"] == {"effort": "low", "summary": "auto"} for body in requests)
    authored_input = [
        (item["role"], [part["text"] for part in item["content"]])
        for item in requests[0]["input"]
    ]
    assert authored_input == [
        ("system", ["Answer briefly from the stock result."]),
        ("user", ["Check stock for snack-box."]),
    ]
    assert requests[-1]["input"][-1]["content"][0]["text"] == "How many snack boxes did you say were available?"
    assert requests[0]["tools"][0]["name"] == "astra_stock"
    outputs = [item for item in requests[1]["input"] if item.get("type") == "function_call_output"]
    assert len(outputs) == 1
    assert outputs[0]["call_id"] == "call_stock"
    stock_result = json.loads(outputs[0]["output"])
    assert stock_result["sku"] == "snack-box"
    assert stock_result["available"] == 12

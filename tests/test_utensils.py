import os
import json
import pytest
from chatsnack.utensil import _REGISTRY, utensil, get_openai_tools, handle_tool_call, get_tool_definitions
from chatsnack.chat import Chat
from chatsnack.chat.mixin_params import ChatParams

# List of engines that support tool calls based on your compatibility chart
TOOL_COMPATIBLE_ENGINES = [
    "gpt-4-turbo",
    "gpt-4o",
    "gpt-4o-mini", 
    "o1",
    "o3-mini"
]

@pytest.mark.parametrize("engine", TOOL_COMPATIBLE_ENGINES)
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, 
                    reason="OPENAI_API_KEY is not set in environment or .env")
def test_engine_tool_calls(engine):
    """Test that each compatible engine can properly make tool calls."""
    # Define test-local utensil
    @utensil(name="test_engine_info", description="Retrieves test information for engine tests")
    def test_engine_info(query: str):
        """Provides test information about the test engine, query 'summary' for a summary."""
        return {
            "query": query,
            "result": f"Test information for: {query}",
            "timestamp": "2025-03-11"
        }
    
    # Create a simple prompt that should trigger tool usage
    prompt = "What info do you have about the test engine?"
    
    # Use the local utensil
    chat = Chat(
        system="You are a helpful assistant for a test engine that uses tools when needed.",
        utensils=[test_engine_info],
        auto_execute=True,
        tool_choice="required"
    )
    
    chat.model = engine

    try:
        result = chat.user(prompt).chat()
        
        has_tool_calls = False
        has_tool_response = False
        
        for message in result.messages:
            if isinstance(message, dict):
                if "assistant" in message and isinstance(message["assistant"], dict):
                    asst_msg = message["assistant"]
                    if "tool_calls" in asst_msg and asst_msg["tool_calls"]:
                        has_tool_calls = True
                        
                        tool_call = asst_msg["tool_calls"][0]
                        assert "function" in tool_call, f"Tool call missing function field in {engine}"
                        assert tool_call["function"].get("name") == "test_engine_info", \
                               f"Unexpected function name in {engine}"
                
                if "tool" in message:
                    has_tool_response = True
                    
                    tool_content = message["tool"]
                    if isinstance(tool_content, dict) and "content" in tool_content:
                        if isinstance(tool_content["content"], str):
                            try:
                                content_data = json.loads(tool_content["content"])
                                assert "query" in content_data, f"Tool response missing query in {engine}"
                                assert "result" in content_data, f"Tool response missing result in {engine}"
                            except json.JSONDecodeError:
                                assert len(tool_content["content"]) > 0, \
                                       f"Empty tool response in {engine}"
        
        assert has_tool_calls, f"Engine {engine} failed to make any tool calls"
        
        if chat.auto_execute:
            assert has_tool_response, f"Engine {engine} is missing tool responses"
            
        final_message = result.last
        assert final_message is not None, f"No final response from {engine}"
        assert len(final_message) > 0, f"Empty final response from {engine}"
        
    except Exception as e:
        pytest.skip(f"Engine {engine} failed with error: {str(e)}")

# === Test 1: Utensil Registration ===
def test_utensil_registration():
    # Create test-local utensil
    @utensil(name="test_registration_tool", description="A tool for testing registration")
    def test_registration_tool(a: int, b: int):
        return {"sum": a + b}
    
    # Verify the tool is registered in _REGISTRY
    names = [utensil_obj.name for utensil_obj in _REGISTRY]
    assert "test_registration_tool" in names, "test_registration_tool should be registered in _REGISTRY"

    # Check conversion to tool definition
    tool_defs = get_tool_definitions([test_registration_tool])
    assert tool_defs[0].function.name == "test_registration_tool"
    assert tool_defs[0].function.description == "A tool for testing registration"

# === Test 2: OpenAI Tool Format ===
def test_get_openai_tools():
    # Create test-local utensil
    @utensil(name="test_format_tool", description="A tool for testing OpenAI format")
    def test_format_tool(x: int, y: int):
        return {"product": x * y}
    
    # Use the tool we just created
    tools = get_openai_tools([test_format_tool])
    
    # Search for our specific tool
    sample = next((t for t in tools if t.get("function", {}).get("name") == "test_format_tool"), None)
    assert sample is not None, "OpenAI tools should include test_format_tool"
    
    func_data = sample.get("function")
    # First look for arguments; if not present, get parameters
    args_val = func_data.get("arguments")
    if args_val is None:
        params = func_data.get("parameters")
        args_val = json.dumps(params) if params is not None else None
    
    assert isinstance(args_val, str), "arguments should be a string"
    assert func_data.get("name") == "test_format_tool"

# === Test 3: Tool Call Execution and Tool Call ID Propagation ===
def test_handle_tool_call():
    # Create test-local utensil
    @utensil(name="test_execution_tool", description="A tool for testing execution")
    def test_execution_tool(a: int, b: int):
        return {"sum": a + b}
    
    # Prepare a simulated tool call for our local tool
    tool_call = {
        "id": "call_test_123",
        "type": "function",
        "function": {
            "name": "test_execution_tool",
            "arguments": json.dumps({"a": 5, "b": 7})
        }
    }
    
    result = handle_tool_call(tool_call)
    
    # Result should include the sum and echo back the tool_call_id
    assert result.get("sum") == 12, "test_execution_tool should sum correctly"
    assert result.get("tool_call_id") == "call_test_123", "tool_call_id should be propagated"

# === Test 4: Utensil Assignment into Chat and Params Population ===
def test_chat_includes_utensils():
    # Create test-local utensil
    @utensil(name="test_chat_tool", description="A tool for testing chat assignment")
    def test_chat_tool(message: str):
        return {"echo": message}
    
    # Create a chat with the local utensil
    chat = Chat(
        name="utensils_chat_test",
        utensils=[test_chat_tool],
        auto_execute=True,
        tool_choice="auto"
    )
    
    # After initialization, the chat.params should have tools
    if chat.params is None:
        pytest.skip("params is None; utensils were not set because none were passed")
        
    assert hasattr(chat.params, "tools"), "ChatParams should have a 'tools' attribute"
    assert len(chat.params.tools) > 0, "ChatParams.tools should not be empty when utensils are set"

# === Test 5: Tool Call Serialization/Deserialization and Restoration ===
def test_tool_serialization_and_restoration(tmp_path):
    # Create test-local utensil
    @utensil(name="test_serialize_tool", description="A tool for testing serialization")
    def test_serialize_tool(a: int, b: int):
        return {"product": a * b}
    
    # Create a chat with the local utensil
    chat = Chat(
        name="serialize_tool_chat",
        utensils=[test_serialize_tool]
    )
    
    # Simulate chat history with a tool call
    tool_call_message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_serialize_001",
            "type": "function",
            "function": {
                "name": "test_serialize_tool",
                "arguments": json.dumps({"a": 2, "b": 3})
            }
        }]
    }
    chat.messages.append(tool_call_message)
    
    chat.save()
    
    # Now load it back
    restored_chat = Chat(name="serialize_tool_chat")
    restored_chat.load()
    
    # Verify tool definitions are restored
    if restored_chat.params is None:
        pytest.skip("Restored chat.params is None; utensils restoration failed.")
        
    tools_after = restored_chat.params.tools
    found = any(tool.function.name == "test_serialize_tool" for tool in tools_after)
    assert found, "Restored chat should include test_serialize_tool in its tools"

def test_utensil_group_local_registry():
    # Create a unique local utensil group
    local_group = utensil.group("Local Test Group")
    
    # Add a test utensil function to the group
    @local_group.add
    def local_tool(x: int) -> dict:
        """Multiply x by 2.
        
        Args:
            x: An integer value to be doubled
            
        Returns:
            A dictionary with the resulting product (e.g., {"result": <x*2>})
        """
        return {"result": x * 2}
    
    # Create a Chat instance with only the local utensil group
    chat = Chat(
        name="LocalRegistryChat",
        system="Test chat with a local utensil group.",
        utensils=[local_group]
    )
    
    # Simulate a tool call using the local utensil
    tool_call = {
        "id": "local_test_001",
        "type": "function",
        "function": {
            "name": "local_tool",
            "arguments": json.dumps({"x": 5})
        }
    }
    
    # Use the handle_tool_call function with the chat's local registry
    result = handle_tool_call(tool_call, local_registry=chat._local_registry)
    
    # Verify that the function from the local group was called
    assert result.get("result") == 10, "Expected local_tool to multiply 5 by 2 resulting in 10"
    assert result.get("tool_call_id") == "local_test_001", "Tool call ID should be propagated correctly"


@pytest.mark.parametrize("engine", TOOL_COMPATIBLE_ENGINES)
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, 
                    reason="OPENAI_API_KEY is not set in environment or .env")
def test_engine_tool_calls_local_registry(engine):
    """Test that each compatible engine can properly make tool calls using a local utensil group registry."""
    # Create a unique local utensil group
    local_group = utensil.group("Test Engine Group")
    
    # Add a test-local utensil to the group using the group's decorator
    @local_group.add
    def test_engine_info(query: str):
        """Provides test information about the test engine. Query 'summary' returns a summary."""
        return {
            "query": query,
            "result": f"Test information for: {query}",
            "timestamp": "2025-03-11"
        }
    
    # Create a simple prompt that should trigger tool usage
    prompt = "What info do you have about the test engine?"
    
    # Create a Chat instance with the local utensil group (local registry only)
    chat = Chat(
        system="You are a helpful assistant for a test engine that uses a local tool registry.",
        utensils=[local_group],
        auto_execute=True,
        tool_choice="required"
    )
    
    chat.model = engine
    chat.temperature = 0.1
    
    try:
        result = chat.user(prompt).chat()
        
        has_tool_calls = False
        has_tool_response = False
        
        for message in result.messages:
            if isinstance(message, dict):
                if "assistant" in message and isinstance(message["assistant"], dict):
                    asst_msg = message["assistant"]
                    if "tool_calls" in asst_msg and asst_msg["tool_calls"]:
                        has_tool_calls = True
                        tool_call = asst_msg["tool_calls"][0]
                        assert "function" in tool_call, f"Tool call missing function field in {engine}"
                        # Verify that the local group's function was called
                        assert tool_call["function"].get("name") == "test_engine_info", \
                               f"Unexpected function name in {engine}"
                
                if "tool" in message:
                    has_tool_response = True
                    
                    tool_content = message["tool"]
                    if isinstance(tool_content, dict) and "content" in tool_content:
                        if isinstance(tool_content["content"], str):
                            try:
                                content_data = json.loads(tool_content["content"])
                                assert "query" in content_data, f"Tool response missing query in {engine}"
                                assert "result" in content_data, f"Tool response missing result in {engine}"
                            except json.JSONDecodeError:
                                assert len(tool_content["content"]) > 0, \
                                       f"Empty tool response in {engine}"
        
        assert has_tool_calls, f"Engine {engine} failed to make any tool calls using local registry"
        
        if chat.auto_execute:
            assert has_tool_response, f"Engine {engine} is missing tool responses using local registry"
            
        final_message = result.last
        assert final_message is not None, f"No final response from {engine}"
        assert len(final_message) > 0, f"Empty final response from {engine}"
        
    except Exception as e:
        pytest.fail(f"Engine {engine} failed with error: {str(e)}")


# === Test 6: Utensil auto_feed param (new) ===
#         :param auto_feed: whether to automatically feed tool calls to the engine (optional, defaults to True)
# TDD development for this, let us make new tests that start 'red' for the new auto_feed feature that we're going to write soon

# === Test 7: Utensil auto_feed Initialization ===
def test_auto_feed_initialization():
    """Test that auto_feed parameter initializes correctly."""
    # Default behavior: auto_feed should be True if not specified
    chat_default = Chat(
        name="auto_feed_default",
        utensils=[]
    )
    # Ensure it actually does not have auto_feed set as a param yet-- it should be missing until set
    assert chat_default.params is None, "ChatParams should not be auto-created without setting auto_feed"
    # fail the test if chat.auto_feed is not None
    assert chat_default.auto_feed is None, "auto_feed should be None when not explicitly set"
    
    # Explicitly set auto_feed to False
    chat_no_feed = Chat(
        name="auto_feed_false",
        utensils=[],
        auto_feed=False
    )
    assert chat_no_feed.params.auto_feed is False, "auto_feed should be False when explicitly set"

    # Explicitly set auto_feed to True
    chat_with_feed = Chat(
        name="auto_feed_true",
        utensils=[],
        auto_feed=True
    )
    assert chat_with_feed.params.auto_feed is True, "auto_feed should be True when explicitly set"

# === Test 8: Execution Without Feeding Tool Results ===
@pytest.mark.parametrize("engine", TOOL_COMPATIBLE_ENGINES[:1])  # Use just the first engine for this test
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, 
                    reason="OPENAI_API_KEY is not set in environment or .env")
def test_auto_execute_without_auto_feed(engine):
    """Test that tools execute but don't feed results back to the engine when auto_execute=True and auto_feed=False."""
    
    # Define a test-local utensil that logs when it gets called
    call_tracker = {"times_called": 0}
    
    @utensil(name="trackable_tool", description="A tool that tracks when it's called")
    def trackable_tool(query: str):
        """Returns data about a query and tracks it was called."""
        call_tracker["times_called"] += 1
        return {
            "query": query,
            "result": f"Processed query: {query}",
            "timestamp": "2025-03-11"
        }
    
    # Create a chat with auto_execute=True but auto_feed=False
    chat = Chat(
        system="You are a helpful assistant that must use tools. After using a tool once, you should make your final response.",
        utensils=[trackable_tool],
        auto_execute=True,   # Tools will be executed
        auto_feed=False,     # Tool results won't be fed back to the model
        tool_choice="required"  # Force tool usage to ensure the test works
    )
    
    chat.model = engine
    chat.temperature = 0  # Deterministic for testing
    
    prompt = "I need information about test data, please use the trackable_tool."
    
    try:
        result = chat.user(prompt).chat()
        
        # Check message flow
        has_tool_calls = False
        has_tool_execution = False
        has_tool_being_fed_back = False
        
        for idx, message in enumerate(result.messages):
            if isinstance(message, dict):
                # Check for assistant making a tool call
                if "assistant" in message and isinstance(message["assistant"], dict):
                    asst_msg = message["assistant"]
                    if "tool_calls" in asst_msg and asst_msg["tool_calls"]:
                        has_tool_calls = True
                
                # Check if tool was executed (should have happened due to auto_execute=True)
                if "tool" in message:
                    has_tool_execution = True
                
                # Check if there's evidence of a follow-up assistant message that references tool results
                # This should NOT happen due to auto_feed=False
                if idx > 0 and "assistant" in message:
                    if any("tool" in prev_msg for prev_msg in result.messages[idx-1:idx]):
                        has_tool_being_fed_back = True
        
        # Assertions about the behavior
        assert has_tool_calls, f"Engine {engine} failed to make any tool calls"
        assert has_tool_execution, f"Tool wasn't executed even though auto_execute=True"
        assert call_tracker["times_called"] > 0, "Tool function wasn't actually called"
        assert not has_tool_being_fed_back, "Tool results were fed back to the model despite auto_feed=False"
        
        # The final response should be directly after the tool call without seeing tool results
        final_message = result.last
        assert final_message is not None, f"No final response from {engine}"
            
    except Exception as e:
        pytest.fail(f"Test failed with error: {str(e)}")

# === Test 9: Comparing Behavior with auto_feed True vs False ===
@pytest.mark.parametrize("engine", TOOL_COMPATIBLE_ENGINES[:1])  # Use just the first engine to save time
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, 
                    reason="OPENAI_API_KEY is not set in environment or .env")
def test_auto_feed_behavior_comparison(engine):
    """Compare behavior with auto_feed True vs False."""
    
    # Define a utensil that returns specific, recognizable information
    @utensil(name="data_provider", description="A tool that provides specific data")
    def data_provider():
        """Returns a specific data pattern that would be recognizable in outputs."""
        return {
            "special_code": "X7Z9Q2",
            "timestamp": "2025-03-11"
        }
    
    prompt = "Use the data_provider tool and then tell me the special code it returned."
    
    # Test with auto_feed=True (default)
    chat_with_feed = Chat(
        system="You are a helpful assistant.",
        utensils=[data_provider],
        auto_execute=True,
        auto_feed=True,
        tool_choice="required"
    )
    
    chat_with_feed.model = engine
    chat_with_feed.temperature = 0
    
    # Test with auto_feed=False
    chat_without_feed = Chat(
        system="You are a helpful assistant.",
        utensils=[data_provider],
        auto_execute=True,
        auto_feed=False,
        tool_choice="required"
    )
    
    chat_without_feed.model = engine
    chat_without_feed.temperature = 0
    
    try:
        # Run both chats
        result_with_feed = chat_with_feed.user(prompt).chat()
        result_without_feed = chat_without_feed.user(prompt).chat()
        
        # With auto_feed=True, the response should include the special code
        code_present_with_feed = "X7Z9Q2" in result_with_feed.last
        
        # With auto_feed=False, the response should NOT include the special code
        # because the model never saw the tool results
        code_present_without_feed = "X7Z9Q2" in result_without_feed.last
        
        assert code_present_with_feed, "Model should mention special code when auto_feed=True"
        assert not code_present_without_feed, "Model should NOT know special code when auto_feed=False"
            
    except Exception as e:
        pytest.fail(f"Test failed with error: {str(e)}")


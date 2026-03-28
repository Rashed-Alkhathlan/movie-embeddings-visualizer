import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from models.chat_model import MCPChatbot

'''
This is a test for the MCPChatbot class. 
It tests and it verifies that the streaming response correctly handles tool calls, token generation.

To run tests run the following command:

    pytest tests/backend/test_ask_stream.py -v

'''


def make_event(kind, **kwargs):
    return {"event": kind, **kwargs}


def make_stream_event(text):
    chunk = MagicMock()
    chunk.content = text
    return {
        "event": "on_chat_model_stream",
        "data": {"chunk": chunk},
        "name": "model",
    }


async def fake_astream_events(input, version):
    # Simulate: tool call → token stream
    yield make_event("on_tool_start", name="web_search",
                     data={"input": {"queries": ["sci-fi movies"]}})
    yield make_event("on_tool_end", data={})
    yield make_stream_event("Here are ")
    yield make_stream_event("some great ")
    yield make_stream_event("sci-fi movies.")
    yield make_event("on_chain_end", name="LangGraph",
                     data={"output": {"messages": []}})


@pytest.fixture
def bot():
    agent = MagicMock()
    agent.astream_events = fake_astream_events
    mcp_client = MagicMock()
    return MCPChatbot(agent=agent, mcp_client=mcp_client, model_name="mock-model")


@pytest.mark.asyncio
async def test_yields_status_on_tool_start(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    types = [e[0] for e in events]
    assert "status" in types


@pytest.mark.asyncio
async def test_yields_status_clear_on_tool_end(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    types = [e[0] for e in events]
    assert "status_clear" in types


@pytest.mark.asyncio
async def test_yields_tokens(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    tokens = [data for kind, data in events if kind == "token"]
    assert "".join(tokens) == "Here are some great sci-fi movies."


@pytest.mark.asyncio
async def test_ends_with_reply_done(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    assert events[-1] == ("reply_done", "")


@pytest.mark.asyncio
async def test_history_updated(bot):
    await bot.ask_stream("best sci-fi").__anext__()  # start it
    events = [e async for e in bot.ask_stream("best sci-fi")]
    assert any(h["role"] == "user" for h in bot.history)


@pytest.mark.asyncio
async def test_tokens_narration_filtering_on_tool_call(bot):
    """A single narration token before a tool call should not be returned or trigger tokens_reset."""
    async def stream_with_narration(input, version):
        # Narration before tool
        yield make_stream_event("I will search for this.")
        yield make_event("on_tool_start", name="web_search",
                         data={"input": {"queries": ["sci-fi"]}})
        yield make_event("on_tool_end", data={})
        yield make_stream_event("Here are the results.")
        yield make_event("on_chain_end", name="LangGraph",
                         data={"output": {"messages": []}})

    bot.agent.astream_events = stream_with_narration
    events = [e async for e in bot.ask_stream("sci-fi")]
    # Final answer should not contain narration
    tokens = "".join(d for k, d in events if k == "token")
    assert "I will search" not in tokens


@pytest.mark.asyncio
async def test_tokens_reset_on_new_tool_call(bot):
    """Multiple narration tokens before a tool call should trigger tokens_reset."""
    async def stream_with_narration(input, version):
        # Narration before tool
        yield make_stream_event("I will search for this.")
        yield make_stream_event("And this too.")
        yield make_event("on_tool_start", name="web_search",
                         data={"input": {"queries": ["sci-fi"]}})
        yield make_event("on_tool_end", data={})
        yield make_stream_event("Here are the results.")
        yield make_event("on_chain_end", name="LangGraph",
                         data={"output": {"messages": []}})

    bot.agent.astream_events = stream_with_narration
    events = [e async for e in bot.ask_stream("sci-fi")]
    types = [e[0] for e in events]
    assert "tokens_reset" in types


@pytest.mark.asyncio
async def test_no_api_calls_made(bot):
    """Confirm the real LLM is never invoked."""
    with patch("models.chat_model.ChatGoogleGenerativeAI") as mock_llm:
        events = [e async for e in bot.ask_stream("test")]
        mock_llm.assert_not_called()
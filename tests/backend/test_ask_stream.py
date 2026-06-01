import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from models.chat_model import MCPChatbot, _tool_status

'''
Tests for MCPChatbot.ask_stream — verifies tool status, token streaming,
reasoning ("thinking") separation, and history handling.

    pytest tests/backend/test_ask_stream.py -v
'''


def make_event(kind, **kwargs):
    return {"event": kind, **kwargs}


def make_stream_event(text):
    """A plain answer-text chunk (no reasoning), as an OpenAI-style provider emits."""
    chunk = MagicMock()
    chunk.content = text
    chunk.content_blocks = None
    chunk.additional_kwargs = {}
    return {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}


def make_reasoning_event(reasoning):
    """A reasoning chunk surfaced via additional_kwargs.reasoning_content."""
    chunk = MagicMock()
    chunk.content = ""
    chunk.content_blocks = None
    chunk.additional_kwargs = {"reasoning_content": reasoning}
    return {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}


def make_blocks_event(reasoning="", text=""):
    """A chunk that exposes typed content blocks (Gemini / NVIDIA style)."""
    blocks = []
    if reasoning:
        blocks.append({"type": "reasoning", "reasoning": reasoning})
    if text:
        blocks.append({"type": "text", "text": text})
    chunk = MagicMock()
    chunk.content_blocks = blocks
    return {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}


async def fake_astream_events(input, version):
    # tool call → answer tokens
    yield make_event("on_tool_start", name="web_search",
                     data={"input": {"queries": ["sci-fi movies"]}})
    yield make_event("on_tool_end", data={})
    yield make_stream_event("Here are ")
    yield make_stream_event("some great ")
    yield make_stream_event("sci-fi movies.")


@pytest.fixture
def bot():
    agent = MagicMock()
    agent.astream_events = fake_astream_events
    mcp_client = MagicMock()
    return MCPChatbot(agent=agent, mcp_client=mcp_client, model_name="mock-model")


# ── status / tokens ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_yields_status_on_tool_start(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    assert "status" in [k for k, _ in events]


@pytest.mark.asyncio
async def test_yields_status_clear_on_tool_end(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    assert "status_clear" in [k for k, _ in events]


@pytest.mark.asyncio
async def test_yields_tokens(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    tokens = "".join(d for k, d in events if k == "token")
    assert tokens == "Here are some great sci-fi movies."


@pytest.mark.asyncio
async def test_ends_with_reply_done(bot):
    events = [e async for e in bot.ask_stream("best sci-fi")]
    assert events[-1] == ("reply_done", "")


@pytest.mark.asyncio
async def test_history_updated(bot):
    [e async for e in bot.ask_stream("best sci-fi")]
    assert bot.history[-2:] == [
        {"role": "user", "content": "best sci-fi"},
        {"role": "assistant", "content": "Here are some great sci-fi movies."},
    ]


# ── reasoning ("thinking") separation ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_yields_thinking_from_reasoning_content(bot):
    async def stream(input, version):
        yield make_reasoning_event("I am reasoning about this.")
        yield make_stream_event("Final answer.")
    bot.agent.astream_events = stream

    events = [e async for e in bot.ask_stream("q")]
    thinking = "".join(d for k, d in events if k == "thinking")
    tokens = "".join(d for k, d in events if k == "token")

    assert thinking == "I am reasoning about this."
    assert tokens == "Final answer."
    # Reasoning is never stored in history, only the answer.
    assert bot.history[-1] == {"role": "assistant", "content": "Final answer."}


@pytest.mark.asyncio
async def test_yields_thinking_from_content_blocks(bot):
    async def stream(input, version):
        yield make_blocks_event(reasoning="block reasoning", text="block answer")
    bot.agent.astream_events = stream

    events = [e async for e in bot.ask_stream("q")]
    thinking = "".join(d for k, d in events if k == "thinking")
    tokens = "".join(d for k, d in events if k == "token")

    assert thinking == "block reasoning"
    assert tokens == "block answer"


# ── narration before a tool call ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_narration_before_tool_resets_and_drops_from_history(bot):
    """Text streamed before a tool call is reset on the wire and excluded from history."""
    async def stream(input, version):
        yield make_stream_event("Let me look that up.")
        yield make_event("on_tool_start", name="web_search",
                         data={"input": {"queries": ["sci-fi"]}})
        yield make_event("on_tool_end", data={})
        yield make_stream_event("Here are the results.")
    bot.agent.astream_events = stream

    events = [e async for e in bot.ask_stream("sci-fi")]

    assert ("tokens_reset", "") in events
    assert bot.history[-1] == {"role": "assistant", "content": "Here are the results."}


# ── tool status formatting ────────────────────────────────────────────────────

def test_tool_status_movie_db():
    assert "movie database" in _tool_status("find_similar_movies", {"query": "Inception"})
    assert "**Inception**" in _tool_status("find_similar_movies", {"query": "Inception"})


def test_tool_status_web_search():
    assert _tool_status("web_search", {"query": "best sci-fi"}).startswith("🔍 Searching")


def test_tool_status_fetch():
    assert "Fetching page" in _tool_status("fetch_web_page", {"url": "https://example.com"})


# ── no API calls ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_api_calls_made(bot):
    """The real LLM is never constructed while streaming through a mocked agent."""
    with patch("models.chat_model.ChatGoogleGenerativeAI") as mock_llm:
        [e async for e in bot.ask_stream("test")]
        mock_llm.assert_not_called()

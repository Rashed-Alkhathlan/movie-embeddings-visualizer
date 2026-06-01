import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from models.chat_model import MCPChatbot

'''
Tests for MCPChatbot model switching and history clearing.

    pytest tests/backend/test_model_switching.py -v
'''


@pytest.fixture
def bot():
    agent = MagicMock()
    mcp_client = MagicMock()
    mcp_client.get_tools = AsyncMock(return_value=["mock_tool"])
    b = MCPChatbot(agent=agent, mcp_client=mcp_client, model_name="gemini-3.1-flash-lite")
    b.history = [
        {"role": "user",      "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    return b


# ── reset() ───────────────────────────────────────────────────────────────────

def test_reset_clears_history(bot):
    bot.reset()
    assert bot.history == []


def test_reset_on_empty_history_is_safe(bot):
    bot.history = []
    bot.reset()
    assert bot.history == []


# ── switch_model() ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_switch_model_clears_history(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-3.1-flash-lite")
    assert bot.history == []


@pytest.mark.asyncio
async def test_switch_model_updates_current_model(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-3.1-flash-lite")
    assert bot.current_model == "gemini-3.1-flash-lite"


@pytest.mark.asyncio
async def test_switch_model_replaces_agent(bot):
    old_agent = bot.agent
    new_agent = MagicMock()
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent", return_value=new_agent):
        await bot.switch_model("gemini-3.1-flash-lite")
    assert bot.agent is new_agent
    assert bot.agent is not old_agent


@pytest.mark.asyncio
async def test_switch_model_fetches_tools(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-3.1-flash-lite")
    bot.mcp_client.get_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_to_gemini_uses_google_llm(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI") as mock_google, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-3.1-flash-lite")
    mock_google.assert_called_once()


@pytest.mark.asyncio
async def test_switch_to_cohere_uses_chat_cohere(bot):
    with patch("models.chat_model.ChatCohere") as mock_cohere, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("command-a-03-2025")
    mock_cohere.assert_called_once()
    assert bot.current_model == "command-a-03-2025"


@pytest.mark.asyncio
async def test_switch_to_cerebras_uses_chat_cerebras(bot):
    with patch("models.chat_model.ChatCerebras") as mock_cerebras, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gpt-oss-120b")
    mock_cerebras.assert_called_once()
    assert bot.current_model == "gpt-oss-120b"


@pytest.mark.asyncio
async def test_switch_to_nvidia_uses_chat_nvidia(bot):
    with patch("models.chat_model.ChatNVIDIA") as mock_nvidia, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("stepfun-ai/step-3.7-flash")
    mock_nvidia.assert_called_once()
    assert bot.current_model == "stepfun-ai/step-3.7-flash"


@pytest.mark.asyncio
async def test_switch_model_unknown_raises(bot):
    with pytest.raises(ValueError, match="Unknown model"):
        await bot.switch_model("gpt-4o")


@pytest.mark.asyncio
async def test_switch_model_preserves_mcp_client(bot):
    original_client = bot.mcp_client
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-3.1-flash-lite")
    assert bot.mcp_client is original_client


@pytest.mark.asyncio
async def test_switch_model_temperature_passed(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI") as mock_google, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-3.1-flash-lite", temperature=0.2)
    _, kwargs = mock_google.call_args
    assert kwargs.get("temperature") == 0.2


@pytest.mark.asyncio
async def test_switch_model_multiple_times(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.ChatCohere"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-3.1-flash-lite")
        bot.history = [{"role": "user", "content": "test"}]
        await bot.switch_model("command-a-03-2025")

    assert bot.history == []
    assert bot.current_model == "command-a-03-2025"

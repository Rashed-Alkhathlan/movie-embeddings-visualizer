import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from models.chat_model import MCPChatbot

'''
This is a test for the MCPChatbot class. 
It tests and it verifies that the model switching and history clearing both work correctly.

To run tests run the following command:

    pytest tests/backend/test_model_switching.py -v

'''

@pytest.fixture
def bot():
    agent = MagicMock()
    mcp_client = MagicMock()
    mcp_client.get_tools = AsyncMock(return_value=["mock_tool"])
    b = MCPChatbot(agent=agent, mcp_client=mcp_client, model_name="gemini-2.0-flash")
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
        await bot.switch_model("gemini-1.5-flash")
    assert bot.history == []


@pytest.mark.asyncio
async def test_switch_model_updates_current_model(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-1.5-flash")
    assert bot.current_model == "gemini-1.5-flash"


@pytest.mark.asyncio
async def test_switch_model_replaces_agent(bot):
    old_agent = bot.agent
    mock_new_agent = MagicMock()
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent", return_value=mock_new_agent):
        await bot.switch_model("gemini-1.5-flash")
    assert bot.agent is mock_new_agent
    assert bot.agent is not old_agent


@pytest.mark.asyncio
async def test_switch_model_fetches_tools(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-1.5-flash")
    bot.mcp_client.get_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_to_cohere_uses_chat_cohere(bot):
    with patch("models.chat_model.ChatCohere") as mock_cohere, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("command-a-03-2025")
    mock_cohere.assert_called_once()
    assert bot.current_model == "command-a-03-2025"


@pytest.mark.asyncio
async def test_switch_to_mistral_uses_chat_mistral(bot):
    with patch("models.chat_model.ChatMistralAI") as mock_mistral, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("mistral-large-latest")
    mock_mistral.assert_called_once()
    assert bot.current_model == "mistral-large-latest"


@pytest.mark.asyncio
async def test_switch_to_gemini_uses_google_llm(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI") as mock_google, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-2.0-flash")
    mock_google.assert_called_once()


@pytest.mark.asyncio
async def test_switch_to_gemma_uses_google_llm(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI") as mock_google, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemma-3-27b-it")
    mock_google.assert_called_once()


@pytest.mark.asyncio
async def test_switch_model_unknown_raises(bot):
    with pytest.raises(ValueError, match="Unknown model"):
        await bot.switch_model("gpt-4o")


@pytest.mark.asyncio
async def test_switch_model_preserves_mcp_client(bot):
    original_client = bot.mcp_client
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-2.0-flash")
    assert bot.mcp_client is original_client


@pytest.mark.asyncio
async def test_switch_model_temperature_passed(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI") as mock_google, \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-2.0-flash", temperature=0.2)
    _, kwargs = mock_google.call_args
    assert kwargs.get("temperature") == 0.2


@pytest.mark.asyncio
async def test_switch_model_multiple_times(bot):
    with patch("models.chat_model.ChatGoogleGenerativeAI"), \
         patch("models.chat_model.ChatCohere"), \
         patch("models.chat_model.create_agent"):
        await bot.switch_model("gemini-2.0-flash")
        bot.history = [{"role": "user", "content": "test"}]
        await bot.switch_model("command-a-03-2025")

    assert bot.history == []
    assert bot.current_model == "command-a-03-2025"
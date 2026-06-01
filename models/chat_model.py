import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_cohere import ChatCohere
from langchain_cerebras import ChatCerebras
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_mcp_adapters import client

log = logging.getLogger("app.tools")

# Available models for the frontend switcher. Update when adding a model.
AVAILABLE_MODELS = {
    "gemini-3.1-flash-lite":             {"label": "Gemini 3.1 Flash Lite", "provider": "Google"},
    "command-a-03-2025":                 {"label": "Command A",             "provider": "Cohere"},
    "gpt-oss-120b":                      {"label": "GPT OSS",               "provider": "Cerebras"},
    "zai-glm-4.7":                       {"label": "Z.ai GLM 4.7",          "provider": "Cerebras"},
    "nvidia/nemotron-3-super-120b-a12b": {"label": "NemoTron 3 Super 120B", "provider": "NVIDIA"},
    "stepfun-ai/step-3.7-flash":         {"label": "Step 3.7 Flash",        "provider": "NVIDIA"},
}

MODEL_PROVIDERS = {
    "Google":   lambda model, temp: ChatGoogleGenerativeAI(model=model, temperature=temp),
    "Cohere":   lambda model, temp: ChatCohere(model=model, temperature=temp),
    "Cerebras": lambda model, temp: ChatCerebras(model=model, temperature=temp),
    "NVIDIA":   lambda model, temp: ChatNVIDIA(model=model, temperature=temp),
}

SYSTEM_PROMPT = (
    "You are a knowledgeable movie assistant. You help users discover films, find "
    "similar titles, and answer questions about movies, the people who make them, and "
    "the industry.\n\n"
    "Tools available to you:\n"
    "- find_similar_movies: searches a vector database of films for titles similar to a "
    'given movie. Use it for recommendations or "movies like X" requests. Pass a title, '
    'optionally with the year, e.g. "Inception (2010)".\n'
    "- web_search, fetch_web_page, research_topic, research_multiple_topics: use these "
    "for facts that may be recent or that you are unsure of — release dates, current "
    "cast, reviews, streaming availability, box office, or news.\n\n"
    "Guidelines:\n"
    "- For recommendation requests, prefer calling find_similar_movies and blend its "
    "results with your own knowledge, clearly distinguishing which suggestions come from "
    "the database and which are your own. Honor a requested count; otherwise offer around five.\n"
    "- Reach for the web tools when an answer depends on up-to-date or verifiable facts "
    "rather than relying on memory, and cite the source URLs you used.\n"
    "- If a tool returns nothing useful, say so plainly and fall back to your own knowledge.\n"
    "- Keep answers concise and well organized."
)


# ---------------------------------------------------------------------------
# Tool-result compatibility shim
# ---------------------------------------------------------------------------

def _flatten_tool_content(blocks: list) -> str | None:
    """Join text content blocks into one string; None if a non-text block is present."""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        else:
            return None  # leave image/file results untouched
    return "\n".join(parts)


class FlattenToolContentMiddleware(AgentMiddleware):
    """Force tool-result content to a plain string before the model call.

    langchain-mcp-adapters returns each MCP result as a list of content blocks
    (e.g. ``[{"type": "text", "text": ..., "id": "lc_..."}]``). OpenAI-compatible
    providers such as Cerebras require tool message content to be a string and reject
    the auto-generated ``id`` (HTTP 400). Flattening here keeps the payload valid for
    every provider without mutating the agent's stored state.
    """

    def _rewrite(self, request):
        messages = []
        changed = False
        for msg in request.messages:
            if isinstance(msg, ToolMessage) and isinstance(msg.content, list):
                text = _flatten_tool_content(msg.content)
                if text is not None:
                    msg = msg.model_copy(update={"content": text})
                    changed = True
            messages.append(msg)
        return request.override(messages=messages) if changed else request

    def wrap_model_call(self, request, handler):
        return handler(self._rewrite(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._rewrite(request))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_llm(model_name: str, temperature: float):
    model = AVAILABLE_MODELS.get(model_name)
    if not model:
        raise ValueError(f"Unknown model: {model_name}")
    factory = MODEL_PROVIDERS.get(model["provider"])
    if not factory:
        raise ValueError(f"Unsupported provider: {model['provider']}")
    return factory(model_name, temperature)


def _build_agent(llm: Any, tools: list) -> Any:
    return create_agent(
        llm, tools=tools, system_prompt=SYSTEM_PROMPT,
        middleware=[FlattenToolContentMiddleware()],
    )


def _tool_status(name: str, tool_input: dict) -> str:
    """Human-friendly status line shown in the UI while a tool runs."""
    name = name.lower()
    if "similar" in name or "movie" in name:
        query = tool_input.get("query") or ""
        return f"🎬 Searching the movie database for **{query}**" if query else "🎬 Searching the movie database"
    if "search" in name or "research" in name:
        query = tool_input.get("queries") or tool_input.get("query")
        if isinstance(query, list):
            return "🔎 Researching the web for: " + ", ".join(f"**{q}**" for q in query)
        verb = "Researching" if "research" in name else "Searching"
        return f"🔍 {verb} the web for: **{query}**"
    if "fetch" in name or "browse" in name:
        url = tool_input.get("url") or tool_input.get("path", "")
        short = url[:60] + "…" if len(url) > 60 else url
        return f"🌐 Fetching page: `{short}`"
    return f"⚙️ Using tool: `{name}`"


def _reasoning_and_answer(chunk: Any) -> tuple[str, str]:
    """Pull (reasoning, answer) text deltas out of a streamed model chunk.

    Reasoning arrives either as typed content blocks (Gemini, NVIDIA) or as
    ``reasoning_content`` in additional_kwargs (OpenAI-compatible providers).
    """
    blocks = getattr(chunk, "content_blocks", None)
    if blocks:
        reasoning = "".join(b.get("reasoning", "") for b in blocks if b.get("type") == "reasoning")
        answer = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return reasoning, answer

    reasoning = (getattr(chunk, "additional_kwargs", {}) or {}).get("reasoning_content", "") or ""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return reasoning, content
    if isinstance(content, list):
        return reasoning, "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return reasoning, ""


# ---------------------------------------------------------------------------
# Chatbot
# ---------------------------------------------------------------------------

class MCPChatbot:
    def __init__(self, agent: Any, mcp_client: client.MultiServerMCPClient, model_name: str = "") -> None:
        self.agent = agent
        self.mcp_client = mcp_client  # keep a reference so the MCP servers stay alive
        self.history: list[dict[str, str]] = []
        self.current_model = model_name

    async def ask(self, text: str, keep_history: bool = True) -> str:
        messages = (list(self.history) if keep_history else []) + [{"role": "user", "content": text}]
        result = await self.agent.ainvoke({"messages": messages})

        out = result.get("messages", []) if isinstance(result, dict) else []
        answer = out[-1].content if out else str(result)
        if isinstance(answer, list):  # content blocks → join their text
            answer = "".join(b.get("text", "") for b in answer if isinstance(b, dict))

        if keep_history:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": answer})
        return answer

    async def ask_stream(self, text: str, keep_history: bool = True):
        """Stream the reply as (event_type, data) pairs.

        Event types: ``status``/``status_clear`` (tool activity), ``thinking``
        (reasoning), ``token`` (answer text), ``tokens_reset`` (discard answer shown
        so far), ``reply_done``.
        """
        messages = (list(self.history) if keep_history else []) + [{"role": "user", "content": text}]

        answer = ""
        tool_active = False

        async for event in self.agent.astream_events({"messages": messages}, version="v2"):
            kind = event.get("event")

            if kind == "on_tool_start":
                tool_active = True
                if answer:  # discard any narration streamed before the tool call
                    answer = ""
                    yield ("tokens_reset", "")
                name = event.get("name", "tool")
                tool_input = event.get("data", {}).get("input", {})
                log.info("tool_start name=%s input=%s", name, tool_input)
                yield ("status", _tool_status(name, tool_input))

            elif kind == "on_tool_end":
                tool_active = False
                yield ("status_clear", "")

            elif kind == "on_chat_model_stream" and not tool_active:
                chunk = event.get("data", {}).get("chunk")
                if not chunk:
                    continue
                reasoning, token = _reasoning_and_answer(chunk)
                if reasoning:
                    yield ("thinking", reasoning)
                if token:
                    answer += token
                    yield ("token", token)

        if keep_history:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": answer})
        yield ("reply_done", "")

    async def switch_model(self, model_name: str, temperature: float = 0.7) -> None:
        llm = _make_llm(model_name, temperature)
        tools = await self.mcp_client.get_tools()
        self.agent = _build_agent(llm, tools)
        self.current_model = model_name
        self.history.clear()

    def reset(self) -> None:
        self.history.clear()


async def build_chatbot(model_name: str = "gemini-3.1-flash-lite", temperature: float = 0.7) -> MCPChatbot:
    load_dotenv()
    mcp_dir = Path(__file__).resolve().parent.parent / "mcps"
    mcp_client = client.MultiServerMCPClient({
        "web_search": {
            "command": sys.executable,
            "args": [str(mcp_dir / "web_search_mcp.py")],
            "transport": "stdio",
        },
        "database_search": {
            "command": sys.executable,
            "args": [str(mcp_dir / "database_search_mcp.py")],
            "transport": "stdio",
        },
    })

    llm = _make_llm(model_name, temperature)
    tools = await mcp_client.get_tools()
    agent = _build_agent(llm, tools)
    return MCPChatbot(agent=agent, mcp_client=mcp_client, model_name=model_name)


def create_chatbot() -> MCPChatbot:
    return asyncio.run(build_chatbot())


# Run this file directly to chat in the console.
if __name__ == "__main__":
    chatbot = create_chatbot()
    print("Chatbot ready! Type 'exit' to quit.")
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        print("Bot:", asyncio.run(chatbot.ask(user_input)))

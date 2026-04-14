import asyncio
import sys
from pathlib import Path
from typing import Any
import json

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_cohere import ChatCohere 
from langchain_mistralai import ChatMistralAI
from langchain_cerebras import ChatCerebras
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_mcp_adapters import client

# Avalible LLM models                                               PS: Update list when adding a new one
# Used for frontend model switching and fallbacks
AVAILABLE_MODELS = {
    "gemini-3.1-flash-lite-preview":    {"label": "Gemini 3.1 Flash Lite Preview",   "provider": "Google"},
    "command-a-03-2025":                {"label": "Command A",                       "provider": "Cohere"},
    "qwen-3-235b-a22b-instruct-2507":   {"label": "Qwen 3 235b",                     "provider": "Cerebras"},
    "moonshotai/kimi-k2-instruct":      {"label": "Kimi K2 Instruct",                "provider": "NVIDIA"},
    "stepfun-ai/step-3.5-flash":        {"label": "Step 3.5 Flash",                  "provider": "NVIDIA"},
}

MODEL_PROVIDERS = {
    "Google":   lambda model, temp: ChatGoogleGenerativeAI(model=model, temperature=temp),
    "Cohere":   lambda model, temp: ChatCohere(model=model, temperature=temp),
    "Cerebras": lambda model, temp: ChatCerebras(model=model, temperature=temp),
    "NVIDIA":   lambda model, temp: ChatNVIDIA(model=model, temperature=temp),
}


def print_agent_trace(result: Any) -> None:
    for msg in result["messages"]:
        role = type(msg).__name__

        print(f"\n[{role}]")

        if getattr(msg, "tool_calls", None):
            for tool in msg.tool_calls:
                print("TOOL:", tool["name"])
                print("ARGS:", tool["args"])

        if getattr(msg, "content", None):
            content = msg.content
            if isinstance(content, str):
                print(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        text = item["text"]

                        try:
                            parsed = json.loads(text)
                            print(json.dumps(parsed, indent=2))
                        except:
                            print(text)

class MCPChatbot:

    def __init__(self, agent: Any, mcp_client: client.MultiServerMCPClient, model_name: str = "") -> None:
        self.agent = agent
        self.mcp_client = mcp_client  # Keep a reference so MCP servers stay alive.
        self.history: list[dict[str, str]] = []
        self.current_model = model_name  # track active model


    async def ask(self, text: str, keep_history: bool = True) -> str:
        messages = list(self.history) if keep_history else []
        messages.append({"role": "user", "content": text})

        result = await self.agent.ainvoke({"messages": messages})

        print_agent_trace(result)

        result_messages = result.get("messages", []) if isinstance(result, dict) else []
        answer = result_messages[-1].content if result_messages else str(result)

        if isinstance(answer, list):
            answer = answer[0].get("text", str(answer))

        if keep_history:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": answer})

        return answer
    
    
    async def ask_stream(self, text: str, keep_history: bool = True):
        messages = list(self.history) if keep_history else []
        messages.append({"role": "user", "content": text})

        final_answer = ""
        collected_messages = []
        tool_active = False

        async for event in self.agent.astream_events({"messages": messages}, version="v2"):
            kind = event.get("event")

            print(kind)

            if kind == "on_chain_end" and event.get("name") == "LangGraph":
                output = event.get("data", {}).get("output", {})
                collected_messages = output.get("messages", [])

            elif kind == "on_tool_start":
                tool_active = True

                if final_answer:
                    final_answer = ""
                    yield ("tokens_reset", "")

                tool_name = event.get("name", "tool")
                tool_input = event.get("data", {}).get("input", {})

                if "search" in tool_name.lower():
                    queries = tool_input.get("queries") or tool_input.get("query")
                    if isinstance(queries, list):
                        query_text = ", ".join(f"**{q}**" for q in queries)
                        status = f"🔎 Multi-Researching the web for: {query_text}"
                    else:
                        query_text = f"**{queries}**"
                        if "research" in tool_name.lower():
                            status = f"🔍 Researching the web for: {query_text}"
                        else:
                            status = f"🔍 Searching the web for: {query_text}"

                elif "fetch" in tool_name.lower() or "browse" in tool_name.lower():
                    url = tool_input.get("url", tool_input.get("path", ""))
                    short_url = url[:60] + "…" if len(url) > 60 else url
                    status = f"🌐 Fetching page: `{short_url}`"

                else:
                    status = f"⚙️ Using tool: `{tool_name}`"

                yield ("status", status)

            elif kind == "on_tool_end":
                tool_active = False
                yield ("status_clear", "")

            elif kind == "on_chat_model_stream":
                if tool_active:
                    continue

                chunk = event.get("data", {}).get("chunk")
                if not chunk:
                    continue

                content_blocks = getattr(chunk, "content_blocks", None)
                if content_blocks:
                    # Path 1: Gemini, Anthropic, NVIDIA (future) — structured blocks

                    for block in content_blocks:
                        if block.get("type") == "reasoning":
                            thinking_text = block.get("reasoning", "")
                            if thinking_text:
                                yield ("thinking", thinking_text)

                        elif block.get("type") == "text":
                            token = block.get("text", "")

                            if token:
                                if "</think>" in token: # For Step 3.5 Flash which may include thinking and answer in the same block, we split them and emit a reset event for the thinking part
                                    token = token.split("\n</think>\n")[-1].strip()
                                    yield ("tokens_reset", "")

                                if token:
                                    final_answer += token
                                    yield ("token", token)

                else:
                    # Path 2: additional_kwargs (fallback for providers without content_blocks)
                    reasoning = (getattr(chunk, "additional_kwargs", {}) or {}).get("reasoning_content", "")
                    if reasoning:
                        yield ("thinking", reasoning)


                    # Path 3: plain string content
                    content = getattr(chunk, "content", "")
                    if isinstance(content, str) and content:
                        final_answer += content
                        yield ("token", content)
                    elif isinstance(content, list):
                        for item in content:
                            token = item.get("text", "") if isinstance(item, dict) else ""
                            if token:
                                final_answer += token
                                yield ("token", token)

        if collected_messages:
            # print_agent_trace({"messages": collected_messages})   # Uncomment for printing the agent's trace for debuging
            pass

        if keep_history:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": final_answer})

        yield ("reply_done", "")


    async def switch_model(self, model_name: str, temperature: float = 0.7) -> None:
        model = AVAILABLE_MODELS.get(model_name)
        if not model:
            raise ValueError(f"Unknown model: {model_name}")

        provider = model["provider"]

        model_provider = MODEL_PROVIDERS.get(provider)
        if not model_provider:
            raise ValueError(f"Unsupported provider: {provider}")

        llm = model_provider(model_name, temperature)

        tools = await self.mcp_client.get_tools()
        self.agent = create_agent(llm, tools=tools)

        self.current_model = model_name
        self.history.clear()


    def reset(self) -> None:
        self.history.clear()


async def build_chatbot(
    model_name: str = "gemini-3.1-flash-lite-preview",
    temperature: float = 0.7,
    enable_tools: bool = True,
) -> MCPChatbot:
    
    load_dotenv()
    base_dir = Path(__file__).resolve().parent.parent
    mcp_dir = base_dir / "mcps"

    mcp_client = client.MultiServerMCPClient(
        {
            "web_research": {
                "command": sys.executable,
                "args": [str(mcp_dir / "web_research_mcp.py")],
                "transport": "stdio",
            }
        }
    )

    model = AVAILABLE_MODELS.get(model_name)
    if not model:
        raise ValueError(f"Unknown model: {model_name}")

    provider = model["provider"]

    model_provider = MODEL_PROVIDERS.get(provider)
    if not model_provider:
        raise ValueError(f"Unsupported provider: {provider}")

    llm = model_provider(model_name, temperature)

    if enable_tools:
        tools = await mcp_client.get_tools()
        agent = create_agent(llm, tools=tools)
    else:
        agent = create_agent(llm)

    return MCPChatbot(agent=agent, mcp_client=mcp_client, model_name=model_name)


def create_chatbot() -> MCPChatbot:
    return asyncio.run(build_chatbot())


# For testing purposes, you can run this file directly to interact with the chatbot in the console.
if __name__ == "__main__":
    chatbot = create_chatbot()
    print("Chatbot is ready! Type your messages below (type 'exit' to quit).")
    while True:
        user_input = input("You: ")
        if user_input.lower() == "exit":
            break
        response = asyncio.run(chatbot.ask(user_input))
        print(f"Bot: {response}")
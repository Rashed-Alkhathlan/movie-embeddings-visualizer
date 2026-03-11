import asyncio
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters import client


class MCPChatbot:
    def __init__(self, agent: Any, mcp_client: client.MultiServerMCPClient) -> None:
        self.agent = agent
        self.mcp_client = mcp_client  # Keep a reference so MCP servers stay alive.
        self.history: list[dict[str, str]] = []

    def ask(self, text: str, keep_history: bool = True) -> str:
        messages = list(self.history) if keep_history else []
        messages.append({"role": "user", "content": text})

        result = self.agent.invoke({"messages": messages})
        result_messages = result.get("messages", []) if isinstance(result, dict) else []
        answer = result_messages[-1].content if result_messages else str(result)

        if keep_history:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": answer})

        return answer

    def reset(self) -> None:
        self.history.clear()


async def build_chatbot(
    model_name: str = "gemma-3-27b-it",
    temperature: float = 0.7,
    enable_tools: bool = False,
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

    llm = ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    if enable_tools:
        tools = await mcp_client.get_tools()
        agent = create_agent(llm, tools=tools)
    else:
        agent = create_agent(llm)

    return MCPChatbot(agent=agent, mcp_client=mcp_client)


def create_chatbot(
    model_name: str = "gemma-3-27b-it",
    temperature: float = 0.7,
    enable_tools: bool = False,
) -> MCPChatbot:
    return asyncio.run(build_chatbot(model_name=model_name, temperature=temperature, enable_tools=enable_tools))
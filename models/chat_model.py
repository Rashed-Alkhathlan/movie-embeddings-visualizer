import asyncio
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_cohere import ChatCohere 
from langchain_mistralai import ChatMistralAI
from langchain_mcp_adapters import client

def print_agent_trace(result):
    for msg in result["messages"]:
        role = type(msg).__name__

        print(f"\n[{role}]")

        if getattr(msg, "tool_calls", None):
            for tool in msg.tool_calls:
                print("TOOL:", tool["name"])
                print("ARGS:", tool["args"])

        if getattr(msg, "content", None):
            print(msg.content)

class MCPChatbot:

    def __init__(self, agent: Any, mcp_client: client.MultiServerMCPClient) -> None:
        self.agent = agent
        self.mcp_client = mcp_client  # Keep a reference so MCP servers stay alive.
        self.history: list[dict[str, str]] = []

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

    def reset(self) -> None:
        self.history.clear()


async def build_chatbot(
    model_name: str = "gemma-3-27b-it",
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

    if "gemma" in model_name or "gemini" in model_name:
        llm = ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    elif "command" in model_name:
        llm = ChatCohere(model=model_name, temperature=temperature) # best is "command-a-03-2025"
    elif "mistral" in model_name:
        llm = ChatMistralAI(model=model_name, temperature=temperature)

    if enable_tools:
        tools = await mcp_client.get_tools()
        agent = create_agent(llm, tools=tools)
    else:
        agent = create_agent(llm)

    return MCPChatbot(agent=agent, mcp_client=mcp_client)


def create_chatbot() -> MCPChatbot:
    return asyncio.run(build_chatbot(model_name="gemini-3.1-flash-lite-preview"))


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
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
from langchain_mcp_adapters import client

# Avalible LLM models                                               PS: Update list when adding a new one
# Used for frontend model switching and fallbacks
AVAILABLE_MODELS = [
    {"id": "gemini-3.1-flash-lite-preview",     "label": "Gemini 3.1 Flash Lite Preview",   "provider": "Google"},
    {"id": "command-a-03-2025",                 "label": "Command A",                       "provider": "Cohere"},
    {"id": "qwen-3-235b-a22b-instruct-2507",    "label": "Qwen 3 235b",                     "provider": "Cerebras"},
]


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
        step = 0
        current_step = 0
        step_token_buffer = []  # buffer tokens for current step

        async for event in self.agent.astream_events({"messages": messages}, version="v2"):
            kind = event.get("event")

            if kind == "on_chain_end" and event.get("name") == "LangGraph":
                output = event.get("data", {}).get("output", {})
                collected_messages = output.get("messages", [])

            elif kind == "on_tool_start":
                tool_active = True
                current_step = step

                # Discard buffered tokens — they were planning narration
                if step_token_buffer:
                    step_token_buffer.clear()
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


                if step > current_step:
                    # New step — flush previous buffer as real tokens
                    for token in step_token_buffer:
                        final_answer += token
                        yield ("token", token)
                    step_token_buffer.clear()
                    current_step = step

                step += 1

                chunk = event.get("data", {}).get("chunk")
                if chunk:
                    content = chunk.content if hasattr(chunk, "content") else ""
                    if isinstance(content, str) and content:
                        step_token_buffer.append(content)
                    elif isinstance(content, list) and content:
                        token = content[0].get("text", "")
                        if token:
                            step_token_buffer.append(token)

        # Flush remaining buffer — these are the final answer tokens
        for token in step_token_buffer:
            final_answer += token
            yield ("token", token)
        step_token_buffer.clear()

        if collected_messages:
            # print_agent_trace({"messages": collected_messages})   # Uncomment for printing the agent's trace for debuging
            pass

        if keep_history:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": final_answer})

        yield ("reply_done", "")


    async def switch_model(self, model_name: str, temperature: float = 0.7) -> None:
        if "gemma" in model_name or "gemini" in model_name:
            llm = ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
        elif "command" in model_name:
            llm = ChatCohere(model=model_name, temperature=temperature)
        elif "mistral" in model_name or "mixtral" in model_name:
            llm = ChatMistralAI(model_name=model_name, temperature=temperature)
        elif "cerebras" in model_name or "qwen" in model_name or "llama" in model_name:
            llm = ChatCerebras(model=model_name, temperature=temperature)
        else:
            raise ValueError(f"Unknown model: {model_name}")

        tools = await self.mcp_client.get_tools()
        self.agent = create_agent(llm, tools=tools)
        self.current_model = model_name  # update on switch
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

    if "gemma" in model_name or "gemini" in model_name:
        llm = ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    elif "command" in model_name:
        llm = ChatCohere(model=model_name, temperature=temperature) # best is "command-a-03-2025"
    elif "mistral" in model_name:
        llm = ChatMistralAI(model_name=model_name, temperature=temperature)
    elif "cerebras" in model_name or "qwen" in model_name or "llama" in model_name:
        llm = ChatCerebras(model=model_name, temperature=temperature)

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
import sys
from pathlib import Path

# Ensure the repo root is importable when this server is launched as a standalone
# script (python mcps/database_search_mcp.py): Python puts mcps/ on sys.path, not
# the project root, so without this `movie_data` would not resolve. Importing
# movie_data (numpy/pandas/scipy only) avoids pulling in the Flask app/chatbot.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Any

from movie_data import get_closest_movies


try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except ModuleNotFoundError:

    class FastMCP:  # type: ignore[override]
        """Minimal stub so the module can be imported without the *mcp* package."""

        def __init__(self, _name: str) -> None:
            self._name = _name

        def tool(self):
            def decorator(func):
                return func
            return decorator

        def run(self, transport: str = "stdio") -> None:
            raise RuntimeError(
                "FastMCP is unavailable.  Install the 'mcp' package to run as an MCP "
                f"server.  Requested transport={transport!r}."
            )

DEFAULT_TRANSPORT = "stdio"

mcp = FastMCP("database_search")

@mcp.tool()
def find_similar_movies(query: str, top_k: int = 3) -> dict[str, Any]:
    """Return vector-search results for movies similar to the movie title (Query should be a title like: \"Title (year)\" the year is optional)."""
    title, results = get_closest_movies(query, n=top_k)
    if results is None:
        return {"query": query, "found": False, "results": []}
    return {"query": title, "found": True, "results": results}


if __name__ == "__main__":
    mcp.run(transport=DEFAULT_TRANSPORT)
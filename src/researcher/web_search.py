"""Web search with Tavily (primary) and DuckDuckGo (fallback).

Usage:
    # Auto-select engine (Tavily if TAVILY_API_KEY is set, else DuckDuckGo):
    results = search_batch(["query1", "query2"])

    # Force a specific engine:
    results = search_tavily(["query1"], max_results=5)
    results = search_duckduckgo(["query1"], max_results=5)

    # Test individual engines from CLI:
    python3 -m src.researcher.web_search --engine tavily "Descartes Discourse on Method"
    python3 -m src.researcher.web_search --engine duckduckgo "Descartes biography"
    python3 -m src.researcher.web_search "auto select query"
"""

import os
import time


def search_tavily(queries: list[str], max_results: int = 5) -> list[dict]:
    """Search via Tavily API. Requires TAVILY_API_KEY environment variable.

    Returns list of dicts with: query, title, url, body.
    Raises RuntimeError if TAVILY_API_KEY is not set or tavily-python not installed.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY environment variable is not set")

    try:
        from tavily import TavilyClient
    except ImportError:
        raise RuntimeError("tavily-python is not installed. Run: pip install tavily-python")

    client = TavilyClient(api_key=api_key)
    all_results = []

    for i, query in enumerate(queries):
        try:
            response = client.search(query=query, max_results=max_results)
            for r in response.get("results", []):
                all_results.append({
                    "query": query,
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "body": r.get("content", ""),
                })
        except Exception as e:
            print(f"      [tavily] Query failed: '{query}': {e}")

        if i < len(queries) - 1:
            time.sleep(0.5)

    return all_results


def search_duckduckgo(queries: list[str], max_results: int = 5) -> list[dict]:
    """Search via DuckDuckGo (no API key needed).

    Returns list of dicts with: query, title, url, body.
    Raises RuntimeError if ddgs package is not installed.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise RuntimeError(
                "Neither ddgs nor duckduckgo-search is installed. "
                "Run: pip install ddgs"
            )

    all_results = []
    for i, query in enumerate(queries):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            for r in results:
                all_results.append({
                    "query": query,
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "body": r.get("body", ""),
                })
        except Exception as e:
            print(f"      [duckduckgo] Query failed: '{query}': {e}")

        if i < len(queries) - 1:
            time.sleep(1.5)

    return all_results


def get_available_engine() -> str | None:
    """Return the best available search engine name, or None."""
    if os.environ.get("TAVILY_API_KEY"):
        try:
            import tavily  # noqa: F401
            return "tavily"
        except ImportError:
            pass
    # Try ddgs
    try:
        import ddgs  # noqa: F401
        return "duckduckgo"
    except ImportError:
        try:
            import duckduckgo_search  # noqa: F401
            return "duckduckgo"
        except ImportError:
            pass
    return None


def search_batch(queries: list[str], max_results: int = 5) -> list[dict]:
    """Run multiple search queries, auto-selecting the best available engine.

    Priority: Tavily (if TAVILY_API_KEY set) > DuckDuckGo > empty results.
    Each result dict has: query, title, url, body.
    Failures are non-fatal — returns empty list if no engine is available.
    """
    engine = get_available_engine()

    if engine == "tavily":
        print("      [web_search] Using Tavily search engine")
        try:
            return search_tavily(queries, max_results)
        except RuntimeError as e:
            print(f"      [web_search] Tavily failed ({e}), trying DuckDuckGo fallback...")
            try:
                return search_duckduckgo(queries, max_results)
            except RuntimeError as e2:
                print(f"      [web_search] DuckDuckGo also unavailable: {e2}")
                return []

    elif engine == "duckduckgo":
        print("      [web_search] Using DuckDuckGo search engine (set TAVILY_API_KEY for Tavily)")
        try:
            return search_duckduckgo(queries, max_results)
        except RuntimeError as e:
            print(f"      [web_search] DuckDuckGo failed: {e}")
            return []

    else:
        print("      [web_search] No search engine available. Install tavily-python or ddgs.")
        return []


def format_search_results(results: list[dict]) -> str:
    """Format search results into a readable text block for LLM consumption."""
    if not results:
        return "(No web search results available)"

    lines = []
    for r in results:
        lines.append(f"**{r['title']}**")
        lines.append(f"Source: {r['url']}")
        lines.append(r["body"])
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test web search engines")
    parser.add_argument("query", nargs="+", help="Search query (multiple words joined)")
    parser.add_argument(
        "--engine",
        choices=["tavily", "duckduckgo", "auto"],
        default="auto",
        help="Search engine to use (default: auto)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=3,
        help="Max results per query (default: 3)",
    )
    args = parser.parse_args()

    query_str = " ".join(args.query)
    queries = [query_str]

    print(f"Query: {query_str}")
    print(f"Engine: {args.engine}")
    print(f"Max results: {args.max_results}")
    print()

    if args.engine == "tavily":
        results = search_tavily(queries, args.max_results)
    elif args.engine == "duckduckgo":
        results = search_duckduckgo(queries, args.max_results)
    else:
        results = search_batch(queries, args.max_results)

    if not results:
        print("No results found.")
    else:
        print(f"Found {len(results)} result(s):\n")
        for i, r in enumerate(results, 1):
            print(f"  [{i}] {r['title']}")
            print(f"      {r['url']}")
            print(f"      {r['body'][:200]}")
            print()

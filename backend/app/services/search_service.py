"""
Search Service — abstraction over Tavily web search.

The synchronous TavilyClient is wrapped in asyncio.to_thread()
to avoid blocking the FastAPI event loop.
"""

import asyncio
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ConfigurationError, ExternalServiceError

logger = get_logger(__name__)

# Tavily client is lazily created
_tavily_client = None


def _get_tavily_client():
    """Get or create the Tavily client. Validates API key."""
    global _tavily_client
    if _tavily_client is None:
        if not settings.TAVILY_API_KEY:
            raise ConfigurationError(
                "TAVILY_API_KEY is not configured. Set it in your .env file."
            )
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    return _tavily_client


async def search_web_schemes(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """
    Search the web for government schemes using Tavily.
    
    The Tavily client is synchronous, so we run it in a thread
    to avoid blocking the async event loop.
    
    Returns empty list on failure instead of crashing.
    """
    try:
        client = _get_tavily_client()

        # Run synchronous Tavily call in a thread to avoid blocking
        result = await asyncio.to_thread(
            client.search,
            query=query,
            search_depth="advanced",
            max_results=max_results,
        )

        # Keep url and title: source URLs must be preserved for provenance and
        # trust classification (Phase 7 BUG-009).
        web_schemes = [
            {
                "source": "Tavily Web",
                "title": res.get("title", ""),
                "url": res.get("url", ""),
                "content": res.get("content", ""),
            }
            for res in result.get("results", [])
        ]

        logger.info(f"Tavily search returned {len(web_schemes)} results.")
        return web_schemes

    except ConfigurationError:
        raise
    except Exception as e:
        # Raised (not swallowed) so the retrieval agent reports live_web as failed
        logger.warning(f"Tavily web search failed: {e}")
        raise ExternalServiceError("Tavily", "Web search failed.")

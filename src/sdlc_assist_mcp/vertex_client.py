"""Client for calling Vertex AI Agent Engine agents.

Used by MCP tools that need to invoke Gemini-based agents
(e.g., IT estimation, PRD generation) deployed on Vertex AI.
"""

import asyncio
import os
from typing import Any

try:
    import vertexai
    from vertexai import agent_engines
    _HAS_VERTEXAI = True
except ImportError:
    _HAS_VERTEXAI = False


# Cache initialized agents by resource name
_agent_cache: dict[str, Any] = {}
_initialized = False


def _ensure_vertexai() -> None:
    if not _HAS_VERTEXAI:
        raise RuntimeError(
            "vertexai SDK is not installed. "
            "Install it with: pip install google-cloud-aiplatform"
        )


def _ensure_initialized() -> None:
    """Initialize Vertex AI SDK once."""
    global _initialized
    _ensure_vertexai()
    if not _initialized:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "sdlc-assist")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        vertexai.init(project=project, location=location)
        _initialized = True


def _get_agent(resource_name: str) -> Any:
    """Get or create a cached AgentEngine instance."""
    _ensure_initialized()
    if resource_name not in _agent_cache:
        _agent_cache[resource_name] = agent_engines.AgentEngine(resource_name)
    return _agent_cache[resource_name]


async def run_agent(resource_name: str, message: str) -> str:
    """Send a message to a Vertex AI agent and return the response text.

    The Vertex AI SDK is synchronous, so this wraps the call in
    asyncio.to_thread() to avoid blocking the MCP server's event loop.

    Args:
        resource_name: Full Vertex AI resource name, e.g.
            "projects/sdlc-assist/locations/us-central1/agents/abc123"
        message: The full context message to send to the agent.

    Returns:
        The agent's text response (typically JSON for estimation agent).

    Raises:
        Exception: If the Vertex AI call fails.
    """
    agent = _get_agent(resource_name)

    def _sync_call() -> str:
        session = agent.create_session()
        response = agent.send_message(
            session_id=session.session_id,
            message=message,
        )
        # Handle different response shapes from the SDK
        if hasattr(response, "text"):
            return response.text
        if isinstance(response, dict) and "text" in response:
            return response["text"]
        return str(response)

    return await asyncio.to_thread(_sync_call)

"""Client for calling Vertex AI Agent Engine agents via REST API.

Uses the same pattern as the Java backend: async_create_session → streamQuery → parse.
Avoids SDK wrapper issues by calling the REST API directly with httpx.
"""

import json
import os
import uuid

import google.auth
import google.auth.transport.requests
import httpx


_credentials = None


def _get_access_token() -> str:
    """Get a fresh access token using application default credentials."""
    global _credentials
    if _credentials is None:
        _credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


async def run_agent(resource_name: str, message: str) -> str:
    """Send a message to a Vertex AI agent and return the response text.

    Uses the REST API directly: async_create_session → streamQuery → parse.

    Args:
        resource_name: The reasoning engine resource ID (numeric) or full resource path.
        message: The full context message to send to the agent.

    Returns:
        The agent's text response.
    """
    # Support both full resource path and bare resource ID
    # Use VERTEXAI_PROJECT_ID (project name like "sdlc-assist") for the API path,
    # NOT GOOGLE_CLOUD_PROJECT which may be the numeric ID and cause 404s.
    vertexai_project = os.environ.get("VERTEXAI_PROJECT_ID", "sdlc-assist")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", os.environ.get("VERTEXAI_LOCATION", "us-central1"))

    if "/" in resource_name:
        engine_path = resource_name
    else:
        engine_path = f"projects/{vertexai_project}/locations/{location}/reasoningEngines/{resource_name}"

    token = _get_access_token()
    user_id = str(uuid.uuid4())
    api_host = f"https://{location}-aiplatform.googleapis.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        # 1. Create session — try v1 first (most agents), fall back to v1beta1
        session_resp = None
        for api_version in ("v1", "v1beta1"):
            session_url = f"{api_host}/{api_version}/{engine_path}:async_create_session"
            session_resp = await client.post(
                session_url, headers=headers, json={"user_id": user_id},
            )
            if session_resp.status_code == 200:
                break
            if session_resp.status_code != 404:
                raise RuntimeError(
                    f"async_create_session failed ({session_resp.status_code}): {session_resp.text}"
                )

        if session_resp is None or session_resp.status_code != 200:
            raise RuntimeError(
                f"async_create_session failed on both v1 and v1beta1 ({session_resp.status_code}): {session_resp.text}"
            )

        working_version = "v1" if "v1/" in str(session_resp.url) else "v1beta1"
        session_data = session_resp.json()
        session_id = session_data.get("id") or session_data.get("session_id") or session_data.get("name", "")

        # 2. Stream query — use same API version that worked for session creation
        query_url = f"{api_host}/{working_version}/{engine_path}:streamQuery"
        query_resp = await client.post(
            query_url,
            headers=headers,
            json={
                "user_id": user_id,
                "session_id": session_id,
                "message": message,
            },
        )

        if query_resp.status_code != 200:
            raise RuntimeError(
                f"streamQuery failed ({query_resp.status_code}): {query_resp.text}"
            )

        # 3. Parse chunked response — collect all text from the streamed JSON chunks
        return _parse_stream_response(query_resp.text)


def _parse_stream_response(raw: str) -> str:
    """Parse the streamQuery response, extracting agent text from JSON chunks.

    The response may be a JSON array of chunks or a single JSON object.
    Each chunk may contain content.parts[].text or just text fields.
    """
    text_parts = []

    # Try parsing as a JSON array first (common for streaming responses)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            for chunk in data:
                _extract_text(chunk, text_parts)
        elif isinstance(data, dict):
            _extract_text(data, text_parts)
        else:
            return str(data)
    except json.JSONDecodeError:
        # If not valid JSON, return raw text
        return raw.strip()

    return "".join(text_parts) if text_parts else raw.strip()


def _extract_text(chunk: dict, parts: list[str]) -> None:
    """Extract text content from a streamQuery response chunk."""
    # Pattern: {"content": {"parts": [{"text": "..."}]}}
    content = chunk.get("content", {})
    if isinstance(content, dict):
        for part in content.get("parts", []):
            if isinstance(part, dict) and "text" in part:
                parts.append(part["text"])

    # Pattern: {"text": "..."}
    if "text" in chunk and not parts:
        parts.append(chunk["text"])

    # Pattern: {"response": "..."} or {"output": "..."}
    for key in ("response", "output"):
        if key in chunk and not parts:
            val = chunk[key]
            parts.append(val if isinstance(val, str) else json.dumps(val))

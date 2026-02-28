"""Client for calling Vertex AI Gemini directly via REST API.

Calls the Vertex AI generateContent endpoint using service account credentials.
No Agent Engine dependency — just a direct Gemini call with a system prompt.
"""

import json
import os

import google.auth
import google.auth.transport.requests
import httpx


_credentials = None

GEMINI_MODEL = "gemini-2.0-flash"


def _get_access_token() -> str:
    """Get a fresh access token using application default credentials."""
    global _credentials
    if _credentials is None:
        _credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


async def call_gemini(system_prompt: str, user_message: str) -> str:
    """Call Vertex AI Gemini and return the text response.

    Uses the Vertex AI REST API with service account auth (no API key needed).

    Args:
        system_prompt: Instructions for the model.
        user_message: The user content (project context + request).

    Returns:
        The model's text response.
    """
    project = os.environ.get("VERTEXAI_PROJECT_ID", "sdlc-assist")
    location = os.environ.get(
        "GOOGLE_CLOUD_LOCATION",
        os.environ.get("VERTEXAI_LOCATION", "us-central1"),
    )

    endpoint = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/publishers/google/models/{GEMINI_MODEL}:generateContent"
    )

    token = _get_access_token()

    body = {
        "contents": [
            {"role": "user", "parts": [{"text": user_message}]},
        ],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        resp = await client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Gemini API failed ({resp.status_code}): {resp.text[:500]}"
            )

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [p["text"] for p in parts if "text" in p]
        return "".join(text_parts)

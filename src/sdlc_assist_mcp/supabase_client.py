"""Async Supabase REST API client for the SDLC Assist MCP server.

Uses httpx to call the Supabase PostgREST API directly.
This avoids pulling in the full supabase-py SDK and keeps
the dependency footprint minimal.
"""

import json
import os
from typing import Any, Optional

import httpx


class SupabaseClient:
    """Lightweight async client for Supabase PostgREST queries."""

    def __init__(self, url: str, service_role_key: str) -> None:
        self._base_url = url.rstrip("/")
        self._rest_url = f"{self._base_url}/rest/v1"
        self._headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    async def query(
        self,
        table: str,
        select: str = "*",
        filters: Optional[dict[str, str]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Execute a PostgREST SELECT query.

        Args:
            table: Table name (e.g. 'projects')
            select: Comma-separated column list or '*'
            filters: Dict of PostgREST filter params
                     e.g. {"status": "eq.ACTIVE", "id": "eq.abc-123"}
            order: Order clause e.g. "created_at.desc"
            limit: Max rows to return

        Returns:
            List of row dicts from the API response.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx status.
        """
        params: dict[str, str] = {"select": select}

        if filters:
            for col, value in filters.items():
                params[col] = value

        if order:
            params["order"] = order

        if limit is not None:
            params["limit"] = str(limit)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._rest_url}/{table}",
                headers=self._headers,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def query_single(
        self,
        table: str,
        select: str = "*",
        filters: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        """Query expecting exactly one row. Returns None if not found."""
        rows = await self.query(table, select=select, filters=filters, limit=1)
        return rows[0] if rows else None


def create_client_from_env() -> SupabaseClient:
    """Create a SupabaseClient from environment variables.

    Expects:
        SUPABASE_URL - The project URL (e.g. https://xyz.supabase.co)
        SUPABASE_SERVICE_ROLE_KEY - The service role key (bypasses RLS)
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url:
        raise ValueError(
            "SUPABASE_URL environment variable is required. "
            "Set it to your Supabase project URL "
            "(e.g. https://your-project.supabase.co)"
        )
    if not key:
        raise ValueError(
            "SUPABASE_SERVICE_ROLE_KEY environment variable is required. "
            "Find it in Supabase Dashboard > Settings > API > service_role key."
        )

    return SupabaseClient(url=url, service_role_key=key)

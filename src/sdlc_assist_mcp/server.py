#!/usr/bin/env python3
"""SDLC Assist MCP Server.

Exposes read-only tools for querying SDLC project artifacts
stored in Supabase. Designed to be used with Claude Desktop,
Claude Code, or any MCP-compatible client.

Tools:
  - sdlc_list_projects: List all projects with completion status
  - sdlc_get_project_summary: Detailed overview of a single project
  - sdlc_get_artifact: Fetch any artifact (PRD, data model, etc.)
  - sdlc_get_screens: List UI screens for a project
  - sdlc_get_tech_preferences: Fetch tech stack choices
"""

import argparse
import json
import os
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from sdlc_assist_mcp.models.inputs import (
    ARTIFACT_COLUMN_MAP,
    ArtifactType,
    GetArtifactInput,
    GetProjectSummaryInput,
    GetScreensInput,
    GetTechPreferencesInput,
    ListProjectsInput,
)
from sdlc_assist_mcp.supabase_client import SupabaseClient, create_client_from_env

# ---------------------------------------------------------------------------
# Load .env (for local development)
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Initialize MCP server
# host 0.0.0.0 is required for Cloud Run; ignored when using stdio
# PORT env var is set by Cloud Run; defaults to 8080
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "sdlc_assist_mcp",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8080)),
)

# ---------------------------------------------------------------------------
# Supabase client (created lazily on first tool call)
# ---------------------------------------------------------------------------
_db: SupabaseClient | None = None


def _get_db() -> SupabaseClient:
    global _db
    if _db is None:
        _db = create_client_from_env()
    return _db


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _handle_error(e: Exception) -> str:
    if hasattr(e, "response"):
        status = getattr(e.response, "status_code", "unknown")
        if status == 404:
            return "Error: Resource not found. Check that the project_id is correct."
        if status == 401:
            return "Error: Authentication failed. Check your SUPABASE_SERVICE_ROLE_KEY."
        return f"Error: Supabase API returned status {status}."
    return f"Error: {type(e).__name__}: {e}"


ARTIFACT_LABELS: dict[str, str] = {
    "prd_content": "PRD",
    "design_system_content": "Design System",
    "arch_overview_content": "Architecture Overview",
    "data_model_content": "Data Model",
    "api_contract_content": "API Contract",
    "sequence_diagrams_content": "Sequence Diagrams",
    "implementation_plan_content": "Implementation Plan",
    "claude_md_content": "CLAUDE.md",
    "corporate_guidelines_content": "Corporate Guidelines",
}


# ===========================================================================
# Tool 1: List Projects
# ===========================================================================
@mcp.tool(
    name="sdlc_list_projects",
    annotations={
        "title": "List SDLC Projects",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sdlc_list_projects(params: ListProjectsInput) -> str:
    """List all SDLC Assist projects with their status and artifact completion.

    Returns a summary of every project including which artifacts have been
    generated (PRD, Architecture, Data Model, etc.) and how many UI screens
    exist. Use this to discover project IDs for other tools.

    Args:
        params (ListProjectsInput): Optional filters:
            - status_filter (Optional[str]): Filter by status
              ('DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED')

    Returns:
        str: Markdown-formatted list of projects with completion info.
    """
    try:
        db = _get_db()

        select = (
            "id,name,status,created_at,updated_at,"
            "prd_content,design_system_content,arch_overview_content,"
            "data_model_content,api_contract_content,"
            "sequence_diagrams_content,implementation_plan_content,"
            "claude_md_content"
        )

        filters = {}
        if params.status_filter:
            filters["status"] = f"eq.{params.status_filter}"

        rows = await db.query(
            "projects",
            select=select,
            filters=filters,
            order="created_at.desc",
        )

        if not rows:
            return "No projects found."

        lines = [f"# SDLC Assist Projects ({len(rows)} total)", ""]

        for proj in rows:
            artifact_cols = [
                "prd_content",
                "design_system_content",
                "arch_overview_content",
                "data_model_content",
                "api_contract_content",
                "sequence_diagrams_content",
                "implementation_plan_content",
                "claude_md_content",
            ]
            completed = sum(
                1 for col in artifact_cols if proj.get(col) is not None
            )
            total = len(artifact_cols)

            lines.append(f"## {proj['name']}")
            lines.append(f"- **ID:** `{proj['id']}`")
            lines.append(f"- **Status:** {proj['status']}")
            lines.append(f"- **Artifacts:** {completed}/{total} complete")
            lines.append(f"- **Created:** {proj['created_at']}")
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


# ===========================================================================
# Tool 2: Get Project Summary
# ===========================================================================
@mcp.tool(
    name="sdlc_get_project_summary",
    annotations={
        "title": "Get SDLC Project Summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sdlc_get_project_summary(params: GetProjectSummaryInput) -> str:
    """Get a detailed summary of a single SDLC project.

    Returns the project name, status, tech stack preferences, which
    artifacts have been generated (and when), and the number of UI screens.
    Does NOT return artifact content — use sdlc_get_artifact for that.

    Args:
        params (GetProjectSummaryInput): Contains:
            - project_id (str): UUID of the project

    Returns:
        str: Markdown-formatted project summary with artifact status.
    """
    try:
        db = _get_db()

        proj = await db.query_single(
            "projects",
            filters={"id": f"eq.{params.project_id}"},
        )

        if not proj:
            return (
                f"Error: No project found with ID `{params.project_id}`. "
                "Use sdlc_list_projects to see available project IDs."
            )

        screens = await db.query(
            "project_screens",
            select="id",
            filters={"project_id": f"eq.{params.project_id}"},
        )

        files = await db.query(
            "project_files",
            select="id,original_filename",
            filters={"project_id": f"eq.{params.project_id}"},
        )

        lines = [f"# Project: {proj['name']}", ""]
        lines.append(f"- **ID:** `{proj['id']}`")
        lines.append(f"- **Status:** {proj['status']}")
        lines.append(f"- **Created:** {proj['created_at']}")
        lines.append(f"- **Updated:** {proj['updated_at']}")
        lines.append("")

        if proj.get("tech_preferences"):
            tp = proj["tech_preferences"]
            if isinstance(tp, str):
                tp = json.loads(tp)
            lines.append("## Tech Stack Preferences")
            for key, value in tp.items():
                lines.append(f"- **{key}:** {value}")
            lines.append("")

        lines.append("## Artifact Status")
        lines.append("")
        lines.append("| Artifact | Status | Generated At |")
        lines.append("|----------|--------|-------------|")

        artifact_checks = [
            ("PRD", "prd_content", None),
            ("Design System", "design_system_content", "design_system_updated_at"),
            ("Architecture", "arch_overview_content", "arch_overview_generated_at"),
            ("Data Model", "data_model_content", "data_model_generated_at"),
            ("API Contract", "api_contract_content", "api_contract_generated_at"),
            ("Sequence Diagrams", "sequence_diagrams_content", "sequence_diagrams_generated_at"),
            ("Implementation Plan", "implementation_plan_content", "implementation_plan_generated_at"),
            ("CLAUDE.md", "claude_md_content", None),
            ("Corporate Guidelines", "corporate_guidelines_content", None),
        ]

        for label, col, ts_col in artifact_checks:
            has_it = proj.get(col) is not None
            status_icon = "✅" if has_it else "❌"
            generated = proj.get(ts_col, "—") if ts_col else "—"
            if generated is None:
                generated = "—"
            lines.append(f"| {label} | {status_icon} | {generated} |")

        lines.append("")
        lines.append(f"## UI Screens: {len(screens)} defined")
        lines.append(f"## Uploaded Files: {len(files)}")

        if files:
            for f in files:
                lines.append(f"- {f.get('original_filename', 'unnamed')}")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


# ===========================================================================
# Tool 3: Get Artifact
# ===========================================================================
@mcp.tool(
    name="sdlc_get_artifact",
    annotations={
        "title": "Get SDLC Project Artifact",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sdlc_get_artifact(params: GetArtifactInput) -> str:
    """Fetch the full content of a specific artifact from a project.

    Retrieves artifacts like the PRD, Architecture Overview, Data Model,
    API Contract, Sequence Diagrams, Implementation Plan, CLAUDE.md,
    or Corporate Guidelines.

    Args:
        params (GetArtifactInput): Contains:
            - project_id (str): UUID of the project
            - artifact_type (ArtifactType): Which artifact to fetch.
              One of: 'prd', 'design_system', 'architecture', 'data_model',
              'api_contract', 'sequence_diagrams', 'implementation_plan',
              'claude_md', 'corporate_guidelines'

    Returns:
        str: The full artifact content (Markdown or JSON depending on type),
             or an error message if the artifact hasn't been generated yet.
    """
    try:
        db = _get_db()

        column = ARTIFACT_COLUMN_MAP[params.artifact_type]
        label = ARTIFACT_LABELS.get(column, params.artifact_type.value)

        proj = await db.query_single(
            "projects",
            select=f"id,name,{column}",
            filters={"id": f"eq.{params.project_id}"},
        )

        if not proj:
            return (
                f"Error: No project found with ID `{params.project_id}`. "
                "Use sdlc_list_projects to see available project IDs."
            )

        content = proj.get(column)

        if content is None:
            return (
                f"The **{label}** artifact has not been generated yet "
                f"for project **{proj['name']}**. "
                "The user needs to generate this artifact in the "
                "SDLC Assist application first."
            )

        if params.artifact_type in (
            ArtifactType.DESIGN_SYSTEM,
            ArtifactType.IMPLEMENTATION_PLAN,
        ):
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
                return (
                    f"# {label} — {proj['name']}\n\n"
                    f"```json\n{json.dumps(parsed, indent=2)}\n```"
                )
            except (json.JSONDecodeError, TypeError):
                pass

        return f"# {label} — {proj['name']}\n\n{content}"

    except Exception as e:
        return _handle_error(e)


# ===========================================================================
# Tool 4: Get Screens
# ===========================================================================
@mcp.tool(
    name="sdlc_get_screens",
    annotations={
        "title": "Get SDLC Project Screens",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sdlc_get_screens(params: GetScreensInput) -> str:
    """List all UI screens defined for a project with their metadata.

    Returns screen names, types, complexity, epic assignments, and
    design notes. Optionally includes the full HTML prototype content.

    Args:
        params (GetScreensInput): Contains:
            - project_id (str): UUID of the project
            - include_prototypes (bool): If true, include HTML content
              (default false — prototypes can be very large)

    Returns:
        str: Markdown-formatted screen inventory grouped by epic.
    """
    try:
        db = _get_db()

        proj = await db.query_single(
            "projects",
            select="id,name",
            filters={"id": f"eq.{params.project_id}"},
        )

        if not proj:
            return (
                f"Error: No project found with ID `{params.project_id}`. "
                "Use sdlc_list_projects to see available project IDs."
            )

        select_cols = (
            "id,name,description,screen_type,epic_name,"
            "complexity,user_role,notes,display_order,"
            "prototype_generated_at"
        )
        if params.include_prototypes:
            select_cols += ",prototype_content"

        screens = await db.query(
            "project_screens",
            select=select_cols,
            filters={"project_id": f"eq.{params.project_id}"},
            order="display_order.asc.nullsfirst",
        )

        if not screens:
            return (
                f"No screens defined for project **{proj['name']}**. "
                "Screens are generated during the UX Design phase."
            )

        epics: dict[str, list[dict]] = {}
        for screen in screens:
            epic = screen.get("epic_name") or "Ungrouped"
            epics.setdefault(epic, []).append(screen)

        lines = [
            f"# UI Screens — {proj['name']} ({len(screens)} screens)",
            "",
        ]

        for epic_name, epic_screens in epics.items():
            lines.append(f"## {epic_name}")
            lines.append("")

            for s in epic_screens:
                has_proto = s.get("prototype_generated_at") is not None
                proto_icon = "🎨" if has_proto else "⬜"
                lines.append(
                    f"### {proto_icon} {s['name']} "
                    f"({s.get('screen_type', '—')} · "
                    f"{s.get('complexity', '—')} complexity)"
                )
                lines.append(f"- **Description:** {s.get('description', '—')}")
                lines.append(f"- **User Role:** {s.get('user_role', '—')}")

                if s.get("notes"):
                    lines.append(f"- **Design Notes:** {s['notes']}")

                if params.include_prototypes and s.get("prototype_content"):
                    lines.append("")
                    lines.append("<details><summary>HTML Prototype</summary>")
                    lines.append("")
                    lines.append(f"```html\n{s['prototype_content']}\n```")
                    lines.append("</details>")

                lines.append("")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


# ===========================================================================
# Tool 5: Get Tech Preferences
# ===========================================================================
@mcp.tool(
    name="sdlc_get_tech_preferences",
    annotations={
        "title": "Get SDLC Tech Stack Preferences",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def sdlc_get_tech_preferences(params: GetTechPreferencesInput) -> str:
    """Fetch the technology stack preferences for a project.

    Returns the user's selected frontend, backend, database, deployment
    target, authentication method, and API style choices.

    Args:
        params (GetTechPreferencesInput): Contains:
            - project_id (str): UUID of the project

    Returns:
        str: Markdown-formatted tech stack summary, or a message
             indicating preferences haven't been set yet.
    """
    try:
        db = _get_db()

        proj = await db.query_single(
            "projects",
            select="id,name,tech_preferences,tech_preferences_saved_at",
            filters={"id": f"eq.{params.project_id}"},
        )

        if not proj:
            return (
                f"Error: No project found with ID `{params.project_id}`. "
                "Use sdlc_list_projects to see available project IDs."
            )

        tp = proj.get("tech_preferences")
        if tp is None:
            return (
                f"Tech preferences have not been set for project "
                f"**{proj['name']}**. The user needs to select their "
                "tech stack in the SDLC Assist application."
            )

        if isinstance(tp, str):
            tp = json.loads(tp)

        lines = [f"# Tech Stack — {proj['name']}", ""]

        if proj.get("tech_preferences_saved_at"):
            lines.append(f"*Saved at: {proj['tech_preferences_saved_at']}*")
            lines.append("")

        for key, value in tp.items():
            display_key = key.replace("_", " ").replace("-", " ").title()
            lines.append(f"- **{display_key}:** {value}")

        return "\n".join(lines)

    except Exception as e:
        return _handle_error(e)


# ===========================================================================
# Entry point
# ===========================================================================
def main() -> None:
    """Run the MCP server.

    Supports two transports:
      --transport stdio             (default, for Claude Desktop / Claude Code)
      --transport streamable-http   (for Cloud Run / remote deployment)
    """
    parser = argparse.ArgumentParser(description="SDLC Assist MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport to use (default: stdio)",
    )
    args = parser.parse_args()

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()

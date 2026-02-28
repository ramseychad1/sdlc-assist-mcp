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
  - sdlc_generate_estimation: Generate Traditional vs AI-Assisted cost estimates
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
    GenerateEstimationInput,
)
from sdlc_assist_mcp.supabase_client import SupabaseClient, create_client_from_env
from sdlc_assist_mcp.vertex_client import call_gemini

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
# Tool 6: Generate IT Estimation
# ===========================================================================
@mcp.tool(
    name="sdlc_generate_estimation",
    annotations={
        "title": "Generate IT Cost Estimation",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
#async def sdlc_generate_estimation(project_id: str) -> str:
async def sdlc_generate_estimation(params: GenerateEstimationInput) -> str:
    """Generate Traditional vs AI-Assisted cost estimates for a project.

    Produces two side-by-side estimates showing hours and costs for each
    SDLC phase (Requirements, Design, Develop, Test, Deploy, Data Cleansing,
    Transition to Run, Project Management), then highlights the savings
    from using SDLC-Assist + agentic development.

    Requires all upstream artifacts to be generated first (PRD, architecture,
    data model, API contract, screens, implementation plan).

    Args:
        project_id: The project UUID.

    Returns:
        str: JSON with traditionalEstimate, aiAssistedEstimate, savings,
             and assumptions.
    """
    try:
        db = _get_db()

        # -- 1. Fetch project --
        proj = await db.query_single(
            "projects",
            filters={"id": f"eq.{params.project_id}"},
        )
        if not proj:
            return json.dumps({"error": f"No project found with ID {params.project_id}"})

        # -- 2. Check required artifacts exist --
        required_artifacts = [
            ("prd_content", "PRD"),
            ("arch_overview_content", "Architecture Overview"),
            ("data_model_content", "Data Model"),
            ("api_contract_content", "API Contract"),
            ("implementation_plan_content", "Implementation Plan"),
        ]
        missing = [
            label
            for col, label in required_artifacts
            if proj.get(col) is None
        ]
        if missing:
            return json.dumps({
                "error": "Missing required artifacts. Generate these first: "   
                + ", ".join(missing)
            })

        # -- 3. Fetch screens --
        screens = await db.query(
            "project_screens",
            select="id,name,description,screen_type,epic_name,complexity,user_role,notes",
            filters={"project_id": f"eq.{params.project_id}"},
            order="display_order.asc.nullsfirst",
        )

        # -- 4. Build context message for the estimation agent --
        context_parts = []

        context_parts.append(
            f"## PROJECT NAME\n{proj.get('name', 'Unknown Project')}"
        )

        if proj.get("tech_preferences"):
            tp = proj["tech_preferences"]
            if isinstance(tp, str):
                tp = json.loads(tp)
            context_parts.append(
                f"## TECHNOLOGY STACK\n{json.dumps(tp, indent=2)}"
            )

        context_parts.append(
            f"## PRODUCT REQUIREMENTS DOCUMENT\n{proj['prd_content']}"
        )

        if screens:
            context_parts.append(
                f"## CONFIRMED UI SCREENS\n{json.dumps(screens, indent=2)}"
            )

        context_parts.append(
            f"## ARCHITECTURE OVERVIEW\n{proj['arch_overview_content']}"
        )

        context_parts.append(
            f"## DATA MODEL\n{proj['data_model_content']}"
        )

        context_parts.append(
            f"## API CONTRACT\n{proj['api_contract_content']}"
        )

        if proj.get("sequence_diagrams_content"):
            context_parts.append(
                f"## SEQUENCE DIAGRAMS\n{proj['sequence_diagrams_content']}"
            )

        context_parts.append(
            f"## IMPLEMENTATION PLAN\n{proj['implementation_plan_content']}"
        )

        context_message = "\n\n---\n\n".join(context_parts)

        # -- 5. Call Gemini directly for estimation --
        system_prompt = (
            "CRITICAL: Return ONLY a valid JSON object. No preamble, no explanation, no Markdown, no code fences.\n"
            "The very first character of your response must be { and the very last must be }.\n\n"

            "You are a senior IT estimation specialist. You produce cost estimates for enterprise software projects.\n"
            "FIXED RATE: $80/hour for ALL tasks. Never use any other rate.\n\n"

            "## NON-NEGOTIABLE RULES\n"
            "RULE 1: AI-Assisted Requirements hours = 0. Always. No exceptions.\n"
            "RULE 2: AI-Assisted Design hours = 0. Always. No exceptions.\n"
            "RULE 3: Rate = 80. Always. Cost = hours * 80. Always.\n"
            "RULE 4: Every breakdown field must show the multiplication math, not just a total.\n"
            "RULE 5: Do not round to convenient numbers. Use the formula outputs exactly.\n\n"

            "## STEP 1: COUNT COMPLEXITY DRIVERS\n"
            "Count these from the artifacts. Be precise.\n"
            "- epicCount: Count Epics in the PRD\n"
            "- storyCount: Count Stories in the PRD\n"
            "- taskCount: Count Tasks in the PRD\n"
            "- screenCount: Total confirmed UI screens\n"
            "- complexScreens: screens with complexity = high\n"
            "- mediumScreens: screens with complexity = medium\n"
            "- simpleScreens: screens with complexity = low\n"
            "- entityCount: Count entity definition tables in the Data Model\n"
            "- endpointCount: Count API endpoints in the API Contract\n"
            "- integrationCount: Count distinct external system integrations\n"
            "- userRoleCount: Count distinct user roles\n\n"

            "## STEP 2: TRADITIONAL ESTIMATE FORMULAS\n\n"

            "Task 1 Requirements: (epicCount * 16) + (storyCount * 4) + (integrationCount * 8) + 40\n"
            "Example: 4 epics * 16h + 13 stories * 4h + 4 integrations * 8h + 40h = 64 + 52 + 32 + 40 = 188h\n\n"

            "Task 2 Design: (complexScreens * 16) + (mediumScreens * 8) + (simpleScreens * 4) + (epicCount * 24) + (entityCount * 8) + (integrationCount * 16) + 40\n"
            "Example: 3*16 + 4*8 + 2*4 + 4*24 + 5*8 + 4*16 + 40 = 48+32+8+96+40+64+40 = 328h\n\n"

            "Task 3 Develop: (complexScreens * 16) + (mediumScreens * 8) + (simpleScreens * 4) + (entityCount * 16) + (endpointCount * 8) + (integrationCount * 40) + (userRoleCount * 24) + 40\n"
            "Example: 3*16 + 4*8 + 2*4 + 5*16 + 15*8 + 4*40 + 2*24 + 40 = 48+32+8+80+120+160+48+40 = 536h\n\n"

            "Task 4 Test: (developHours * 0.30) + (developHours * 0.20) + (screenCount * 8) + (integrationCount * 16) + 24\n"
            "Example: 536*0.30 + 536*0.20 + 9*8 + 4*16 + 24 = 161+107+72+64+24 = 428h\n\n"

            "Task 5 Deploy: 40 + 24 + 16 + 24 + 16 + 16 = 136h (always fixed)\n\n"

            "Task 6 Data Cleansing: If PRD mentions data migration: (entityCount * 16) + (dataSourceCount * 24) + 40. Otherwise: 0h\n\n"

            "Task 7 Transition: (epicCount * 8) + 16 + 24 + 16\n"
            "Example: 4*8 + 16 + 24 + 16 = 32+16+24+16 = 88h\n\n"

            "Task 8 PM: sum(tasks 1-7) * 0.15\n\n"

            "## STEP 3: AI-ASSISTED ESTIMATE FORMULAS\n\n"

            "Task 1 Requirements: 0 hours (automated by SDLC-Assist)\n"
            "Task 2 Design: 0 hours (automated by SDLC-Assist)\n\n"

            "Task 3 AI Develop: (complexScreens * 4) + (mediumScreens * 2) + (simpleScreens * 1) + (entityCount * 4) + (endpointCount * 2) + (integrationCount * 16) + (userRoleCount * 8) + 8\n"
            "Example: 3*4 + 4*2 + 2*1 + 5*4 + 15*2 + 4*16 + 2*8 + 8 = 12+8+2+20+30+64+16+8 = 160h\n\n"

            "Task 4 AI Test: (aiDevelopHours * 0.30) + (screenCount * 4) + (integrationCount * 8) + 8\n"
            "Example: 160*0.30 + 9*4 + 4*8 + 8 = 48+36+32+8 = 124h\n\n"

            "Task 5 AI Deploy: traditionalDeployHours * 0.60\n"
            "Example: 136 * 0.60 = 82h\n\n"

            "Task 6 AI Data Cleansing: same as Traditional\n\n"

            "Task 7 AI Transition: traditionalTransitionHours * 0.50\n"
            "Example: 88 * 0.50 = 44h\n\n"

            "Task 8 AI PM: sum(AI tasks 1-7) * 0.05\n\n"

            "## STEP 4: SAVINGS\n"
            "hoursSaved = traditionalTotal - aiTotal\n"
            "costSaved = hoursSaved * 80\n"
            "percentReduction = round((hoursSaved / traditionalTotal) * 100)\n\n"

            "## STEP 5: JUDGMENT ADJUSTMENTS (after formulas)\n"
            "- Regulated domain (healthcare, finance): +10-15% to Traditional Requirements and Test\n"
            "- More than 3 integrations: +10% to Traditional Develop and Test\n"
            "- 20+ screens: +10% to Traditional Design and Develop\n"
            "- Simple CRUD: -10% Traditional Design and Develop\n"
            "Document adjustments in assumptions.\n\n"

            "## JSON SCHEMA\n"
            "{\n"
            '  "projectName": "string",\n'
            '  "generatedAt": "ISO-8601 datetime",\n'
            '  "rate": 80,\n'
            '  "complexityDrivers": {\n'
            '    "epicCount": 0, "storyCount": 0, "taskCount": 0,\n'
            '    "screenCount": 0, "simpleScreens": 0, "mediumScreens": 0, "complexScreens": 0,\n'
            '    "entityCount": 0, "endpointCount": 0, "integrationCount": 0, "userRoleCount": 0\n'
            "  },\n"
            '  "traditionalEstimate": {\n'
            '    "label": "Traditional SDLC",\n'
            '    "description": "Estimated cost using traditional software development without AI assistance.",\n'
            '    "tasks": [\n'
            '      {"id": 1, "name": "Requirements", "hours": 0, "cost": 0, "breakdown": "show math"},\n'
            '      {"id": 2, "name": "Design", "hours": 0, "cost": 0, "breakdown": "show math"},\n'
            '      {"id": 3, "name": "Develop", "hours": 0, "cost": 0, "breakdown": "show math"},\n'
            '      {"id": 4, "name": "Test", "hours": 0, "cost": 0, "breakdown": "show math"},\n'
            '      {"id": 5, "name": "Deploy", "hours": 0, "cost": 0, "breakdown": "40+24+16+24+16+16=136h"},\n'
            '      {"id": 6, "name": "Data Cleansing and Conversion", "hours": 0, "cost": 0, "breakdown": "string"},\n'
            '      {"id": 7, "name": "Transition to Run", "hours": 0, "cost": 0, "breakdown": "show math"},\n'
            '      {"id": 8, "name": "Project Management", "hours": 0, "cost": 0, "breakdown": "15% of tasks 1-7"}\n'
            "    ],\n"
            '    "totalHours": 0, "totalCost": 0\n'
            "  },\n"
            '  "aiAssistedEstimate": {\n'
            '    "label": "AI-Assisted SDLC (SDLC-Assist + Agentic Development)",\n'
            '    "description": "Estimated cost using SDLC-Assist for requirements/design plus agentic AI development.",\n'
            '    "tasks": [\n'
            '      {"id": 1, "name": "Requirements", "hours": 0, "cost": 0, "breakdown": "Automated by SDLC-Assist"},\n'
            '      {"id": 2, "name": "Design", "hours": 0, "cost": 0, "breakdown": "Automated by SDLC-Assist"},\n'
            '      {"id": 3, "name": "Develop", "hours": 0, "cost": 0, "breakdown": "show AI math"},\n'
            '      {"id": 4, "name": "Test", "hours": 0, "cost": 0, "breakdown": "show AI math"},\n'
            '      {"id": 5, "name": "Deploy", "hours": 0, "cost": 0, "breakdown": "60% of traditional"},\n'
            '      {"id": 6, "name": "Data Cleansing and Conversion", "hours": 0, "cost": 0, "breakdown": "string"},\n'
            '      {"id": 7, "name": "Transition to Run", "hours": 0, "cost": 0, "breakdown": "50% of traditional"},\n'
            '      {"id": 8, "name": "Project Management", "hours": 0, "cost": 0, "breakdown": "5% of AI tasks 1-7"}\n'
            "    ],\n"
            '    "totalHours": 0, "totalCost": 0\n'
            "  },\n"
            '  "savings": {\n'
            '    "hoursSaved": 0, "costSaved": 0, "percentReduction": 0,\n'
            '    "narrative": "3-5 sentences: name the project, call out Requirements and Design at zero hours, state savings % and $"\n'
            "  },\n"
            '  "assumptions": ["each assumption or adjustment"]\n'
            "}\n\n"

            "## VALIDATION BEFORE RESPONDING\n"
            "- Is rate exactly 80? (cost = hours * 80)\n"
            "- Are AI Requirements hours exactly 0?\n"
            "- Are AI Design hours exactly 0?\n"
            "- Does every breakdown show multiplication math?\n"
            "- Does totalHours = sum of all task hours?\n"
            "- Does totalCost = totalHours * 80?\n"
            "- Does percentReduction = round((hoursSaved / traditionalTotal) * 100)?\n"
        )

        result = await call_gemini(system_prompt, context_message)

        # -- 6. Validate JSON response --
        try:
            parsed = json.loads(result)
            return json.dumps(parsed)
        except json.JSONDecodeError:
            return json.dumps({
                "error": "Estimation agent returned invalid JSON",
                "raw_response": result[:2000],
            })

    except Exception as e:
        return json.dumps({
            "error": f"Failed to generate estimation: {type(e).__name__}: {e}"
        })


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

# SDLC Assist MCP Server

An MCP (Model Context Protocol) server that gives AI assistants read access to your SDLC Assist project artifacts stored in Supabase.

## What This Does

When connected to Claude Desktop or Claude Code, this server lets you have conversations about your SDLC projects:

- "What projects do I have?"
- "Show me the data model for the DEP Multi-Tenant project"
- "What API endpoints handle authentication?"
- "List all the screens for the HCP Portal"
- "What tech stack did we choose?"

The AI reads your project data directly from Supabase — PRDs, architecture docs, data models, API contracts, screen inventories, and more. It can also delegate to Vertex AI agents for tasks like IT cost estimation.

## How MCP Works (Quick Primer)

```
You (in Claude Desktop)
  │  "What does the data model look like for DEP Multi-Tenant?"
  │
  ▼
Claude (the AI)
  │  Thinks: "I need the data model artifact for that project"
  │  Calls: sdlc_get_artifact(project_id="dc744778...", artifact_type="data_model")
  │
  ▼
This MCP Server
  │  Queries Supabase for the data_model_content column
  │  Returns the full markdown document
  │
  ▼
Claude (the AI)
  │  Reads the data model, answers your question
  ▼
You see the answer
```

MCP is just a protocol — a standardized way for AI to call functions. This server exposes 6 tools (5 read-only + 1 agent-delegated) that the AI can call when it needs project data.

## Available Tools

### Read-Only Tools

| Tool | What it does |
|------|-------------|
| `sdlc_list_projects` | Lists all projects with completion status |
| `sdlc_get_project_summary` | Detailed overview of one project (artifacts, screens, files) |
| `sdlc_get_artifact` | Fetches any artifact: PRD, architecture, data model, API contract, sequence diagrams, implementation plan, CLAUDE.md, or corporate guidelines |
| `sdlc_get_screens` | Lists UI screens with metadata, optionally includes HTML prototypes |
| `sdlc_get_tech_preferences` | Returns the tech stack choices for a project |

### Agent-Delegated Tools

| Tool | What it does |
|------|-------------|
| `sdlc_generate_estimation` | Generates Traditional vs AI-Assisted IT cost estimates by delegating to a Vertex AI estimation agent. Requires all upstream artifacts (PRD, architecture, data model, API contract, implementation plan) to be generated first. |

## Architecture

```
┌─────────────────────────────────────┐
│         MCP Client (Claude)         │
└──────────────┬──────────────────────┘
               │ MCP Protocol
               ▼
┌─────────────────────────────────────┐
│       sdlc-assist-mcp Server        │
│  (FastMCP · streamable-http/stdio)  │
├──────────────┬──────────────────────┤
│  Read Tools  │  Agent-Delegated     │
│  (1-5)       │  Tools (6)           │
└──────┬───────┴──────────┬───────────┘
       │                  │
       ▼                  ▼
┌──────────────┐  ┌───────────────────┐
│   Supabase   │  │   Vertex AI       │
│  PostgREST   │  │   Agent Engine    │
│  (httpx)     │  │  (IT Estimation)  │
└──────────────┘  └───────────────────┘
```

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Supabase project with the SDLC Assist schema
- Claude Desktop or Claude Code
- (For estimation tool) Google Cloud project with Vertex AI agent deployed

## Setup

### 1. Clone and install

```bash
git clone https://github.com/ramseychad1/sdlc-assist-mcp.git
cd sdlc-assist-mcp

# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```
# Required — Supabase
SUPABASE_URL=https://mtzcookrjzewywyirhja.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-here

# Optional — Vertex AI (only needed for sdlc_generate_estimation)
GOOGLE_CLOUD_PROJECT=sdlc-assist
GOOGLE_CLOUD_LOCATION=us-central1
IT_ESTIMATION_AGENT_RESOURCE=projects/sdlc-assist/locations/us-central1/agents/your-agent-id
```

Find your Supabase service role key in: **Supabase Dashboard → Settings → API → service_role (secret)**

### 3. Test it works

```bash
# Quick syntax check
python -c "from sdlc_assist_mcp.server import mcp; print('Server loads OK')"
```

### 4. Connect to Claude Desktop

Edit your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Add this to the `mcpServers` section:

```json
{
  "mcpServers": {
    "sdlc-assist": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/ABSOLUTE/PATH/TO/sdlc-assist-mcp",
        "sdlc-assist-mcp"
      ]
    }
  }
}
```

Or if using pip instead of uv:

```json
{
  "mcpServers": {
    "sdlc-assist": {
      "command": "/ABSOLUTE/PATH/TO/sdlc-assist-mcp/.venv/bin/sdlc-assist-mcp"
    }
  }
}
```

Restart Claude Desktop. You should see the SDLC Assist tools in the tools menu.

### 5. Connect to Claude Code (Antigravity IDE)

```bash
claude mcp add sdlc-assist -- uv run --directory /ABSOLUTE/PATH/TO/sdlc-assist-mcp sdlc-assist-mcp
```

## Project Structure

```
sdlc-assist-mcp/
├── pyproject.toml                          # Dependencies + entry point
├── Dockerfile                              # Cloud Run container image
├── deploy.sh                               # GCP deployment script
├── .env.example                            # Environment template
├── .gitignore
├── README.md
├── src/
│   └── sdlc_assist_mcp/
│       ├── __init__.py
│       ├── server.py                       # MCP server + all 6 tool definitions
│       ├── supabase_client.py              # Async Supabase REST client (httpx)
│       ├── vertex_client.py                # Async Vertex AI Agent Engine client
│       └── models/
│           ├── __init__.py
│           └── inputs.py                   # Pydantic input models for tools
└── tests/
    └── (coming soon)
```

## Deployment

The server supports two transports:

- **stdio** (default) — For local use with Claude Desktop / Claude Code
- **streamable-http** — For remote deployment on Cloud Run

### Deploy to Cloud Run

```bash
./deploy.sh
```

This builds the container with Cloud Build, stores Supabase credentials in Secret Manager, and deploys to Cloud Run. See `deploy.sh` for full details.

### Environment Variables (Cloud Run)

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service role key (stored in Secret Manager) |
| `IT_ESTIMATION_AGENT_RESOURCE` | For estimation tool | Vertex AI agent resource name |
| `GOOGLE_CLOUD_PROJECT` | For estimation tool | GCP project ID (defaults to `sdlc-assist`) |
| `GOOGLE_CLOUD_LOCATION` | For estimation tool | GCP region (defaults to `us-central1`) |

## Future Enhancements

- **Write tools** — Update PRDs, add screens, modify artifacts
- **More agent-delegated tools** — Route additional tasks through Vertex AI agents
- **Search across artifacts** — Find mentions of a term across all project documents
- **Project creation** — Start new projects from the chat interface

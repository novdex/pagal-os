# PAGAL OS — Agent Runtime Design Specification

**Date:** 2026-03-31
**Project:** PAGAL OS (AI Agent Operating System)
**Phase:** Phase 1 — Agent Runtime (kernel)
**Author:** Arshdeep + Claude

---

## Overview

PAGAL OS is an operating system for AI agents. Like Android runs apps, PAGAL OS runs agents. Users create agents by describing what they want in plain English. Each agent is a YAML config file with a personality, tools, and model. The runtime loads agents, gives them tools, and manages their execution in isolated sandboxes.

## Target Users

- **Normal people (non-coders):** Describe what they want → get a working agent
- **Developers:** Write YAML configs, create custom tools, extend the system
- **Businesses:** Run specialized agents for their workflows

## Architecture

```
WEB DASHBOARD (localhost:3000)
  Create agents | Monitor | Logs | Settings
       ↓
CLI / API (localhost:8080)
  pagal run | pagal create | pagal list
       ↓
AGENT RUNTIME
  Load YAML → Start LLM → Give tools → Execute → Return output
  Each agent runs isolated (own memory, own tools, own config)
       ↓
LLM PROVIDERS
  OpenRouter (300+ cloud models)
  Ollama (local, free, private)
       ↓
TOOL REGISTRY
  search | file | shell | browser | api (plug-and-play)
       ↓
STORAGE
  SQLite | Agent configs (~/.pagal-os/agents/) | Memory
```

---

## Agent Format

An agent is a YAML file:

```yaml
name: research_agent
description: "Finds and summarises information on any topic"
model: openrouter/nvidia/nemotron-3-super-120b-a12b:free
tools:
  - search_web
  - read_webpage
  - write_file
personality: "You are a thorough researcher. Always cite sources."
memory: true
schedule: null
```

### Agent Lifecycle

1. CREATE — user describes agent or writes YAML → saved to ~/.pagal-os/agents/
2. RUN — runtime loads YAML, starts LLM with personality, provides tools
3. EXECUTE — agent thinks, calls tools in a loop, produces output
4. DONE — output returned, memory saved, agent sleeps until next run

---

## Core Components

### 1. Agent Runtime (core/runtime.py)

The kernel. Loads agent YAML, initializes LLM connection, provides tools, runs the agent loop.

Functions:
- `load_agent(name: str) -> AgentConfig` — Load YAML config
- `run_agent(agent: AgentConfig, task: str) -> AgentResult` — Execute agent with a task
- `list_agents() -> list` — List all available agents
- `stop_agent(name: str) -> bool` — Stop a running agent
- `get_agent_status(name: str) -> dict` — Check if agent is running/idle

### 2. Agent Sandbox (core/sandbox.py)

Each agent runs isolated. One agent crash doesn't affect others.

- Separate thread per agent
- Own memory store
- Tool access controlled by agent config
- Timeout protection
- Error isolation

### 3. LLM Provider (core/llm.py)

Unified interface for cloud and local models.

- `call_llm(messages, model, tools) -> response` — Routes to OpenRouter or Ollama
- Auto-detects: if model starts with "ollama/" → local, otherwise → OpenRouter
- Handles errors, timeouts, retries

### 4. Tool Registry (tools/registry.py)

Plug-and-play tools that agents can use.

Built-in tools:
- `search_web` — DuckDuckGo search
- `read_webpage` — Extract text from URL
- `read_file` / `write_file` — Local file operations
- `run_shell` — Execute shell commands (sandboxed)
- `browse_url` — Headless browser

Custom tools: Drop a .py file in ~/.pagal-os/tools/ with a register() function.

### 5. Agent Creator (via LLM)

When user describes an agent in plain English:
1. Send description to LLM
2. LLM generates YAML config
3. Save to ~/.pagal-os/agents/
4. Agent ready to run

### 6. CLI (cli/main.py)

Commands:
- `pagal create "description"` — Create agent from description
- `pagal run <agent> "task"` — Run agent with a task
- `pagal list` — List all agents
- `pagal status` — Show running agents
- `pagal stop <agent>` — Stop an agent
- `pagal logs <agent>` — View agent logs
- `pagal doctor` — Diagnose and fix issues

### 7. Web Dashboard (web/)

Simple HTML/JS served by FastAPI at localhost:3000.

Pages:
- My Agents — list, start, stop, status
- Create — describe in plain English, click create
- Logs — real-time agent activity
- Settings — API keys, default model, storage

### 8. API (api/server.py)

RESTful endpoints:
- POST /agents — create agent
- GET /agents — list agents
- POST /agents/{name}/run — run agent with task
- GET /agents/{name}/status — check status
- DELETE /agents/{name} — delete agent
- GET /agents/{name}/logs — get logs

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Web framework | FastAPI |
| Dashboard | Jinja2 templates + vanilla JS |
| Database | SQLite |
| LLM (cloud) | OpenRouter via httpx |
| LLM (local) | Ollama via HTTP |
| Agent isolation | threading + subprocess |
| Config | YAML (PyYAML) |
| CLI | argparse |
| Search | DuckDuckGo (duckduckgo-search) |
| Browser | httpx + BeautifulSoup |

---

## File Structure

```
pagal-os/
├── src/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── runtime.py
│   │   ├── sandbox.py
│   │   ├── llm.py
│   │   └── config.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   ├── search.py
│   │   ├── files.py
│   │   ├── shell.py
│   │   └── browser.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── server.py
│   │   └── routes.py
│   ├── web/
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── dashboard.html
│   │   │   ├── create.html
│   │   │   ├── logs.html
│   │   │   └── settings.html
│   │   └── static/
│   │       ├── style.css
│   │       └── app.js
│   └── cli/
│       ├── __init__.py
│       └── main.py
├── tests/
│   ├── __init__.py
│   ├── test_runtime.py
│   ├── test_llm.py
│   ├── test_tools.py
│   └── test_api.py
├── config.yaml
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── pagal.py              # Entry point: python pagal.py
```

---

## Storage

All data in ~/.pagal-os/:
```
~/.pagal-os/
├── agents/          # Agent YAML configs
├── memory/          # Per-agent memory stores
├── tools/           # Custom tool plugins
├── logs/            # Agent execution logs
├── pagal.db         # SQLite database
└── config.yaml      # System settings
```

---

## Configuration

config.yaml:
```yaml
# PAGAL OS System Config
version: 1
api_port: 8080
web_port: 3000
default_model: "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
ollama_url: "http://localhost:11434"
max_concurrent_agents: 5
agent_timeout_seconds: 300
storage_path: "~/.pagal-os"
```

.env:
```
OPENROUTER_API_KEY=your_key
```

---

## Success Criteria

Phase 1 is done when:
1. `pagal create "research agent"` creates an agent from description
2. `pagal run research_agent "find AI news"` returns a real result
3. `pagal list` shows all agents
4. Web dashboard shows agents and their status
5. Agents use tools (search, files) successfully
6. Two agents can run simultaneously without interfering
7. Works with both OpenRouter (cloud) and Ollama (local)

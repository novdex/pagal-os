# PAGAL OS Agent Runtime — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PAGAL OS Agent Runtime — an operating system that creates, runs, and manages AI agents from YAML configs with a CLI and web dashboard.

**Architecture:** Agents are YAML configs loaded by a runtime engine. Each agent runs in an isolated thread with its own tools, memory, and LLM connection. CLI for power users, web dashboard for normal people. OpenRouter for cloud models, Ollama for local.

**Tech Stack:** Python 3.12+, FastAPI, Jinja2, SQLite, httpx, PyYAML, duckduckgo-search, BeautifulSoup4, argparse

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `config.yaml`
- Create: `src/__init__.py`
- Create: `src/core/__init__.py`
- Create: `src/core/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi>=0.100.0
uvicorn>=0.23.0
httpx>=0.27.0
pyyaml>=6.0
python-dotenv>=1.0.0
jinja2>=3.1.0
duckduckgo-search>=4.0
beautifulsoup4>=4.12.0
pytest>=8.0.0
```

- [ ] **Step 2: Create .gitignore, .env.example, config.yaml**

- [ ] **Step 3: Create src/core/config.py** — Settings dataclass, load from config.yaml + .env

- [ ] **Step 4: Create tests/test_config.py and run**

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: project scaffold with config"
```

---

### Task 2: LLM Provider

**Files:**
- Create: `src/core/llm.py`
- Create: `tests/test_llm.py`

- [ ] **Step 1: Create src/core/llm.py**

Unified LLM interface:
- `call_llm(messages: list, model: str, tools: list = None) -> dict`
- If model starts with "ollama/" → call Ollama at localhost:11434
- Otherwise → call OpenRouter API
- Returns: `{"ok": bool, "content": str, "tool_calls": list | None}`
- Handles timeouts (30s), errors, retries (1 retry)

OpenRouter format: POST https://openrouter.ai/api/v1/chat/completions
Ollama format: POST http://localhost:11434/api/chat

- [ ] **Step 2: Tests and commit**

---

### Task 3: Tool Registry + Built-in Tools

**Files:**
- Create: `src/tools/__init__.py`
- Create: `src/tools/registry.py`
- Create: `src/tools/search.py`
- Create: `src/tools/files.py`
- Create: `src/tools/shell.py`
- Create: `src/tools/browser.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Create src/tools/registry.py**

```python
TOOLS: dict[str, dict] = {}  # name -> {"function": callable, "schema": dict}

def register_tool(name, function, description, parameters):
    """Register a tool."""

def get_tool(name) -> callable:
    """Get a tool function by name."""

def get_tool_schemas(tool_names: list) -> list:
    """Get OpenAI function-calling schemas for given tool names."""

def list_tools() -> list[str]:
    """List all registered tool names."""

def load_custom_tools(tools_dir: Path):
    """Load .py plugins from ~/.pagal-os/tools/"""
```

- [ ] **Step 2: Create built-in tools**

search.py:
- `search_web(query: str, num_results: int = 5) -> dict` — DuckDuckGo search

files.py:
- `read_file(path: str) -> dict` — Read file content
- `write_file(path: str, content: str) -> dict` — Write file

shell.py:
- `run_shell(command: str, timeout: int = 10) -> dict` — Run command, capture output

browser.py:
- `browse_url(url: str) -> dict` — Fetch URL, extract text with BeautifulSoup

Each tool returns: `{"ok": bool, "result": str | dict}` and registers itself on import.

- [ ] **Step 3: Tests and commit**

---

### Task 4: Agent Runtime (The Kernel)

**Files:**
- Create: `src/core/runtime.py`
- Create: `src/core/sandbox.py`
- Create: `tests/test_runtime.py`

- [ ] **Step 1: Create AgentConfig dataclass**

```python
@dataclass
class AgentConfig:
    name: str
    description: str
    model: str
    tools: list[str]
    personality: str
    memory: bool = True
    schedule: str | None = None

@dataclass
class AgentResult:
    ok: bool
    output: str
    tools_used: list[str]
    duration_seconds: float
    error: str = ""
```

- [ ] **Step 2: Create src/core/runtime.py**

```python
AGENTS_DIR = Path.home() / ".pagal-os" / "agents"
_running_agents: dict[str, dict] = {}  # name -> {thread, status, started_at}

def load_agent(name: str) -> AgentConfig:
    """Load agent YAML from ~/.pagal-os/agents/{name}.yaml"""

def run_agent(agent: AgentConfig, task: str) -> AgentResult:
    """Execute agent: build messages, call LLM in loop with tools, return result."""
    # 1. Build system message from personality
    # 2. Add user task message
    # 3. Call LLM with tools
    # 4. If tool_calls → execute tools → append results → call LLM again
    # 5. Repeat until LLM gives final text response (max 20 loops)
    # 6. Return AgentResult

def run_agent_async(name: str, task: str):
    """Run agent in background thread, update _running_agents status."""

def list_agents() -> list[dict]:
    """List all YAML files in agents dir."""

def stop_agent(name: str) -> bool:
    """Stop a running agent."""

def get_agent_status(name: str) -> dict:
    """Return status of an agent (running/idle/error)."""
```

- [ ] **Step 3: Create src/core/sandbox.py**

Agent isolation wrapper:
- `run_in_sandbox(agent: AgentConfig, task: str, timeout: int = 300) -> AgentResult`
- Runs `run_agent` in a separate thread with timeout
- Catches all exceptions — never crashes the main process
- Returns AgentResult with error if anything goes wrong

- [ ] **Step 4: Tests and commit**

---

### Task 5: Agent Creator (Natural Language → YAML)

**Files:**
- Create: `src/core/creator.py`

- [ ] **Step 1: Create src/core/creator.py**

```python
def create_agent_from_description(description: str, model: str = None) -> str:
    """Ask LLM to generate agent YAML from plain English description.

    Returns the agent name (filename stem).
    """
    # 1. Call LLM with prompt:
    #    "Create a YAML agent config for: {description}
    #     Available tools: {list_tools()}
    #     Return ONLY valid YAML with keys: name, description, model, tools, personality, memory"
    # 2. Parse YAML from response
    # 3. Save to ~/.pagal-os/agents/{name}.yaml
    # 4. Return name
```

- [ ] **Step 2: Commit**

---

### Task 6: CLI

**Files:**
- Create: `src/cli/__init__.py`
- Create: `src/cli/main.py`
- Create: `pagal.py`

- [ ] **Step 1: Create src/cli/main.py**

```python
def main():
    parser = argparse.ArgumentParser(prog="pagal", description="PAGAL OS — AI Agent Operating System")
    subparsers = parser.add_subparsers(dest="command")

    # pagal create "description"
    create_p = subparsers.add_parser("create")
    create_p.add_argument("description")

    # pagal run <agent> "task"
    run_p = subparsers.add_parser("run")
    run_p.add_argument("agent")
    run_p.add_argument("task")

    # pagal list
    subparsers.add_parser("list")

    # pagal status
    subparsers.add_parser("status")

    # pagal stop <agent>
    stop_p = subparsers.add_parser("stop")
    stop_p.add_argument("agent")

    # pagal server (starts API + web dashboard)
    subparsers.add_parser("server")

    args = parser.parse_args()
    # Route to appropriate function
```

- [ ] **Step 2: Create pagal.py** (entry point)

```python
#!/usr/bin/env python3
"""PAGAL OS — AI Agent Operating System. Run: python pagal.py <command>"""
from src.cli.main import main
if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Test CLI manually and commit**

---

### Task 7: API Server

**Files:**
- Create: `src/api/__init__.py`
- Create: `src/api/server.py`
- Create: `src/api/routes.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Create src/api/server.py**

FastAPI app with Jinja2 templates:
```python
app = FastAPI(title="PAGAL OS")
templates = Jinja2Templates(directory="src/web/templates")
app.mount("/static", StaticFiles(directory="src/web/static"))
```

- [ ] **Step 2: Create src/api/routes.py**

Endpoints:
- `POST /api/agents` — create agent from description
- `GET /api/agents` — list all agents
- `POST /api/agents/{name}/run` — run agent with task (returns result)
- `GET /api/agents/{name}/status` — get agent status
- `DELETE /api/agents/{name}` — delete agent
- `GET /api/agents/{name}/logs` — get agent logs

Web pages (serve HTML):
- `GET /` — dashboard
- `GET /create` — create agent page
- `GET /logs` — logs page
- `GET /settings` — settings page

- [ ] **Step 3: Tests and commit**

---

### Task 8: Web Dashboard

**Files:**
- Create: `src/web/templates/base.html`
- Create: `src/web/templates/dashboard.html`
- Create: `src/web/templates/create.html`
- Create: `src/web/templates/logs.html`
- Create: `src/web/templates/settings.html`
- Create: `src/web/static/style.css`
- Create: `src/web/static/app.js`

- [ ] **Step 1: Create base.html** — Layout with nav (My Agents, Create, Logs, Settings)

- [ ] **Step 2: Create dashboard.html** — Shows all agents with status, start/stop buttons

- [ ] **Step 3: Create create.html** — Text input + "Create Agent" button, calls API

- [ ] **Step 4: Create logs.html** — Shows agent logs, auto-refreshes

- [ ] **Step 5: Create settings.html** — API keys, default model config

- [ ] **Step 6: Create style.css** — Clean dark theme, cards for agents

- [ ] **Step 7: Create app.js** — Fetch API calls, auto-refresh, form handling

- [ ] **Step 8: Commit**

---

### Task 9: Starter Agents + README

**Files:**
- Create: `README.md`
- Create starter agents in ~/.pagal-os/agents/

- [ ] **Step 1: Create 3 starter agents**

research_agent.yaml — searches web and summarises
file_helper.yaml — reads, writes, organises files
shell_agent.yaml — runs commands and explains output

- [ ] **Step 2: Create README.md**

Quick start guide: install, configure API key, create first agent, run it.

- [ ] **Step 3: Commit**

---

### Task 10: Integration Test + Push to GitHub

- [ ] **Step 1: Start server** — `python pagal.py server`
- [ ] **Step 2: Test CLI** — create, run, list agents
- [ ] **Step 3: Test web dashboard** — open browser, create agent, run it
- [ ] **Step 4: Fix any issues**
- [ ] **Step 5: Final commit and push**

```bash
git add -A && git commit -m "feat: PAGAL OS v0.1 — complete Agent Runtime"
git push origin master
```

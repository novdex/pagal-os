# PAGAL OS — AI Agent Operating System

An operating system that creates, runs, and manages AI agents from YAML configs. Features a CLI for power users and a web dashboard for everyone else.

## Quick Start

### 1. Install dependencies

**Linux / macOS (Bash):**

```bash
cd ~/projects/pagal-os
pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
cd C:\projects\pagal-os
pip install -r requirements.txt
```

### 2. Configure API key

**Linux / macOS:**

```bash
cp .env.example .env
# Edit .env and add your OpenRouter API key
```

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
# Edit .env and add your OpenRouter API key
```

Get a free key at [openrouter.ai/keys](https://openrouter.ai/keys).

### 3. Create an agent

```bash
python pagal.py create "a research agent that finds AI news"
```

### 4. Run an agent

```bash
python pagal.py run research_agent "find the latest AI news today"
```

### 5. Web Dashboard

```bash
python pagal.py server
```

Then open [http://localhost:3000](http://localhost:3000) in your browser.

## CLI Commands

| Command | Description |
|---------|-------------|
| `python pagal.py create "description"` | Create agent from description |
| `python pagal.py run <agent> "task"` | Run an agent with a task |
| `python pagal.py list` | List all agents |
| `python pagal.py status [agent]` | Show agent status |
| `python pagal.py stop <agent>` | Stop a running agent |
| `python pagal.py server` | Start web dashboard |

## Architecture

- **Agents** are YAML configs stored in `~/.pagal-os/agents/`
  - On Windows: `C:\Users\<username>\.pagal-os\agents\`
- **Runtime** loads configs and runs agents in isolated threads
- **Tools** are pluggable (search, files, shell, browser)
- **LLM** supports OpenRouter (cloud) and Ollama (local)

## Storage Paths

All PAGAL OS data lives under a single directory:

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.pagal-os/` |
| Windows | `C:\Users\<username>\.pagal-os\` |

Sub-directories:

| Directory | Purpose |
|-----------|---------|
| `agents/` | Agent YAML configuration files |
| `memory/` | Persistent agent memory |
| `backups/` | System backups |
| `screenshots/` | Computer-use screenshots |
| `logs/` | Agent execution logs |

## Built-in Tools

| Tool | Description |
|------|-------------|
| `search_web` | DuckDuckGo web search |
| `browse_url` | Fetch and extract text from URLs |
| `read_file` | Read file contents |
| `write_file` | Write content to files |
| `run_shell` | Execute shell commands |

## Starter Agents

- **research_agent** — Searches the web and creates research reports
- **file_helper** — Reads, writes, and organises files
- **shell_agent** — Runs shell commands and explains output

## Project Structure

```
pagal-os/
├── pagal.py              # Entry point
├── config.yaml           # Configuration
├── requirements.txt      # Dependencies
├── src/
│   ├── core/
│   │   ├── config.py     # Settings loader
│   │   ├── llm.py        # LLM provider (OpenRouter/Ollama)
│   │   ├── runtime.py    # Agent runtime kernel
│   │   ├── sandbox.py    # Isolation wrapper
│   │   ├── database.py   # SQLite connection manager
│   │   └── creator.py    # Natural language agent creator
│   ├── tools/
│   │   ├── registry.py   # Tool plugin system
│   │   ├── search.py     # Web search tool
│   │   ├── files.py      # File read/write tools
│   │   ├── shell.py      # Shell command tool
│   │   └── browser.py    # URL browser tool
│   ├── api/
│   │   ├── server.py     # FastAPI app
│   │   └── routes/       # API + web route modules
│   ├── cli/
│   │   └── main.py       # CLI commands
│   └── web/
│       ├── templates/    # Jinja2 HTML templates
│       └── static/       # CSS + JS
└── tests/
    ├── test_config.py
    ├── test_tools.py
    ├── test_runtime.py
    └── test_api.py
```

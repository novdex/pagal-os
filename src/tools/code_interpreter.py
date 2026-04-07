"""Code Interpreter — agents can write and execute Python code in a sandbox.

Runs Python code in a subprocess with:
  - Restricted environment (no API keys leaked)
  - Timeout protection (default 30s)
  - Output capture (stdout, stderr, generated files)
  - Pre-installed: math, json, csv, statistics, datetime, collections, re
  - Matplotlib/pandas available if installed

The agent writes Python, the interpreter runs it, and returns the output.
This enables: data analysis, chart generation, calculations, file transforms.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

# Env vars to strip from child process
_BLOCKED_ENV = {
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "GH_TOKEN",
    "PAGAL_API_TOKEN", "EMAIL_PASSWORD", "WHATSAPP_TOKEN",
}


def run_python(code: str, timeout: int = 30) -> dict[str, Any]:
    """Execute Python code in an isolated subprocess.

    Args:
        code: Python source code to execute.
        timeout: Max execution time in seconds.

    Returns:
        Dict with 'ok', 'stdout', 'stderr', 'files' (list of generated file paths).
    """
    if not code or not code.strip():
        return {"ok": False, "error": "No code provided"}

    # Block obviously dangerous code
    dangerous = ["os.system", "subprocess", "shutil.rmtree", "os.remove",
                 "__import__('os')", "exec(", "eval(", "open('/etc"]
    code_lower = code.lower()
    for d in dangerous:
        if d.lower() in code_lower:
            return {"ok": False, "error": f"Blocked: code contains disallowed pattern '{d}'"}

    try:
        # Create temp dir for output files
        work_dir = tempfile.mkdtemp(prefix="pagal_code_")

        # Wrap code to capture matplotlib figures
        wrapped_code = f"""
import sys, os
os.chdir({repr(work_dir)})

# Make matplotlib non-interactive if available
try:
    import matplotlib
    matplotlib.use('Agg')
except ImportError:
    pass

# --- User code ---
{code}

# --- Auto-save matplotlib figures ---
try:
    import matplotlib.pyplot as plt
    figs = [plt.figure(n) for n in plt.get_fignums()]
    for i, fig in enumerate(figs):
        fig.savefig(os.path.join({repr(work_dir)}, f'figure_{{i}}.png'), dpi=100, bbox_inches='tight')
        print(f'[saved figure_{{i}}.png]')
except Exception:
    pass
"""

        # Build safe environment
        env = {k: v for k, v in os.environ.items() if k not in _BLOCKED_ENV}
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [sys.executable, "-c", wrapped_code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=work_dir,
        )

        # Collect generated files
        files = []
        for f in Path(work_dir).iterdir():
            if f.is_file():
                files.append(str(f))

        output = {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip()[:10000],
            "stderr": result.stderr.strip()[:2000] if result.returncode != 0 else "",
            "files": files,
        }

        if result.returncode != 0:
            output["error"] = f"Code exited with error:\n{result.stderr.strip()[:500]}"

        return output

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Code execution timed out after {timeout}s"}
    except Exception as e:
        return {"ok": False, "error": f"Execution failed: {e}"}


# Auto-register
register_tool(
    name="run_python",
    function=run_python,
    description="Execute Python code in a sandboxed environment. Use for data analysis, calculations, chart generation, file processing. Matplotlib and standard library available. Returns stdout and any generated files.",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python source code to execute"},
            "timeout": {"type": "integer", "description": "Max execution time in seconds (default 30)", "default": 30},
        },
        "required": ["code"],
    },
)

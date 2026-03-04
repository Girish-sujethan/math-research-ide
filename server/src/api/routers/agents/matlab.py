"""Python visualization agent.

Executes user-submitted NumPy / SciPy / Matplotlib code in an isolated
subprocess with a hard timeout.  Returns captured stdout and an optional
PNG plot encoded as base64.

Security posture: this is a single-user research tool.  A basic pattern
blocklist prevents the most obvious shell-escape patterns; it is *not* a
full sandbox.
"""

import asyncio
import json
import logging
import re
import sys
import tempfile
import textwrap
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.schemas import PythonVisualRequest, PythonVisualResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents/python-visual", tags=["agents"])

EXEC_TIMEOUT = 20  # seconds

_BLOCKED = re.compile(
    r"\b(import\s+os|import\s+subprocess|import\s+shutil|"
    r"__import__\s*\(|exec\s*\(|eval\s*\(|open\s*\(|"
    r"pathlib|socket|ctypes|pickle)\b"
)

# ── Script template ──────────────────────────────────────────────────────────
# User code is indented and dropped into the try block.  A final JSON line is
# always printed to stdout so we can parse it reliably.
_TEMPLATE = """\
import sys, io, json, traceback, base64

import numpy as np
import scipy
from scipy import linalg, stats, signal, integrate, optimize, fft

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

_stdout_buf = io.StringIO()
sys.stdout = _stdout_buf
_image_b64 = None
_error = None

try:
{user_code}
    # Capture any open figure
    if plt.get_fignums():
        _buf = io.BytesIO()
        plt.savefig(_buf, format="png", dpi=140, bbox_inches="tight")
        plt.close("all")
        _buf.seek(0)
        _image_b64 = base64.b64encode(_buf.read()).decode()
except Exception:
    _error = traceback.format_exc()
finally:
    sys.stdout = sys.__stdout__

print(json.dumps({{"output": _stdout_buf.getvalue(), "image": _image_b64, "error": _error}}))
"""


@router.post("", response_model=PythonVisualResponse)
async def execute_python_visual(req: PythonVisualRequest) -> PythonVisualResponse:
    """Execute NumPy/SciPy/Matplotlib code and return output + optional plot."""
    code = req.code.strip()

    if not code:
        raise HTTPException(status_code=400, detail="Code is empty.")
    if len(code) > 8_000:
        raise HTTPException(status_code=400, detail="Code exceeds 8 000 character limit.")
    if _BLOCKED.search(code):
        raise HTTPException(
            status_code=400,
            detail="Code contains a disallowed pattern (unsafe import or built-in).",
        )

    return await asyncio.to_thread(_run_code, code)


def _run_code(user_code: str) -> PythonVisualResponse:
    indented = textwrap.indent(user_code, "    ")
    script = _TEMPLATE.format(user_code=indented)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        tmp = Path(f.name)

    try:
        import subprocess  # noqa: S404 – deliberate internal use only

        result = subprocess.run(  # noqa: S603
            [sys.executable, str(tmp)],
            capture_output=True,
            text=True,
            timeout=EXEC_TIMEOUT,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if not stdout:
            return PythonVisualResponse(
                output="",
                image_base64=None,
                error=stderr or "No output produced. Did you forget to call print() or plt.show()?",
            )

        try:
            data = json.loads(stdout)
            return PythonVisualResponse(
                output=data.get("output", ""),
                image_base64=data.get("image"),
                error=data.get("error"),
            )
        except json.JSONDecodeError:
            return PythonVisualResponse(output=stdout, image_base64=None, error=stderr or None)

    except subprocess.TimeoutExpired:
        return PythonVisualResponse(
            output="",
            image_base64=None,
            error=f"Execution timed out after {EXEC_TIMEOUT} seconds.",
        )
    except Exception as exc:
        logger.exception("Python visualization execution error")
        return PythonVisualResponse(output="", image_base64=None, error=str(exc))
    finally:
        tmp.unlink(missing_ok=True)

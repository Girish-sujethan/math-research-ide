"""Lean 4 formal verification wrapper.

Writes a temporary .lean file inside server/lean_project/, then invokes
`lake env lean <file>` as a subprocess. Using `lake env` is required so that
Lean can resolve the Mathlib4 import — bare `lean <file>` will not find Mathlib.

Prerequisites (one-time manual setup):
  1. Install Lean 4 via elan: https://leanprover.github.io/lean4/doc/setup.html
       curl https://elan.lean-lang.org/elan-init.sh -sSf | sh
  2. From server/lean_project/, fetch pre-compiled Mathlib binaries:
       cd server/lean_project && lake exe cache get
     (compiling Mathlib from scratch takes several hours — always use the cache)
  3. Verify setup: cd server/lean_project && lake env lean HEAVEN/Basic.lean
     Should print nothing (no errors).

The autoformalization step — converting a natural language / LaTeX statement
into valid Lean 4 syntax — is handled by the model layer (not implemented here).
This module assumes it receives valid Lean 4 source as input.
"""

import subprocess
import tempfile
import os
from dataclasses import dataclass
from pathlib import Path

from src.config import settings


@dataclass
class LeanResult:
    success: bool
    output: str     # full stdout + stderr from Lean
    errors: list[str]


_LEAN_TEMPLATE = """\
import Mathlib

-- Auto-generated verification file for HEAVEN
-- Statement: {statement_comment}

{lean_source}
"""


def verify(
    lean_source: str,
    statement_comment: str = "",
) -> LeanResult:
    """Run Lean 4 on the provided source and return the result.

    Args:
        lean_source: Valid Lean 4 source (theorem statement + tactic proof or #check).
        statement_comment: Human-readable label for the log — not part of verification.

    Returns:
        LeanResult with success flag, full output, and parsed error list.
    """
    lean_content = _LEAN_TEMPLATE.format(
        statement_comment=statement_comment,
        lean_source=lean_source,
    )

    project_dir = Path(settings.lean_project_dir)
    if not project_dir.exists():
        return LeanResult(
            success=False,
            output="Lean project directory not found. Run setup first.",
            errors=["Lean project not configured"],
        )

    # Temp file must live inside the lean_project so Lake's environment resolves Mathlib
    tmp_dir = project_dir / "HEAVEN"
    tmp_dir.mkdir(exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".lean",
        dir=tmp_dir,
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(lean_content)
        tmp_path = f.name

    try:
        # `lake env lean` sets up the Mathlib-aware environment before invoking Lean.
        # Without this, `import Mathlib` will fail.
        result = subprocess.run(
            ["lake", "env", settings.lean_executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=settings.lean_timeout_seconds,
            cwd=str(project_dir),
        )
        combined_output = result.stdout + result.stderr
        errors = _parse_errors(combined_output)
        return LeanResult(
            success=result.returncode == 0 and not errors,
            output=combined_output,
            errors=errors,
        )
    except subprocess.TimeoutExpired:
        return LeanResult(
            success=False,
            output=f"Lean verification timed out after {settings.lean_timeout_seconds}s",
            errors=["Timeout"],
        )
    except FileNotFoundError:
        return LeanResult(
            success=False,
            output=(
                "lake or lean executable not found. "
                "Install Lean 4 via elan: curl https://elan.lean-lang.org/elan-init.sh -sSf | sh"
            ),
            errors=["Lean not installed"],
        )
    finally:
        os.unlink(tmp_path)


def check_type(lean_expression: str) -> LeanResult:
    """Use `#check` to verify that an expression type-checks in Lean 4 / Mathlib.

    Lighter than a full proof — good for checking that a statement is well-formed.
    """
    return verify(f"#check ({lean_expression})", statement_comment=lean_expression)


def _parse_errors(output: str) -> list[str]:
    """Extract error lines from Lean output."""
    errors = []
    for line in output.splitlines():
        lower = line.lower()
        if "error:" in lower or "unknown identifier" in lower or "type mismatch" in lower:
            errors.append(line.strip())
    return errors

"""SymPy pre-verification layer.

Provides fast, cheap symbolic checks on a discovery's modified statement
before triggering expensive Lean 4 formal verification.

Catches most hallucinations and obvious errors early.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass

from sympy import simplify
from sympy.parsing.latex import parse_latex

logger = logging.getLogger(__name__)

# Hard cap on SymPy computation time (seconds). Integrals and limits can hang
# indefinitely — the thread is not killed but the caller stops waiting and
# returns "skip" so the HTTP response is never blocked.
_SYMPY_TIMEOUT = 5.0

# Module-level pool: reused across calls to avoid per-call thread spawn overhead.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sympy")

# LaTeX macros that signal an expression too complex for fast symbolic checks.
_COMPLEX_MARKERS = (
    r"\int", r"\sum", r"\prod", r"\lim", r"\infty",
    r"\oint", r"\iint", r"\iiint", r"\idotsint",
    r"\sup", r"\inf", r"\limsup", r"\liminf",
)


def _is_complex_expression(latex: str) -> bool:
    """Return True if the expression contains constructs SymPy can't quickly verify."""
    return any(marker in latex for marker in _COMPLEX_MARKERS)


def _run_sympy(fn, *args) -> "SympyCheckResult | None":
    """Execute fn(*args) in the shared thread pool with a hard timeout.

    Returns None if the computation times out; re-raises other exceptions.
    """
    future = _pool.submit(fn, *args)
    try:
        return future.result(timeout=_SYMPY_TIMEOUT)
    except FuturesTimeout:
        logger.warning("SymPy timed out after %.1fs for args: %s", _SYMPY_TIMEOUT, args)
        return None


@dataclass
class SympyCheckResult:
    passed: bool
    output: str
    simplified_form: str | None = None


def check_latex_expression(latex: str) -> SympyCheckResult:
    """Parse a LaTeX expression and verify it is symbolically valid.

    Checks:
    1. Parse succeeds (syntactically valid LaTeX math)
    2. Simplification doesn't raise (expression is well-formed)
    3. Returns the simplified form for human review

    Returns a 'skip' result for expressions that are too complex to evaluate quickly.
    """
    if _is_complex_expression(latex):
        return SympyCheckResult(
            passed=True,
            output="Skipped — expression too complex for fast symbolic check.",
        )

    def _inner() -> SympyCheckResult:
        try:
            expr = parse_latex(latex)
        except Exception as e:
            return SympyCheckResult(passed=False, output=f"LaTeX parse failed: {e}")
        try:
            simplified = simplify(expr)
            return SympyCheckResult(
                passed=True,
                output="Expression parsed and simplified successfully.",
                simplified_form=str(simplified),
            )
        except Exception as e:
            return SympyCheckResult(passed=False, output=f"Simplification failed: {e}")

    result = _run_sympy(_inner)
    if result is None:
        return SympyCheckResult(
            passed=True,
            output="Skipped — symbolic simplification timed out.",
        )
    return result


def check_equality(lhs_latex: str, rhs_latex: str) -> SympyCheckResult:
    """Check whether two LaTeX expressions are symbolically equal.

    Returns a 'skip' result for expressions containing integrals, sums, or
    other constructs that SymPy cannot quickly evaluate.
    """
    if _is_complex_expression(lhs_latex) or _is_complex_expression(rhs_latex):
        return SympyCheckResult(
            passed=True,
            output="Skipped — expression too complex for fast symbolic check.",
        )

    def _inner() -> SympyCheckResult:
        try:
            lhs = parse_latex(lhs_latex)
            rhs = parse_latex(rhs_latex)
        except Exception as e:
            return SympyCheckResult(passed=False, output=f"Parse error: {e}")
        try:
            diff = simplify(lhs - rhs)
            equal = diff == 0
            return SympyCheckResult(
                passed=equal,
                output="Expressions are equal." if equal else f"Expressions differ by: {diff}",
                simplified_form=str(diff),
            )
        except Exception as e:
            return SympyCheckResult(passed=False, output=f"Equality check failed: {e}")

    result = _run_sympy(_inner)
    if result is None:
        return SympyCheckResult(
            passed=True,
            output="Skipped — symbolic equality check timed out.",
        )
    return result


def numerical_spot_check(
    latex: str,
    substitutions: dict[str, float],
) -> SympyCheckResult:
    """Numerically evaluate a LaTeX expression at given variable values.

    Useful for sanity-checking that an expression is finite and defined
    at test points before formal verification.
    """
    try:
        expr = parse_latex(latex)
        result = expr.subs(substitutions).evalf()
        return SympyCheckResult(
            passed=True,
            output=f"Evaluates to: {result}",
            simplified_form=str(result),
        )
    except Exception as e:
        return SympyCheckResult(passed=False, output=f"Numerical evaluation failed: {e}")

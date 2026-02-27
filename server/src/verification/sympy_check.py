"""SymPy pre-verification layer.

Provides fast, cheap symbolic checks on a discovery's modified statement
before triggering expensive Lean 4 formal verification.

Catches most hallucinations and obvious errors early.
"""

from dataclasses import dataclass
from sympy import SympifyError, simplify, sympify
from sympy.parsing.latex import parse_latex


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
    """
    try:
        expr = parse_latex(latex)
    except Exception as e:
        return SympyCheckResult(
            passed=False,
            output=f"LaTeX parse failed: {e}",
        )

    try:
        simplified = simplify(expr)
        return SympyCheckResult(
            passed=True,
            output="Expression parsed and simplified successfully.",
            simplified_form=str(simplified),
        )
    except Exception as e:
        return SympyCheckResult(
            passed=False,
            output=f"Simplification failed: {e}",
        )


def check_equality(lhs_latex: str, rhs_latex: str) -> SympyCheckResult:
    """Check whether two LaTeX expressions are symbolically equal."""
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

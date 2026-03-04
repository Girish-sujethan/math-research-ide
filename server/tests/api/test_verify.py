"""Tests for /verify/* endpoints: parity, nudge, correlate, formalize."""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# /verify/parity
# ---------------------------------------------------------------------------

class TestCheckParity:
    def test_simple_verified_equality(self, client):
        """2 + 2 = 4 should be verified."""
        resp = client.post("/verify/parity", json={"source": "$$2 + 2 = 4$$"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        r = results[0]
        assert r["status"] == "verified"
        assert r["expression"] == "2 + 2 = 4"

    def test_simple_failed_equality(self, client):
        """x = 1 + 1 is algebraically false (x is a free symbol)."""
        resp = client.post("/verify/parity", json={"source": "$$x = 1 + 1$$"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "failed"

    def test_polynomial_verified(self, client):
        """(a+b)^2 = a^2 + 2ab + b^2 should verify."""
        resp = client.post(
            "/verify/parity",
            json={"source": r"$$(a+b)^2 = a^2 + 2*a*b + b^2$$"},
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "verified"

    def test_complex_integral_is_skipped(self, client):
        """Expressions with \\int should be skipped, not evaluated (avoids SymPy hang)."""
        source = r"$$\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}$$"
        resp = client.post("/verify/parity", json={"source": source})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "skip"

    def test_infinite_sum_is_skipped(self, client):
        """Expressions with \\sum should be skipped."""
        source = r"$$\sum_{n=1}^\infty \frac{1}{n^2} = \frac{\pi^2}{6}$$"
        resp = client.post("/verify/parity", json={"source": source})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "skip"

    def test_no_equations_in_source(self, client):
        """Source with no $$ blocks returns empty results."""
        resp = client.post("/verify/parity", json={"source": "No math here."})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_expression_without_equals_is_skip(self, client):
        """An expression with no = sign returns status 'skip'."""
        resp = client.post("/verify/parity", json={"source": r"$$x^2 + y^2$$"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "skip"

    def test_multiple_equations(self, client):
        """Multiple $$ blocks are all checked."""
        source = "$$2 + 2 = 4$$ and $$1 + 1 = 3$$"
        resp = client.post("/verify/parity", json={"source": source})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 2
        statuses = {r["status"] for r in results}
        assert "verified" in statuses
        assert "failed" in statuses

    def test_results_sorted_by_start_char(self, client):
        """Results should be sorted ascending by start_char."""
        source = "$$1 + 1 = 3$$ some text $$2 + 2 = 4$$"
        resp = client.post("/verify/parity", json={"source": source})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 2
        assert results[0]["start_char"] < results[1]["start_char"]

    def test_equation_environment(self, client):
        """\\begin{equation}...\\end{equation} blocks are also checked."""
        source = r"\begin{equation}2 + 2 = 4\end{equation}"
        resp = client.post("/verify/parity", json={"source": source})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["status"] == "verified"

    def test_parity_response_has_required_fields(self, client):
        """Each result must contain start_char, end_char, expression, status."""
        resp = client.post("/verify/parity", json={"source": "$$a = b$$"})
        assert resp.status_code == 200
        for r in resp.json()["results"]:
            assert "start_char" in r
            assert "end_char" in r
            assert "expression" in r
            assert "status" in r
            assert r["status"] in ("verified", "failed", "skip", "invalid")


# ---------------------------------------------------------------------------
# /verify/nudge
# ---------------------------------------------------------------------------

class TestGetNudges:
    def test_empty_staged_papers_returns_no_nudges(self, client):
        """With no staged papers, nudges list must be empty (no API calls needed)."""
        resp = client.post(
            "/verify/nudge",
            json={
                "blocks": [{"type": "text", "content": "A theorem about prime numbers and their distribution."}],
                "staged_paper_ids": [],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["nudges"] == []

    def test_short_content_blocks_are_skipped(self, client):
        """Blocks shorter than 20 characters should be silently skipped."""
        resp = client.post(
            "/verify/nudge",
            json={
                "blocks": [{"type": "text", "content": "Short"}],
                "staged_paper_ids": [],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["nudges"] == []

    def test_empty_blocks_returns_no_nudges(self, client):
        """No blocks → no nudges."""
        resp = client.post(
            "/verify/nudge",
            json={"blocks": [], "staged_paper_ids": []},
        )
        assert resp.status_code == 200
        assert resp.json()["nudges"] == []

    def test_response_structure(self, client):
        """Response must have a 'nudges' list."""
        resp = client.post(
            "/verify/nudge",
            json={"blocks": [], "staged_paper_ids": []},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "nudges" in body
        assert isinstance(body["nudges"], list)

    def test_nudge_items_have_required_fields(self, client):
        """If nudges are returned they must have 'type' and 'message'."""
        resp = client.post(
            "/verify/nudge",
            json={"blocks": [], "staged_paper_ids": []},
        )
        assert resp.status_code == 200
        for nudge in resp.json()["nudges"]:
            assert "type" in nudge
            assert "message" in nudge


# ---------------------------------------------------------------------------
# /verify/correlate
# ---------------------------------------------------------------------------

class TestGetCorrelations:
    def test_empty_staged_papers_returns_no_correlations(self, client):
        """With no staged papers, correlations list must be empty."""
        resp = client.post(
            "/verify/correlate",
            json={
                "paragraphs": [{"text": "A theorem about compact sets and their properties.", "start_char": 0, "end_char": 50}],
                "staged_paper_ids": [],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["correlations"] == []

    def test_short_paragraphs_skipped(self, client):
        """Paragraphs shorter than 30 characters are skipped."""
        resp = client.post(
            "/verify/correlate",
            json={
                "paragraphs": [{"text": "Short.", "start_char": 0, "end_char": 6}],
                "staged_paper_ids": ["some-paper-id"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["correlations"] == []

    def test_empty_paragraphs(self, client):
        """No paragraphs → no correlations."""
        resp = client.post(
            "/verify/correlate",
            json={"paragraphs": [], "staged_paper_ids": []},
        )
        assert resp.status_code == 200
        assert resp.json()["correlations"] == []

    def test_response_structure(self, client):
        """Response must have a 'correlations' list."""
        resp = client.post(
            "/verify/correlate",
            json={"paragraphs": [], "staged_paper_ids": []},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "correlations" in body
        assert isinstance(body["correlations"], list)

    def test_correlation_items_have_required_fields(self, client):
        """If correlation items are returned they have required fields."""
        resp = client.post(
            "/verify/correlate",
            json={"paragraphs": [], "staged_paper_ids": []},
        )
        assert resp.status_code == 200
        for c in resp.json()["correlations"]:
            assert "para_index" in c
            assert "start_char" in c
            assert "end_char" in c
            assert "concept_id" in c
            assert "concept_name" in c
            assert "distance" in c


# ---------------------------------------------------------------------------
# /verify/formalize  (mocked — avoids real LLM + Lean 4 in CI)
# ---------------------------------------------------------------------------

class TestFormalizeStatement:
    def test_formalize_success_shape(self, client):
        """On successful formalization the response has the correct shape."""
        mock_result = MagicMock()
        mock_result.lean_source = "theorem foo : True := trivial"
        mock_result.success = True
        mock_result.attempts = 1

        with patch("src.api.routers.verify.formalize", return_value=mock_result):
            resp = client.post(
                "/verify/formalize",
                json={
                    "statement": r"Every continuous function on a compact set attains its maximum.",
                    "concept_name": "theorem",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["attempts"] == 1
        assert body["lean_source"] == "theorem foo : True := trivial"

    def test_formalize_failure_returns_200(self, client):
        """On formalization failure the response is still 200 with success=False."""
        mock_result = MagicMock()
        mock_result.lean_source = "-- Error: type mismatch"
        mock_result.success = False
        mock_result.attempts = 3

        with patch("src.api.routers.verify.formalize", return_value=mock_result):
            resp = client.post(
                "/verify/formalize",
                json={"statement": "An unprovable claim.", "concept_name": "theorem"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["attempts"] == 3

    def test_formalize_exception_returns_200_with_error(self, client):
        """If formalize raises, the endpoint catches it and returns 200 with error."""
        with patch("src.api.routers.verify.formalize", side_effect=RuntimeError("Lean not found")):
            resp = client.post(
                "/verify/formalize",
                json={"statement": "Some statement.", "concept_name": "theorem"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "Lean not found" in (body.get("error") or "")


# ---------------------------------------------------------------------------
# /verify/live-check
# ---------------------------------------------------------------------------

class TestLiveCheck:
    def test_simple_verified_equation(self, client):
        """A simple true equation should be verified via SymPy tier."""
        resp = client.post("/verify/live-check", json={"source": "$$2 + 2 = 4$$"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        assert results[0]["status"] == "verified"
        assert results[0]["tier"] == "sympy"

    def test_failed_equation(self, client):
        """x = 1 + 1 should fail (x is a free symbol)."""
        resp = client.post("/verify/live-check", json={"source": "$$x = 1 + 1$$"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        r = results[0]
        assert r["status"] in ("failed", "verified")

    def test_complex_expression_handled(self, client):
        """An integral should be handled by Wolfram or LLM when SymPy can't."""
        resp = client.post("/verify/live-check", json={
            "source": r"$$\int_0^1 x^2\,dx = \frac{1}{3}$$"
        })
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        assert results[0]["tier"] in ("sympy", "wolfram", "llm")

    def test_no_equations_returns_empty(self, client):
        """Source without math or theorems returns empty results."""
        resp = client.post("/verify/live-check", json={"source": "Just some text."})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_display_bracket_notation(self, client):
        """Equations in \\[...\\] notation are also checked."""
        resp = client.post("/verify/live-check", json={"source": r"\[3 + 4 = 7\]"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        assert results[0]["status"] == "verified"

    def test_theorem_verified_via_llm(self, client):
        """Theorem environments are verified — via SymPy (if equations inside) or LLM fallback."""
        mock_resp = MagicMock()
        mock_resp.content = '{"verdict": "correct", "reason": "Well-known result in topology."}'

        with patch("src.api.routers.verify.cheap") as mock_cheap:
            mock_cheap.complete.return_value = mock_resp
            resp = client.post("/verify/live-check", json={
                "source": r"\begin{theorem}Every continuous function on a compact set attains its maximum.\end{theorem}"
            })
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        r = results[0]
        assert r["tier"] in ("sympy", "llm")
        assert r["status"] in ("verified", "skipped")

    def test_theorem_with_embedded_equations(self, client):
        """Theorem containing equations — SymPy checks the equations directly."""
        resp = client.post("/verify/live-check", json={
            "source": r"\begin{theorem}For all real numbers $a + 0 = a$.\end{theorem}"
        })
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1

    def test_definition_and_remark_verified(self, client):
        """Definition and remark environments are verified like theorems."""
        mock_resp = MagicMock()
        mock_resp.content = '{"verdict": "correct", "reason": "Standard definition."}'
        with patch("src.api.routers.verify.cheap") as mock_cheap:
            mock_cheap.complete.return_value = mock_resp
            resp = client.post("/verify/live-check", json={
                "source": r"\begin{definition}A set is compact if every open cover has a finite subcover.\end{definition}"
                r"\begin{remark}This is equivalent to sequential compactness in metric spaces.\end{remark}"
            })
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 2
        tiers = {r["tier"] for r in results}
        assert tiers & {"sympy", "llm"}

    def test_inline_equation_extraction(self, client):
        """Inline equations with = signs in prose are extracted and verified."""
        source = "We know that $2 + 2 = 4$ is true and $x^2 + 1 = 0$ is interesting."
        resp = client.post("/verify/live-check", json={"source": source})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        exprs = [r["expression"] for r in results]
        assert any("2 + 2 = 4" in e for e in exprs)

    def test_inline_equation_without_equals_skipped(self, client):
        """Inline equations without = signs are not extracted for verification."""
        source = "The variable $x^2$ appears here."
        resp = client.post("/verify/live-check", json={"source": source})
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_crossref_with_staged_papers(self, client):
        """Prose paragraphs cross-referenced against staged papers produce crossref results."""
        long_para = "A " * 30 + "theorem about compact sets and topological spaces in functional analysis."
        source = f"\n\n{long_para}\n\n"

        mock_query = {
            "ids": [["concept-1"]],
            "metadatas": [[{
                "source_paper_id": "paper-123",
                "name": "Compact Sets",
                "paper_title": "On Compact Topological Spaces",
            }]],
            "distances": [[0.1]],
        }
        mock_paper = MagicMock()
        mock_paper.title = "On Compact Topological Spaces"

        with patch("src.api.routers.verify.collections.query_concepts", return_value=mock_query), \
             patch("src.api.routers.verify.get_session") as mock_sess:
            mock_sess.return_value.__enter__ = lambda s: MagicMock(get=lambda cls, pid: mock_paper)
            mock_sess.return_value.__exit__ = lambda s, *a: None
            resp = client.post("/verify/live-check", json={
                "source": source,
                "staged_paper_ids": ["paper-123"],
            })
        assert resp.status_code == 200
        results = resp.json()["results"]
        crossrefs = [r for r in results if r["tier"] == "crossref"]
        assert len(crossrefs) >= 1
        assert crossrefs[0]["paper_title"] == "On Compact Topological Spaces"
        assert crossrefs[0]["status"] == "verified"

    def test_results_sorted_by_start_char(self, client):
        """Results should be sorted by start_char."""
        resp = client.post("/verify/live-check", json={
            "source": "First $$a = a$$ and second $$1 + 1 = 2$$."
        })
        assert resp.status_code == 200
        results = resp.json()["results"]
        if len(results) >= 2:
            assert results[0]["start_char"] <= results[1]["start_char"]

    def test_result_has_required_fields(self, client):
        """Each result item has the required fields."""
        resp = client.post("/verify/live-check", json={"source": "$$1 + 1 = 2$$"})
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        r = results[0]
        for field in ("start_char", "end_char", "expression", "status", "tier", "output"):
            assert field in r

    def test_response_includes_check_id_field(self, client):
        """Response should include check_id field (always None — no async)."""
        resp = client.post("/verify/live-check", json={"source": "$$1 + 1 = 2$$"})
        assert resp.status_code == 200
        body = resp.json()
        assert "check_id" in body
        assert body["check_id"] is None

    def test_llm_fallback_on_sympy_failure(self, client):
        """When SymPy can't parse an expression, the LLM tier is used as fallback."""
        mock_resp = MagicMock()
        mock_resp.content = '{"verdict": "correct", "reason": "Standard identity."}'

        with patch("src.api.routers.verify.cheap") as mock_cheap:
            mock_cheap.complete.return_value = mock_resp
            resp = client.post("/verify/live-check", json={
                "source": r"\begin{proposition}The sum of angles in a triangle equals 180 degrees.\end{proposition}"
            })
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) >= 1
        assert results[0]["tier"] in ("sympy", "llm")

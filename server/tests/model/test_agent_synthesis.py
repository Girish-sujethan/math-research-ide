"""Tests for agent_synthesis: build_agent_prompt, parse_report_and_note (no LLM)."""

import pytest

from src.model.graphs.agent_synthesis import build_agent_prompt, parse_report_and_note


class TestBuildAgentPrompt:
    def test_no_staged_papers(self):
        system, user = build_agent_prompt("What is convergence?", [], "")
        assert "mathematical research assistant" in system
        assert "DOCUMENT_CONTENT" in system and "HEAVEN_NOTE" in system
        assert "REASONING" in system
        assert "No papers are currently staged" in user
        assert "Research query: What is convergence?" in user

    def test_with_staged_papers(self):
        papers = [
            {"title": "Analysis 101", "abstract": "Intro to analysis.", "concepts": [{"name": "limit"}]},
        ]
        system, user = build_agent_prompt("Define limit", papers, "")
        assert "STAGED PAPERS" in user
        assert "Analysis 101" in user
        assert "limit" in user
        assert "Research query: Define limit" in user

    def test_canvas_summary_included(self):
        system, user = build_agent_prompt("Continue", [], "We have defined $x$.")
        assert "CURRENT DOCUMENT" in user
        assert "We have defined $x$." in user

    def test_latex_instructions_in_system(self):
        system, _ = build_agent_prompt("test", [], "")
        assert "\\section{}" in system
        assert "\\begin{theorem}" in system
        assert "Python visualization" in system or "Python" in system

    def test_reasoning_section_in_system(self):
        system, _ = build_agent_prompt("test", [], "")
        assert "REASONING:" in system
        assert "step-by-step" in system


class TestParseReportAndNote:
    def test_parses_all_three_sections(self):
        raw = (
            "REASONING:\nI will prove this using contradiction.\n\n"
            "DOCUMENT_CONTENT:\n\n$$a^2 + b^2$$\n\n"
            "HEAVEN_NOTE:\nBased on Paper X."
        )
        reasoning, report, note = parse_report_and_note(raw)
        assert "contradiction" in reasoning
        assert "$$a^2 + b^2$$" in report
        assert note == "Based on Paper X."

    def test_parses_document_and_note_without_reasoning(self):
        raw = "DOCUMENT_CONTENT:\n\n$$a^2 + b^2$$\n\nHEAVEN_NOTE:\nBased on Paper X."
        reasoning, report, note = parse_report_and_note(raw)
        assert "$$a^2 + b^2$$" in report
        assert note == "Based on Paper X."
        assert reasoning == ""

    def test_missing_sections_short_raw_yields_empty_report(self):
        raw = "Just some text without section headers."
        reasoning, report, note = parse_report_and_note(raw)
        assert report == ""
        assert "Content generated" in note

    def test_missing_sections_long_raw_used_as_report(self):
        raw = "Abel proved that there is no general formula for polynomials of degree five or higher using radicals."
        reasoning, report, note = parse_report_and_note(raw)
        assert "Abel" in report
        assert "Content generated" in note

    def test_empty_note_uses_default(self):
        raw = "DOCUMENT_CONTENT:\n\nx=1\n\nHEAVEN_NOTE:\n"
        reasoning, report, note = parse_report_and_note(raw)
        assert report.strip() == "x=1"
        assert "Content generated" in note

    def test_empty_document_content_between_headers_uses_fallback(self):
        raw = "DOCUMENT_CONTENT:\n\n\nHEAVEN_NOTE:\nUsed model knowledge."
        reasoning, report, note = parse_report_and_note(raw)
        assert note == "Used model knowledge."

    def test_case_insensitive_headers(self):
        raw = "document_content:\n\nHello world of math.\n\nheaven_note:\nOk."
        reasoning, report, note = parse_report_and_note(raw)
        assert "Hello world of math" in report
        assert note == "Ok."

    def test_markdown_heading_headers(self):
        raw = "## DOCUMENT_CONTENT\n\nTheorem: $a+b=c$.\n\n## HEAVEN_NOTE\nBased on paper."
        reasoning, report, note = parse_report_and_note(raw)
        assert "Theorem" in report
        assert "Based on paper" in note

    def test_bold_headers(self):
        raw = "**DOCUMENT_CONTENT:**\n\nProof of the theorem.\n\n**HEAVEN_NOTE:**\nDone."
        reasoning, report, note = parse_report_and_note(raw)
        assert "Proof of the theorem" in report
        assert "Done" in note

    def test_no_headers_raw_used_as_report(self):
        raw = (
            "Abel's impossibility theorem states that there is no general algebraic solution "
            "to polynomial equations of degree five or higher."
        )
        reasoning, report, note = parse_report_and_note(raw)
        assert "Abel" in report
        assert "Content generated" in note

    def test_only_heaven_note_header_present(self):
        raw = "The quintic cannot be solved by radicals.\n\nHEAVEN_NOTE:\nUsed Galois theory."
        reasoning, report, note = parse_report_and_note(raw)
        assert "quintic" in report
        assert "Galois theory" in note

    def test_heaven_note_with_space_variant(self):
        raw = "DOCUMENT CONTENT:\n\nContent here.\n\nHEAVEN NOTE:\nNote here."
        reasoning, report, note = parse_report_and_note(raw)
        assert "Content here" in report
        assert "Note here" in note

    def test_reasoning_extracted_separately(self):
        raw = (
            "REASONING:\n"
            "The user wants a proof of irrationality of sqrt(2). "
            "I will use proof by contradiction. No visualization needed.\n\n"
            "DOCUMENT_CONTENT:\n"
            "\\section{Irrationality of $\\sqrt{2}$}\n\n"
            "\\begin{theorem}\n$\\sqrt{2}$ is irrational.\n\\end{theorem}\n\n"
            "HEAVEN_NOTE:\nGenerated from model knowledge."
        )
        reasoning, report, note = parse_report_and_note(raw)
        assert "proof by contradiction" in reasoning
        assert "No visualization" in reasoning
        assert "\\section{" in report
        assert "\\begin{theorem}" in report
        assert "Generated from model" in note

    def test_latex_content_preserved(self):
        raw = (
            "DOCUMENT_CONTENT:\n"
            "\\section{Main Result}\n\n"
            "\\begin{theorem}\nLet $f: \\mathbb{R} \\to \\mathbb{R}$.\n\\end{theorem}\n\n"
            "\\begin{proof}\nBy contradiction.\n\\end{proof}\n\n"
            "HEAVEN_NOTE:\nDone."
        )
        reasoning, report, note = parse_report_and_note(raw)
        assert "\\section{Main Result}" in report
        assert "\\begin{theorem}" in report
        assert "\\begin{proof}" in report
        assert "\\mathbb{R}" in report

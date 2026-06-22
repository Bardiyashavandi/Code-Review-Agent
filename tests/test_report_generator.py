"""
tests/test_report_generator.py
--------------------------------
Tests for report_generator.py's Markdown rendering.

Run with:
    pytest tests/test_report_generator.py -v
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from report_generator import generate_markdown_report, write_report


def make_issue(path="a.py", line=1, severity="HIGH", title="t", description="d",
               suggested_fix="f", rule_id=None) -> SimpleNamespace:
    return SimpleNamespace(path=path, line=line, severity=severity, title=title,
                            description=description, suggested_fix=suggested_fix,
                            rule_id=rule_id)


def make_result(issues=None, stage_errors=None, findings_count=0, skipped=None,
                 truncated=False, summary="All good.", model="gemini-2.5-flash"):
    fetch = SimpleNamespace(files=[SimpleNamespace(path="a.py", content="x=1")], truncated=truncated)
    findings = [SimpleNamespace(path="a.py", rule_id=f"r{i}", severity="WARNING",
                                 line_start=1, message="m") for i in range(findings_count)]
    scan = SimpleNamespace(findings=findings, scanned=1, skipped=skipped or [], duration_s=0.1)
    review = SimpleNamespace(issues=issues or [], summary=summary, model=model,
                              files_reviewed=1, duration_s=0.1)
    return SimpleNamespace(
        repo_url="https://github.com/owner/repo",
        fetch_result=fetch,
        scan_report=scan,
        review_report=review,
        stage_errors=stage_errors or [],
        duration_s=0.5,
    )


class TestMarkdownGeneration:

    def test_header_contains_repo_url(self):
        text = generate_markdown_report(make_result())
        assert "https://github.com/owner/repo" in text

    def test_no_issues_renders_placeholder(self):
        text = generate_markdown_report(make_result(issues=[]))
        assert "No issues found." in text

    def test_issues_grouped_by_severity_order(self):
        issues = [
            make_issue(severity="LOW", title="low issue"),
            make_issue(severity="CRITICAL", title="critical issue"),
            make_issue(severity="MEDIUM", title="medium issue"),
        ]
        text = generate_markdown_report(make_result(issues=issues))
        assert text.index("### CRITICAL") < text.index("### MEDIUM") < text.index("### LOW")

    def test_stage_errors_section_omitted_when_empty(self):
        text = generate_markdown_report(make_result(stage_errors=[]))
        assert "Stage Errors" not in text

    def test_stage_errors_section_present_when_nonempty(self):
        err = SimpleNamespace(stage="scan", message="semgrep not installed")
        text = generate_markdown_report(make_result(stage_errors=[err]))
        assert "Stage Errors" in text
        assert "semgrep not installed" in text

    def test_malicious_title_is_escaped(self):
        issue = make_issue(title="<script>alert(1)</script>")
        text = generate_markdown_report(make_result(issues=[issue]))
        assert "<script>" not in text
        assert "&lt;script&gt;" in text


class TestWriteReport:

    def test_write_report_creates_file(self, tmp_path):
        out = tmp_path / "report.md"
        path = write_report(make_result(), str(out))
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "https://github.com/owner/repo" in content

    def test_write_report_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "nested" / "dir" / "report.md"
        path = write_report(make_result(), str(out))
        assert os.path.exists(path)

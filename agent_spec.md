# Spec: `agent` Module (Orchestrator)

**Project:** AI Code Review Agent
**Module:** `agent.py`
**Version:** 1.0
**Status:** Draft

---

## 1. Purpose

Wire `github_fetcher`, `semgrep_runner`, and `gemini_reviewer` together as a single Google ADK 2.0 agent that takes a GitHub repo URL and produces a complete `PipelineResult`. This is the module the Kaggle capstone actually demos — everything else is a library the agent calls.

---

## 2. Public Interface

```python
from agent import CodeReviewAgent

agent = CodeReviewAgent(
    github_token=os.environ["GITHUB_TOKEN"],
    gemini_api_key=os.environ["GEMINI_API_KEY"],
)
result = agent.review_repo("https://github.com/owner/repo", branch="main")
# Returns: PipelineResult
```

### `PipelineResult` (dataclass)

| Field          | Type                  | Description                                      |
|----------------|-----------------------|----------------------------------------------------|
| `repo_url`     | `str`                 | The URL that was reviewed                          |
| `fetch_result` | `FetchResult`         | Output of `github_fetcher`                         |
| `scan_report`  | `ScanReport`          | Output of `semgrep_runner`                         |
| `review_report`| `ReviewReport`        | Output of `gemini_reviewer`                         |
| `stage_errors` | `list[StageError]`    | Non-fatal errors from any stage (see 3.3)          |
| `duration_s`   | `float`               | Total wall-clock time for the full pipeline         |

### `StageError` (dataclass)

| Field   | Type  | Description                              |
|---------|-------|--------------------------------------------|
| `stage` | `str` | `"fetch"`, `"scan"`, or `"review"`          |
| `message` | `str` | Human-readable error description          |

### `CodeReviewAgent`

| Method | Signature | Returns | Description |
|--------|-----------|---------|--------------|
| `__init__` | `(github_token: str, gemini_api_key: str, semgrep_config: str = "auto")` | — | Constructs the three underlying clients; validates both tokens non-empty |
| `review_repo` | `(url: str, branch: str = "main", max_files: int = 100) → PipelineResult` | `PipelineResult` | Runs fetch → scan → review in sequence, handling partial failures per §3.3 |

### ADK Integration

The agent is also exposed as a Google ADK `Agent` (or `LlmAgent`/`FunctionTool`, per ADK 2.0 conventions) via a single tool function:

```python
def review_repo_tool(repo_url: str, branch: str = "main") -> dict:
    """ADK-callable tool wrapping CodeReviewAgent.review_repo, returning a JSON-serializable dict."""
```

This is the function registered with the ADK agent definition so the capstone demo can be driven by natural-language requests ("review https://github.com/x/y") as well as direct calls.

---

## 3. Behavior

### 3.1 Pipeline Sequence
1. `GitHubFetcher.fetch_python_files(url, branch, max_files)` → `FetchResult`.
2. `SemgrepRunner.scan(fetch_result.files)` → `ScanReport`.
3. `GeminiReviewer.review(fetch_result.files, scan_report)` → `ReviewReport`.
4. Assemble `PipelineResult`.

### 3.2 Input Validation
- `github_token` and `gemini_api_key` must be non-empty; raise `ValueError` immediately (delegates to the underlying modules' own validation, but checked here too for a fast, clear failure before any network/process work starts).
- `url` is not pre-validated here — `GitHubFetcher.parse_repo_url` is the single source of truth for URL validation; its `ValueError` propagates unchanged.

### 3.3 Partial Failure Handling
This is the key orchestration decision: a failure in `scan` or `review` should not discard the work already done in earlier stages.

- **Fetch stage fails** (e.g. `RepoNotFoundError`, `AuthenticationError`): fatal. Re-raise immediately — there is nothing to review without files.
- **Scan stage fails** (e.g. `SemgrepNotInstalledError`, `SemgrepExecutionError`): non-fatal. Record a `StageError(stage="scan", message=...)`, continue to the review stage with an empty `ScanReport(findings=[], scanned=0, skipped=[f.path for f in files])` so Gemini still reviews the code without Semgrep context.
- **Review stage fails** (e.g. `GeminiAuthenticationError`, `GeminiRateLimitError`): non-fatal from the pipeline's perspective. Record a `StageError(stage="review", message=...)`, return a `PipelineResult` with `review_report=ReviewReport(issues=[], summary="Review unavailable: <reason>", model=<model>, files_reviewed=0)`.
- This means `review_repo` only ever raises for fetch-stage failures; everything downstream degrades gracefully and is visible via `stage_errors`.

### 3.4 Logging & Observability
- Each stage logs start/end with file counts and duration at INFO.
- No secrets (`github_token`, `gemini_api_key`) are ever logged — this module passes them straight through to the underlying clients and does not touch them otherwise.
- `PipelineResult.duration_s` covers the whole pipeline; each underlying report already carries its own stage-level `duration_s` for breakdown.

### 3.5 Security
- This module performs no I/O itself beyond delegating to the three already-hardened modules — no new attack surface should be introduced here.
- The ADK tool function (`review_repo_tool`) validates that `repo_url` is a string and delegates all real validation to `GitHubFetcher.parse_repo_url`; it does not attempt its own regex/parsing duplicate logic (single source of truth).
- The ADK tool function's return dict is built from dataclasses via explicit field mapping — never `vars()`/`__dict__` dumped wholesale — so any future field added to an internal dataclass doesn't leak into the tool's output by accident.

---

## 4. Error Hierarchy

```
AgentError (base)
└── (fetch-stage errors propagate unchanged from github_fetcher;
     scan/review-stage errors are captured as StageError, not raised)
```

`AgentError` is reserved for orchestrator-level problems only (e.g. bad constructor args), not for re-wrapping the underlying modules' own exceptions.

---

## 5. Configuration

| Parameter         | Default   | Description                                    |
|--------------------|-----------|--------------------------------------------------|
| `github_token`     | required  | Passed to `GitHubFetcher`                         |
| `gemini_api_key`   | required  | Passed to `GeminiReviewer`                         |
| `semgrep_config`   | `"auto"`  | Passed to `SemgrepRunner`                           |
| `branch`           | `"main"`  | Passed through to `fetch_python_files`              |
| `max_files`        | `100`     | Passed through to `fetch_python_files`              |

---

## 6. Tests (`tests/test_agent.py`)

`GitHubFetcher`, `SemgrepRunner`, and `GeminiReviewer` are all mocked at the `agent` module level — this module's tests verify orchestration logic only, not the underlying modules (already covered by their own suites).

| Test ID | Scenario | Expected |
|---------|----------|----------|
| `test_empty_github_token_raises` | `CodeReviewAgent(github_token="", ...)` | `ValueError` |
| `test_empty_gemini_key_raises` | `CodeReviewAgent(gemini_api_key="", ...)` | `ValueError` |
| `test_happy_path_runs_all_three_stages` | All stages succeed | `PipelineResult` has all three reports populated, `stage_errors == []` |
| `test_fetch_failure_is_fatal` | `fetch_python_files` raises `RepoNotFoundError` | Propagates unchanged out of `review_repo` |
| `test_scan_failure_is_non_fatal` | `scan` raises `SemgrepExecutionError` | `PipelineResult` returned; `stage_errors` has one `stage="scan"` entry; `review` was still called |
| `test_scan_failure_falls_back_empty_report` | `scan` raises | `review` called with a `ScanReport` whose `findings == []` |
| `test_review_failure_is_non_fatal` | `review` raises `GeminiRateLimitError` | `PipelineResult` returned; `stage_errors` has one `stage="review"` entry; `review_report.issues == []` |
| `test_both_scan_and_review_fail` | Both raise | Both stage errors recorded; pipeline still returns (doesn't raise) |
| `test_pipeline_result_has_duration` | Happy path | `duration_s > 0` (or `>= 0` with mocked instant calls) |
| `test_review_repo_tool_returns_json_serializable_dict` | ADK tool function called | `json.dumps(result)` does not raise |
| `test_review_repo_tool_does_not_leak_internal_fields` | Inspect tool output keys | Only documented keys present, no stray internal attributes |
| `test_secrets_never_logged` | Run full pipeline with `caplog` | Neither token nor API key substring appears in any log record |

---

## 7. File Layout

```
code-review-agent/
├── github_fetcher.py
├── semgrep_runner.py
├── gemini_reviewer.py
├── agent.py                  ← this module
├── tests/
│   ├── test_github_fetcher.py
│   ├── test_semgrep_runner.py
│   ├── test_gemini_reviewer.py
│   └── test_agent.py
└── ...
```

---

## 8. Dependencies

```
google-adk>=2.0          # Agent framework / tool registration
```

No other new dependencies — `agent.py` only imports the three existing project modules plus ADK.

---

## 9. Out of Scope

- Multi-repo / batch review in a single call (one `review_repo` call = one repo)
- Persisting `PipelineResult` to disk (that's the report generator's job, next module)
- Async/concurrent stage execution (stages are sequential since each depends on the previous one's output)
- ADK session/memory management beyond the single tool function — conversational state is ADK's concern, not this module's

---

## 10. Acceptance Criteria

- [ ] All tests in `tests/test_agent.py` pass with `pytest -v`
- [ ] A scan or review failure never prevents `review_repo` from returning a result
- [ ] Only a fetch failure propagates as an exception
- [ ] Neither `github_token` nor `gemini_api_key` ever appears in logs
- [ ] `review_repo_tool`'s output is valid JSON via `json.dumps`
- [ ] End-to-end manual run against `https://github.com/Bardiyashavandi/Internship` completes and returns a populated `PipelineResult`

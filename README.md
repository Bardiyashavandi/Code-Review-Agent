# AI Code Review Agent

A Kaggle 5-Day AI Agents Capstone submission (track: Agents for Business). Given a GitHub repository URL, the agent fetches its Python source, runs Semgrep static analysis, and sends the code plus findings to Gemini 2.5 Flash for a structured, severity-ranked code review. The result is a Markdown report with prioritized issues and concrete fix suggestions.

## How it works

The pipeline runs in three stages, each implemented as an independent, individually-tested module: `github_fetcher.py` walks a repo's file tree via the GitHub API and pulls down every Python file (skipping virtual environments, build artifacts, and other noise); `semgrep_runner.py` writes those files into an isolated temporary sandbox and runs Semgrep against them, parsing the JSON output into typed findings; `gemini_reviewer.py` batches the files and findings into prompts and asks Gemini 2.5 Flash for a structured JSON review, retrying automatically on rate limits or transient server overload. `agent.py` orchestrates all three stages behind a single `CodeReviewAgent.review_repo()` call and also exposes the same pipeline as a Google ADK 2.0 agent tool, so a Gemini-powered ADK `Agent` can decide on its own, from a natural-language request, to call `review_repo_tool` and summarize the results. `report_generator.py` renders the final result into a Markdown report, and `main.py` is the command-line entry point that wires credentials, runs the pipeline, and writes the report to disk.

Only a fetch failure is treated as fatal, since there's nothing to review without files. A Semgrep or Gemini failure is captured as a non-fatal `StageError` instead, so the pipeline always returns a usable result — degraded, but never empty-handed.

## Setup

```bash
git clone https://github.com/Bardiyashavandi/Internship
cd code-review-agent
python3 -m pip install -r requirements.txt
pipx install semgrep
```

Semgrep is installed separately via `pipx` rather than as a normal dependency. `google-adk` and `semgrep` pin incompatible ranges of `opentelemetry-api`/`opentelemetry-sdk`, so installing both into the same environment breaks one or the other. `pipx` gives Semgrep its own isolated virtual environment; `semgrep_runner.py` only ever shells out to the `semgrep` binary on `PATH`, so this isolation is invisible to the rest of the project.

Create a `.env` file in the project root with:

```
GITHUB_TOKEN=ghp_your_token_here
GEMINI_API_KEY=your_gemini_key_here
```

Neither key is ever logged, printed, or embedded in an exception message — this is enforced by `test_secrets_never_logged` in the test suite. Note that `load_dotenv()` never overrides a variable already exported in your shell, so if you've previously exported a `GEMINI_API_KEY` or `GITHUB_TOKEN` for testing, that stale value will silently win over `.env`. Run `echo $GEMINI_API_KEY` if authentication fails unexpectedly.

## Usage

```bash
python3 main.py https://github.com/owner/repo --branch main --out review_report.md -v
```

This prints a one-line summary (files fetched, Semgrep findings, review issues, any stage errors) and writes the full report to the path given by `--out`. `--max-files` caps how many Python files are reviewed for very large repositories.

To use the agent programmatically:

```python
import os
from agent import CodeReviewAgent

agent = CodeReviewAgent(
    github_token=os.environ["GITHUB_TOKEN"],
    gemini_api_key=os.environ["GEMINI_API_KEY"],
)
result = agent.review_repo("https://github.com/owner/repo")
for issue in result.review_report.issues:
    print(issue.severity, issue.path, issue.title)
```

To run it as a Google ADK agent that decides for itself when to invoke the review tool:

```python
from agent import build_adk_agent

adk_agent = build_adk_agent(
    github_token=os.environ["GITHUB_TOKEN"],
    gemini_api_key=os.environ["GEMINI_API_KEY"],
)
```

`adk_agent` can then be run through any ADK `Runner` (e.g. `google.adk.runners.InMemoryRunner`). Given a prompt like "review https://github.com/owner/repo and summarize the top issues," the model calls `review_repo_tool` itself, with no manual function dispatch required — this was verified directly against this project's own repository, with the model correctly invoking the tool, receiving structured results, and prioritizing the summary by severity.

## Testing

```bash
pytest -v
```

83 tests cover all five modules. Every external dependency — GitHub's API, the Semgrep subprocess, and the Gemini SDK — is mocked, so the suite runs in about a second with no network access or real credentials required. Tests specifically cover: path-traversal and config-injection rejection in the Semgrep runner; that a malicious or injected title/description from Semgrep or Gemini output is escaped before reaching the report and never evaluated as code; that authentication errors never leak the API key into a log line or exception message; and that a real macOS quirk (the system temp directory living behind a symlink) doesn't crash the scan — a bug this project's own end-to-end run against a real repository caught and fixed.

## Security notes

All subprocess calls (`semgrep`) use explicit argument lists, never `shell=True`. File paths from a fetched repository are validated against path traversal before being written into the Semgrep sandbox. Semgrep's `--config` argument is allow-listed by regex to prevent argument injection. Gemini's system prompt explicitly instructs the model to treat all file contents and Semgrep messages as untrusted data, not as instructions — code (or a malicious commit) embedding "ignore previous instructions" text cannot redirect the review. No credentials are ever hardcoded; both API keys are read from the environment only.

## What this demonstrates

This project was built end-to-end as a spec-driven exercise: each module started as a written specification (interface, behavior, error hierarchy, and a test table) before any implementation code was written, mirroring how a production team would scope work before building it. The orchestrator in `agent.py` is exposed as a real Google ADK 2.0 tool, with the agent runtime itself (not hand-written glue code) deciding when to invoke the review pipeline based on a natural-language request — verified against this repository's actual GitHub source. Building this also surfaced and required fixing several real integration issues rather than synthetic ones: a Python dependency conflict between `google-adk` and `semgrep` over `opentelemetry` versions (resolved via `pipx` isolation), a stale exported environment variable silently shadowing a working API key, and a macOS-specific symlink-resolution bug in the Semgrep sandboxing logic that only appeared under a real filesystem, not in mocked tests.

## Known limitations

`--config auto` for Semgrep requires reaching `semgrep.dev`'s rule registry over the network; environments with restrictive egress (locked-down CI runners, some sandboxes) will need a local or registry-pinned ruleset instead. Gemini occasionally returns a transient `503 Service Unavailable` under high demand; `gemini_reviewer.py` retries this automatically up to three times with exponential backoff, but a sustained outage will still surface as a non-fatal `StageError` rather than blocking the whole pipeline.

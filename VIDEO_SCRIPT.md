# Video script — AI Code Review Agent (target: 4:30, hard cap 5:00)

Recording notes: screen-record your terminal + editor/browser as needed. Talk over it live rather than scripting word-for-word — the timings below are budgets, not a teleprompter. Run `main.py` for real during the recording; don't fake the output.

---

## 0:00–0:30 — The hook (face-to-camera or voiceover over a slide)

"Code review doesn't scale with how fast teams ship. Static analyzers like Semgrep catch real bugs but their output is rule-ID jargon nobody wants to read. Ask an LLM to 'review my code' with no grounding and you get plausible-sounding nonsense, because it's reviewing a paste, not your actual repo. I built an agent that closes that gap: give it a GitHub URL, it fetches the real code, runs real static analysis, and asks Gemini to turn both into a prioritized review a human can act on."

**On screen:** title card — "AI Code Review Agent" / Agents for Business track.

---

## 0:30–1:15 — Architecture walkthrough

Show the architecture diagram from the README (or screen-share `agent.py` briefly).

"Three stages, each its own tested module. `github_fetcher` pulls every Python file from the repo via the GitHub API. `semgrep_runner` writes those files into an isolated sandbox and runs Semgrep — that's the deterministic, ground-truth half. `gemini_reviewer` takes the source plus the Semgrep findings and asks Gemini 2.5 Flash for a structured, severity-ranked review — that's the judgment half. `agent.py` wires all three together, and `report_generator` writes the final Markdown report."

"Only a fetch failure is fatal — there's nothing to review without files. If Semgrep or Gemini has a bad day, the pipeline degrades gracefully instead of crashing, which mattered in practice: Gemini occasionally throws a transient 503 under load, and the agent retries automatically rather than giving up."

---

## 1:15–2:30 — Live demo: real end-to-end run

Run this for real, on camera:

```bash
python3 main.py https://github.com/<your-repo> --branch main --out review_report.md -v
```

While it runs (~60–90s in practice), narrate:

"This is a live run against [repo name] — not a recording, not a mock. It's fetching files from GitHub right now, running Semgrep, and sending everything to Gemini."

When it finishes, open `review_report.md` and scroll through 2–3 real findings:

"Here's a critical finding — [read one issue title and its suggested fix]. Note it's not just 'this is bad,' it's a specific fix. This run found a Flask app with debug mode left on, a hardcoded mock API key, and an endpoint trusting a client-supplied session ID — all real issues, all found by the actual pipeline doing its actual job, not staged for the demo."

---

## 2:30–3:15 — Agent / ADK tool-calling

Show (or briefly screen-record) the ADK agent being driven by natural language — e.g. a short Python REPL session:

```python
from agent import build_adk_agent
adk_agent = build_adk_agent(github_token=..., gemini_api_key=...)
# run via google.adk.runners.InMemoryRunner with prompt:
# "review https://github.com/<repo> and summarize the top issues"
```

"This is the part that makes it an agent rather than a script: I'm not calling `review_repo()` directly. I'm giving a Google ADK agent a plain-language request, and the model itself decides to call the `review_repo_tool`, with the right arguments, and turns the structured result back into a natural-language summary. I verified this against this project's own repository — the model correctly invoked the tool with no manual function dispatch in the loop."

---

## 3:15–4:00 — Security, by design

"Security wasn't bolted on after — it shaped the architecture. Every subprocess call uses explicit argument lists, never `shell=True`. File paths from a fetched repo are validated against path traversal before they ever touch disk. Semgrep's config argument is allow-listed by regex against injection. And the system prompt explicitly tells Gemini to treat all code and Semgrep output as untrusted data, not instructions — so a malicious commit can't talk its way past the review with a comment like 'ignore previous instructions.' No credentials are ever hardcoded; both API keys come from environment variables only, and I have a test that specifically asserts a key never leaks into a log line or an error message."

(Optional: flash a 2-second screen of the relevant test names in `tests/` to back this up visually.)

---

## 4:00–4:30 — Deployability + close

"The pipeline is fully stateless — one repo URL in, one report out, no persistent storage. That means it drops into a CI step, a scheduled job, or a containerized service behind a webhook with no architectural changes. Eighty-three tests pass in about a second with everything mocked, and — more importantly — I ran this against a real repo with real credentials and it found real issues, including three integration bugs in my own code that only a real run could have surfaced. Code, tests, and writeup are all linked below."

**On screen:** GitHub URL + "Agents for Business — Kaggle 5-Day AI Agents Capstone."

---

## Shot list / what to have ready before recording
- [ ] Terminal with `.env` already populated (keys hidden/never shown on screen)
- [ ] A target repo to scan live (don't reuse `review_report.md` from a previous run — actually run it fresh on camera)
- [ ] Architecture diagram open (README or a slide)
- [ ] Short ADK/`InMemoryRunner` snippet ready to paste into a REPL, not typed live (saves time)
- [ ] `tests/` directory open in editor for the 2-second security cutaway
- [ ] Final slide with GitHub link + track name

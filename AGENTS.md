# Agent setup

This is a local Python app for reading the user's own AI session archives. Follow these steps with any coding agent.

1. Get this repository into a user-chosen folder: clone the repository URL the user supplies, or use their downloaded checkout. Do not invent a remote URL. Preserve existing edits before updating.
2. Read README.md and docs/verification.md. Check Python: `python3 --version` on Mac or `py -3 --version` on Windows. Python 3.10+ and SQLite FTS5 are required. No frontend build or required package install.
3. From the repo run `python3 viewer.py` (Mac) or `py -3 viewer.py` (Windows). Give the user http://127.0.0.1:8765 and open it if browser access is available. Use `--port 8766` if occupied.
4. Review Sources with the user. Enable desired detected stores and save; nothing indexes before this step. Unsupported means found, not readable yet. Copied folders and official Claude.ai / ChatGPT export ZIPs can be added in the UI.
5. Wait for Ready and review warnings. Test with a phrase the user supplies; do not print private transcripts into logs or commit them. Tool calls should remain folded and lineage links should open related sessions.
6. For compressed archives on older Python, optional `zstandard` can be installed using that Python's `-m pip install zstandard`. Setup can download packages; the running app stays offline. Python 3.14+ needs no decoder package.
7. Stop with Ctrl-C. All generated data belongs in the per-user app-data folder described in README.md, outside the repo and source trees. Use a separate `--data-dir` for synthetic checks.

Troubleshooting: check Python and FTS5 first; choose another port for an address-in-use error; refresh during a quiet moment if a database snapshot cannot settle. Copy SQLite databases with their matching WAL or a completed backup. Source changes require Refresh. JSONL warnings may be an incomplete final record in an active session. A changed app schema needs an adapter update and a synthetic fixture, not experiments that write to the source.

For development, run the unittest suite and update docs/testing-runbook.md with the results. Keep HTML, CSS and JavaScript separate; use CSS variables for restyling. Fixtures must be synthetic. Scan staged files for credentials, personal paths and private content before committing. This repository has no fleet, agent-provider, account or cloud-service dependency.

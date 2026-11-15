# LEJ AI Session Archive Viewer

Your past AI work, in one local reading page. Find a session, read the conversation, open tool details, follow related sessions, or export Markdown. Add your own keyword tags to follow work across sessions in time order.

Works on macOS and Windows. Python 3.10 or newer with SQLite FTS5; no build step or required packages. The interface is deliberately plain and ready for a separate design pass.

## Start

Download or clone this repository to a folder of your choice. In that folder, run:

**macOS:** `python3 viewer.py`

**Windows (PowerShell or Command Prompt):** `py -3 viewer.py`

Open **http://127.0.0.1:8765**. Stop with Ctrl-C. Use `--port 8766` if the port is busy. The app does not launch a browser or contact any service.

On first run, **Sources** shows supported apps, detected locations, session counts and toggles. Nothing is indexed until you enable a source and choose **Save sources and tags**. A location is detected from files on disk, not from an assumption that an app is installed. Enable only what you want. Choose **Sessions** to read the archive. Wait for **Ready** before judging full search coverage. Refresh rebuilds the index; large archives can take several minutes. Disabling a source removes its sessions from the rebuilt index. Deleted source files disappear on refresh too.

### Set it up with your agent

Paste this into Claude Code, Codex, Cursor, or another coding agent, with this repository attached or its location supplied:

> Set up LEJ AI Session Archive Viewer from this repository: read AGENTS.md, check Python, start it locally, and give me the URL. Keep my source stores unchanged and all session data out of Git.

There is no cloud account, API key, or subscription to configure. Agents can follow [AGENTS.md](AGENTS.md).

## Sources

| Source | What the viewer reads |
| --- | --- |
| Claude Code | `.claude/projects/**/*.jsonl`, including helper files |
| Codex | Versioned `thread_history_*.sqlite` and `state_*.sqlite`; active and archived JSONL, legacy JSON, `.jsonl.zst`; `history.jsonl` |
| T3 Code | `.t3/userdata/statev2.sqlite`; messages, folded tools and parent/child links |
| OpenCode | `opencode.db`, legacy `storage/session`, `storage/message`, `storage/part` JSON, legacy database message/part and newer session_v2/session_message stores |
| Cursor | `.cursor/projects/**/*.jsonl` transcript files |
| Claude.ai / Claude desktop | Import an official export ZIP containing `conversations.json` |
| ChatGPT | Import an official export ZIP containing `conversations.json` |
| Grok CLI | `.grok/sessions/**/chat_history.jsonl`, summary metadata and folded tools |
| Gemini CLI | Detected at `.gemini`; current local format not yet supported |
| Antigravity | Detected at `.gemini/antigravity`; current local format not yet supported |
| Cursor app store | Detected separately in app support; database format not yet supported |

OpenCode's legacy `storage/` JSON reader is covered by synthetic tests; this Mac's storage folder contains only session diffs, so real transcript verification used its database. Detection of an unsupported source does not claim a transcript count. Cloud apps have no supported local transcript store; use **Import data export** even if their desktop app is installed.

**OpenRouter is an API, with no local session store.** Its traffic appears under whichever app called it.

Codex database items take precedence over rollouts with the same native session ID. State databases provide titles, dates, models and lineage; turn metadata alone does not suppress a file transcript. Realtime items merge with regular items by item ID. If several history versions contain a thread, the highest numeric version wins. Typed prompt history is one extra searchable transcript and can repeat prompts. Different apps can record the same work; the viewer keeps their source records separate. Counts describe records, not unique human conversations.

Compressed Codex archives work with Python 3.14's standard `compression.zstd`, the optional well-known `zstandard` package, or a `zstd` executable already on PATH. On earlier Python, install optional support with `python3 -m pip install zstandard` (Mac) or `py -3 -m pip install zstandard` (Windows). Setup may use the internet; the running viewer does not. Without a decoder, affected files produce a visible warning.

## Read and organize

Search words or a phrase across messages and tool details. Filter by source, project folder, dates or tag. Tool calls stay folded. Text is displayed as text, including HTML found in a session. Images and attachments are omitted; nothing is fetched. Open a parent or child link when the source supplies one.

In Sources, edit the tag rules as JSON, for example:

```json
{"garden": ["garden planner", "seed calendar"], "learning": ["practice exercise"]}
```

A session matches when any keyword appears as whole words, ignoring case and allowing flexible spaces. Matches include its title, project and transcript. Save to rebuild. Select a tag and **Chain: oldest first** to read its sessions in time order. Export one session or the whole tag chain as Markdown. Chain export includes every session with that tag, regardless of the current filters.

Tag rules and source toggles also live in `config.json` in the app-data folder below. Stop the viewer before editing that file, then restart and refresh. No rules come bundled with personal or client names.

## Copied folders and Windows paths

Choose **Add a folder**, select the format and enter the full local path. Claude accepts either a `.claude` root or its `projects` folder. Codex expects the `.codex` root containing databases and `sessions` / `archived_sessions`. OpenCode expects its data root containing `opencode.db`. Cursor accepts its `.cursor` root or `projects`. T3 expects the full database path. Save to scan and index. Multiple roots can be enabled together.

Default homes use the current account. Windows probes `%USERPROFILE%\.claude`, `%USERPROFILE%\.codex`, `%USERPROFILE%\.t3`, `%USERPROFILE%\.cursor`, and app data under `%APPDATA%` / `%LOCALAPPDATA%`. OpenCode also probes its XDG-style `.local/share/opencode` root. macOS probes home dot-folders, `.local/share/opencode` and `Library/Application Support/Cursor`. Linux paths are resolved too, but launch verification targets Mac and Windows.

WSL homes are optional extra roots: add a copied WSL folder, or an accessible `\\wsl.localhost\DISTRO\home\USER\.codex` path. The viewer does not start WSL or search other user accounts. Project paths from another OS remain labels; those projects need not exist locally.

For copied SQLite data, use a completed SQLite backup or copy the database and its matching `-wal` file while the app is stopped. A database copied alone from a running app can miss recent messages.

## Private by default

- Reads source stores without editing them. Live SQLite databases are never opened through SQLite: a stable database/WAL pair is copied by ordinary file reads. Only that private copy is recovered; transcript reads use SQLite `mode=ro&immutable=1`. This takes no SQLite lock on a live store, so apps can stay running.
- Binds only to **127.0.0.1**. Rejects foreign Host headers and cross-origin writes. No telemetry, network calls, CDN, external fonts, or remote assets. All HTML, CSS and JavaScript ship in this repo.
- Indexes, database snapshots, configuration and imported export JSON live in per-user app data, never the repository: macOS `~/Library/Application Support/lej-ai-session-archive-viewer`; Windows `%LOCALAPPDATA%\lej-ai-session-archive-viewer`; Linux `$XDG_DATA_HOME/lej-ai-session-archive-viewer` (default `~/.local/share`). Override with `--data-dir` pointing outside the checkout and source folders.

The private index contains your conversations and may contain secrets from them. Keep app data on an encrypted disk and out of shared folders. Disabling a source removes it from search on refresh; snapshots and imported originals remain in app data until you remove that folder with the viewer stopped. Markdown exports contain tool details too. The viewer is not a secret-redaction tool. Other programs running under your account can read local data.

## Troubleshoot

Check `python3 --version` or `py -3 --version`. Install Python from python.org if missing. A missing FTS5 error means your Python SQLite build needs replacing with one that includes FTS5. A missing source is skipped. Unsupported formats show their status rather than an invented count.

If a database keeps changing during copying, refresh during a quiet moment. Partial JSONL lines are skipped with a warning. Schemas can change; report the app/version and table or field names without attaching private transcripts. Refresh errors appear in the status bar; a failed adapter can leave partial results until the next successful refresh. Refresh currently rebuilds enabled sources rather than incrementally updating them. Allow several GB for large archives and snapshots.

Official export import is local: enter the full ZIP path in Sources. Nothing is uploaded and ZIP members are never extracted. The importer reads only `conversations.json` (up to 512 MB uncompressed). ChatGPT alternate branches are included once each in timestamp order. Attachments are not imported. Reimporting an identical ZIP does not duplicate it; conversation IDs keep updated exports from duplicating sessions.

## Development and license

Run `python3 -m unittest discover -s tests -v` (Mac) or `py -3 -m unittest discover -s tests -v` (Windows). CI includes both OSes. [Verification](docs/verification.md) records local results and limits; [test runbook](docs/testing-runbook.md) explains retesting. HTML, CSS and JS are separated in `static/`; colors and fonts have CSS variables.

MIT, copyright Limited Edition Jonathan. See [LICENSE](LICENSE).

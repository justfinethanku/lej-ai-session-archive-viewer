# Test runbook

## Synthetic regression and local HTTP

Status: tested on macOS with Python 3.14. No account needed.

From the repository run `python3 -m unittest discover -s tests -v`; on Windows use `py -3 -m unittest discover -s tests -v`. The suite creates made-up stores and official-export-shaped ZIPs in temporary folders, starts an ephemeral loopback HTTP server, and removes its data afterward. It does not use real sources or network services. No fixture downloads or credentials are needed.

Coverage: Windows and Mac/Linux paths; Claude blocks/tags/search/source removal; Codex database precedence/realtime/state lineage/legacy/history; T3 lineage and folded tools; both OpenCode database schemas and legacy JSON storage; Cursor; Grok; both cloud imports and reimport; invalid ZIPs; transcript pagination and Markdown; stable live-WAL snapshot with unchanged source signatures and read-only copied DB; database copies expired after refresh and after a source check, unrelated look-alike files in app data left alone, a failed delete retried at the next cleanup, and no staging folder left after a copy error; repository/cache collision rejection; unsupported detection; bundled asset/API routes, including fonts, the font-src policy and 404s for anything outside the shipped static files; forbidden foreign writes; valid same-origin configuration.

Compressed-archive coverage uses Python 3.14 compression.zstd or a local zstd executable. That case skips on older Python without an encoder. CI uses macos-latest and windows-latest with Python 3.10 and 3.14. CI is included but has not been run remotely. JavaScript syntax check: `node --check static/app.js` when Node is available; Node is not required to run the app.

Safe actions: run this suite and inspect synthetic exports. For a manual UI pass, use `--data-dir` pointing to a fresh temporary folder outside the checkout, add only made-up stores, enable and save. Check Sources, tag editing, source toggles, search, filters, folded tools, lineage, pagination, import and download. UI controls have stable IDs in static/index.html. The quickest synthetic setup is `python3 tools/demo.py` (port 8799; add `--first-run` for a new install's first screen). It builds a pretend home folder with every supported app, a parent and two child T3 threads, two tags, an unsupported folder, and two export ZIPs to import.

Real-store testing is read-only on originals but creates private snapshots and an index. Do not commit those files, exports, screenshots, actual transcripts or full source paths. Stop the viewer before deleting its chosen test data folder. No source cleanup or configuration changes are part of testing. Ordinary launch on an existing configured archive can expose its contents locally.

## Interface pass in a browser

Status: tested November 15, 2026 on macOS in headless Chrome, against tools/demo.py data. No account needed.

Checked: first run lands on Sources with everything off; turning sources on shows the save bar; Save and index moves to Sessions and the status shows progress; a tag with no keywords is refused with a plain message; Add a folder strips pasted quotes and shows a pending row; Discard restores the saved state; import succeeds with the demo ZIP and shows a plain error for a missing file; search marks matches and Next match walks them; tool steps fold and open; parent and child links open each other; the folder filter narrows by typing; `/`, `J`, `K`, arrow keys and Enter work; light and dark schemes; widths of 1440, 1100 and 420 px. The page made no request to any other host, and the console stayed free of errors apart from the expected 400 for the bad import.

Also opened once against the real local index, read-only, to check speed and real tool-record shapes (list in under 0.1 s, phrase search over about 10,400 sessions in about 0.4 s, checking sources about 6 s). Nothing from that run was saved to the repository.

Not checked: Windows, Safari and Firefox, and a screen reader. The first-index progress display was checked with a simulated status feed, not timed on a real first run.

## Privacy scan before a public commit

Status: tested; see verification.md.

Scan every repository file, excluding Git internals and ignored bytecode. Check personal home paths, emails, API token prefixes and private/client names, including names from any private predecessor configuration. Do not copy the private name list into this repository or print matched secrets. Review every at-sign match: Python decorators, CSS media queries and GitHub Action version refs are expected. Review staged file names and sizes, confirm all test data is synthetic, inspect the root commit, verify no remotes, and check that caches/indexes/exports are absent. A scan is evidence, not a guarantee of secret redaction.

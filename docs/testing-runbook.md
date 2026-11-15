# Test runbook

## Synthetic regression and local HTTP

Status: tested on macOS with Python 3.14. No account needed.

From the repository run `python3 -m unittest discover -s tests -v`; on Windows use `py -3 -m unittest discover -s tests -v`. The suite creates made-up stores and official-export-shaped ZIPs in temporary folders, starts an ephemeral loopback HTTP server, and removes its data afterward. It does not use real sources or network services. No fixture downloads or credentials are needed.

Coverage: Windows and Mac/Linux paths; Claude blocks/tags/search/source removal; Codex database precedence/realtime/state lineage/legacy/history; T3 lineage and folded tools; both OpenCode database schemas and legacy JSON storage; Cursor; Grok; both cloud imports and reimport; invalid ZIPs; transcript pagination and Markdown; stable live-WAL snapshot with unchanged source signatures and read-only copied DB; repository/cache collision rejection; unsupported detection; bundled asset/API routes; forbidden foreign writes; valid same-origin configuration.

Compressed-archive coverage uses Python 3.14 compression.zstd or a local zstd executable. That case skips on older Python without an encoder. CI uses macos-latest and windows-latest with Python 3.10 and 3.14. CI is included but has not been run remotely. JavaScript syntax check: `node --check static/app.js` when Node is available; Node is not required to run the app.

Safe actions: run this suite and inspect synthetic exports. For a manual UI pass, use `--data-dir` pointing to a fresh temporary folder outside the checkout, add only made-up stores, enable and save. Check Sources, tag editing, source toggles, search, filters, folded tools, lineage, pagination, import and download. UI controls have stable IDs in static/index.html. This implementation pass used HTTP checks, not an automated browser; interactive visual verification remains for the design pass.

Real-store testing is read-only on originals but creates private snapshots and an index. Do not commit those files, exports, screenshots, actual transcripts or full source paths. Stop the viewer before deleting its chosen test data folder. No source cleanup or configuration changes are part of testing. Ordinary launch on an existing configured archive can expose its contents locally.

## Privacy scan before a public commit

Status: tested; see verification.md.

Scan every repository file, excluding Git internals and ignored bytecode. Check personal home paths, emails, API token prefixes and private/client names, including names from any private predecessor configuration. Do not copy the private name list into this repository or print matched secrets. Review every at-sign match: Python decorators, CSS media queries and GitHub Action version refs are expected. Review staged file names and sizes, confirm all test data is synthetic, inspect the root commit, verify no remotes, and check that caches/indexes/exports are absent. A scan is evidence, not a guarantee of secret redaction.

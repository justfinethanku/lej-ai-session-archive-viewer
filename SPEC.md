# Archive contract

Python 3.10+, standard library HTTP server on 127.0.0.1. The bundled static interface talks only to same-origin JSON routes. No transcript content executes: session text is inserted as text nodes, with light formatting for headings, bold and code only. The Content-Security-Policy allows scripts, styles, fonts and images from this origin alone. SQLite FTS5 indexes compressed transcript blocks in per-user app data. Original stores remain authoritative.

## Normalized sessions

Each session has a source, native ID, title, project label, start/end, model label, message count and optional parent. Each block has role, message/tool kind, time, model and plain text. Empty source fields remain empty. Cursor's observed JSONL format has no reliable timestamps, so it shows Unknown time. Provider model labels describe stored metadata, not a promise about every turn.

Codex state databases supply thread metadata and spawn edges. History databases supply thread_items.item_json and thread_realtime_items.item_json ordered by rollout ordinal, with millisecond timestamps. thread_turns supplies turn metadata but does not count as a transcript by itself. Database items override matching rollout native IDs. Version suffixes are globbed and ordered numerically. File rollouts parse session_meta, turn_context, response_item and legacy message arrays; mirrored event_msg records are skipped. Typed history is a separate prompt transcript.

Claude Code reads user/assistant JSONL messages and summary metadata, deduplicating repeated message UUIDs within a file. T3 reads projection_projects and orchestration_v2 projection threads/messages/turn_items, with lineage from thread payloads. OpenCode reads legacy session/message/part plus session_v2/session_message/session_part, preferring v2 for repeated session IDs, and legacy storage/session, storage/message and storage/part JSON trees. Database records take precedence over storage JSON with the same ID. Grok reads chat_history.jsonl and sibling summary.json; encrypted reasoning is omitted. Cursor reads project JSONL role/message.content records.

Claude export ZIPs read chat_messages from conversations.json. ChatGPT exports read all mapping message nodes once, ordered by create_time, preserving alternate branches. ZIP members are not extracted; exactly one conversations.json is required, at most 512 MB. Reimport is content-addressed and native conversation IDs avoid duplicate sessions.

## Discovery and storage

Sources are configured by kind, ID, local path and enabled flag. Default locations resolve for each OS, and copied folders are additive. New installations begin with sources disabled and no tag rules. Unknown stores appear as detected but unsupported, without guessed counts. Export-only sources are offered separately.

A stable DB/WAL snapshot requires unchanged file identity, size and timestamps across copying. Live databases are never opened through SQLite. Recovery affects only the private copy; final reads are mode=ro&immutable=1. An active writer can exhaust the bounded retries and require another refresh. Snapshots are temporary: they are deleted when a refresh finishes and when a source check runs outside a refresh. Only viewer-made copies are deleted: a `<key>.sqlite` (with any `-wal`/`-shm`) whose `<key>.json` marker holds `[source path, signatures]` and whose key is that path's hash. The marker is removed last, and only once its copy is gone, so a failed delete is retried at the next cleanup. Each snapshot's staging folder is removed by the same call, on success or error. A refresh therefore copies each database again; the index is the only kept artifact.

Refresh rebuilds enabled sources and removes disabled/missing source records from the searchable index. It is not transactional across the entire archive: sessions can appear progressively, and an adapter error may leave partial results. Imported originals remain private app data. Stop the viewer before deleting app data to reset everything.

Tags map names to keyword lists. Whole-word, case-insensitive keyword matching uses title, project and transcript. Tag chains sort by start and ID; tag Markdown exports ignore list filters. Lists have 50 sessions per page; transcript pages have 100 blocks. FTS searches quoted phrases across all block text. Exports stream Markdown including tools.

## Interface boundaries

GET: /, any file that ships in static/ with a .css, .js, .woff2 or .svg extension (matched by exact name; nothing else is served), /api/status, /api/sources, /api/list, /api/session, /export.

POST: /api/config, /api/import, /api/refresh. Writes require the exact loopback Host and same-origin Origin. Config/import requests are limited to 64 KB, and modifications wait until refresh finishes. HTTP bodies and search terms are not logged. Source and app-data folders must be separate; app data cannot live inside the checkout.

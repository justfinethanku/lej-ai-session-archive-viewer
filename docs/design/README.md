# Design pass: LEJ Design System v1

November 15, 2026. The interface was restyled to the LEJ look: a near-white page, charcoal type, one terracotta accent, and hierarchy from layout. Every picture here was taken from `python3 tools/demo.py`, which uses made-up sessions. No real session text, names or paths appear.

## Before and after

| | Before | After |
| --- | --- | --- |
| Sources | ![](before-sources.png) | ![](after-sources.png) |
| Session list | ![](before-sessions.png) | ![](after-sessions.png) |
| Transcript | ![](before-transcript.png) | ![](after-transcript.png) |

## The rest of the after set

| Screen | Picture |
| --- | --- |
| First run, nothing turned on yet | ![](after-first-run.png) |
| First run, sources picked, ready to save | ![](after-first-run-picked.png) |
| Indexing, with the status panel open | ![](after-indexing.png) |
| A tag read as a chain | ![](after-chain.png) |
| Search, with matches marked | ![](after-search.png) |
| Parent and child sessions, tool steps open | ![](after-lineage-tools.png) |
| Add a folder and import an export | ![](after-add-and-import.png) |
| An import that failed | ![](after-import-error.png) |
| Dark mode, transcript | ![](after-dark-transcript.png) |
| Dark mode, sources | ![](after-dark-sources.png) |
| Laptop width, 1100 px | ![](after-laptop-1100.png) |
| Narrow, list | ![](after-narrow-list.png) |
| Narrow, reading | ![](after-narrow-reader.png) |

The indexing picture is the one simulated state. Demo data indexes in milliseconds, so the status feed was faked in the browser for that shot. The screen itself is the real one.

## Choices worth knowing

- **Tokens.** `static/style.css` opens with the LEJ tokens, unchanged. Dark mode redefines the same names and follows the system setting.
- **Small gray text.** The system's `--stone` is 4.0:1 on the page, under the 4.5:1 that AA asks of small text. Meta text here uses a derived `--meta` (#696B71, 5.2:1). `--stone` is kept as a token and not used for text.
- **Accent in dark mode.** Terracotta text lightens to #E7805C (6.5:1 on the dark page). Filled buttons keep #BD4F2E with white text (4.9:1).
- **App marks.** Each app gets a two-letter tile (CC, Cx, T3) in the list, and its full name everywhere there is room. No logos.
- **Chains.** A tag read oldest first draws the list as a rail, the same shape the design system uses for progress.
- **Progress.** The bar compares sessions indexed so far with the count found when sources were checked, and says "about" because that count can drift while apps run.
- **Fonts.** Latin and Latin Extended subsets of the three variable fonts ship in `static/fonts/`, about 170 KB in all. Other scripts fall back to system fonts.

## Retake the pictures

Run `python3 tools/demo.py --dir /tmp/lej-archive-demo` (and again with `--first-run --port 8798 --dir /tmp/lej-archive-demo-first`), then capture at 1440 by 900. Choose a `--dir` whose path holds no personal name, because source paths are shown on screen.

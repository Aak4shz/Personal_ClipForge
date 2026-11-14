# ClipForge Memory

| | |
|---|---|
| **Document** | Memory (living file), version 1.0 |
| **Purpose** | Cross-session project state: what is done, what is in progress, what is next |
| **Maintainer** | Whoever is working: Aakash or any agent |
| **Repo** | `/home/aakash/Code/Personal_ClipForge` |
| **Remote** | `https://github.com/Aak4shz/Personal_ClipForge.git` |
| **Last updated** | 2026-11-14 |

**Start every session on this project by reading this file.** It is the fastest map of where things stand, and it is written to be read by the next session, the next model, or the next agent with no other context. Everything here is kept current on purpose; trust it, and keep it that way by updating it as you work.

Companion documents, in the order a new session should read them: this file, then [Rules.md](Rules.md) (binding conduct), then [Phases.md](Phases.md) (the current phase section), then [ARCHITECTURE.md](ARCHITECTURE.md) (the module being touched), then [PRD.md](PRD.md) (requirement IDs). [README.md](README.md) and [Design.md](Design.md) are reference material.

---

## 1. Session protocol

### 1.1 On session start

1. Read the snapshot in section 2. It says the phase in progress, the next action, and any blockers
2. Read Rules.md. It binds everything you are about to do
3. Read the current phase's section in Phases.md, including its done-when list
4. Claim the work in section 5 before writing any code, so a parallel session sees the claim
5. Check section 7 (gotchas) for anything the last session learned the hard way

### 1.2 Update triggers

Update this file at each of these moments, not on a timer and not only when a phase fully closes:

| Trigger | What to update |
|---|---|
| Work claimed | Section 5 (current work block) |
| A build table item from Phases.md is finished | Section 4 phase tracker row, if the phase advances |
| A phase's done-when list passes | Section 3 (new log entry), section 4 (status done with date), section 2 (snapshot) |
| The owner makes a decision | Section 6 (decisions log) |
| Something cost you time that the next session would not expect | Section 7 (gotchas) |
| A document is created or materially changed | Section 9 (document inventory) |
| Session ends mid-phase | Section 5 must state exactly where you stopped, down to the file and the failing test if any |

### 1.3 Log entry format

Section 3 entries follow this shape, newest first:

```text
### YYYY-MM-DD · short label
what: one to three lines, concrete
evidence: how it was verified (tests, commands, scanner output)
next: what this unblocks or points at
```

### 1.4 Rules for this file

- Append, never erase. Superseded entries stay and get marked
- Update it in the same commit as the work it describes, so git history and memory never disagree
- Write entries that survive out of context: file names, numbers, commands. "Made some progress on the CLI" is not an entry
- Keep the snapshot honest even mid-work. An in-progress phase says in progress, with what is left

## 2. Snapshot

*This block is rewritten every session. Read it first.*

| Field | Value |
|---|---|
| Project state | Phase 1 (Foundation) done; Phases 2 to 15 remain |
| Current phase | Phase 2 (Probe), not started |
| Next action | Build `probe/ffprobe.py`, `metadata.py`, `compatibility.py` and wire `clipforge probe` (Phases.md, Phase 2 build table) |
| Blockers | None. Open decisions D1 to D12 do not block Phase 2 |
| Last session | 2026-11-14: completed Phase 1, including install, CLI, doctor, and tests (section 3) |
| Coding session plan | Phases 2 and 3 next per Phases.md section 2, taken one phase at a time |

## 3. Completed work log

Newest first.

### 2026-11-14 · Phase 1 review and fixes

what: dispatched a senior-reviewer subagent over the whole Phase 1 tree; it confirmed all build items, all rules, and all done-when conditions, and found no Critical defects. Five Important findings, four fixed in code and one (the commit) pending owner word:
- demuxer count was off by one (the `D..` legend line counted as a row): regex tightened to `\s*D\s`, fake runner regenerated from real `ffmpeg -demuxers` output, doctor now reports 377 and matches reality
- empty or comment-only `config.yaml` was rejected; now yields defaults (users create such files ahead of configuring)
- XDG environment variables were ignored for config, database, and logs: new `utils/paths.py` resolvers (`config_home`, `data_home`, `state_home`), wired into `core/config.py`, honored by `default_config_path()` and `PathsConfig` defaults
- pyproject license moved from `GPL-3.0-or-later` to `GPL-3.0-only` to match LICENSE and the docs; the precise only-or-later choice is flagged to the owner
- stale doc claims fixed: PRD and ARCHITECTURE build-status lines now say Phase 1 of 15 done; ARCHITECTURE tree label for `cli/__init__.py` corrected

evidence: pytest 19 passed (3 new tests: empty YAML, XDG override, relative XDG ignored); mypy strict 0 issues in 37 files; ruff clean; doctor reports 377 demuxers, equal to the real count from `ffmpeg -demuxers`.

next: deferred minors from the review, listed in the gotchas entry below. The commit itself (review Important 5) is held at the owner's request: review only, no commit, no push.

### 2026-11-14 · Phase 1, Foundation

what: built the installable package skeleton per the Phase 1 build table:
- `pyproject.toml`: PEP 621 packaging, console script `clipforge`, ruff, mypy (strict), and pytest config; editable install with `pip install -e ".[dev]"` on Python 3.14
- `src/clipforge/**`: all 11 module directories with `__init__.py` and a `py.typed` marker; `core/constants.py` (states, caps 4/3/8, 4 MiB, 5% margin, target 3,984,589 bytes, exit codes, 2/5/10 s delays), `core/errors.py` (full 8-class hierarchy), `core/config.py` (every blueprint section 18 key, YAML load, CLI-over-file-over-defaults)
- CLI: Typer app with all 16 commands registered (FR-CLI-01 order); `doctor` and `info` are real; 14 stubs print the delivering phase and exit 2
- `doctor` runs against the real stack (RULE-05 argument lists from the first call): ffmpeg 9.0.2, ffprobe, libvpx-vp9, libopus, vaapi all present; libvmaf honestly reported optional and absent in this build; 377 demuxers; all 8 common container families readable
- tests: `tests/unit/test_config.py` (11 tests, precedence and key-naming errors) and `tests/unit/test_doctor.py` (5 tests, mocked runner)

evidence: `pytest` 16 passed; `mypy --strict` 0 issues in 36 files; `ruff check` and `ruff format --check` clean; `clipforge --help` lists 16 commands; `clipforge doctor` exit 0; stubs exit 2 with the RULE-19 message shape.

next: Phase 2 (Probe). The doctor error path (exit 3 on missing required components) is wired but untested on a real broken machine; the mocked test covers it.

### 2026-11-13 · project documents

what: created the full documentation suite in the repo root:
- `PRD.md`: requirements with FR/NFR IDs, personas, workflows, data model, success metrics
- `ARCHITECTURE.md`: runtime model, 11-module reference with file-level layout, sequence diagrams, storage design, tech stack, design decisions
- `Rules.md`: 75 binding rules in two halves (what we do / what we avoid), library whitelist and blocklist, error handling law, AI boundaries, escalation list, pre-merge checklist
- `Phases.md`: blueprint milestones M0-M9 expanded into 15 balanced phases with build tables, done-when lists, and a progress log
- `Design.md`: CLI design system: color tokens with hex and 256 values, four themes, font requirements, typography hierarchy, layout zones, symbols, motion, microcopy voice with examples

evidence: every file passed the no-slop scanners (`banned_phrase_scan.py` and `structure_scan.py` from the unslop skill) with zero violations and zero em-dashes per 1k. Git status shows all six as untracked or modified pending the next commit.

next: implementation starts at Phase 1. Nothing in code exists yet.

### 2026-11-12 · repository created

what: repository initialized as `Personal_ClipForge` with remote `Aak4shz/Personal_ClipForge` on GitHub. Initial commit `8d3dcb1` added the GNU GPL v3 `LICENSE` and an empty `README.md`.

evidence: `git log` shows one commit; `LICENSE` is the standard GPL-3.0 text.

next: documentation (done 2026-11-13), then Phase 1.

## 4. Phase tracker

The done-when criteria for each phase live in Phases.md; this table is the state mirror. Statuses: `not started`, `in progress`, `done (date)`.

| Phase | Name | Status | Date |
|---|---|---|---|
| 1 | Foundation | done (2026-11-14) | 2026-11-14 |
| 2 | Probe | not started | |
| 3 | Plan and dry-run | not started | |
| 4 | Encode engine | not started | |
| 5 | MVP full run | not started | |
| 6 | Smart size control | not started | |
| 7 | Quality gates and ladder | not started | |
| 8 | Persistence | not started | |
| 9 | Resume and recovery | not started | |
| 10 | Fault tolerance | not started | |
| 11 | Recovery commands | not started | |
| 12 | Batch, queue, dashboard | not started | |
| 13 | Performance and diagnostics | not started | |
| 14 | Hardening | not started | |
| 15 | Packaging | not started | |

Blueprint milestone mapping (for cross-reference with the PRD): M0 is Phase 1; M1 is Phases 2 and 3; M2 is Phases 4 and 5; M3 is Phases 6 and 7; M4 is Phases 8 and 9; M5 is Phases 10 and 11; M6 is Phase 12; M7 is Phase 13; M8 is Phase 14; M9 is Phase 15.

## 5. Currently working on

*Filled in by whoever claims work. Cleared when the claim finishes or is abandoned (say which in the log).*

| Field | Value |
|---|---|
| Claimed by | (nobody; Phase 1 claim finished 2026-11-14) |
| Phase | next claim: Phase 2 (Probe) |
| Files in flight | |
| In-flight detail | |
| Claimed at | |

## 6. Decisions log

Owner decisions that shaped the project, newest first. The open decisions D1 to D13 live in PRD.md section 14; they land here as they get made.

| Date | Decision | Choice | Where it lands |
|---|---|---|---|
| 2026-11-14 | D13, SPDX precision | GPL-3.0-only | `pyproject.toml` license field; LICENSE and docs already read as plain GPL-3.0 |
| 2026-11-12 | D13, license half | GPL-3.0 | `LICENSE` committed; noted in README and ARCHITECTURE.md |
| 2026-11-13 | D13, naming half | Product name stays ClipForge; repo stays `Personal_ClipForge` | README title; this file's header |

Still open: D1 through D12 (PRD.md section 14). None block Phase 2. D1 (which platform drives the 4 MiB limit) is worth settling before Phase 5 tunes defaults, because it may move the margin and profile defaults.

Commit status: the owner has held off committing Phase 1 for now ("only review"); git history still shows only the initial commit. The Phase 1 work and its doc updates stay uncommitted in the working tree until the owner says otherwise.

## 7. Gotchas and lessons

Append-only. One entry per lesson, written for the session that has not lived it.

| Date | Lesson |
|---|---|
| 2026-11-13 | Project prose has a hard no-slop standard. The unslop skill's scanners (`banned_phrase_scan.py`, `structure_scan.py`) are the objective check; run them on any new or edited project document. Zero em-dashes is the recurring trap: they hide inside diagram labels and table cells, not just prose |
| 2026-11-13 | Owner preference, learned across sessions: documents in humanized English, no emojis anywhere in project files, direct tone. Chat with the owner is Hinglish; project files are English |
| 2026-11-13 | The docs deliberately split heavy blueprint milestones into two phases (M2 into Phases 4 and 5, and so on). Do not merge them back; the balance is the point |
| 2026-11-13 | Budget math must land in Phase 3, not Phase 6, because the dry-run feasibility estimate needs it. `optimizer/budget.py` is built early and reused later. Phases.md Phase 3 build table says this explicitly |
| 2026-11-14 | `modern-web-guidance` skill (Google Chrome team) installed at `.agents/skills/`, with `skills-lock.json` at repo root. It triggers only for HTML/CSS/client-side JS work, so it stays quiet during the Python CLI phases. It is untracked in git; commit it (keeps the skill pinned for any machine or agent) or gitignore it before the first commit. Telemetry opt-out: `DISABLE_TELEMETRY=1` |
| 2026-11-14 | Pydantic v2 does not validate field defaults unless `validate_default=True` is set on the model config. The paths expansion validator silently never ran on defaults until a test caught it. All config sections now set it, so a bad built-in default fails loudly. Relevant again the next time a config validator is added |
| 2026-11-14 | This machine's ffmpeg 9.0.2 build has no libvmaf filter, so `clipforge doctor` reports it as optional and absent. When Phase 7 needs the vmaf gate, the Arch `ffmpeg` package may need checking for a vmaf-enabled alternative, or `metric: ssim` stays the default. Doctor already tells the truth about this |
| 2026-11-14 | Deferred review minors, each with its landing point: stub phase numbers for `status`/`report`/`config`/`clean` are not in any Phases.md build table (plan gap; owner assigns, 8 and 11 look right); escaped per-clip exceptions' exit codes are provisional and revisit in Phase 5; doctor could distinguish "absent" from "ran and failed" in details; doctor's exit-3 path and non-zero-runner path need one test each; CLI-level tests (stub exits 2, error codes, Ctrl+C 130) worth adding in Phase 2; `retry_delays_seconds` accepts an empty list, add `min_length=1` in Phase 10; test names should carry FR IDs as they grow; Phase 7 needs a `psnr_min` key or a special case; Phase 3's budget math must compute the target from the effective config (`max_size` x margin), not from `TARGET_CLIP_SIZE_BYTES`; FR-SPL-01's 1..600 s duration bound is unenforced and belongs in Phase 3; version lives in pyproject and `__init__.py`, dedupe or sync in Phase 15 |

## 8. Environment and quick facts

| Fact | Value |
|---|---|
| Platform | Arch Linux (primary and only supported target for v1.0) |
| Target hardware | Intel i3-1215U, 8 GB RAM, Intel UHD graphics |
| Runtime | Python 3.11+ (planned) |
| Media engine | FFmpeg and FFprobe, system packages, features verified by `clipforge doctor` |
| Core libraries (whitelist) | Typer, pydantic, PyYAML, Rich, psutil, sqlite3 stdlib; full list in Rules.md section 1.2 |
| Non-negotiable caps | 4 MiB hard limit per clip, 5% internal margin, 4 size attempts, 3 fault retries, 8 total encodes per clip; details in Rules.md RULE-15 and PRD FR-OPT |
| Priority order | reliability, then size, then quality, then performance (RULE-53 protects it) |
| Test policy | Fixtures generated by script, never committed; acceptance criteria in PRD section 12 |

## 9. Document inventory

| File | Purpose | Status | Last touched |
|---|---|---|---|
| `README.md` | Public face: what the tool is, planned interface, honest status badge | complete | 2026-11-12 |
| `PRD.md` | Requirements: FR/NFR IDs, personas, workflows, ER model, metrics, open decisions | complete | 2026-11-12 |
| `ARCHITECTURE.md` | How it is built: modules, files, flows, storage, stack, design decisions | complete | 2026-11-12 |
| `Rules.md` | Conduct: whitelist, blocklist, error handling, AI boundaries, checklist | complete | 2026-11-13 |
| `Phases.md` | Build schedule: 15 phases, build tables, done-when, session discipline | complete | 2026-11-13 |
| `Design.md` | Presentation: colors, themes, fonts, typography, layout, symbols, voice | complete | 2026-11-13 |
| `Memory.md` | This file: cross-session state | living | 2026-11-14 |
| `LICENSE` | GPL-3.0 | complete | 2026-11-12 |
| `pyproject.toml` | Packaging and tool config: deps, console script, ruff, mypy, pytest | complete | 2026-11-14 |
| `src/clipforge/**` | All source code: skeleton with constants, errors, config, CLI (doctor and info real, 14 stubs) | Phase 1 done; modules grow phase by phase | 2026-11-14 |
| `tests/**` | Test suite: `tests/unit/test_config.py`, `tests/unit/test_doctor.py` | Phase 1 done; grows phase by phase | 2026-11-14 |
| `.venv/` | Local virtualenv, Python 3.14, editable install (gitignored) | active | 2026-11-14 |

## 10. Open questions

| Question | Blocks | Owner action |
|---|---|---|
| D1: which platform or use drives the 4 MiB limit? | Phase 5 default tuning (margin, profile) | Decide before or during Phase 5 |
| D2 to D12 (PRD section 14) | Mostly defaults; none block Phases 1 to 4 | Settle as the relevant phase arrives |

---

*This file works only if it stays true. If you find it stale, fix it before trusting anything else in the repo. If you finish work and do not update it, the next session inherits a lie; that is the one failure this document cannot recover from on its own.*

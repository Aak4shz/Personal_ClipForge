# ClipForge Rules

| | |
|---|---|
| **Document** | Rules, version 1.0 |
| **Status** | Binding |
| **Owner** | Aakash |
| **Sources** | Master Blueprint v2.0, [PRD.md](PRD.md), [ARCHITECTURE.md](ARCHITECTURE.md) |
| **Last updated** | 2026-11-13 |

This file governs how code gets written for ClipForge, whether the writer is a human or an AI assistant. The PRD says what to build. The architecture document says how it fits together. This document says what is allowed, what is forbidden, and where an AI must stop and ask instead of deciding.

AI assistants: treat this file as binding. "It seemed useful" is not a justification against a rule here; it is a reason to ask the owner first.

**When documents disagree:** the blueprint's corrected v2 behavioral rules win, then the PRD, then ARCHITECTURE.md, then this file. If code contradicts the docs, find out which one is wrong and fix them together. Never reconcile a conflict by silently changing code to match a habit.

Every rule carries an ID (`RULE-01` and up) so a review comment can cite it.

---

## 1. What we do

### 1.1 Before writing any code

| ID | Rule |
|---|---|
| RULE-01 | Read the PRD section and the ARCHITECTURE section for the module you are touching before touching it. Requirements carry IDs; cite the relevant FR or NFR ID in the commit message and in the test name |
| RULE-02 | Work within the current milestone only. The roadmap in the PRD is the order of operations; M2 does not import code that belongs to M4 |
| RULE-03 | One concern per commit. A commit that fixes a bug and renames half a module is two commits |
| RULE-04 | Match the style of the surrounding code. Once M0 lands, existing files define the conventions, not personal preference |

### 1.2 Libraries we use

The whitelist is short on purpose. Runtime dependencies (beyond the standard library):

| Library | Allowed for | Rules of use |
|---|---|---|
| Typer | Every CLI surface | All commands, options, and help text go through Typer. Never argparse or raw click, even for "just one quick command" |
| pydantic | Config model, validation, typed models | Every config key is a field with a type and a default. Validation errors name the key |
| PyYAML | Loading `config.yaml` only | YAML is read once at startup and validated into pydantic models; YAML never becomes an internal data format |
| Rich | Dashboard, progress, terminal summaries, CLI error rendering | Terminal output goes through Rich's Console. Errors exit with a non-zero code and a message that names the recovery command |
| psutil | CPU, RAM, and disk sampling | Read-only sampling; monitoring never mutates state outside its own snapshot |
| sqlite3 (stdlib) | All persistent state | The only storage engine. Access lives in `storage/`; no module outside `storage/` writes SQL |

Standard library modules are always allowed and preferred: `subprocess`, `fcntl`, `os`, `signal`, `hashlib`, `logging`, `json`, `pathlib`, `math`, `time`, `datetime`. If the stdlib can do it, no third-party library is added.

Development tooling whitelist: `pytest`, `ruff`, `mypy`. Anything else needs approval (see section 3).

### 1.3 How we call FFmpeg

| ID | Rule |
|---|---|
| RULE-05 | FFmpeg and FFprobe run from an argument list with `shell=False`, always. No shell strings, no `os.system`, no f-string command lines |
| RULE-06 | Filenames are passed defensively: `--` before positional arguments, `file:` prefix where the API allows it, so a file named `-rf` or `note; rm.mp4` cannot do damage |
| RULE-07 | Cuts use input seek (`-ss` before `-i`) plus re-encode. Stream copy (`-c copy`) is never used for splitting |
| RULE-08 | Encodes write to a `.part` file inside the output folder, get verified, then publish by fsync and `os.replace()`. A `.part` file is never renamed before verification passes |
| RULE-09 | Progress comes from `-progress pipe:1`. Exit code plus a fresh ffprobe check decide success; stderr text never decides success on its own |
| RULE-10 | The kill ladder is fixed: SIGTERM to the process group, wait 5 seconds, then SIGKILL. No skipping the grace period because a run looks stuck |

### 1.4 How we handle errors

The four error classes from the PRD (tunable, transient, permanent clip, fatal job) are the spine of error handling. Every failure gets a class before it gets a response.

| ID | Rule |
|---|---|
| RULE-11 | Classify first, act second, commit third. No retry, skip, or pause happens without a classification recorded in the database |
| RULE-12 | Raise and catch exceptions from the hierarchy in `core/errors.py`. No ad-hoc exception classes per module, no raising strings |
| RULE-13 | A `try` block must re-raise, wrap, classify, or handle. An empty handler or a bare `except:` is a bug, not a style choice |
| RULE-14 | Permanent errors are never retried. Retrying an undecodable clip wastes three attempts that a real transient fault may need later |
| RULE-15 | The counters are law: 1 initial attempt plus at most 3 fault retries, at most 4 size attempts, at most 8 total FFmpeg runs per clip. Changing any of these is a blueprint change, not a code change |
| RULE-16 | Fatal job errors pause the job and protect completed clips. A fatal path never deletes, truncates, or renames finished output |
| RULE-17 | Every contained failure is recorded: an `attempts` row, an `events` row, and a log line. Silence is the one unacceptable outcome |
| RULE-18 | Full FFmpeg stderr goes to the per-job log file. Only the last 2 KB go into the database. The database stays small |
| RULE-19 | Error messages follow one shape: what happened, what it means, what to run next. "Something went wrong" is not a message |
| RULE-20 | Library code never prints. Errors surface as exceptions; the CLI layer renders them on stderr with the right exit code |
| RULE-21 | Exit codes come from the fixed table (0, 1, 2, 3, 4, 130). Scripts depend on them; inventing a new one breaks them |

### 1.5 How we manage state

| ID | Rule |
|---|---|
| RULE-22 | Commit the new state to SQLite before mutating the filesystem. State ahead of file is correctable at resume; file ahead of state is corruption |
| RULE-23 | All boundary math in integer microseconds with half-open `[start, end)` intervals. Float seconds for boundaries are forbidden in committed code |
| RULE-24 | `attempts` history is append-only. Reprocesses add rows; nothing ever updates or deletes an old attempt |
| RULE-25 | The input file is read-only: never moved, never modified, never deleted, never written |
| RULE-26 | Resume begins with the fingerprint check. A changed fingerprint stops the job; `--relocate` is the only path around it |
| RULE-27 | Every config snapshot lands in the `jobs` row, so any report can say exactly which settings produced which result |

### 1.6 How we write code

| ID | Rule |
|---|---|
| RULE-28 | Type hints on every function signature. mypy runs clean on the whole package |
| RULE-29 | Boundary math, budget math, recalculation, and classification are pure functions with no I/O, so they are unit-testable without FFmpeg |
| RULE-30 | The FTJM is the only orchestrator. Modules under it never call each other sideways; if the encoder needs a quality decision, the scheduler asks the optimizer and passes the answer down |
| RULE-31 | Comments explain why, never narrate what. A comment that restates the next line gets deleted |
| RULE-32 | Public functions carry a docstring with purpose, arguments, and raised exceptions. Internal helpers stay lean |
| RULE-33 | No dead code, no commented-out blocks, no "keep it for later". Deletion is version control's job |

### 1.7 How we test

| ID | Rule |
|---|---|
| RULE-34 | Logic lands with tests in the same commit. No exception for "small" changes to `boundaries.py`, `budget.py`, `size_loop.py`, or `classifier.py`, those four files hold the blueprint's hardest bugs |
| RULE-35 | Test fixtures are generated by `scripts/make_fixtures.sh` and never committed. No media files in git, ever |
| RULE-36 | Integration tests must cover the ugly five: interrupt mid-encode, `kill -9` on FFmpeg, disk full, duplicate job, corrupted database |
| RULE-37 | A milestone is done when the PRD's acceptance criteria for its features pass as tests, not when the code exists |

### 1.8 What the AI must always do

| ID | Rule |
|---|---|
| RULE-38 | Stop and ask when a task touches an open decision from the PRD (D1 to D13). Those decisions belong to the owner; picking one silently is a violation even if the choice looks obvious |
| RULE-39 | Report adjacent bugs instead of fixing them silently. "While I was in there" changes get their own commit and their own explanation |
| RULE-40 | Verify claims with a run or a test before stating them. "This should work" is a hypothesis, not a status |
| RULE-41 | Keep responses and commit messages factual. Working code and passing tests are the evidence; adjectives are not |

## 2. What we avoid

### 2.1 Forbidden libraries

The default answer to a new dependency is no. The burden of proof sits on the dependency, and the proof is a written reason in a proposal to the owner.

| Forbidden | Why | Use instead |
|---|---|---|
| NumPy, SciPy, Pillow, OpenCV | Frames are never processed in Python; the codec does pixel work | FFmpeg filters |
| torch, tensorflow, transformers, onnxruntime, any ML runtime | No AI features exist in this product | Nothing; the product does not need them |
| requests, urllib3, httpx, aiohttp, websocket libs | Runtime network use is banned outright | Nothing; the tool works offline by design |
| Celery, Redis, RabbitMQ, kafka-python, any queue broker | One process, one lock, SQLite-backed queue. Daemons multiply failure modes for a single-user CLI | `storage/repo.py` queries |
| Flask, FastAPI, Django, uvicorn, any server framework | No server exists in this product | Typer CLI |
| asyncio in the pipeline | The design is synchronous and sequential by decision; async would complicate the watchdog and the kill ladder for no throughput gain | Threads only where the architecture allows (monitoring sampler) |
| sh, plumbum, any subprocess wrapper | stdlib subprocess covers spawn, timeout, and pipes with argument lists | `subprocess` |
| pickle, shelve, marshal | State must survive crashes readably and queryably; pickles do neither | SQLite |
| eval, exec, dynamic imports of user-influenced paths | No dynamic code execution, ever | Explicit code |
| argparse, click used directly | Typer is the CLI layer; two CLI stacks in one codebase is confusion | Typer |
| orjson, ujson, simplejson | stdlib `json` is sufficient at this data volume | `json` |
| pandas | No analytics workload exists | Plain Python over SQLite rows |
| tkinter, PyQt, PySide, GTK, any GUI toolkit | CLI-only product in v1.0 | Nothing |
| colorama, termcolor, loguru, structlog | Rich owns the terminal; stdlib logging owns the files | Rich + `logging` |
| watchdog (filesystem events), APScheduler, schedule | Polling checks and the user's cron cover these jobs | psutil checks, cron |

Two notes on the list. Asynchronous programming is listed as a design boundary, not a moral judgment: the watchdog, the kill ladder, and the single-writer database model all assume synchronous flow, and that assumption is what makes the failure paths testable. And "no ML runtime" is not an expression of doubt about ML; it is a statement of product scope, and the PRD lists scene-aware splitting as a future idea precisely because it would change this rule.

### 2.2 Forbidden error handling patterns

| ID | Forbidden pattern | The rule instead |
|---|---|---|
| RULE-42 | `except:` or `except Exception: pass` | RULE-13: classify, record, or re-raise |
| RULE-43 | Retrying a permanent error | RULE-14: one attempt, mark `FAILED`, move on |
| RULE-44 | A retry loop without a cap | RULE-15: 3 faults, 4 size attempts, 8 total encodes |
| RULE-45 | Deleting a clip because its quality gate failed | Keep the file, mark `NEEDS_REVIEW`, name the recovery command |
| RULE-46 | Reporting an oversize file as complete | `FAILED_SIZE`, or a ladder step if the policy allows |
| RULE-47 | Returning error strings from internal APIs | Raise a typed exception; strings are for humans, not control flow |
| RULE-48 | Trusting exit code 0 as proof of a good clip | ffprobe verification decides: codecs, resolution, duration, frame count, size |
| RULE-49 | One exit code for every failure | RULE-21: the six documented codes, nothing else |
| RULE-50 | A silent fallback that changes output, such as downscaling without policy | Degradation happens only through `--on-oversize` and is recorded in manifest and report |
| RULE-51 | Swallowing stderr and moving on | stderr feeds classification (RULE-11); the log keeps the full text (RULE-18) |
| RULE-52 | A `TODO` without a tracking note in committed code | Open work gets an issue reference or a PRD line, not a comment orphan |

### 2.3 Boundaries for the AI

These are the lines an AI assistant does not cross while working in this repository, stated so there is no room for "I assumed".

| ID | The AI must not |
|---|---|
| RULE-53 | Change the priority order (reliability, size, quality, performance) or any cap (4 MiB limit, 5% margin, 4/3/8 counters) without an owner decision recorded in the blueprint |
| RULE-54 | Add a dependency, including "just a helper", without approval. This covers transitive additions pulled in by an approved library |
| RULE-55 | Build features outside the PRD: no GUI, no AI scene detection, no convert mode, no parallel encoding, no AV1 profile, no plugin system. Future ideas stay future until the PRD moves them |
| RULE-56 | Write outside the chosen output folder and the XDG paths. Creating files elsewhere, even temp files in `/tmp`, breaks the atomic-rename design |
| RULE-57 | Make any network request, check for updates, or "phone home" for any reason |
| RULE-58 | Mark a requirement complete without a passing test named after its FR ID. Claiming completion is the one failure mode that no test suite catches |
| RULE-59 | Skip, xfail, or weaken a failing test to land other work. A red test is information, not an obstacle |
| RULE-60 | Edit generated files or commit fixture media. Fixtures regenerate from scripts |
| RULE-61 | Change the license, the license claims, or attribution lines |
| RULE-62 | Rewrite git history, force-push, or rebase shared branches without being asked |
| RULE-63 | Hardcode absolute paths, usernames, or machine-specific assumptions. Paths resolve through `utils/paths.py` and XDG |
| RULE-64 | Introduce secrets, tokens, or credentials. The product needs none, and finding one in the codebase is an incident |
| RULE-65 | Refactor code beyond the task at hand. Drive-by cleanup hides real changes inside noise |
| RULE-66 | Re-encode, overwrite, or delete a completed clip outside the documented reprocess flow with explicit `--clip` and confirmation |
| RULE-67 | "Simplify" the state machines. Merging states, dropping `NEEDS_REVIEW`, or collapsing `FAILED_SIZE` into `FAILED` removes information the recovery flows depend on |
| RULE-68 | Decide an open question (D1 to D13) silently. Propose, show the tradeoff, wait |
| RULE-69 | Generate documentation that promises behavior the tests do not exercise. Docs describe what is, not what is planned |
| RULE-70 | Continue past a failing acceptance criterion in the PRD. Stop, report the failure with the run's numbers, and let the owner decide |

A pattern runs through these: the AI's authority is implementation within a decided design. The design itself, its caps, its scope, and its priority order are the owner's to change.

### 2.4 Forbidden reporting behavior

| ID | Forbidden |
|---|---|
| RULE-71 | Showing a `.part` file or an unverified file as completed, in any output: dashboard, manifest, report, or summary |
| RULE-72 | Writing a manifest entry without SHA-256 and size |
| RULE-73 | Claiming "all clips under 4 MiB" unless every clip was individually checked in that same run |
| RULE-74 | Reporting a job `COMPLETED` when any clip sits in `FAILED` or `NEEDS_REVIEW`; the honest status is `COMPLETED_WITH_ISSUES` with exit code 1 |
| RULE-75 | Quoting performance or quality numbers without the run that produced them (profile, hardware, fixture) |

## 3. When to stop and ask

An AI assistant stops and asks the owner before:

1. Adding any dependency, runtime or development
2. Changing a cap, a default, or the priority order
3. Touching the database schema (migrations are design changes)
4. Adding or changing an exit code
5. Anything on the open decisions list D1 to D13
6. Deleting user data: output folders, manifests, or database rows
7. Licensing or attribution questions
8. Any task where the PRD and the code disagree about what is supposed to happen

Asking is cheap. Un-asking a wrong decision that already shipped to the database schema is not.

## 4. Pre-merge checklist

Run through this before any merge. It is short on purpose, so it actually gets used.

- [ ] Tests pass, including the new ones for this change
- [ ] ruff and mypy are clean
- [ ] New logic in `boundaries.py`, `budget.py`, `size_loop.py`, or `classifier.py` carries unit tests (RULE-34)
- [ ] Every failure path in the change has a class, a record, and a message (RULE-11, RULE-17, RULE-19)
- [ ] Filesystem mutation still happens after the database commit (RULE-22)
- [ ] No new imports outside the whitelist (section 1.2)
- [ ] No fixtures, `.part` files, or media committed (RULE-35)
- [ ] Behavior changes are reflected in PRD.md and ARCHITECTURE.md
- [ ] Commit message cites the FR, NFR, or bug it serves (RULE-01)
- [ ] If a rule was bent or nearly broken, it is named in the merge description, not buried

---

*These rules serve the design, not the reverse. If a rule makes the blueprint's behavior impossible, the rule is wrong: raise it, change the rule through the owner, and record why.*

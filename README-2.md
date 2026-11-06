# ClipForge — The Story, The Why, and Everything Under the Hood

> **A personal project born from real frustration. This document tells the story in plain English — no corporate speak, no fluff.**

---

## 🎬 The Project Idea — Where It All Started

### The Problem I Kept Hitting

You know that feeling when you have a long video — maybe a two-hour recording of a family event, a gaming session, or a lecture — and you need to share it somewhere that has a **strict file size limit**?

I hit this wall constantly:

| Platform / Use Case | Typical Limit | My Pain |
|---|---|---|
| Discord / Slack / Telegram | 8–50 MB | Upload fails, or I have to manually chop and re-encode |
| Self-hosted galleries (Immich, PhotoPrism, etc.) | Configurable, often small | No automatic splitting that respects a hard ceiling |
| Email attachments | 25 MB | Same story |
| Forums / communities | Often 4–10 MB | "Your file is too large" — every single time |

**The core issue:** Every tool I tried fell into one of these traps:

1. **Cloud converters** — "Upload your 2 GB video to our server!" → No thanks. Privacy, bandwidth, accounts, subscriptions. For a *local* job? Hard pass.
2. **Generic cutters (ffmpeg, HandBrake, etc.)** — They split on keyframes and give you whatever size comes out. "Usually around 50 MB" doesn't help when the limit is **4 MiB**.
3. **Fragile long-running jobs** — A 2-hour video at 10-second clips = 720 clips. If the tool crashes at clip 500 and leaves you guessing what's done? You never run it again.
4. **Tools built for beefy hardware** — My laptop is an i3 with 8 GB RAM. Encoding 4K with default settings kills it. The tool needs to *respect* limited resources.

### The "Aha!" Moment

> **What if there was a tool that:**
> - Runs **100% offline** — nothing leaves your machine
> - Guarantees **every single clip ≤ 4 MiB** — hard ceiling, not a suggestion
> - **Survives crashes** — resume exactly where you left off, zero duplicate work
> - **Tells you the truth** — a manifest with hashes, a report with real metrics, no "it probably worked"
> - **Runs on modest hardware** — tuned for an i3 / 8 GB RAM, not a Threadripper

That's **ClipForge**.

---

## 🎯 The Purpose — One Sentence, Then The Details

### The Elevator Pitch

> **Feed ClipForge any local video. Get back verified, frame-accurate 10-second WebM clips (VP9 + Opus), each guaranteed under 4 MiB, with a manifest and report that prove it. All offline. All local. Crash-proof.**

### What "Purpose" Means in Practice

| Goal | What It Looks Like When It Works |
|---|---|
| **Privacy by default** | Zero network calls. No telemetry. No accounts. Your videos never leave your disk. |
| **Hard size guarantee** | 4 MiB is a *ceiling*. Not "around 4 MiB." Not "usually under." *Never over.* |
| **Reliability > Speed** | A finished clip is *never* reported as in-progress. A crash *never* corrupts output. If quality must drop to meet the size limit, quality drops — but the size limit *holds*. |
| **Honest quality** | We measure SSIM on every clip. If it falls below the floor, we flag it `NEEDS_REVIEW` instead of pretending it's fine. |
| **Resumability** | Ctrl+C at clip 400 of 720? Run `clipforge resume` and it picks up at 401. No re-encoding what's done. |
| **Observability** | Live terminal dashboard (Rich), structured logs, `manifest.json` (hashes, attempts, sizes), `report.json` (summary, failures, wall time). |
| **Runs on your hardware** | Memory guard, thermal guard, thread capping. It *knows* when your laptop is struggling and backs off. |
---

## 🛠️ The Toolbox — What Powers ClipForge

### Core Technologies (The "Must-Haves")

| Layer | Tool | Why It's Here |
|---|---|---|
| **Language** | **Python 3.11+** | Readable, great ecosystem, type hints (mypy strict), fast enough for orchestration |
| **CLI Framework** | **Typer** | Modern, type-safe, auto-generates help, shell completions |
| **Terminal UI** | **Rich** | Live dashboard, tables, progress bars, color themes — all accessible |
| **Media Engine** | **FFmpeg + FFprobe** | The industry standard. We *don't* reimplement encoding — we drive it correctly |
| **Video Codec** | **VP9 (libvpx)** | Best quality/byte at 4 MiB, universal browser support, hardware decode everywhere |
| **Audio Codec** | **Opus (libopus)** | Transparent at low bitrates, mandatory for WebM |
| **Container** | **WebM** | Open, royalty-free, designed for VP9/Opus |
| **State & Persistence** | **SQLite (WAL mode)** | ACID, crash recovery, queries, zero external deps |
| **Config** | **Pydantic + YAML** | Validation, defaults, type safety, human-editable |
| **System Monitoring** | **psutil** | CPU, RAM, disk, temps — for guards and dashboard |
| **Testing** | **pytest + mypy + ruff** | Strict types, linting, unit + reliability tests |

### What We *Deliberately Don't Use* (And Why)

| Not Used | Reason |
|---|---|
| NumPy, Pillow, OpenCV | **No frame ever touches Python memory.** FFmpeg does the pixel work. |
| PyTorch, TensorFlow, any ML | **Splitting is deterministic math.** No AI needed. |
| Celery, Redis, queue daemons | **Single-user CLI.** Daemons multiply failure modes for no gain. |
| GUI toolkits (Qt, GTK, etc.) | **CLI-first.** A GUI would be a separate app shell around the same core. |
| `requests`, `urllib`, any HTTP | **Zero runtime network use.** By design. |
| Shell=True subprocesses | **Security.** Argument lists only — safe with spaces, quotes, leading dashes. |

### External Dependencies (You Need These Installed)

| Dependency | Minimum | What It Provides |
|---|---|---|
| **ffmpeg** | 6.0+ | Encoding, cutting, probing |
| **ffprobe** | 6.0+ | Metadata extraction (comes with ffmpeg) |
| **libvpx** | 1.13+ | VP9 encoder (usually bundled in ffmpeg) |
| **libopus** | 1.4+ | Opus encoder (usually bundled in ffmpeg) |

> 💡 **Pro tip:** Run `clipforge doctor` — it detects your exact builds, versions, and tells you what's missing or misconfigured.
---

## 📋 The Requirements — What ClipForge *Must* Do

### Functional Requirements (The "What")

| ID | Requirement | Priority |
|---|---|---|
| **FR-01** | Accept a single video file or a folder of videos (batch mode) | **Must** |
| **FR-02** | Probe each video: duration, resolution, fps, codecs, bitrate, VFR flag, rotation, HDR, audio channels | **Must** |
| **FR-03** | Show a compatibility report *before* encoding (what will convert, what might be tricky) | **Must** |
| **FR-04** | Split timeline into **frame-accurate 10-second segments** (configurable) | **Must** |
| **FR-05** | Handle tail segments: merge short tail into previous, or emit as-is (policy-driven) | **Must** |
| **FR-06** | Encode each segment to **WebM (VP9 + Opus)** independently | **Must** |
| **FR-07** | **Hard size ceiling: 4 MiB per clip** — enforce via bitrate budget + size-check loop | **Must** |
| **FR-08** | Smart bitrate budget: start at 5% under limit, recalculate on overshoot (≥3% reduction), ladder fallback, two-pass fallback | **Must** |
| **FR-09** | Quality gate: measure **SSIM** on every clip; floor at 0.95; flag `NEEDS_REVIEW` if below | **Must** |
| **FR-10** | Per-clip retry logic: **size retries (max 3)** + **fault retries (max 3)** + **total encode cap (8)** | **Must** |
| **FR-11** | **Atomic publish**: write to `.part`, `fsync`, `os.replace()` — crash = orphan `.part`, never half-written clip | **Must** |
| **FR-12** | **SQLite persistence**: every clip state, attempt, error, metric in DB — source of truth | **Must** |
| **FR-13** | **Resume after interrupt**: Ctrl+C, kill -9, power loss — pick up at next pending clip, zero duplicates | **Must** |
| **FR-14** | **Fault isolation**: one corrupt region → only affected clips fail; job continues | **Must** |
| **FR-15** | **Selective retry commands**: `retry --failed`, `retry --review`, `reprocess` (force re-encode) | **Must** |
| **FR-16** | **Verification pass**: re-read every clip, check size, duration, decode-ability, hash | **Must** |
| **FR-17** | **Live terminal dashboard**: progress bar, active clip stats, CPU/RAM/temp/disk, ETA | **Should** |
| **FR-18** | **Batch mode**: multiple videos → each gets own output folder, queue with locks | **Should** |
| **FR-19** | **Configuration file**: YAML with profiles, hardware accel toggles, quality thresholds | **Should** |
| **FR-20** | **Benchmark command**: profile encodes on your hardware, suggest optimal defaults | **Could** |

### Non-Functional Requirements (The "How Well")

| ID | Requirement | Target |
|---|---|---|
| **NFR-01** | **Reliability** — finished clip never reported as in-progress; crash never corrupts output | Zero data loss |
| **NFR-02** | **Size enforcement** — successful clip never > 4 MiB | 100% compliance |
| **NFR-03** | **Quality** — best possible under size limit, measured by SSIM | ≥ 0.95 typical |
| **NFR-04** | **Memory** — peak RSS on 1080p30 ≤ 2.5 GB (8 GB system) | Measured |
| **NFR-05** | **CPU** — thermal guard throttles at 85°C (configurable) | No thermal throttle |
| **NFR-06** | **Disk** — write to output folder (same FS for atomic rename); guard on free space | ≥ 2 GB free |
| **NFR-07** | **Startup** — `clipforge doctor` < 2 seconds | Fast feedback |
| **NFR-08** | **Portability** — Linux-first (Arch), pipx installable, PKGBUILD | Works on target |
| **NFR-09** | **Accessibility** — dashboard degrades to plain text, colorblind-safe, no emoji | Inclusive |
| **NFR-10** | **Determinism** — same input + same config = same output hashes | Reproducible |
---

## 🏗️ Architecture — How It Fits Together (Mental Model)

```
┌─────────────────────────────────────────────────────────────┐
│                    ClipForge Process (Python)               │
│  ┌──────┐  ┌─────────┐  ┌────────┐  ┌────────┐  ┌────────┐ │
│  │ CLI  │──▶│  FTJM   │──▶│Planner │──▶│Encoder │──▶│Optimzer│ │
│  │Typer │   │Scheduler│   │Boundaries│  │Runner  │  │Budget  │ │
│  └──────┘   │Retries  │   │Tail    │   │Watchdog│   │Loop    │ │
│             │Recovery │   │Feasible│   └────────┘   │Ladder  │ │
│             │Locks    │   └────────┘                │SSIM    │ │
│             └────┬────┘                             └────┬────┘ │
│                  │                                     │      │
│         ┌────────▼────────┐                   ┌────────▼────────┐ │
│         │    Probe        │                   │    Storage      │ │
│         │  (ffprobe wrap) │                   │   (SQLite WAL)  │ │
│         └────────┬────────┘                   └────────┬────────┘ │
│                  │                                     │          │
└──────────────────┼─────────────────────────────────────┼──────────┘
                   │                                     │
           ┌───────▼───────┐                   ┌─────────▼─────────┐
           │  ffmpeg       │                   │  Output Folder    │
           │  subprocesses │                   │  clips + manifest │
           └───────────────┘                   │  + report + DB    │
                                               └───────────────────┘
```

### The Four Architectural Principles (Conflict Order)

1. **A clip is the unit of failure** — One bad clip never stops the job or corrupts a finished one. Drives state machines, DB, atomic publish, scheduler.
2. **The database is the source of truth** — Files are outputs; `manifest.json` is a mirror; SQLite is the authority. Every state change commits *before* file rename.
3. **FFmpeg does media, Python does control** — No frame in Python memory. Ever. We spawn, read progress, decide.
4. **Everything is bounded** — Threads, retries, attempts, RAM, log size, stderr in DB, timeouts. Named caps everywhere.
---

## ⚙️ The Processing Pipeline — Step by Step

### 1. **Probe** (`clipforge probe` / auto-run)
- `ffprobe` extracts: duration (µs), streams, codecs, resolution, fps (avg + VFR flag), bitrate, rotation, HDR, audio layout, chapters
- Feasibility check: "Can this even work?" (e.g., 4K 60fps on 8 GB RAM → warning)

### 2. **Plan** (`clipforge split --dry-run`)
- Integer microsecond boundaries, half-open intervals `[start, end)` — *float seconds drift across 360 clips*
- Tail policy: `merge_into_previous` (default, min 1s) or `emit_as_is`
- Output folder naming: `<video_name>/clip_0001.webm` ...

### 3. **Encode Loop** (per clip, sequential)
```
for each clip:
    budget = calculate_bitrate_budget(clip_duration, size_limit_4MiB)
    for attempt in 1..max_attempts:
        run_ffmpeg(clip, budget, profile)
        if size > 4 MiB:
            budget = recalculate_lower(budget, at_least_3_percent)
            continue  # size retry
        if decode_error / timeout / signal:
            if fault_retries < 3: continue  # fault retry
            else: mark FAILED_LIMIT
        measure_ssim()
        if ssim < 0.95: mark NEEDS_REVIEW (but keep file!)
        atomic_publish(.part → .webm)
        db.commit(state=COMPLETED)
        break
```

### 4. **Verify** (end of job or `clipforge verify`)
- Re-read every clip: size ≤ 4 MiB, duration ≈ 10s, decodes clean, hash matches manifest
- Produces `report.json` + terminal summary

### 5. **Output Artifacts**
```
holiday_video/
├── clip_0001.webm       # 00:00 - 00:10
├── clip_0002.webm       # 00:10 - 00:20
├── ...
├── clip_0060.webm       # 09:50 - 10:00
├── manifest.json        # every clip: hash, size, duration, attempts, SSIM, state
├── report.json          # summary: counts, wall time, largest, failures, review items
└── clipforge.db         # SQLite — the source of truth (not shipped by default)
```

---

## 🎚️ The 4 MiB Budget — Why It Exists and How It Works

### The Real-World Origin

> **4 MiB isn't arbitrary.** It matches real constraints:
> - **Discord free tier:** 8 MB (but 4 MiB leaves headroom for container overhead)
> - **Matrix/Element:** Often 4–10 MB per file
> - **Self-hosted galleries:** Admins set low limits to control storage
> - **Email:** 25 MB total, but 4 MiB clips = 6 per email comfortably
> - **Mobile data:** Small clips = fast shares, no "wait for upload"

### The "Smart Balance" Algorithm

```
Target size = 4 MiB - 5% safety margin = ~3.99 MiB (4,188,160 bytes)

1. First pass: estimate bitrate from probe (duration × bitrate ≈ size)
2. Encode with -b:v (target) -maxrate -bufsize (CBR-like control)
3. If clip > 4 MiB:
     new_bitrate = old_bitrate × (4 MiB / actual_size) × 0.97
     # Always at least 3% lower — prevents oscillation
     retry (max 3 size retries)
4. If still failing after ladder + two-pass:
     mark FAILED_SIZE (honest failure, not silent corruption)
```

### The Quality Ladder (Fallback Profile)

| Rung | Profile | Speed | Quality/Byte | When Used |
|---|---|---|---|---|
| 1 | `balanced` (default) | Medium | Best | First attempt |
| 2 | `quality` | Slower | Better | Size retry 2 |
| 3 | `speed` | Faster | Worse | Size retry 3 |
| 4 | Two-pass VP9 | 2× time | Best control | Last resort |
| 5 | `FAILED_SIZE` | — | — | Give up honestly |
---

## 🛡️ Fault Tolerance — Built for the Ugly Cases

| Scenario | What Happens |
|---|---|
| **Ctrl+C at clip 400/720** | DB has 399 `COMPLETED`. Resume → starts at 400. Zero re-encode. |
| **`kill -9` mid-encode** | `.part` orphan left. Resume → sees incomplete, re-encodes that clip cleanly. |
| **Corrupt frame at 00:42:13** | Only clip 5 (covering that region) fails. Job continues. `report.json` shows exactly which clip and why (`DECODE_ERROR`). |
| **Disk full at clip 200** | Guard checks free space before each clip. Pauses with clear message. Resume after cleanup. |
| **Input file changed between runs** | Probe hash mismatch → `CHANGED_INPUT` state → user chooses: resume (risky), reprocess, or new job. |
| **Duplicate job (same video, same output folder)** | Lock file + DB check → "Job exists. Resume / New / Overwrite?" (interactive) or error (non-interactive). |
| **Corrupted SQLite DB** | WAL mode + integrity check on open. `clipforge clean` can rebuild from manifest. |

### The Error Taxonomy (Every Failure Has a Name)

| Category | Codes | Retryable? |
|---|---|---|
| **Transient** | `ENCODE_TIMEOUT`, `SIGNAL_INTERRUPT`, `DISK_FULL` | Yes (fault budget) |
| **Size** | `OVERSIZE` | Yes (size budget, different counter) |
| **Permanent** | `DECODE_ERROR`, `UNSUPPORTED_FORMAT`, `PERMISSION_DENIED` | No — marked `FAILED` |
| **Quality** | `SSIM_BELOW_FLOOR` | No retry — marked `NEEDS_REVIEW` (file kept!) |

---

## ⏸️ Pause, Resume, Recovery — The User Experience

### Commands You'll Actually Use

```bash
# Start a job (creates DB, folder, starts encoding)
clipforge split holiday_video.mp4

# ^C here... go to sleep, come back tomorrow
clipforge resume           # Picks up exactly where it left off

# One clip failed? Retry just the failed ones
clipforge retry --failed

# One clip flagged NEEDS_REVIEW? Force re-encode with higher quality
clipforge reprocess --clip 42

# Verify everything at the end (or anytime)
clipforge verify

# See status without running anything
clipforge status

# Batch multiple videos
clipforge batch ./vacation_videos/
```

### What "Resume" Actually Does

1. Reads SQLite → finds last `COMPLETED` clip
2. Checks output folder → verifies `.webm` files exist and hashes match
3. Starts encoding at `last_completed + 1`
4. **Never re-encodes a `COMPLETED` clip** — that's the contract

---

## 📊 State Machines — The Clip Lifecycle

```
PENDING → PROBING → PLANNED → ENCODING → VERIFYING → COMPLETED
                ↓           ↓           ↓           ↓
             FAILED      FAILED      FAILED      NEEDS_REVIEW
             (permanent) (size)      (fault)     (quality)
```

- **Every transition is a DB commit** — crash mid-transition = safe state
- **Counters per clip:** `size_attempts`, `fault_attempts`, `total_encodes` (cap 8)
- **Job-level states:** `RUNNING`, `PAUSED`, `COMPLETED`, `COMPLETED_WITH_ISSUES`, `FAILED`

---

## 📁 What Lands On Disk — No Surprises

| File | Purpose | Format |
|---|---|---|
| `clip_XXXX.webm` | The actual clips | WebM (VP9 + Opus) |
| `manifest.json` | Complete audit trail | JSON (2-space indent, stable keys, no ANSI) |
| `report.json` | Human-readable summary | JSON |
| `clipforge.db` | SQLite DB (source of truth) | SQLite3 (WAL) — *stays in output folder* |
| `application.log` | Structured events | ISO-8601 UTC, level, event, message |
| `errors.log` | Just errors | Same format, grep-friendly |

> 📝 **Note:** Log files are **never colored**. They're for `less`, `grep`, `journalctl`. Color only hits the terminal (TTY).
---

## 🖥️ The CLI — Designed for Humans

### Core Commands

| Command | What It Does |
|---|---|
| `clipforge doctor` | **Run this first.** Detects FFmpeg, FFprobe, libvpx, libopus, hardware accel, reports versions and capabilities. |
| `clipforge probe <video>` | Shows full metadata + compatibility report (what converts, warnings). |
| `clipforge split <video>` | Main command. Probe → plan → encode → verify → manifest + report. |
| `clipforge split --dry-run <video>` | Shows plan without encoding. Boundaries, estimated clips, feasibility. |
| `clipforge resume` | Resume interrupted job in current folder (or `--job-id`). |
| `clipforge retry --failed` | Re-encode only `FAILED` clips. |
| `clipforge retry --review` | Re-encode `NEEDS_REVIEW` clips (try for better quality). |
| `clipforge reprocess --clip N` | Force re-encode specific clip(s), ignoring history. |
| `clipforge verify` | Full verification pass: size, duration, decode, hash. |
| `clipforge status` | Live or static view of job progress. |
| `clipforge batch <folder>` | Queue multiple videos, each in own subfolder. |
| `clipforge queue` | Manage batch queue (list, pause, cancel, reorder). |
| `clipforge benchmark` | Profile encodes on your hardware, suggest optimal defaults. |
| `clipforge config` | Show/edit configuration (YAML). |
| `clipforge clean` | Remove `.part` orphans, optionally rebuild DB from manifest. |

### Global Flags

| Flag | Effect |
|---|---|
| `--dry-run` | Plan only, no encode |
| `--jobs N` | Batch queue concurrency (default 1 — sequential for memory safety) |
| `--profile <name>` | Use named encoding profile (`balanced`, `quality`, `speed`) |
| `--on-oversize <fail|allow>` | Override size policy (default: `fail`) |
| `--tail-policy <merge|emit>` | Override tail handling |
| `--no-dashboard` | Disable live UI (for scripts, pipes, CI) |
| `--plain` | Plain text output, no color, no ANSI |
| `-v / -vv / -vvv` | Verbosity: info / debug / trace |
---

## 🎨 The Terminal Dashboard — Information Dense, Visually Quiet

```
╭────────────────────────────────────────────────────────────────╮
│  ClipForge  ████████████░░░░░░░░  47/60  (78%)  12:34 ETA     │
├────────────────────────────────────────────────────────────────┤
│  clip 47  ENCODING  ████████░░  63%  3.21/3.80 MiB  2.1× rt   │
│  clip 48  PENDING                                                  │
├────────────────────────────────────────────────────────────────┤
│  CPU 62%  │  RAM 1.1/7.8 GB  │  TEMP 71°C  │  DISK 38 GB free  │
├────────────────────────────────────────────────────────────────┤
│  Completed: 46  │  Active: 1  │  Pending: 12  │  Failed: 0    │
│  Review: 0      │  Skipped: 0                                      │
╰────────────────────────────────────────────────────────────────╯
```

- **One accent color (amber)** — brand identity, never status
- **Status colors:** Green (ok), Yellow (warn), Red (err), Blue (active)
- **Degrades gracefully:** `--plain`, `--no-color`, dumb terminals, colorblind mode
- **No emoji, no gradients, no bold sentences** — calm density

---

## ⚙️ Configuration — Sensible Defaults, Full Control

### Config File Location
```
Linux: ~/.config/clipforge/config.yaml
```

### Key Settings (YAML)

```yaml
# ClipForge configuration
version: 1

# Output
clip_duration_seconds: 10
size_limit_mib: 4
tail_policy: merge_into_previous
min_tail_seconds: 1.0

# Encoding
profile: balanced              # balanced | quality | speed
hardware_accel: false          # true = VA-API / NVENC / QSV (doctor-verified)
threads: auto                  # 0 = auto (capped by memory guard)
on_oversize: fail              # fail | allow (allow marks NEEDS_REVIEW)

# Quality
ssim_floor: 0.95
vmaf_enabled: false            # optional, sampled only

# Retries
max_size_retries: 3
max_fault_retries: 3
max_total_encodes: 8

# Guards
memory_limit_gb: 6             # peak RSS target
thermal_limit_celsius: 85
disk_free_min_gb: 2

# Dashboard
refresh_hz: 4
show_eta: true
theme: dark                    # dark | light | mono | plain

# Batch
batch_concurrency: 1           # 1 = sequential (safer on low RAM)
```

> Run `clipforge config edit` to open in `$EDITOR`. Run `clipforge config show` to see effective config (defaults + file + CLI overrides).
---

## 🔒 Privacy & Safety — Non-Negotiable

| Principle | Implementation |
|---|---|
| **Zero network** | No `import requests`, no `urllib`, no telemetry, no update checks, no crash reporting |
| **Local only** | All processing on your CPU, your disk, your memory |
| **No accounts** | Nothing to sign up for, nothing to log into |
| **Open source** | GPL-3.0 — audit the code, fork it, self-host |
| **FFmpeg licensing** | `clipforge doctor` reports your FFmpeg build's license (GPL vs LGPL components) |

---

## 📦 Project Layout — Where Code Lives

```
Personal_ClipForge/
├── src/
│   └── clipforge/
│       ├── cli/           # Typer commands (split, probe, resume, batch, etc.)
│       ├── core/          # Config, constants, errors, types
│       ├── probe/         # ffprobe wrapper, metadata extraction
│       ├── planner/       # Boundary math, tail policy, feasibility
│       ├── encoding/      # FFmpeg command builder, runner, watchdog
│       ├── optimizer/     # Bitrate budget, size loop, ladder, SSIM
│       ├── storage/       # SQLite, migrations, manifest, resume logic
│       ├── manager/       # FTJM — scheduler, retries, recovery, locks
│       ├── monitoring/    # CPU/RAM/disk/thermal, Rich dashboard
│       ├── reporting/     # report.json, terminal summaries
│       └── utils/         # Paths, hashing, atomic writes
├── tests/                 # Unit + reliability tests (pytest)
├── docs/                  # (this README, ARCHITECTURE.md, PRD.md, Design.md, etc.)
├── pyproject.toml         # Build, deps, scripts, tool config
├── LICENSE                # GPL-3.0
└── README.md              # The "official" README (this is README-2.md — the deep dive)
```

---

## 🧪 Testing Approach — Reliability Over Coverage Numbers

| Layer | What We Test | How |
|---|---|---|
| **Unit (pure logic)** | Boundary math (µs, half-open, tail), bitrate budget formula, recalculation (≥3% drop), error classifier, state machine transitions, counter caps | `pytest tests/unit/` — fast, deterministic |
| **Integration** | Probe → plan → encode → verify flow, DB persistence, atomic publish, manifest generation | `pytest tests/integration/` — uses synthetic FFmpeg sources |
| **Reliability (ugly cases)** | Ctrl+C resume, `kill -9` mid-encode, disk full (tmpfs), changed input, duplicate job, corrupt DB, orphan `.part` cleanup | `pytest tests/reliability/` — slow, real subprocesses |
| **Fixtures** | Generated by FFmpeg: 1080p30 clean, noise-stressed (worst case for size), truncated, mid-file corrupt, VFR, rotated, HDR, multichannel audio | No large media in repo — generated on demand |

### v1.0 Acceptance Bar (The "Ship It" Criteria)

1. ✅ 10-min 1080p30 video → 60 clips, **all ≤ 4 MiB**
2. ✅ Resume after mid-job interrupt → **zero duplicate encodes**, nothing missed
3. ✅ Video with one corrupt region → **only affected clips fail**, job completes
4. ✅ Peak RAM on 1080p **stays within target** (≤ 2.5 GB on 8 GB system)
5. ✅ Report, manifest, and database **agree with each other** (cross-verified)
---

## 🗺️ Roadmap — Milestones That Ship

| # | Milestone | Delivers | Done When |
|---|---|---|---|
| **M0** | Setup | Repo, pyproject, Typer skeleton, `doctor` | `doctor` detects FFmpeg, FFprobe, libvpx, libopus |
| **M1** | Probe + Planner | `probe`, `split --dry-run` | Boundary unit tests pass (tail, VFR, non-zero start) |
| **M2** | MVP Encode | One video → clips, basic size check + retry, no DB | 10-min test → 60 clips, all ≤ 4 MiB |
| **M3** | Optimizer | Budget, CQ mode, size loop, two-pass, ladder, SSIM gate | Predictable on noisy + 4K fixtures; caps enforced |
| **M4** | Persistence | SQLite, state machines, atomic publish, manifest, resume | Ctrl+C → resume, zero duplicate encodes |
| **M5** | Fault Tolerance | Error classifier, fault retries, watchdog, `retry`, `reprocess`, `verify` | Kill-test + corrupt-test pass |
| **M6** | Batch + Queue + Dashboard | `batch`, `queue`, Rich dashboard, locks | Multi-video job stable |
| **M7** | Performance | Resource monitor, thermal guard, `benchmark`, profile tuning | Defaults finalized from real measurements |
| **M8** | Hardening | Full test matrix, docs, error message polish | Acceptance criteria above pass |
| **M9** | Packaging | PKGBUILD, pipx, man page, completion | Clean install on Arch |

> **Current status:** Phase 1 of 15 done (M0 + M1 skeleton). The master blueprint, full doc suite, and installable package skeleton exist. Video splitting starts landing in Phase 2+.

---

## 🤝 Honest Limits — What ClipForge *Won't* Do (v1.0)

| Limit | Why | Workaround / Future |
|---|---|---|
| **Not every 10s clip fits 4 MiB at original quality** | Physics. High motion + high res = more bits. | Smart Balance drops quality *controlled*, flags `NEEDS_REVIEW` |
| **WebM/VP9/Opus doesn't carry every source format** | Codec constraints | 4:2:2/4:4:4 → 4:2:0 (recorded), 10-bit → VP9 Profile 2 (warn), HDR → kept with warning |
| **Gapless playback not guaranteed** | Opus pre-skip + independent clips = possible seam | Join clips back with a future `clipforge join` tool |
| **Upfront corruption detection is bounded** | Quick check = structure only, not content | `--deep-scan` trades time for certainty; per-clip containment covers default |
| **4K on 8 GB RAM is tight** | VP9 memory scales with resolution | Memory guard lowers threads/lag; ladder or `FAILED_SIZE` is honest end |
| **Hardware accel is opt-in** | Driver/FFmpeg build variance | `doctor` reports capability; you enable knowingly |
| **Sequential encoding caps throughput** | 1 hour 1080p = 360 clips = real wall time | Design spends time on reliability + quality/byte; `benchmark` makes tradeoff visible |

---

## 📄 License

**GPL-3.0** — See [LICENSE](LICENSE).

> ⚖️ **One caveat:** FFmpeg's own licensing is build-dependent. Builds with GPL components carry different terms than minimal (LGPL) ones. `clipforge doctor` reports which build you're running with — know your stack.

---

## 🙏 Closing Thoughts

ClipForge exists because **I needed it and couldn't find it**. If you've ever:

- Uploaded a 2 GB video to a cloud converter just to get 4 MB clips
- Had a 3-hour encode die at 90% with no resume
- Wondered "which of these 200 clips actually finished?"
- Wanted a tool that *just works* on your laptop without melting it

...this is for you.

**It's not done yet.** But the foundation is solid, the plan is clear, and every decision traces back to a real problem I've personally felt.

---

*Built with frustration, patience, and too much coffee. ☕*

**— Aakash**

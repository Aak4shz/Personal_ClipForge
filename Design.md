# ClipForge Design

| | |
|---|---|
| **Document** | Design, version 1.0 |
| **Status** | Approved for build |
| **Owner** | Aakash |
| **Applies to** | Terminal dashboard, CLI output, reports, logs |
| **Built in** | Phase 12 (dashboard), Phases 1 to 11 (message voice) |
| **Sources** | [PRD.md](PRD.md), [ARCHITECTURE.md](ARCHITECTURE.md), [Rules.md](Rules.md) |
| **Last updated** | 2026-11-13 |

ClipForge is a command-line tool, so its design lives in the terminal: color, type, layout, symbols, motion, and the voice of every message it prints. A GUI would have buttons and margins to design. This product has boxes, tables, and words, and the same rules of craft apply to all three.

One principle sits above everything here, inherited from RULE-71 and RULE-74: **the interface never paints a picture the database does not back.** A clip that has not been verified never renders green, whatever the code around it wishes.

---

## Contents

1. [Design principles](#1-design-principles)
2. [Color system](#2-color-system)
3. [Themes](#3-themes)
4. [Fonts](#4-fonts)
5. [Typography](#5-typography)
6. [Layout system](#6-layout-system)
7. [Symbols](#7-symbols)
8. [Motion](#8-motion)
9. [Voice and microcopy](#9-voice-and-microcopy)
10. [Mockups](#10-mockups)
11. [Output artifacts](#11-output-artifacts)
12. [Design don'ts](#12-design-donts)
13. [Implementation map](#13-implementation-map)

---

## 1. Design principles

| # | Principle | What it decides |
|---|---|---|
| D1 | Truth before beauty | A status renders in its color only after the database says so. Unverified work looks like work in progress |
| D2 | Calm density | The dashboard is information-dense but visually quiet: one accent color, few weights, no decoration |
| D3 | Degrade with dignity | Every visual feature has a stated fallback for dumb terminals, pipes, and colorblind users |
| D4 | Words carry the meaning | Color marks state; words state it. Any colored item also reads as text when color is gone |
| D5 | One accent | Amber belongs to the product identity. Green, red, yellow, and blue belong to status. The two groups never swap roles |

## 2. Color system

### 2.1 Palette tokens

Token names are the implementation contract (`monitoring/theme.py`). Hex values target truecolor terminals; the 256-color index is the downgrade path; Rich falls back automatically for 16-color terminals.

| Token | Hex | 256 | Used for |
|---|---|---|---|
| `brand.amber` | `#F5A524` | 214 | Banner rule, the recovery command line, headline numbers such as clip 47/60 |
| `status.ok` | `#3FB950` | 114 | COMPLETED states, passing gates, the full portion of a progress bar |
| `status.warn` | `#E3B341` | 179 | NEEDS_REVIEW, PAUSED, INTERRUPTED, COMPLETED_WITH_ISSUES |
| `status.err` | `#F85149` | 203 | FAILED, FAILED_SIZE, FAILED_LIMIT, error prefixes |
| `status.active` | `#58A6FF` | 75 | ENCODING, VERIFYING, RETRYING, anything in flight |
| `text.primary` | `#E6EDF3` | 255 | Values, data, body text |
| `text.secondary` | `#9DA7B3` | 245 | Field labels, captions, unit suffixes |
| `text.muted` | `#6E7681` | 243 | Timestamps, elapsed clocks, anything skippable |
| `ui.border` | `#30363D` | 236 | Panel frames, table rules |
| `ui.surface` | `#161B22` | 234 | Panel background on truecolor terminals; unused elsewhere |
| `bar.empty` | `#30363D` | 236 | Unfilled progress bar track |

The amber accent is a forge reference: fire, metal, heat. It sits far from the four status hues, so the eye never confuses brand with state. Status colors use known terminal-safe values with a luminance gap between green and red, which matters for red-green colorblind users (see 2.4).

### 2.2 State-to-color mapping

Every state in the machine maps to exactly one token. There is no "almost done" color; a state is either terminal, in flight, or waiting.

| State | Token | Non-color label |
|---|---|---|
| COMPLETED | `status.ok` | the word itself |
| NEEDS_REVIEW | `status.warn` | the word itself |
| FAILED, FAILED_SIZE, FAILED_LIMIT | `status.err` | the word itself |
| ENCODING, VERIFYING, RETRYING | `status.active` | the word itself |
| PAUSED, INTERRUPTED, COMPLETED_WITH_ISSUES | `status.warn` | the word itself |
| PENDING, SKIPPED, CANCELLED | `text.muted` | the word itself |

### 2.3 Contrast

Contrast targets, computed against the `ui.surface` value of the default dark theme:

| Pair | Ratio | Verdict |
|---|---|---|
| `text.primary` on surface | about 14 to 1 | Clears 4.5:1 with room to spare |
| `brand.amber` on surface | about 8 to 1 | Fine for large glyphs and numbers |
| `status.ok` on surface | about 7 to 1 | Passes |
| `status.err` on surface | about 5 to 1 | Passes |
| `text.muted` on surface | about 4 to 1 | Below target, deliberately |

The muted token misses 4.5:1 on purpose. It is reserved for information the user can skip: clocks, timestamps, padding digits. Nothing a decision depends on renders in muted text. If a value matters, it gets `text.primary` or a status color.

### 2.4 Accessibility

| Concern | Rule |
|---|---|
| Colorblind users | Color marks state; text labels it (D4). Every colored item also carries its state name, position, or both. The green and red tokens differ in luminance, not only hue |
| `NO_COLOR` environment variable | Respected before config. Output renders with no color at all |
| Light terminal backgrounds | The `forge-light` theme swaps in darker token values; see section 3 |
| Screen readers and pipes | Non-TTY output is plain text with no ANSI sequences at all |
| Photosensitivity | No flashing, no blinking, one spinner at a gentle rate (section 8) |

## 3. Themes

Four themes ship. One config key selects them: `dashboard.theme`.

| Theme | Background assumption | Notes |
|---|---|---|
| `forge-dark` (default) | Dark terminal | The token table above, unchanged |
| `forge-light` | Light terminal | Same hues, darkened for contrast on white: `status.ok` `#1A7F37`, `status.err` `#CF222E`, `status.warn` `#9A6700`, `status.active` `#0969DA`, `brand.amber` `#9A5B00`, `text.primary` `#1F2328`, `text.secondary` `#656D76`, `ui.border` `#D0D7DE`, `ui.surface` unused |
| `mono` | Any | Default color only, plus bold and dim. For 16-color terminals and conservative SSH sessions |
| `plain` | Any | No color, ASCII characters instead of box drawing and blocks. Also forced by `NO_COLOR`, `--no-dashboard`, and non-TTY output |

Selection order, first match wins:

1. `NO_COLOR` set in the environment: `plain`
2. Non-TTY stdout: `plain`
3. `--plain` or `--no-dashboard` flag: `plain`
4. `dashboard.theme` in config: that theme
5. Otherwise: `forge-dark`

The chain means a user never has to configure anything for sensible output, and a script never receives escape sequences it did not ask for.

## 4. Fonts

The product does not embed or load fonts. The user's terminal font decides everything, so the design states what it needs from that font and what to pick.

### 4.1 Requirements

| Requirement | Why |
|---|---|
| Monospace, naturally | Column alignment in tables and the dashboard depends on it |
| Box-drawing glyphs: `─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼` and doubles `═ ║ ╔ ╗ ╚ ╝ ╠ ╣ ╦ ╩ ╬` | Panel frames and the banner |
| Block elements: `█ ░` | Progress bar fill and track |
| Braille spinner range: `⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏` | The encode spinner |

Every terminal emulator ships these ranges in its default font today. When a font lacks them (rare, but real over serial connections), the `mono` or `plain` theme is the answer, and `plain` needs none of them.

### 4.2 Recommended fonts

| Font | Character |
|---|---|
| JetBrains Mono | Tall x-height, clear at small sizes, designed for code |
| Iosevka | Narrow; fits the dashboard's density on small windows |
| IBM Plex Mono | Even rhythm, good for long log reading |
| Fira Code | Familiar default in the Linux world |
| Cascadia Code | Strong glyph coverage on Windows terminals |

Any of these renders the dashboard identically in structure. The design does not depend on ligatures or font features; a plain DejaVu Sans Mono works too, just with less polish.

## 5. Typography

Terminal typography has no font sizes to scale, so hierarchy comes from four tools: weight, color, case, and spacing. Used together they produce the scale below; used carelessly they produce noise.

### 5.1 Text hierarchy

| Level | Style | Where it appears |
|---|---|---|
| L0 banner | Uppercase, bold, inside the double-line frame | Dashboard header and `info` output only |
| L1 section head | Bold, `text.primary` | Panel titles inside the dashboard, report sections |
| L2 label | `text.secondary`, sentence case, trailing two spaces | Field labels: `input`, `profile`, `eta` |
| L3 value | `text.primary` or a status token | Everything after a label |
| L4 muted | `text.muted` | Clocks, timestamps, skipped details |

### 5.2 Case and emphasis rules

| Rule | Detail |
|---|---|
| Sentence case everywhere | Except the L0 banner. A heading like "Size against budget" never becomes "Size Against Budget" |
| Uppercase only in the banner and status badges | Status badges such as `NEEDS_REVIEW` are uppercase because the state machine defines them that way |
| Bold, at most once per panel | Bold marks the single most important number on screen, usually the clip counter. Never bold whole lines |
| No italics | Terminal italic support is unreliable; the design does not use it |
| No underline | Underline is reserved for the future `--help` link syntax, nothing else |

### 5.3 Numbers and units

| Quantity | Format | Example |
|---|---|---|
| File size, 1 MiB and up | Two decimals, MiB | `3.42 MiB` |
| File size, under 1 MiB | One decimal, KiB | `512.0 KiB` |
| Exact byte counts | Raw integer, JSON and tables only | `3741920` |
| Bitrate | Two decimals, Mbps | `3.12 Mbps` |
| Percent | Integer plus bar; no decimals in the bar label | `78%` |
| Duration | `HH:MM:SS`, hours dropped when zero | `06:40` |
| Counts | Plain integers, no separators | `720` |

Alignment rules: numeric columns right-align; label-value pairs align values after the longest label; the decimal point never moves between rows of the same column. A table where `3.42` and `512.0` sit in the same column without a fixed decimal width is a bug.

## 6. Layout system

### 6.1 Dashboard zones

The dashboard is a stack of five zones inside one double-line frame. Zone order never changes, because regular watchers build muscle memory for where each fact lives.

| Zone | Rows | Holds |
|---|---|---|
| Z1 header | 2 | Title, version, input summary: name, duration, resolution, fps, profile |
| Z2 progress | 2 | Bar, percentage, clip counter, ETA, elapsed |
| Z3 current | 3 | Active clip name, attempt counters, size against budget |
| Z4 vitals | 1 | CPU, RAM, temperature, free disk |
| Z5 counters | 2 | Status counts, one line each |

Full mockup with all zones occupied:

```text
╔══════════════════════════════════════════════════╗
║                  CLIPFORGE v2                    ║
║            OFFLINE VIDEO PROCESSOR               ║
╠══════════════════════════════════════════════════╣
║ Input:  holiday_video.mp4                        ║
║ Duration: 00:10:00   1920x1080   30 fps          ║
║ Output: WebM / VP9 / Opus   Profile: balanced    ║
╠══════════════════════════════════════════════════╣
║ Progress: 47 / 60     [███████████████░░░░] 78%  ║
║ ETA: 00:06:40         Elapsed: 00:23:10          ║
║                                                  ║
║ Current: clip_0048.webm                          ║
║ Attempt: size 2/4 · fault 0/3                    ║
║ Size: 3.42 MiB / 4.00 MiB (target 3.80)          ║
╠══════════════════════════════════════════════════╣
║ CPU 62%   RAM 1.1 GB   Temp 71C   Disk 38 GB free║
╠══════════════════════════════════════════════════╣
║ Completed 47 · Active 1 · Pending 12             ║
║ Failed 0 · Needs review 0                        ║
╚══════════════════════════════════════════════════╝
```

### 6.2 Adaptation

| Condition | Response |
|---|---|
| Terminal under 20 rows | Compact mode: Z3 merges into Z2, vitals drop, total height about 10 rows |
| Terminal under 80 columns | Vitals compress to one line, long input names truncate from the middle (`…day_video.mp4`) |
| Terminal over 120 columns | Zones keep their width; the frame does not stretch to full width. A 60-column-wide dashboard on a 200-column terminal reads better than a stretched one |
| No TTY | No dashboard at all: plain lines, one per event (section 10.4) |

### 6.3 Progress bar

| Property | Spec |
|---|---|
| Fill character | `█` in `status.ok` |
| Track character | `░` in `bar.empty` |
| Width | Terminal width minus labels, clamped between 20 and 60 cells |
| Label format | `Progress: 47 / 60   [bar] 78%` |
| Never moves backward | A resumed job recalculates before drawing; the bar never re-fills on screen |
| Job bar vs clip bar | The job bar counts clips; a thinner sub-bar under Z3 shows frame progress inside the current clip from `-progress` frames |

### 6.4 Tables

`status`, `report`, and `queue` print tables:

| Property | Spec |
|---|---|
| Frame | Single-line rules in `ui.border`, no vertical lines between columns |
| Header | Bold, followed by a rule line |
| Numbers | Right-aligned, fixed decimal width per column |
| Paths | Truncated from the middle when over the column width |
| Row color | Only the status column carries a status token; rows stay neutral |

### 6.5 Spacing

One blank line between zones, two between separate panels, one before and after the dashboard itself. Inside panels, labels and values sit on their own lines with two trailing spaces after labels. Never more than one consecutive blank line anywhere in CLI output; vertical padding is spacing, not aesthetics.

## 7. Symbols

The allowed set is small, and each symbol has a stated job.

| Symbol | Job | ASCII fallback |
|---|---|---|
| `█ ░` | Bar fill and track | `#` and `.` |
| `═ ║ ╔ ╗ ╚ ╝ ╠ ╣` | Frame and banner | `=` and `|` |
| `─ │` | Table rules, inner separators | `-` and `|` |
| `·` | Separator between counters on one line | `,` |
| `…` | Middle truncation | `...` |
| Braille frames | Spinner | `| / - \\` in mono, nothing in plain |
| `●` | Status dot next to per-clip lines in verbose mode | `[ok]`, `[REV]`, `[FAIL]`, `[ .. ]` |

Banned from product output: emoji of any kind, decorative arrows, sparkles, check-mark rows, the bell character, clear-screen sequences, and any full-screen redraw. The dashboard updates in place through Rich's Live region; it does not own the terminal.

## 8. Motion

| Element | Spec |
|---|---|
| Spinner | Braille, 120 ms per frame (about 8 frames per second). Slow enough to feel calm, fast enough to read as alive |
| Dashboard refresh | 4 Hz (250 ms). Data sampling and rendering share this tick |
| ETA smoothing | Rolling mean over the last 10 completed clips, so one slow 4K clip does not swing the estimate wildly |
| Elapsed clock | Real wall clock, `text.muted` |
| Everything else | Static. No pulsing borders, no breathing colors, no animated anything |

Motion in a terminal earns its place only when it reports state: the spinner says a clip is running, the bar says how far. Decoration that moves is noise, and this product's whole design language is quiet.

## 9. Voice and microcopy

The CLI speaks in short, factual lines. RULE-19 already fixes the error shape; this section fixes the tone around it.

### 9.1 Message shapes

| Kind | Shape | Exit code |
|---|---|---|
| Error | `error:` line, meaning line, `fix:` line with a runnable command | non-zero, from the table |
| Warning | `warning:` line, optional second line of context | never changes the exit code alone |
| Confirmation | The exact consequence, then the prompt | 0 on yes, 130-like abort otherwise |
| Status | One line per event, machine-sortable in plain mode | n/a |

### 9.2 Real examples

Error:

```text
error: cannot read holiday_video.mp4
the file exists but this user has no read permission
fix: check ownership with `ls -l holiday_video.mp4` or run as a user with read access
```

Warning:

```text
warning: 4K 60 fps source at balanced profile
about 0.006 bits per pixel per frame; quality will drop or clips will fail the size limit
run `clipforge split video.mp4 --dry-run` to see the full estimate
```

Confirmation:

```text
holiday_video.mp4: 600 s, plan 60 clips, output about 234 MiB in ./holiday_video/
proceed? [y/N]
```

Recovery line after a job with issues (rendered in `brand.amber`):

```text
run: clipforge retry 12 --failed
```

### 9.3 Tone rules

| Do | Do not |
|---|---|
| Name the file, the clip, the number | Say "an error occurred" |
| Sentence case | SHOUT, and never mixed-case emphasis |
| Period-free short lines in output | Exclamation marks, anywhere |
| "cannot read", "refused", "failed" | "oops", "uh-oh", "whoops", apology theater |
| `fix:` with a real command | "see documentation" with no pointer |
| Lowercase `error:` and `warning:` prefixes (cargo-style) | `ERROR!!!` and alarm formatting |

## 10. Mockups

### 10.1 Dashboard (default theme, dark terminal)

Shown in section 6.1.

### 10.2 Plain mode (piped or `--plain`)

```text
ClipForge 2.0.0
input holiday_video.mp4 600s 1920x1080 30fps profile balanced
[###############.....] 47/60 78% eta 06:40 elapsed 23:10
clip 48 encoding  size 2/4 fault 0/3  3.42/3.80 MiB
cpu 62% ram 1.1G temp 71C disk 38G free
completed 47 active 1 pending 12 failed 0 review 0
```

One line per event, no ANSI sequences, greppable with plain tools.

### 10.3 Report summary (end of a job with issues)

```text
job 12  holiday_video.mp4  600 s  60 clips planned

completed   58
review       1
failed       1

largest clip 3.83 MiB   wall time 23:08   encodes 71

failed
  #17  DECODE_ERROR   permanent   1 attempt
review
  #42  SSIM 0.913 below 0.95

run: clipforge retry 12 --failed
```

The `run:` line is the last thing on screen, in the accent color, because the next command is the single most useful fact the tool can leave behind.

### 10.4 Error in plain mode

```text
error: cannot read holiday_video.mp4
the file exists but this user has no read permission
fix: check ownership with `ls -l holiday_video.mp4` or run as a user with read access
```

Identical text with or without color. RULE-19's shape survives every theme.

## 11. Output artifacts

Files the tool writes are not decorated. They are for machines and grepping.

| Artifact | Rules |
|---|---|
| `manifest.json`, `report.json` | Two-space indent, stable key order, exact byte counts, trailing newline, no ANSI ever |
| `application.log`, `errors.log`, per-job logs | ISO-8601 UTC timestamp, level, event type, message: `2026-11-13T08:45:12Z INFO clip.encode.start clip=47` |
| Log color | None. Files are read with less, grep, and journalctl, and color codes would poison all three |
| Terminal output | Color only when stdout is a TTY and no theme forbids it |

## 12. Design don'ts

The negative list, stated once so it does not have to be re-litigated in review:

1. No emoji in any output, ever
2. No decorative arrows, sparkles, or ASCII art beyond the banner
3. No color gradients, in the bar or anywhere; two flat tokens per bar
4. No bold rows, no bold sentences; bold marks one number per panel at most
5. No uppercase sentences; the banner and state names own uppercase
6. No bell, no clear-screen, no full-screen mode; the dashboard lives inside the user's scrollback, not above it
7. Color never replaces text (D4); a colorblind user must lose nothing
8. No third color in a progress bar; success green on neutral track, done
9. No "creative" error messages; RULE-19's shape is the whole personality
10. No motion beyond the spinner and bar refresh

## 13. Implementation map

| Design element | Lands in | Where |
|---|---|---|
| Token tables and theme selection | Phase 12 | New file `monitoring/theme.py` |
| Dashboard zones, bar, adaptation | Phase 12 | `monitoring/dashboard.py` |
| Table rendering | Phase 12 onward | `cli/commands/status.py`, `reporting/summary.py` |
| Message voice | Phases 1 onward | `cli/**`, `core/errors.py`; every error printed from day one follows section 9 |
| Symbols and fallbacks | Phase 12 | `monitoring/theme.py` (tokens) and `dashboard.py` (rendering) |
| Plain and mono themes | Phase 12 | `monitoring/theme.py` |
| Light theme values | Phase 12 | `monitoring/theme.py` |

Adding `monitoring/theme.py` extends the module table in ARCHITECTURE.md section 4.9; that document gets updated in the same commit that lands Phase 12, per the docs-sync discipline in Phases.md.

---

*This document describes presentation only. It changes no behavior, no caps, and no state machines. Where a design choice would ever conflict with reporting honesty (RULE-71, RULE-74), the rules win and the design gets fixed.*

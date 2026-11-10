# Design System — Agent Router

## Mode

Operate: the visitor completes a task (dump thoughts, triage, delegate, review results). Scanability, consistency, native expectations, and the real usage scene outrank expression. Brand lives in precise details.

## Physical scene

A developer at a desk, obsidian-dark environment, long engineering sessions, zero sensory overload, low visual fatigue. Dark mode forced by the scene — not a category default.

## Color strategy

Restrained: obsidian neutrals plus one electric-blue accent carrying ~30% of the surface (active/running states). Amber for warnings/blocked, green for done. No gradients, no glass, no neon.

## Palette (tokens)

| Token | Hex | Role |
|---|---|---|
| `--bg-window` | `#101216` | Core background / canvas |
| `--bg-sidebar` | `#161920` | Left nav / file explorer panel |
| `--bg-header` | `#0D0F13` | Top bar / titlebar |
| `--bg-card` | `#1A1D26` | Prompt capsule, card panels, folding terminal |
| `--bg-card-hover` | `#212530` | Hover surface states |
| `--fg-primary` | `#E2E4EB` | 88% warm ivory for chat & headings |
| `--fg-secondary` | `#989EA8` | 60% muted slate for metadata |
| `--fg-tertiary` | `#646B78` | 40% dim slate for line numbers, file dates |
| `--fg-mono` | `#D1D5DB` | Monospace code & terminal output |
| `--border-subtle` | `#242833` | Default panel & divider borders |
| `--border-active` | `#363C4D` | Focused inputs, active tabs |
| `--accent-primary` | `#007ACC` | Electric blue — active/running/primary |
| `--accent-secondary` | `#CCA700` | Amber — triaging/blocked/warning |
| `--accent-tertiary` | `#89D185` | Green — done/settled |
| `--badge-bg` | `#242018` | Warm dark amber container |
| `--badge-border` | `#4E3E26` | Muted amber border |
| `--selection` | `#264F78` | Selection highlight |

## Typography

- Family: Geist (headline, body, label), Geist Mono (code, terminal, token counts)
- Scale: body 14px, display max 6rem, tracking floor -0.04em
- Body measure: 65–75ch at desktop
- One family for UI + mono for data — no mixing without reason

## Layout

Orca-inspired dark IDE, three zones:

```
┌─────────────────────────────────────────────────────────┐
│  Agent Router  [Project ▼]  [Model: NIM 3 ▼]  [⚙️]   │
├──────────────┬──────────────────────────────────────────┤
│              │                                          │
│  Left Nav    │  Main: Concentrated Chat + Card Detail   │
│  - Projects  │                                          │
│  - Kanban    │  > dump your thoughts here _________     │
│  - Agents    │                                          │
│              │  [Agent: codex] [Model: gpt-6.1-sol]     │
│              │  [Tokens: 2.4k] [Status: running ▶]      │
│              │                                          │
│              │  Agent output streams here...            │
│              │                                          │
│              │  Reply: _______________ [Send]           │
│              │                                          │
│              │  Delegation flow: user → NIM 3 → codex   │
│              │                                          │
│              │  Analytics: agent usage, token costs     │
│              │                                          │
└──────────────┴──────────────────────────────────────────┘
│  Status bar: RAM · SSD · Sensor · time · connection   │
└─────────────────────────────────────────────────────────┘
```

- Left nav: 80px compact, icon + text, Projects / Kanban / Agents / Analytics
- Main: ~75% width, concentrated chat input at top or bottom, card detail overlay
- Right: optional file tree / agent registry (collapsible)
- Bottom status bar: system telemetry + connection status

## Components (refuse list applied)

Banned (generic AI defaults):
- Same-size cards of icon + heading + text as page structure
- Hero-metric template (big number, small label, supporting stats)
- Eyebrow/kicker labels above headings
- Section numbers (01/02/03)
- Gradient text, glass/blur decoration
- Colored border-left/right above 1px on cards
- Hard offset shadows outside neobrutalism
- Monospace as "technical" costume
- System display face as display voice
- Unicode glyphs/emoji as icon system

Required states per control: hover, disabled, loading, error, empty.

## Motion

One authored moment (page-load reveal), not scattered effects. Exponential ease-out from visible default. No fade-and-slide-up on every section, no hover transitions on every card.

## Finish

unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

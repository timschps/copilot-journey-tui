# 🚀 Copilot Journey TUI

A beautiful terminal dashboard that visualizes your GitHub Copilot CLI learning journey.

Built with [Textual](https://github.com/Textualize/textual) and the Catppuccin Mocha theme.

## Features

- **📊 Dashboard** — Overview stats, phase classification, weekly activity sparkline, ROI estimate
- **📅 Timeline** — Interactive milestone history with color-coded phases
- **📖 Walkthrough** — Guided narrative through your evolution phases with dimension breakdowns

## Install

```bash
pip install textual
```

## Usage

```bash
python app.py
```

The TUI auto-detects your Copilot CLI session database at `~/.copilot/session-store.db`.

Specify a custom path:

```bash
python app.py --db /path/to/session-store.db
```

## Navigation

| Key       | Action                  |
|-----------|-------------------------|
| `1/2/3`   | Switch tabs             |
| `Tab`     | Next tab                |
| `↑/↓`     | Navigate timeline rows  |
| `←/→`     | Navigate walkthrough    |
| `q`       | Quit                    |

## How It Works

Reads your local Copilot CLI session history (100% offline, nothing leaves your machine) and:

1. Splits your usage into 3 time windows
2. Scores each window on 6 dimensions (depth, breadth, delivery, tools, consistency, variety)
3. Classifies phases: **Explorer → Builder → Orchestrator → Architect**
4. Detects milestones (first multi-file build, marathon sessions, etc.)
5. Estimates ROI with conservative/moderate/aggressive ranges

## Phase Classification

| Phase | Score | Description |
|-------|-------|-------------|
| 🔍 Explorer | 0-6 | Getting acquainted — short sessions, quick questions |
| 🔨 Builder | 7-11 | Real work — multi-file projects, growing confidence |
| 🎯 Orchestrator | 12-15 | Complex workflows — delegation, cross-file changes |
| 🏛️ Architect | 16-18 | System-level — strategic automation, full mastery |

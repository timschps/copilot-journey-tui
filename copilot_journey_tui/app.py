"""Copilot Journey TUI — A beautiful terminal dashboard for your Copilot CLI learning journey."""

import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import (
    DataTable, Footer, Header, Label, Sparkline, Static, TabbedContent, TabPane,
)

from rich.text import Text

from copilot_journey_tui.data import JourneyData, Phase, find_database, load_data

# ── Phase metadata ──────────────────────────────────────────────────────────

PHASE_DESCRIPTIONS = {
    Phase.EXPLORER: (
        "You were getting acquainted with Copilot — short sessions, "
        "single-file interactions, and quick questions. Testing the waters."
    ),
    Phase.BUILDER: (
        "You started trusting Copilot with real work — longer sessions, "
        "multi-file projects, and more complex tasks. Building confidence."
    ),
    Phase.ORCHESTRATOR: (
        "You began orchestrating complex workflows — deep sessions, "
        "cross-file changes, and delegation. Copilot became a partner."
    ),
    Phase.ARCHITECT: (
        "You're leveraging Copilot at the architectural level — system "
        "design, cross-repo work, and strategic automation. Full mastery."
    ),
}

PHASE_ANALOGIES = {
    Phase.EXPLORER: "Like learning to cook: reading recipes and trying simple dishes.",
    Phase.BUILDER: "Like cooking dinner parties: improvising and handling multi-course meals.",
    Phase.ORCHESTRATOR: "Like running a restaurant kitchen: coordinating multiple stations.",
    Phase.ARCHITECT: "Like designing the menu: thinking in systems and shaping experiences.",
}


# ── Widgets ─────────────────────────────────────────────────────────────────

class DashboardPane(Static):
    """Dashboard tab with overview stats, phase evolution, and ROI."""

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data

        # ── Stats row ──
        with Horizontal(classes="stats-row"):
            yield Static(
                f"[b]📊 Overview[/b]\n\n"
                f"  Sessions     [b]{d.total_sessions}[/b]\n"
                f"  Active Days  [b]{d.active_days}[/b]\n"
                f"  Files        [b]{d.total_files:,}[/b]\n"
                f"  Turns        [b]{d.total_turns:,}[/b]\n"
                f"  Repos        [b]{d.unique_repos}[/b]",
                classes="stat-card",
            )

            color = Phase.color(d.current_phase)
            name = Phase.name(d.current_phase)
            emoji = Phase.emoji(d.current_phase)
            pct = int(d.current_score / 18 * 100)
            bar = "━" * (d.current_score * 2) + "─" * ((18 - d.current_score) * 2)

            yield Static(
                f"[b]🏆 Current Phase[/b]\n\n"
                f"  [{color}]{emoji} {name}[/{color}]\n\n"
                f"  [{color}]{bar}[/{color}]\n"
                f"  Score: [b]{d.current_score}[/b]/18 ({pct}%)",
                classes="stat-card",
            )

        # ── Weekly activity sparkline ──
        if d.sparkline_data and any(v > 0 for v in d.sparkline_data):
            yield Label("[b]📈 Weekly Activity[/b]", classes="section-label")
            yield Sparkline(d.sparkline_data, summary_function=max, classes="activity-spark")

        # ── Phase evolution ──
        yield Label("[b]🔄 Phase Evolution[/b]", classes="section-label")
        for w in d.windows:
            c = Phase.color(w.phase)
            n = Phase.name(w.phase)
            filled = w.score * 2
            empty = (18 - w.score) * 2
            bar = f"[{c}]{'█' * filled}[/{c}]{'░' * empty}"
            yield Static(
                f"  {w.label:<22} {bar} [{c}]{n:<13}[/{c}] ({w.score}/18)",
                classes="phase-bar",
            )

        # ── ROI ──
        yield Label(f"[b]💰 Estimated Time Saved ({d.total_days} days)[/b]",
                    classes="section-label")
        max_roi = max(d.roi.aggressive, 1)
        for label, value, c in [
            ("Conservative", d.roi.conservative, "#585b70"),
            ("Moderate    ", d.roi.moderate, "#a6e3a1"),
            ("Aggressive  ", d.roi.aggressive, "#f9e2af"),
        ]:
            filled = int(value / max_roi * 24)
            bar = f"[{c}]{'█' * filled}[/{c}]{'░' * (24 - filled)}"
            yield Static(f"  {label}  {bar} [b]{value:.0f}h[/b]", classes="roi-bar")

        yield Static(
            f"  [dim]Quick Q&A: {d.roi.quick_qa} │ Code Gen: {d.roi.code_gen} │ "
            f"Deep Build: {d.roi.deep_build} │ Workflow: {d.roi.workflow}[/dim]",
            classes="roi-detail",
        )


class TimelinePane(Static):
    """Timeline tab with milestone table."""

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Label("[b]📅 Milestone Timeline[/b]", classes="section-label")

        table = DataTable(classes="timeline-table")
        table.cursor_type = "row"
        table.add_columns("Date", "●", "Milestone", "Detail")

        for ms in self.data.milestones:
            c = Phase.color(ms.phase)
            table.add_row(
                ms.date.strftime("%b %d"),
                Text("●", style=c),
                Text(ms.title, style=f"bold {c}"),
                Text(ms.detail, style="dim"),
            )

        yield table


class WalkthroughPane(Static):
    """Walkthrough tab — step through each phase with ← / → keys."""

    page = reactive(0)

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Static(id="walk-content")
        yield Static(
            "[dim]  ← / → to navigate phases  │  Tab to switch tabs[/dim]",
            classes="walk-nav",
        )

    def on_mount(self) -> None:
        self._render_page()

    def watch_page(self, _old: int, _new: int) -> None:
        self._render_page()

    def _render_page(self) -> None:
        widget = self.query_one("#walk-content", Static)
        if not self.data.windows:
            widget.update("No data available.")
            return

        page = min(self.page, len(self.data.windows) - 1)
        w = self.data.windows[page]
        c = Phase.color(w.phase)
        name = Phase.name(w.phase)
        emoji = Phase.emoji(w.phase)
        n = max(len(w.sessions), 1)

        avg_turns = sum(s.turn_count for s in w.sessions) / n
        avg_files = sum(s.file_count for s in w.sessions) / n
        desc = PHASE_DESCRIPTIONS.get(w.phase, "")
        analogy = PHASE_ANALOGIES.get(w.phase, "")

        dim_lines = []
        for dim_val, dim_label in zip(w.dimensions, w.dim_labels):
            bar = f"[{c}]{'━' * (dim_val * 4)}[/{c}]{'─' * ((3 - dim_val) * 4)}"
            dim_lines.append(f"  {dim_label:<18} {bar} {dim_val}/3")

        text = (
            f"\n  [{c}]{emoji} THE {name.upper()} PHASE[/{c}]\n"
            f"  [dim]{w.label}[/dim]\n"
            f"  {'─' * 40}\n\n"
            f"  {desc}\n\n"
            f"  [b]Key Characteristics:[/b]\n"
            f"  • Sessions: [b]{len(w.sessions)}[/b]\n"
            f"  • Avg turns/session: [b]{avg_turns:.0f}[/b]\n"
            f"  • Avg files/session: [b]{avg_files:.0f}[/b]\n"
            f"  • Phase score: [b]{w.score}[/b]/18\n\n"
            f"  [b]Dimension Scores:[/b]\n"
            + "\n".join(dim_lines)
            + f"\n\n  💡 [i]{analogy}[/i]\n\n"
            f"  [dim]Page {page + 1} of {len(self.data.windows)}[/dim]"
        )
        widget.update(text)


# ── Main app ────────────────────────────────────────────────────────────────

class JourneyApp(App):
    """Copilot Learning Journey TUI."""

    TITLE = "Copilot Learning Journey"
    SUB_TITLE = "Your AI pair-programming evolution"

    CSS = """
    Screen {
        background: #1e1e2e;
    }

    Header {
        background: #313244;
        color: #cdd6f4;
    }

    Footer {
        background: #313244;
    }

    TabbedContent {
        padding: 0 1;
    }

    ContentSwitcher {
        height: 1fr;
    }

    TabPane {
        padding: 1 0;
        height: auto;
    }

    .stats-row {
        height: auto;
        margin-bottom: 1;
    }

    .stat-card {
        border: round #585b70;
        padding: 1 2;
        width: 1fr;
        margin: 0 1;
        height: auto;
        background: #313244;
    }

    .section-label {
        margin: 1 0 0 1;
        color: #cdd6f4;
        height: auto;
    }

    .activity-spark {
        margin: 0 2;
        height: 3;
    }

    .phase-bar {
        height: 1;
        margin: 0 1;
    }

    .roi-bar {
        height: 1;
        margin: 0 1;
    }

    .roi-detail {
        margin: 1 1;
        height: auto;
    }

    .timeline-table {
        margin: 1 2;
        height: 1fr;
    }

    DataTable > .datatable--cursor {
        background: #45475a;
    }

    .walk-nav {
        dock: bottom;
        height: 1;
        margin: 0 1;
    }

    #walk-content {
        height: 1fr;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "go_tab('tab-1')", "Dashboard", show=False),
        Binding("2", "go_tab('tab-2')", "Timeline", show=False),
        Binding("3", "go_tab('tab-3')", "Walkthrough", show=False),
        Binding("left", "walk_prev", "◀ Prev", show=False),
        Binding("right", "walk_next", "▶ Next", show=False),
    ]

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent("📊 Dashboard", "📅 Timeline", "📖 Walkthrough"):
            with TabPane("📊 Dashboard"):
                yield DashboardPane(self.data)
            with TabPane("📅 Timeline"):
                yield TimelinePane(self.data)
            with TabPane("📖 Walkthrough"):
                yield WalkthroughPane(self.data)
        yield Footer()

    def action_go_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_walk_prev(self) -> None:
        try:
            walk = self.query_one(WalkthroughPane)
            if walk.page > 0:
                walk.page -= 1
        except Exception:
            pass

    def action_walk_next(self) -> None:
        try:
            walk = self.query_one(WalkthroughPane)
            if walk.page < len(walk.data.windows) - 1:
                walk.page += 1
        except Exception:
            pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Copilot Learning Journey TUI")
    parser.add_argument("--db", help="Path to session_store.db (auto-detected if omitted)")
    args = parser.parse_args()

    db_path = args.db
    if not db_path:
        try:
            db_path = find_database()
        except FileNotFoundError as e:
            print(f"❌ {e}")
            sys.exit(1)

    print(f"📂 Loading from {db_path}...")

    try:
        data = load_data(db_path)
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        sys.exit(1)

    app = JourneyApp(data)
    app.run()


if __name__ == "__main__":
    main()

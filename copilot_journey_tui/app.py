"""Copilot Journey TUI — A beautiful terminal dashboard for your Copilot CLI learning journey."""

import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
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

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── Helper ──────────────────────────────────────────────────────────────────

def _bar(value: int, max_val: int, width: int = 20, color: str = "#89b4fa") -> str:
    """Render a horizontal bar using block chars."""
    if max_val <= 0:
        return "░" * width
    filled = int(value / max_val * width)
    return f"[{color}]{'█' * filled}[/{color}]{'░' * (width - filled)}"


# ── Widgets ─────────────────────────────────────────────────────────────────

class DashboardPane(Static):
    """Dashboard tab with overview stats, phase evolution, and ROI."""

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data

        # ── Row 1: Stats + Phase ──
        with Horizontal(classes="row"):
            yield Static(
                f"[b]📊 Overview[/b]\n\n"
                f"  Sessions     [b]{d.total_sessions}[/b]\n"
                f"  Active Days  [b]{d.active_days}[/b]\n"
                f"  Files        [b]{d.total_files:,}[/b]\n"
                f"  Turns        [b]{d.total_turns:,}[/b]\n"
                f"  Repos        [b]{d.unique_repos}[/b]",
                classes="card",
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
                classes="card",
            )

        # ── Row 2: Sparkline (full width) ──
        if d.sparkline_data and any(v > 0 for v in d.sparkline_data):
            yield Label("[b]📈 Weekly Activity[/b]", classes="section-label")
            yield Sparkline(d.sparkline_data, summary_function=max, classes="sparkline")

        # ── Row 3: Phase Evolution + ROI side by side ──
        with Horizontal(classes="row"):
            phase_lines = ["[b]🔄 Phase Evolution[/b]\n"]
            for w in d.windows:
                c = Phase.color(w.phase)
                n = Phase.name(w.phase)
                filled = w.score * 2
                empty = (18 - w.score) * 2
                b = f"[{c}]{'█' * filled}[/{c}]{'░' * empty}"
                phase_lines.append(f"  {w.label:<22} {b} [{c}]{n}[/{c}]")
            yield Static("\n".join(phase_lines), classes="card")

            max_roi = max(d.roi.aggressive, 1)
            roi_lines = [f"[b]💰 Time Saved ({d.total_days}d)[/b]\n"]
            for label, value, c in [
                ("Conservative", d.roi.conservative, "#585b70"),
                ("Moderate    ", d.roi.moderate, "#a6e3a1"),
                ("Aggressive  ", d.roi.aggressive, "#f9e2af"),
            ]:
                filled = int(value / max_roi * 20)
                b = f"[{c}]{'█' * filled}[/{c}]{'░' * (20 - filled)}"
                roi_lines.append(f"  {label} {b} [b]{value:.0f}h[/b]")
            roi_lines.append(
                f"\n  [dim]Q&A:{d.roi.quick_qa} Code:{d.roi.code_gen} "
                f"Deep:{d.roi.deep_build} Flow:{d.roi.workflow}[/dim]"
            )
            yield Static("\n".join(roi_lines), classes="card")


class HabitsPane(Static):
    """Habits tab — usage patterns and behavioral insights."""

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        d = self.data
        h = d.habits

        # ── Row 1: Time of day + Day of week ──
        with Horizontal(classes="row"):
            # Time-of-day distribution (4 buckets with bar chart)
            total_tod = h.morning + h.afternoon + h.evening + h.night
            max_tod = max(h.morning, h.afternoon, h.evening, h.night, 1)
            tod_lines = [
                "[b]🕐 Time of Day[/b]\n",
                f"  ☀️  Morning  (6-12)  {_bar(h.morning, max_tod, 16, '#f9e2af')} {h.morning}",
                f"  🌤️  Afternoon(12-17) {_bar(h.afternoon, max_tod, 16, '#fab387')} {h.afternoon}",
                f"  🌙 Evening  (17-22) {_bar(h.evening, max_tod, 16, '#89b4fa')} {h.evening}",
                f"  🌑 Night    (22-6)  {_bar(h.night, max_tod, 16, '#585b70')} {h.night}",
            ]
            if total_tod > 0:
                peak = "Morning" if h.morning == max_tod else \
                       "Afternoon" if h.afternoon == max_tod else \
                       "Evening" if h.evening == max_tod else "Night"
                tod_lines.append(f"\n  [dim]Peak: {peak} ({max_tod/total_tod:.0%})[/dim]")
            yield Static("\n".join(tod_lines), classes="card")

            # Day-of-week distribution
            max_day = max((h.day_distribution.get(d, 0) for d in DAY_ORDER), default=1)
            dow_lines = ["[b]📅 Day of Week[/b]\n"]
            for day in DAY_ORDER:
                cnt = h.day_distribution.get(day, 0)
                c = "#a6e3a1" if day in ("Sat", "Sun") else "#89b4fa"
                dow_lines.append(f"  {day}  {_bar(cnt, max_day, 16, c)} {cnt}")
            dow_lines.append(f"\n  [dim]Peak: {h.peak_day}[/dim]")
            yield Static("\n".join(dow_lines), classes="card")

        # ── Row 2: Top repos + Top languages ──
        with Horizontal(classes="row"):
            repo_lines = ["[b]📂 Top Repositories[/b]\n"]
            if h.top_repos:
                max_r = h.top_repos[0][1]
                for repo, cnt in h.top_repos[:6]:
                    short = repo.split("/")[-1] if "/" in repo else repo
                    repo_lines.append(
                        f"  {short:<20} {_bar(cnt, max_r, 12, '#cba6f7')} {cnt}"
                    )
            else:
                repo_lines.append("  [dim]No repository data[/dim]")
            yield Static("\n".join(repo_lines), classes="card")

            lang_lines = ["[b]🧬 Languages & File Types[/b]\n"]
            if h.top_extensions:
                max_e = h.top_extensions[0][1]
                ext_colors = {
                    ".py": "#f9e2af", ".js": "#f9e2af", ".ts": "#89b4fa",
                    ".tsx": "#89b4fa", ".md": "#a6e3a1", ".json": "#fab387",
                    ".html": "#f38ba8", ".css": "#cba6f7", ".cs": "#a6e3a1",
                    ".yaml": "#f38ba8", ".bicep": "#89dceb",
                }
                for ext, cnt in h.top_extensions[:8]:
                    ec = ext_colors.get(ext, "#cdd6f4")
                    lang_lines.append(
                        f"  {ext:<8} {_bar(cnt, max_e, 14, ec)} {cnt}"
                    )
            else:
                lang_lines.append("  [dim]No file data[/dim]")
            yield Static("\n".join(lang_lines), classes="card")

        # ── Row 3: Session patterns + Streaks ──
        with Horizontal(classes="row"):
            sd = h.session_size_dist
            max_sd = max(sd.values(), default=1)
            size_lines = ["[b]📏 Session Depth Distribution[/b]\n"]
            size_colors = ["#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8"]
            for (label, cnt), sc in zip(sd.items(), size_colors):
                size_lines.append(f"  {label:<18} {_bar(cnt, max_sd, 14, sc)} {cnt}")
            size_lines.append(f"\n  [dim]Median: {h.median_turns} turns/session[/dim]")
            yield Static("\n".join(size_lines), classes="card")

            streak_lines = [
                "[b]🔥 Streaks & Stats[/b]\n",
                f"  Best Streak      [b]{h.max_streak}[/b] consecutive days",
                f"  Current Streak   [b]{h.current_streak}[/b] day(s)",
                f"  Avg Msg Length   [b]{h.avg_msg_length}[/b] chars",
                f"  Longest Session  [b]{h.longest_session_turns}[/b] turns",
            ]
            if h.longest_session_summary:
                streak_lines.append(
                    f"    [dim]{h.longest_session_summary}[/dim]"
                )
            if h.checkpoint_topics:
                streak_lines.append(f"\n  [b]Recent Topics:[/b]")
                for t in h.checkpoint_topics[:5]:
                    streak_lines.append(f"    [dim]• {t}[/dim]")
            yield Static("\n".join(streak_lines), classes="card")


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
        with Horizontal(classes="row walk-row"):
            yield Static(id="walk-narrative", classes="card walk-left")
            yield Static(id="walk-dimensions", classes="card walk-right")
        yield Static(
            "[dim]  ← / → to navigate phases  │  Tab to switch tabs[/dim]",
            classes="walk-nav",
        )

    def on_mount(self) -> None:
        self._render_page()

    def watch_page(self, _old: int, _new: int) -> None:
        self._render_page()

    def _render_page(self) -> None:
        narrative = self.query_one("#walk-narrative", Static)
        dimensions = self.query_one("#walk-dimensions", Static)

        if not self.data.windows:
            narrative.update("No data available.")
            dimensions.update("")
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

        # Left panel: narrative
        nav_dots = ""
        for i in range(len(self.data.windows)):
            if i == page:
                nav_dots += f"[{c}]●[/{c}] "
            else:
                nav_dots += "[dim]○[/dim] "

        narrative.update(
            f"\n  [{c}]{emoji} THE {name.upper()} PHASE[/{c}]\n"
            f"  [dim]{w.label}[/dim]\n"
            f"  {'─' * 36}\n\n"
            f"  {desc}\n\n"
            f"  [b]At a Glance:[/b]\n"
            f"  Sessions        [b]{len(w.sessions)}[/b]\n"
            f"  Avg turns       [b]{avg_turns:.0f}[/b]\n"
            f"  Avg files       [b]{avg_files:.0f}[/b]\n"
            f"  Phase score     [b]{w.score}[/b]/18\n\n"
            f"  💡 [i]{analogy}[/i]\n\n"
            f"  {nav_dots}"
        )

        # Right panel: dimension radar
        dim_lines = [f"  [{c}]Dimension Scores[/{c}]\n"]
        for dim_val, dim_label in zip(w.dimensions, w.dim_labels):
            bar = f"[{c}]{'━' * (dim_val * 5)}[/{c}]{'─' * ((3 - dim_val) * 5)}"
            dim_lines.append(f"  {dim_label:<18} {bar} {dim_val}/3")

        # Window comparison mini-chart
        dim_lines.append(f"\n\n  [b]Phase Progression[/b]\n")
        for i, win in enumerate(self.data.windows):
            wc = Phase.color(win.phase)
            marker = " ◀" if i == page else ""
            dim_lines.append(
                f"  {_bar(win.score, 18, 18, wc)} "
                f"{Phase.name(win.phase)}{marker}"
            )

        dimensions.update("\n".join(dim_lines))


class TipsPane(Static):
    """Tips tab — actionable recommendations based on usage patterns."""

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        tips = self.data.tips
        if not tips:
            yield Static("  ✅ No tips — you're doing great!", classes="card")
            return

        yield Label(
            f"[b]💡 {len(tips)} Personalized Tips[/b]  "
            "[dim](based on your actual usage patterns)[/dim]",
            classes="section-label",
        )

        # Show tips in pairs (2-column)
        for i in range(0, len(tips), 2):
            with Horizontal(classes="row"):
                tip = tips[i]
                priority_color = (
                    "#f38ba8" if tip.priority >= 8 else
                    "#f9e2af" if tip.priority >= 5 else
                    "#a6e3a1"
                )
                prio_label = (
                    "HIGH" if tip.priority >= 8 else
                    "MEDIUM" if tip.priority >= 5 else
                    "NICE"
                )
                yield Static(
                    f"  {tip.emoji} [b]{tip.title}[/b]  "
                    f"[{priority_color}]({prio_label})[/{priority_color}]\n\n"
                    f"  {tip.body}",
                    classes="card tip-card",
                )
                if i + 1 < len(tips):
                    tip2 = tips[i + 1]
                    pc2 = (
                        "#f38ba8" if tip2.priority >= 8 else
                        "#f9e2af" if tip2.priority >= 5 else
                        "#a6e3a1"
                    )
                    pl2 = (
                        "HIGH" if tip2.priority >= 8 else
                        "MEDIUM" if tip2.priority >= 5 else
                        "NICE"
                    )
                    yield Static(
                        f"  {tip2.emoji} [b]{tip2.title}[/b]  "
                        f"[{pc2}]({pl2})[/{pc2}]\n\n"
                        f"  {tip2.body}",
                        classes="card tip-card",
                    )


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

    .row {
        height: auto;
        margin-bottom: 1;
    }

    .card {
        border: round #585b70;
        padding: 1 2;
        width: 1fr;
        margin: 0 1;
        height: auto;
        background: #313244;
    }

    .tip-card {
        min-height: 7;
    }

    .section-label {
        margin: 1 0 0 1;
        color: #cdd6f4;
        height: auto;
    }

    .sparkline {
        margin: 0 2;
        height: 3;
    }

    .timeline-table {
        margin: 1 2;
        height: 1fr;
    }

    DataTable > .datatable--cursor {
        background: #45475a;
    }

    .walk-row {
        height: 1fr;
    }

    .walk-left {
        width: 1fr;
    }

    .walk-right {
        width: 1fr;
    }

    .walk-nav {
        dock: bottom;
        height: 1;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "go_tab('tab-1')", "Dashboard", show=False),
        Binding("2", "go_tab('tab-2')", "Timeline", show=False),
        Binding("3", "go_tab('tab-3')", "Walkthrough", show=False),
        Binding("4", "go_tab('tab-4')", "Habits", show=False),
        Binding("5", "go_tab('tab-5')", "Tips", show=False),
        Binding("left", "walk_prev", "◀ Prev", show=False),
        Binding("right", "walk_next", "▶ Next", show=False),
    ]

    def __init__(self, data: JourneyData) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(
            "📊 Dashboard", "📅 Timeline", "📖 Walkthrough",
            "🔎 Habits", "💡 Tips",
        ):
            with TabPane("📊 Dashboard"):
                with ScrollableContainer():
                    yield DashboardPane(self.data)
            with TabPane("📅 Timeline"):
                yield TimelinePane(self.data)
            with TabPane("📖 Walkthrough"):
                yield WalkthroughPane(self.data)
            with TabPane("🔎 Habits"):
                with ScrollableContainer():
                    yield HabitsPane(self.data)
            with TabPane("💡 Tips"):
                with ScrollableContainer():
                    yield TipsPane(self.data)
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

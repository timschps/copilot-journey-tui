"""Generate screenshots with synthetic demo data — no personal info."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from copilot_journey_tui.data import (
    JourneyData, TimeWindow, Milestone, ROIEstimate, HabitsData, Tip,
    RepoProfile, Phase, TipAction,
)
from copilot_journey_tui.app import JourneyApp
from datetime import datetime, timedelta


def _demo_data() -> JourneyData:
    now = datetime.now()

    # --- Time windows ---
    windows = [
        TimeWindow(
            label="Weeks 1–4", start=now - timedelta(days=84),
            end=now - timedelta(days=57), sessions=[],
            phase=Phase.EXPLORER, score=5,
            dimensions=[1, 1, 0, 1, 1, 1],
            dim_labels=["Session Depth", "File Breadth", "Delivery Signals",
                        "Tool Diversity", "Consistency", "Prompt Variety"],
        ),
        TimeWindow(
            label="Weeks 5–8", start=now - timedelta(days=56),
            end=now - timedelta(days=29), sessions=[],
            phase=Phase.BUILDER, score=10,
            dimensions=[2, 2, 1, 2, 2, 1],
            dim_labels=["Session Depth", "File Breadth", "Delivery Signals",
                        "Tool Diversity", "Consistency", "Prompt Variety"],
        ),
        TimeWindow(
            label="Weeks 9–12", start=now - timedelta(days=28),
            end=now, sessions=[],
            phase=Phase.ORCHESTRATOR, score=14,
            dimensions=[3, 2, 2, 3, 2, 2],
            dim_labels=["Session Depth", "File Breadth", "Delivery Signals",
                        "Tool Diversity", "Consistency", "Prompt Variety"],
        ),
    ]

    # --- Milestones ---
    milestones = [
        Milestone(now - timedelta(days=80), "First session",
                  "Asked Copilot a quick question", Phase.EXPLORER),
        Milestone(now - timedelta(days=65), "First multi-file edit",
                  "Edited 3 files in one session", Phase.EXPLORER),
        Milestone(now - timedelta(days=50), "Builder unlocked",
                  "Score crossed 7 — real projects begin", Phase.BUILDER),
        Milestone(now - timedelta(days=35), "First marathon session",
                  "30+ turn deep collaboration", Phase.BUILDER),
        Milestone(now - timedelta(days=18), "Orchestrator unlocked",
                  "Score crossed 12 — complex workflows", Phase.ORCHESTRATOR),
        Milestone(now - timedelta(days=5), "First CI/CD generation",
                  "Generated GitHub Actions workflow", Phase.ORCHESTRATOR),
    ]

    # --- ROI ---
    roi = ROIEstimate(
        conservative=18.0, moderate=36.0, aggressive=54.0,
        quick_qa=45, code_gen=30, deep_build=15, workflow=5,
    )

    # --- Habits ---
    habits = HabitsData(
        hour_distribution={9: 15, 10: 22, 11: 18, 14: 12, 15: 10, 19: 8, 20: 6, 21: 4},
        day_distribution={"Mon": 18, "Tue": 16, "Wed": 20, "Thu": 22, "Fri": 12, "Sat": 4, "Sun": 3},
        peak_hour=10, peak_day="Thu",
        top_repos=[
            ("acme/web-app", 28), ("acme/api-service", 22),
            ("acme/infra", 15), ("acme/docs-site", 10),
            ("acme/mobile-app", 8), ("personal/blog", 7),
            ("acme/shared-lib", 5),
        ],
        top_extensions=[
            (".ts", 180), (".py", 95), (".md", 72),
            (".json", 45), (".yaml", 30), (".html", 22),
        ],
        avg_session_mins=25, median_session_mins=15,
        max_streak=7, current_streak=3,
        avg_msg_length=320, median_turns=4,
        session_size_dist={
            "Quick (<5 turns)": 45, "Medium (5-15)": 30,
            "Deep (15-30)": 15, "Marathon (30+)": 5,
        },
        longest_session_summary="Full-stack feature: auth module with tests and docs",
        longest_session_turns=42,
        morning=38, afternoon=32, evening=20, night=5,
        active_dates=[
            (now - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(0, 84, 2)
        ],
        checkpoint_topics=[
            "Building REST API with authentication",
            "Migrating database to PostgreSQL",
            "Setting up CI/CD pipeline",
            "Adding unit tests for billing module",
            "Refactoring shared utilities",
        ],
        has_copilot_instructions=True,
        has_custom_instructions=False,
        has_skills=False,
        has_mcp_config=True,
        test_session_count=9,
        doc_session_count=12,
        cicd_session_count=3,
        instruction_files_found=[".github/copilot-instructions.md"],
        repo_profiles=[
            RepoProfile("acme/web-app", 28, 85, [(".ts", 60), (".css", 15), (".html", 10)],
                         has_copilot_instructions=True, has_tests=True, has_docs=True,
                         primary_language=".ts"),
            RepoProfile("acme/api-service", 22, 62, [(".py", 40), (".yaml", 12), (".json", 10)],
                         has_tests=True, has_docs=True, has_cicd=True,
                         primary_language=".py"),
            RepoProfile("acme/infra", 15, 38, [(".bicep", 20), (".json", 10), (".md", 8)],
                         has_cicd=True, primary_language=".bicep"),
            RepoProfile("acme/docs-site", 10, 25, [(".md", 18), (".ts", 5), (".css", 2)],
                         has_docs=True, primary_language=".md"),
            RepoProfile("acme/mobile-app", 8, 30, [(".ts", 20), (".json", 6), (".md", 4)],
                         primary_language=".ts"),
            RepoProfile("personal/blog", 7, 12, [(".md", 10), (".toml", 2)],
                         primary_language=".md"),
            RepoProfile("acme/shared-lib", 5, 18, [(".ts", 12), (".json", 4), (".md", 2)],
                         has_tests=True, primary_language=".ts"),
        ],
    )

    # --- Tips (repo-specific, using demo repos) ---
    tips = [
        Tip("🏛️", "Path to Architect",
            "Orchestrator phase! For Architect: use Copilot for system design, "
            "IaC, cross-project refactors. Think at the system level.",
            priority=10, category="phase"),
        Tip("📋", "Add copilot-instructions.md",
            "4 active repos lack a copilot-instructions.md: "
            "[b]api-service, infra, mobile-app, shared-lib[/b]. "
            "This file gives Copilot project-specific context.",
            priority=10, category="best-practice",
            how_to=(
                "Start with your most active repo. Create\n"
                ".github/copilot-instructions.md:\n"
                "  ─────────────────────────────────\n"
                "  # Project instructions for Copilot\n"
                "  - Language/framework preferences\n"
                "  - Coding standards & patterns"
            ),
            repo_actions=[
                TipAction(action_id="demo-ci-1", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d1", "")], repo_name="api-service"),
                TipAction(action_id="demo-ci-2", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d2", "")], repo_name="infra"),
                TipAction(action_id="demo-ci-3", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d3", "")], repo_name="mobile-app"),
                TipAction(action_id="demo-ci-4", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d4", "")], repo_name="shared-lib"),
            ]),
        Tip("🎯", "Use custom instruction files",
            "None of your repos use scoped .instructions.md files. "
            "Define per-concern rules (testing, security) that auto-apply.",
            priority=9, category="best-practice",
            how_to=(
                "Create scoped instruction files:\n"
                "  .github/instructions/testing.instructions.md\n\n"
                "With auto-apply glob:\n"
                "  ---\n"
                "  applyTo: \"**/*.test.ts\"\n"
                "  ---\n"
                "  # Testing guidelines\n"
                "  - Use describe/it blocks"
            ),
            repo_actions=[
                TipAction(action_id="demo-cust-1", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d5", "")], repo_name="web-app"),
                TipAction(action_id="demo-cust-2", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d6", "")], repo_name="api-service"),
            ]),
        Tip("📁", "Add .context.md for architecture context",
            "6 repos lack .context.md files: "
            "[b]web-app, api-service, infra, mobile-app[/b]. "
            "These give Copilot architecture awareness.",
            priority=8, category="best-practice",
            how_to=(
                "Create .context.md in key directories:\n\n"
                "Example content:\n"
                "  # Authentication Module\n"
                "  ## Architecture\n"
                "  - JWT tokens in httpOnly cookies"
            ),
            repo_actions=[
                TipAction(action_id="demo-ctx-1", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d7", "")], repo_name="web-app"),
                TipAction(action_id="demo-ctx-2", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d8", "")], repo_name="api-service"),
                TipAction(action_id="demo-ctx-3", label="⚡ Set up", action_type="create_files",
                          files=[("/tmp/d9", "")], repo_name="infra"),
            ]),
        Tip("🧪", "Add tests to more repos",
            "4 repos have no test files: "
            "[b]infra, docs-site, mobile-app, blog[/b]. "
            "Copilot excels at generating tests.",
            priority=8, category="best-practice",
            how_to=(
                "Start with:\n"
                "  → acme/mobile-app (.ts)\n"
                "  → acme/infra (.bicep)\n\n"
                "Prompt: 'Write unit tests for the main module\n"
                "  covering edge cases and error paths'"
            )),
        Tip("🏊", "Dive deeper",
            "47% of sessions are quick Q&As. Try a longer session: "
            "describe a full feature, let Copilot scaffold and iterate.",
            priority=8, category="habit"),
        Tip("📌", "Pin key files with prompt starters",
            "Reference key files explicitly in prompts to ground Copilot "
            "in your actual code rather than generic patterns.",
            priority=7, category="best-practice",
            how_to=(
                "Example:\n"
                '  "Look at src/models/user.ts and add\n'
                '   a resetPassword method matching the\n'
                '   existing pattern"'
            )),
        Tip("🔗", "Connect to delivery",
            "Few sessions link to PRs/commits. Push your Copilot-built "
            "work to track real impact and make ROI tangible.",
            priority=7, category="habit"),
        Tip("🔄", "Master session management",
            "Start fresh sessions for new tasks. Context is per-session "
            "— a clean start avoids stale context.",
            priority=6, category="best-practice",
            how_to=(
                "Session strategies:\n"
                "  • One session per feature/bug\n"
                "  • Start with the goal: 'Build X that does Y'\n"
                "  • Use /compact to free up context mid-session"
            )),
        Tip("🔍", "Use Copilot for code review",
            "Copilot can review changes before you push — catches bugs, "
            "security issues, and style inconsistencies.",
            priority=6, category="best-practice",
            how_to=(
                "Review prompts:\n"
                '  "Review my staged changes for bugs"\n'
                '  "Check this PR for breaking changes"'
            )),
        Tip("📖", "Generate docs for more repos",
            "3 repos lack README/docs: [b]infra, mobile-app, blog[/b]. "
            "Copilot can generate READMEs and API docs from code.",
            priority=5, category="best-practice",
            how_to=(
                "  → acme/infra: 'Generate README from Bicep files'\n"
                "  → acme/mobile-app: 'Generate README from code'\n"
                "  → personal/blog: 'Generate a README'"
            )),
        Tip("✅", "MCP configured",
            "MCP servers set up — you're ahead of most users!",
            priority=1, category="best-practice"),
    ]

    return JourneyData(
        windows=windows, milestones=milestones, roi=roi,
        habits=habits, tips=tips,
        total_sessions=95, active_days=42, total_days=84,
        total_turns=480, total_files=290, unique_repos=7,
        current_phase=Phase.ORCHESTRATOR, current_score=14,
        sparkline_data=[3, 5, 8, 7, 10, 9, 12, 11, 14, 8, 6, 10],
    )


async def take_screenshots():
    data = _demo_data()
    app = JourneyApp(data)
    screenshots_dir = os.path.join(os.path.dirname(__file__), "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    tab_names = [
        ("tab-1", "dashboard"),
        ("tab-2", "timeline"),
        ("tab-3", "walkthrough"),
        ("tab-4", "habits"),
        ("tab-5", "tips"),
    ]

    async with app.run_test(size=(120, 40)) as pilot:
        for tab_id, name in tab_names:
            app.action_go_tab(tab_id)
            await pilot.pause()
            await pilot.pause()
            svg = app.export_screenshot()
            path = os.path.join(screenshots_dir, f"{name}.svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
            print(f"  ✅ {path}")

    print("\nDone — all screenshots use synthetic demo data.")


if __name__ == "__main__":
    asyncio.run(take_screenshots())

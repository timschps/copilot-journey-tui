"""Data loading and analysis for Copilot Journey TUI."""

import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class Phase:
    EXPLORER = 0
    BUILDER = 1
    ORCHESTRATOR = 2
    ARCHITECT = 3

    NAMES = {0: "Explorer", 1: "Builder", 2: "Orchestrator", 3: "Architect"}
    EMOJI = {0: "🔍", 1: "🔨", 2: "🎯", 3: "🏛️"}
    COLORS = {0: "#89b4fa", 1: "#a6e3a1", 2: "#f9e2af", 3: "#cba6f7"}

    @staticmethod
    def name(phase: int) -> str:
        return Phase.NAMES.get(phase, "Unknown")

    @staticmethod
    def emoji(phase: int) -> str:
        return Phase.EMOJI.get(phase, "❓")

    @staticmethod
    def color(phase: int) -> str:
        return Phase.COLORS.get(phase, "#cdd6f4")


# ── File templates for actionable tips ──────────────────────────────────────

TEMPLATE_COPILOT_INSTRUCTIONS = """\
# Project Instructions for GitHub Copilot

## Language & Framework
- {lang_hint}

## Coding Standards
- Follow existing code style and patterns
- Use descriptive variable and function names
- Prefer composition over inheritance

## Error Handling
- Always handle errors explicitly
- Use try/catch for async operations
- Log errors with context

## Testing
- Write tests for new functionality
- Follow AAA pattern (Arrange, Act, Assert)

## Project-Specific Notes
- (Add your project conventions here)
"""

TEMPLATE_CUSTOM_INSTRUCTIONS = """\
---
applyTo: "{glob_pattern}"
---
# {concern} Guidelines

## Rules
- (Add your {concern}-specific rules here)

## Patterns to Follow
- (Describe preferred patterns)

## Anti-Patterns to Avoid
- (List things to avoid)
"""

TEMPLATE_CONTEXT_MD = """\
# {dir_name} Module

## Purpose
(Describe what this module/directory does)

## Architecture
- (Key components and their responsibilities)
- (Data flow between components)

## Dependencies
- (External services or modules this depends on)

## Key Invariants
- (Rules that must always hold true)
"""

TEMPLATE_MCP_JSON = """\
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
"""

TEMPLATE_SKILL_MD = """\
---
name: {skill_name}
description: {skill_desc}
---
# {skill_name}

## What This Skill Does
(Describe the skill's purpose)

## Steps
1. Analyze the current codebase
2. (Add your workflow steps)
3. Report results

## Output Format
- Summary of findings
- Recommended actions
"""


@dataclass
class Session:
    id: str
    cwd: str
    repo: str
    branch: str
    summary: str
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    file_count: int = 0
    has_refs: bool = False
    tools: set = field(default_factory=set)
    duration_mins: float = 0
    msg_lengths: list = field(default_factory=list)


@dataclass
class TimeWindow:
    label: str
    start: datetime
    end: datetime
    sessions: list
    phase: int = 0
    score: int = 0
    dimensions: list = field(default_factory=lambda: [0] * 6)
    dim_labels: list = field(default_factory=lambda: [
        "Session Depth", "File Breadth", "Delivery Signals",
        "Tool Diversity", "Consistency", "Topic Variety",
    ])


@dataclass
class Milestone:
    date: datetime
    title: str
    detail: str
    phase: int


@dataclass
class ROIEstimate:
    conservative: float = 0
    moderate: float = 0
    aggressive: float = 0
    quick_qa: int = 0
    code_gen: int = 0
    deep_build: int = 0
    workflow: int = 0


@dataclass
class RepoProfile:
    """Per-repo adoption profile built from actual session data."""
    name: str                          # e.g. "timschps/hotelsite-demo"
    session_count: int = 0
    file_count: int = 0
    top_extensions: list = field(default_factory=list)  # [(ext, count), ...]
    has_copilot_instructions: bool = False
    has_custom_instructions: bool = False
    has_skills: bool = False
    has_mcp_config: bool = False
    has_context_md: bool = False
    has_tests: bool = False
    has_docs: bool = False
    has_cicd: bool = False
    primary_language: str = ""         # dominant extension
    local_path: str = ""               # local filesystem path (from session cwd)


@dataclass
class HabitsData:
    """Usage habit insights derived from session patterns."""
    hour_distribution: dict = field(default_factory=dict)  # hour → count
    day_distribution: dict = field(default_factory=dict)    # day name → count
    peak_hour: int = 9
    peak_day: str = "Mon"
    top_repos: list = field(default_factory=list)           # (repo, count)
    top_extensions: list = field(default_factory=list)      # (ext, count)
    avg_session_mins: float = 0
    median_session_mins: float = 0
    max_streak: int = 0
    current_streak: int = 0
    avg_msg_length: int = 0
    median_turns: int = 0
    session_size_dist: dict = field(default_factory=dict)   # label → count
    longest_session_summary: str = ""
    longest_session_turns: int = 0
    # Time-of-day buckets
    morning: int = 0     # 6-12
    afternoon: int = 0   # 12-17
    evening: int = 0     # 17-22
    night: int = 0       # 22-6
    active_dates: list = field(default_factory=list)        # sorted date strings
    checkpoint_topics: list = field(default_factory=list)   # recent checkpoint titles
    # Best-practice detection signals
    has_copilot_instructions: bool = False
    has_custom_instructions: bool = False
    has_skills: bool = False
    has_mcp_config: bool = False
    test_session_count: int = 0
    doc_session_count: int = 0
    cicd_session_count: int = 0
    instruction_files_found: list = field(default_factory=list)
    repo_profiles: list = field(default_factory=list)  # list[RepoProfile]


@dataclass
class TipAction:
    """An executable action attached to a tip."""
    action_id: str                     # unique id, e.g. "copilot-instructions-acme-api"
    label: str                         # button text, e.g. "⚡ Set up"
    action_type: str                   # "create_files" | "copy_prompt"
    # For create_files: list of (full_path, content) tuples
    files: list = field(default_factory=list)
    # For copy_prompt: the prompt text to suggest
    prompt: str = ""
    # Display context
    repo_name: str = ""                # short repo name for display


@dataclass
class Tip:
    emoji: str
    title: str
    body: str
    priority: int = 0  # higher = more relevant
    category: str = ""  # "habit", "best-practice", "phase"
    how_to: str = ""  # actionable how-to steps
    action: Optional[TipAction] = None  # bulk action (kept for backward compat)
    repo_actions: list = field(default_factory=list)  # per-repo actions


@dataclass
class JourneyData:
    windows: list
    milestones: list
    roi: ROIEstimate
    habits: HabitsData = field(default_factory=HabitsData)
    tips: list = field(default_factory=list)
    total_sessions: int = 0
    active_days: int = 0
    total_days: int = 0
    total_turns: int = 0
    total_files: int = 0
    unique_repos: int = 0
    current_phase: int = 0
    current_score: int = 0
    sparkline_data: list = field(default_factory=list)


def find_database() -> str:
    """Auto-detect the session_store.db location."""
    home = Path.home()
    candidates = [
        home / ".copilot" / "session-store.db",
        home / ".copilot" / "session-store" / "session_store.db",
        home / ".copilot" / "agent" / "session-store" / "session_store.db",
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    # Recursive search fallback
    copilot_dir = home / ".copilot"
    if copilot_dir.exists():
        for p in copilot_dir.rglob("session_store.db"):
            return str(p)
        for p in copilot_dir.rglob("session-store.db"):
            return str(p)

    raise FileNotFoundError(
        "session_store.db not found in ~/.copilot/ — use --db to specify the path"
    )


def _parse_time(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


def load_data(db_path: str) -> JourneyData:
    """Load session data from the database and perform analysis."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT s.id, COALESCE(s.cwd,'') as cwd,
               COALESCE(s.repository,'') as repo,
               COALESCE(s.branch,'') as branch,
               COALESCE(s.summary,'') as summary,
               s.created_at, s.updated_at,
               COALESCE(tc.cnt, 0) as turn_count,
               COALESCE(fc.cnt, 0) as file_count
        FROM sessions s
        LEFT JOIN (
            SELECT session_id, COUNT(*) as cnt FROM turns GROUP BY session_id
        ) tc ON tc.session_id = s.id
        LEFT JOIN (
            SELECT session_id, COUNT(DISTINCT file_path) as cnt
            FROM session_files GROUP BY session_id
        ) fc ON fc.session_id = s.id
        ORDER BY s.created_at ASC
    """).fetchall()

    if not rows:
        raise ValueError("No sessions found in database")

    sessions = []
    for r in rows:
        created = _parse_time(r["created_at"])
        if not created:
            continue
        updated = _parse_time(r["updated_at"]) or created
        dur = max((updated - created).total_seconds() / 60, 0)
        # Cap obviously broken durations (>48h = likely stale updated_at)
        if dur > 48 * 60:
            dur = 0
        sessions.append(Session(
            id=r["id"], cwd=r["cwd"], repo=r["repo"], branch=r["branch"],
            summary=r["summary"], created_at=created, updated_at=updated,
            turn_count=r["turn_count"], file_count=r["file_count"],
            duration_mins=dur,
        ))

    # Load tool/extension diversity per session
    file_paths: list[str] = []
    try:
        tool_rows = conn.execute(
            "SELECT session_id, file_path, tool_name FROM session_files"
        ).fetchall()
        session_tools: dict[str, set] = {}
        for tr in tool_rows:
            sid = tr["session_id"]
            if sid not in session_tools:
                session_tools[sid] = set()
            session_tools[sid].add(tr["tool_name"])
            fp = tr["file_path"]
            file_paths.append(fp)
            ext = Path(fp).suffix.lower()
            if ext:
                session_tools[sid].add(f"ext:{ext}")
        for s in sessions:
            if s.id in session_tools:
                s.tools = session_tools[s.id]
    except Exception:
        pass

    # Load ref signals
    try:
        ref_rows = conn.execute(
            "SELECT DISTINCT session_id FROM session_refs"
        ).fetchall()
        ref_set = {r["session_id"] for r in ref_rows}
        for s in sessions:
            s.has_refs = s.id in ref_set
    except Exception:
        pass

    # Load user message lengths per session
    try:
        msg_rows = conn.execute(
            "SELECT session_id, LENGTH(user_message) as len "
            "FROM turns WHERE user_message IS NOT NULL"
        ).fetchall()
        session_msgs: dict[str, list] = {}
        for mr in msg_rows:
            sid = mr["session_id"]
            if sid not in session_msgs:
                session_msgs[sid] = []
            session_msgs[sid].append(mr["len"])
        for s in sessions:
            if s.id in session_msgs:
                s.msg_lengths = session_msgs[s.id]
    except Exception:
        pass

    # Load checkpoint titles for habits
    checkpoint_topics: list[str] = []
    try:
        cp_rows = conn.execute(
            "SELECT title FROM checkpoints ORDER BY checkpoint_number DESC LIMIT 20"
        ).fetchall()
        checkpoint_topics = [r["title"] for r in cp_rows if r["title"]]
    except Exception:
        pass

    # Detect best-practice signals from file paths
    bp_signals = _detect_best_practice_signals(conn, file_paths)

    conn.close()
    return _analyze(sessions, file_paths, checkpoint_topics, bp_signals)


def _detect_best_practice_signals(conn, file_paths: list[str]) -> dict:
    """Scan session history for Copilot best-practice adoption signals."""
    signals: dict = {
        "has_copilot_instructions": False,
        "has_custom_instructions": False,
        "has_skills": False,
        "has_mcp_config": False,
        "instruction_files": [],
        "test_sessions": 0,
        "doc_sessions": 0,
        "cicd_sessions": 0,
        "repo_profiles": [],
    }

    # Global file-path checks
    for fp in file_paths:
        fpl = fp.lower().replace("\\", "/")
        if "copilot-instructions.md" in fpl:
            signals["has_copilot_instructions"] = True
            signals["instruction_files"].append(fp)
        if ".instructions.md" in fpl and "copilot-instructions" not in fpl:
            signals["has_custom_instructions"] = True
            signals["instruction_files"].append(fp)
        if fpl.endswith("skill.md"):
            signals["has_skills"] = True
        if "mcp.json" in fpl:
            signals["has_mcp_config"] = True

    # Count sessions touching tests, docs, CI/CD
    for label, pattern_sql, key in [
        ("test", "file_path LIKE '%test%' OR file_path LIKE '%spec%'", "test_sessions"),
        ("doc", "file_path LIKE '%README%' OR file_path LIKE '%docs/%'", "doc_sessions"),
        ("cicd",
         "file_path LIKE '%.github/workflows%' OR file_path LIKE '%Dockerfile%' "
         "OR file_path LIKE '%azure-pipelines%'", "cicd_sessions"),
    ]:
        try:
            r = conn.execute(
                f"SELECT COUNT(DISTINCT session_id) FROM session_files WHERE {pattern_sql}"
            ).fetchone()
            signals[key] = r[0] if r else 0
        except Exception:
            pass

    # ── Build per-repo profiles ──
    try:
        repo_rows = conn.execute(
            "SELECT s.repository, COUNT(DISTINCT s.id) as sess_cnt "
            "FROM sessions s "
            "WHERE s.repository IS NOT NULL AND s.repository != '' "
            "GROUP BY s.repository ORDER BY sess_cnt DESC"
        ).fetchall()

        from collections import Counter as _Counter

        for repo_name, sess_cnt in repo_rows:
            rp = RepoProfile(name=repo_name, session_count=sess_cnt)

            # Resolve local path from most-used cwd for this repo
            cwd_row = conn.execute(
                "SELECT cwd, COUNT(*) as cnt FROM sessions "
                "WHERE repository = ? AND cwd IS NOT NULL AND cwd != '' "
                "GROUP BY cwd ORDER BY cnt DESC LIMIT 1",
                (repo_name,)
            ).fetchone()
            if cwd_row:
                rp.local_path = cwd_row[0]
            # Get all files touched in this repo
            file_rows = conn.execute(
                "SELECT DISTINCT sf.file_path FROM session_files sf "
                "JOIN sessions s ON sf.session_id = s.id "
                "WHERE s.repository = ?", (repo_name,)
            ).fetchall()
            repo_files = [r[0] for r in file_rows]
            rp.file_count = len(repo_files)

            ext_ctr = _Counter()
            for fp in repo_files:
                fpl = fp.lower().replace("\\", "/")
                import os as _os
                ext = _os.path.splitext(fp)[1]
                if ext:
                    ext_ctr[ext] += 1
                if "copilot-instructions.md" in fpl:
                    rp.has_copilot_instructions = True
                if ".instructions.md" in fpl and "copilot-instructions" not in fpl:
                    rp.has_custom_instructions = True
                if fpl.endswith("skill.md"):
                    rp.has_skills = True
                if "mcp.json" in fpl:
                    rp.has_mcp_config = True
                if ".context.md" in fpl:
                    rp.has_context_md = True
                if "test" in fpl or "spec" in fpl:
                    rp.has_tests = True
                if "readme" in fpl or "/docs/" in fpl:
                    rp.has_docs = True
                if ".github/workflows" in fpl or "dockerfile" in fpl or "azure-pipelines" in fpl:
                    rp.has_cicd = True

            rp.top_extensions = ext_ctr.most_common(5)
            if rp.top_extensions:
                rp.primary_language = rp.top_extensions[0][0]

            signals["repo_profiles"].append(rp)
    except Exception:
        pass

    return signals


def _analyze(sessions: list[Session], file_paths: list[str],
             checkpoint_topics: list[str], bp_signals: dict) -> JourneyData:
    active_days_set: set[str] = set()
    repos: set[str] = set()
    total_turns = total_files = 0
    hour_counter: Counter = Counter()
    day_counter: Counter = Counter()

    for s in sessions:
        total_turns += s.turn_count
        total_files += s.file_count
        day_str = s.created_at.strftime("%Y-%m-%d")
        active_days_set.add(day_str)
        if s.repo:
            repos.add(s.repo)
        hour_counter[s.created_at.hour] += 1
        day_counter[s.created_at.strftime("%a")] += 1

    earliest = sessions[0].created_at
    latest = sessions[-1].created_at
    total_days = max((latest - earliest).days + 1, 1)

    # Weekly sparkline
    weeks = max(total_days // 7, 1)
    sparkline = [0] * (weeks + 1)
    for s in sessions:
        week_idx = min((s.created_at - earliest).days // 7, len(sparkline) - 1)
        sparkline[week_idx] += 1

    windows = _split_into_windows(sessions, earliest, latest)
    for w in windows:
        _score_window(w)

    current_phase = windows[-1].phase if windows else Phase.EXPLORER
    current_score = windows[-1].score if windows else 0

    habits = _compute_habits(sessions, file_paths, hour_counter, day_counter,
                             active_days_set, checkpoint_topics, bp_signals)
    tips = _generate_tips(sessions, habits, windows, current_phase)

    return JourneyData(
        windows=windows,
        milestones=_detect_milestones(sessions),
        roi=_calculate_roi(sessions),
        habits=habits,
        tips=tips,
        total_sessions=len(sessions),
        active_days=len(active_days_set),
        total_days=total_days,
        total_turns=total_turns,
        total_files=total_files,
        unique_repos=max(len(repos), 1),
        current_phase=current_phase,
        current_score=current_score,
        sparkline_data=sparkline,
    )


def _split_into_windows(sessions, earliest, latest):
    total_secs = max((latest - earliest).total_seconds(), 86400)
    win_secs = total_secs / 3

    windows = []
    for i in range(3):
        start = earliest + timedelta(seconds=win_secs * i)
        end = earliest + timedelta(seconds=win_secs * (i + 1))
        if i == 2:
            end = latest + timedelta(days=1)

        win_sessions = [s for s in sessions if start <= s.created_at < end]
        windows.append(TimeWindow(
            label=f"{start.strftime('%b %d')} – {end.strftime('%b %d')}",
            start=start, end=end, sessions=win_sessions,
        ))
    return windows


def _score_window(w: TimeWindow):
    if not w.sessions:
        w.phase = Phase.EXPLORER
        return

    n = len(w.sessions)

    # 1. Session depth (avg turns)
    avg_turns = sum(s.turn_count for s in w.sessions) / n
    w.dimensions[0] = (3 if avg_turns >= 30 else 2 if avg_turns >= 15
                        else 1 if avg_turns >= 5 else 0)

    # 2. File breadth (avg files/session)
    avg_files = sum(s.file_count for s in w.sessions) / n
    w.dimensions[1] = (3 if avg_files >= 10 else 2 if avg_files >= 5
                        else 1 if avg_files >= 2 else 0)

    # 3. Delivery signals (sessions with refs)
    refs_pct = sum(1 for s in w.sessions if s.has_refs) / n
    w.dimensions[2] = (3 if refs_pct >= 0.6 else 2 if refs_pct >= 0.3
                        else 1 if refs_pct >= 0.1 else 0)

    # 4. Tool diversity (unique tools + file extensions)
    all_tools: set[str] = set()
    for s in w.sessions:
        all_tools.update(s.tools)
    tool_count = len(all_tools)
    w.dimensions[3] = (3 if tool_count >= 12 else 2 if tool_count >= 7
                        else 1 if tool_count >= 3 else 0)

    # 5. Consistency (sessions per week)
    window_weeks = max((w.end - w.start).days / 7, 1)
    sess_per_week = n / window_weeks
    w.dimensions[4] = (3 if sess_per_week >= 5 else 2 if sess_per_week >= 3
                        else 1 if sess_per_week >= 1 else 0)

    # 6. Topic variety (unique repos)
    repo_count = len({s.repo for s in w.sessions if s.repo})
    w.dimensions[5] = (3 if repo_count >= 7 else 2 if repo_count >= 4
                        else 1 if repo_count >= 2 else 0)

    w.score = sum(w.dimensions)
    if w.score >= 16:
        w.phase = Phase.ARCHITECT
    elif w.score >= 12:
        w.phase = Phase.ORCHESTRATOR
    elif w.score >= 7:
        w.phase = Phase.BUILDER
    else:
        w.phase = Phase.EXPLORER


def _detect_milestones(sessions: list[Session]) -> list[Milestone]:
    if not sessions:
        return []

    milestones = [Milestone(
        date=sessions[0].created_at,
        title="First Session",
        detail=sessions[0].summary[:60] if sessions[0].summary else "Your journey begins",
        phase=Phase.EXPLORER,
    )]

    multi_file = deep_session = marathon = False
    total = 0

    for s in sessions:
        total += 1

        if not multi_file and s.file_count >= 5:
            multi_file = True
            milestones.append(Milestone(
                s.created_at, "First Multi-File Build",
                f"Touched {s.file_count} files in one session", Phase.BUILDER,
            ))

        if not deep_session and s.turn_count >= 30:
            deep_session = True
            milestones.append(Milestone(
                s.created_at, "First Deep Session",
                f"Extended session with {s.turn_count} turns", Phase.BUILDER,
            ))

        if not marathon and s.turn_count >= 80:
            marathon = True
            milestones.append(Milestone(
                s.created_at, "Marathon Session 🏃",
                f"Epic {s.turn_count}-turn session", Phase.ORCHESTRATOR,
            ))

        for m in (10, 25, 50, 100):
            if total == m:
                milestones.append(Milestone(
                    s.created_at, f"Session #{m}",
                    f"Reached {m} total sessions", Phase.BUILDER,
                ))

    milestones.sort(key=lambda ms: ms.date)
    return milestones


def _calculate_roi(sessions: list[Session]) -> ROIEstimate:
    roi = ROIEstimate()
    for s in sessions:
        if s.turn_count >= 30 and s.file_count >= 5:
            roi.workflow += 1
        elif s.turn_count >= 15 or s.file_count >= 3:
            roi.deep_build += 1
        elif s.turn_count >= 5:
            roi.code_gen += 1
        else:
            roi.quick_qa += 1

    # Minutes saved per session type (conservative / moderate / aggressive)
    roi.conservative = (roi.quick_qa * 5 + roi.code_gen * 10
                        + roi.deep_build * 20 + roi.workflow * 30) / 60
    roi.moderate = (roi.quick_qa * 10 + roi.code_gen * 20
                    + roi.deep_build * 40 + roi.workflow * 60) / 60
    roi.aggressive = (roi.quick_qa * 15 + roi.code_gen * 30
                      + roi.deep_build * 60 + roi.workflow * 90) / 60
    return roi


def _compute_habits(sessions: list[Session], file_paths: list[str],
                    hour_counter: Counter, day_counter: Counter,
                    active_days_set: set[str],
                    checkpoint_topics: list[str],
                    bp_signals: dict) -> HabitsData:
    h = HabitsData()
    h.hour_distribution = dict(hour_counter)
    h.day_distribution = dict(day_counter)
    h.peak_hour = hour_counter.most_common(1)[0][0] if hour_counter else 9
    h.peak_day = day_counter.most_common(1)[0][0] if day_counter else "Mon"
    h.checkpoint_topics = checkpoint_topics[:15]

    # Best-practice signals
    h.has_copilot_instructions = bp_signals.get("has_copilot_instructions", False)
    h.has_custom_instructions = bp_signals.get("has_custom_instructions", False)
    h.has_skills = bp_signals.get("has_skills", False)
    h.has_mcp_config = bp_signals.get("has_mcp_config", False)
    h.test_session_count = bp_signals.get("test_sessions", 0)
    h.doc_session_count = bp_signals.get("doc_sessions", 0)
    h.cicd_session_count = bp_signals.get("cicd_sessions", 0)
    h.instruction_files_found = bp_signals.get("instruction_files", [])
    h.repo_profiles = bp_signals.get("repo_profiles", [])

    # Top repos
    repo_counter: Counter = Counter()
    for s in sessions:
        if s.repo:
            repo_counter[s.repo] += 1
    h.top_repos = repo_counter.most_common(8)

    # Top file extensions
    ext_counter: Counter = Counter()
    for fp in file_paths:
        fname = fp.replace("\\", "/").split("/")[-1]
        if "." in fname:
            ext = "." + fname.rsplit(".", 1)[-1].lower()
            ext_counter[ext] += 1
    h.top_extensions = ext_counter.most_common(10)

    # Session durations
    valid_durs = [s.duration_mins for s in sessions if s.duration_mins > 0]
    if valid_durs:
        h.avg_session_mins = sum(valid_durs) / len(valid_durs)
        h.median_session_mins = sorted(valid_durs)[len(valid_durs) // 2]

    # Turns distribution
    turn_counts = sorted(s.turn_count for s in sessions)
    h.median_turns = turn_counts[len(turn_counts) // 2] if turn_counts else 0

    # Message lengths
    all_msg_lens = []
    for s in sessions:
        all_msg_lens.extend(s.msg_lengths)
    if all_msg_lens:
        h.avg_msg_length = int(sum(all_msg_lens) / len(all_msg_lens))

    # Session size distribution
    size_dist = {"Quick (<5 turns)": 0, "Medium (5-15)": 0,
                 "Deep (15-30)": 0, "Marathon (30+)": 0}
    for s in sessions:
        if s.turn_count >= 30:
            size_dist["Marathon (30+)"] += 1
        elif s.turn_count >= 15:
            size_dist["Deep (15-30)"] += 1
        elif s.turn_count >= 5:
            size_dist["Medium (5-15)"] += 1
        else:
            size_dist["Quick (<5 turns)"] += 1
    h.session_size_dist = size_dist

    # Longest session
    by_turns = max(sessions, key=lambda s: s.turn_count)
    h.longest_session_summary = by_turns.summary[:80] if by_turns.summary else "—"
    h.longest_session_turns = by_turns.turn_count

    # Time of day buckets
    for hour, count in hour_counter.items():
        if 6 <= hour < 12:
            h.morning += count
        elif 12 <= hour < 17:
            h.afternoon += count
        elif 17 <= hour < 22:
            h.evening += count
        else:
            h.night += count

    # Streaks
    sorted_dates = sorted(active_days_set)
    h.active_dates = sorted_dates
    if sorted_dates:
        max_streak = cur_streak = 1
        for i in range(1, len(sorted_dates)):
            d1 = datetime.strptime(sorted_dates[i - 1], "%Y-%m-%d")
            d2 = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
            if (d2 - d1).days == 1:
                cur_streak += 1
                max_streak = max(max_streak, cur_streak)
            else:
                cur_streak = 1
        h.max_streak = max_streak

        # Current streak (from most recent active day)
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if sorted_dates[-1] in (today, yesterday):
            cur = 1
            for i in range(len(sorted_dates) - 2, -1, -1):
                d1 = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
                d2 = datetime.strptime(sorted_dates[i + 1], "%Y-%m-%d")
                if (d2 - d1).days == 1:
                    cur += 1
                else:
                    break
            h.current_streak = cur

    return h


def _generate_tips(sessions: list[Session], habits: HabitsData,
                   windows: list[TimeWindow], current_phase: int) -> list[Tip]:
    tips: list[Tip] = []
    n = len(sessions)
    _action_counter = [0]  # mutable counter for unique IDs

    def _make_action_id(prefix: str) -> str:
        _action_counter[0] += 1
        return f"{prefix}-{_action_counter[0]}"

    def _repo_actions(prefix: str, repos: list, build_fn) -> list:
        """Build per-repo TipActions for repos with known local paths."""
        actions = []
        for rp in repos[:6]:
            if not rp.local_path:
                continue
            path, content = build_fn(rp)
            if path and content:
                actions.append(TipAction(
                    action_id=_make_action_id(f"{prefix}-{_short(rp.name)}"),
                    label="⚡ Set up",
                    action_type="create_files",
                    files=[(path, content)],
                    repo_name=_short(rp.name),
                ))
        return actions

    # ═══════════════════════════════════════════════════════════════════════
    # BEST PRACTICES — repo-specific tips based on actual adoption gaps
    # ═══════════════════════════════════════════════════════════════════════

    profiles = habits.repo_profiles
    # Short repo name (strip owner prefix for display)
    def _short(repo: str) -> str:
        return repo.split("/")[-1] if "/" in repo else repo

    # ── copilot-instructions.md ──
    repos_missing_instructions = [
        rp for rp in profiles if not rp.has_copilot_instructions and rp.session_count >= 2
    ]
    repos_with_instructions = [rp for rp in profiles if rp.has_copilot_instructions]

    if repos_missing_instructions:
        names = ", ".join(_short(rp.name) for rp in repos_missing_instructions[:4])

        def _build_instructions(rp):
            gh_dir = os.path.join(rp.local_path, ".github")
            path = os.path.join(gh_dir, "copilot-instructions.md")
            lang = rp.primary_language.lstrip(".").capitalize() if rp.primary_language else "Your language"
            content = TEMPLATE_COPILOT_INSTRUCTIONS.format(lang_hint=f"Primary: {lang}")
            return (path, content)

        per_repo = _repo_actions("ci", repos_missing_instructions, _build_instructions)
        tips.append(Tip(
            "📋", "Add copilot-instructions.md",
            f"{len(repos_missing_instructions)} active repo(s) lack a copilot-instructions.md: "
            f"[b]{names}[/b]. This file gives Copilot project-specific context — "
            "coding standards, preferred libraries, naming conventions.",
            priority=10, category="best-practice",
            how_to=(
                "Start with your most active repo. Create\n"
                ".github/copilot-instructions.md:\n"
                "  ─────────────────────────────────\n"
                "  # Project instructions for Copilot\n"
                "  - Language/framework preferences\n"
                "  - Coding standards & patterns\n"
                "  - Libraries to use or avoid\n"
                "  - Error handling conventions"
            ),
            repo_actions=per_repo,
        ))
    elif repos_with_instructions:
        names = ", ".join(_short(rp.name) for rp in repos_with_instructions[:3])
        tips.append(Tip(
            "✅", "Instructions file in place",
            f"Great — {names} already {'has' if len(repos_with_instructions) == 1 else 'have'} "
            "copilot-instructions.md! Keep it updated as your project evolves.",
            priority=1, category="best-practice",
        ))
    elif not habits.has_copilot_instructions:
        tips.append(Tip(
            "📋", "Add copilot-instructions.md",
            "No copilot-instructions.md found in any repo. This file is the #1 "
            "way to improve Copilot's output — it learns your project's conventions.",
            priority=10, category="best-practice",
            how_to=(
                "Create .github/copilot-instructions.md:\n"
                "  # Project instructions for Copilot\n"
                "  - Use TypeScript with strict mode\n"
                "  - Prefer functional components\n"
                "  - Error handling: always use Result types\n\n"
                "Copilot reads this automatically in every session."
            ),
        ))
    else:
        tips.append(Tip(
            "✅", "Instructions file in place",
            "copilot-instructions.md detected — keep it updated as your project evolves.",
            priority=1, category="best-practice",
        ))

    # ── Custom instruction files ──
    repos_without_custom = [
        rp for rp in profiles
        if not rp.has_custom_instructions and rp.session_count >= 2
    ]
    if repos_without_custom and not habits.has_custom_instructions:
        names = ", ".join(_short(rp.name) for rp in repos_without_custom[:3])

        def _build_custom_instructions(rp):
            instr_dir = os.path.join(rp.local_path, ".github", "instructions")
            path = os.path.join(instr_dir, "testing.instructions.md")
            content = TEMPLATE_CUSTOM_INSTRUCTIONS.format(
                glob_pattern="**/*.test.*",
                concern="Testing",
            )
            return (path, content)

        per_repo = _repo_actions("cust", repos_without_custom, _build_custom_instructions)
        tips.append(Tip(
            "🎯", "Use custom instruction files",
            f"None of your active repos ({names}) use scoped .instructions.md files. "
            "These let you define per-concern rules (testing, security, API design) "
            "that auto-apply based on file patterns.",
            priority=9, category="best-practice",
            how_to=(
                "Create scoped instruction files:\n"
                "  .github/instructions/testing.instructions.md\n\n"
                "With auto-apply glob:\n"
                "  ---\n"
                "  applyTo: \"**/*.test.ts\"\n"
                "  ---\n"
                "  # Testing guidelines\n"
                "  - Use describe/it blocks\n"
                "  - Mock external services"
            ),
            repo_actions=per_repo,
        ))

    # ── MCP config ──
    if not habits.has_mcp_config:
        # MCP config goes in user home, not per-repo
        mcp_path = os.path.join(str(Path.home()), ".copilot", "mcp.json")
        mcp_action = None
        if not os.path.exists(mcp_path):
            mcp_action = TipAction(
                action_id=_make_action_id("mcp-config"),
                label="⚡ Set up now",
                action_type="create_files",
                files=[(mcp_path, TEMPLATE_MCP_JSON)],
            )
        tips.append(Tip(
            "🔌", "Set up MCP servers",
            "MCP (Model Context Protocol) lets Copilot connect to external "
            "tools — databases, APIs, Azure. Like giving Copilot hands to do things.",
            priority=7, category="best-practice",
            how_to=(
                "Create ~/.copilot/mcp.json:\n"
                "  {\n"
                '    "mcpServers": {\n'
                '      "github": {\n'
                '        "command": "npx",\n'
                '        "args": ["-y","@modelcontextprotocol/server-github"]\n'
                "      }\n"
                "    }\n"
                "  }\n\n"
                "Popular: GitHub, Azure, filesystem, databases."
            ),
            action=mcp_action,
        ))
    else:
        tips.append(Tip(
            "✅", "MCP configured",
            "MCP servers set up — you're ahead of most users! "
            "Consider adding more servers as you discover new workflows.",
            priority=1, category="best-practice",
        ))

    # ── Skills ──
    repos_without_skills = [
        rp for rp in profiles if not rp.has_skills and rp.session_count >= 2
    ]
    if repos_without_skills and not habits.has_skills:
        names = ", ".join(_short(rp.name) for rp in repos_without_skills[:3])

        def _build_skill(rp):
            skill_dir = os.path.join(rp.local_path, "skills", "code-reviewer")
            path = os.path.join(skill_dir, "SKILL.md")
            content = TEMPLATE_SKILL_MD.format(
                skill_name="code-reviewer",
                skill_desc="Reviews code for common issues and suggests improvements",
            )
            return (path, content)

        per_repo = _repo_actions("skill", repos_without_skills, _build_skill)
        tips.append(Tip(
            "⚡", "Build a custom skill",
            f"No SKILL.md files found. Skills encapsulate reusable Copilot workflows "
            f"— deploy checkers, code reviewers, data transforms. Try in: [b]{names}[/b].",
            priority=6, category="best-practice",
            how_to=(
                "Create skills/<name>/SKILL.md:\n"
                "  ---\n"
                "  name: deploy-checker\n"
                "  description: Validates deploy readiness\n"
                "  ---\n"
                "  # Deploy Checker\n"
                "  ## Steps\n"
                "  1. Check for uncommitted changes\n"
                "  2. Run test suite\n"
                "  3. Validate env variables"
            ),
            repo_actions=per_repo,
        ))

    # ── .context.md — per-repo ──
    repos_without_context = [
        rp for rp in profiles if not rp.has_context_md and rp.file_count >= 5
    ]
    if repos_without_context:
        names = ", ".join(_short(rp.name) for rp in repos_without_context[:4])

        def _build_context(rp):
            path = os.path.join(rp.local_path, ".context.md")
            short = _short(rp.name)
            content = TEMPLATE_CONTEXT_MD.format(dir_name=short)
            return (path, content)

        per_repo = _repo_actions("ctx", repos_without_context, _build_context)
        tips.append(Tip(
            "📁", "Add .context.md for architecture context",
            f"{len(repos_without_context)} repo(s) lack .context.md files: "
            f"[b]{names}[/b]. These give Copilot architecture awareness — component "
            "relationships, data flows, design decisions.",
            priority=8, category="best-practice",
            how_to=(
                "Create .context.md in key directories:\n\n"
                "Example content:\n"
                "  # Authentication Module\n"
                "  ## Architecture\n"
                "  - JWT tokens in httpOnly cookies\n"
                "  ## Dependencies\n"
                "  - Calls user-service for profile data\n"
                "  ## Invariants\n"
                "  - Tokens expire after 15 minutes"
            ),
            repo_actions=per_repo,
        ))

    # ── Testing — per-repo ──
    repos_without_tests = [
        rp for rp in profiles if not rp.has_tests and rp.file_count >= 3
    ]
    if repos_without_tests:
        names = ", ".join(_short(rp.name) for rp in repos_without_tests[:3])
        lang_hint = repos_without_tests[0].primary_language or "your language"
        tips.append(Tip(
            "🧪", "Add tests with Copilot",
            f"{len(repos_without_tests)} repo(s) have no test files: "
            f"[b]{names}[/b]. Copilot excels at generating tests — it's one "
            "of the highest-ROI use cases.",
            priority=8, category="best-practice",
            how_to=(
                "Start with your most active untested repo:\n"
                + "\n".join(
                    f"  → {rp.name} ({rp.primary_language or 'mixed'})"
                    for rp in repos_without_tests[:3]
                ) + "\n\n"
                "High-impact prompts:\n"
                f'  "Write unit tests for the main module\n'
                f'   covering edge cases and error paths"\n\n'
                '  "Look at the existing code and generate\n'
                '   matching tests with good coverage"'
            ),
        ))
    else:
        test_pct = habits.test_session_count / max(n, 1)
        if test_pct < 0.1:
            tips.append(Tip(
                "🧪", "Use Copilot for testing more",
                f"Only {habits.test_session_count} of {n} sessions touched test files "
                f"({test_pct:.0%}). Try: 'write tests for this module' more often.",
                priority=8, category="best-practice",
            ))

    tips.append(Tip(
        "📌", "Pin key files with prompt starters",
        "Start complex prompts by referencing key files explicitly. This "
        "grounds Copilot in your actual code rather than generic patterns.",
        priority=7, category="best-practice",
        how_to=(
            "Example prompt patterns:\n"
            '  "Look at src/models/user.ts and add a\n'
            '   resetPassword method following the same pattern"\n\n'
            '  "Based on the schema in prisma/schema.prisma,\n'
            '   generate a migration for adding a teams table"\n\n'
            '  "Match the test style in tests/auth.test.ts\n'
            '   and write tests for the new billing module"'
        ),
    ))

    # ── Documentation — per-repo ──
    repos_without_docs = [
        rp for rp in profiles if not rp.has_docs and rp.file_count >= 3
    ]
    doc_pct = habits.doc_session_count / max(n, 1)
    if repos_without_docs and doc_pct < 0.15:
        names = ", ".join(_short(rp.name) for rp in repos_without_docs[:3])
        tips.append(Tip(
            "📖", "Generate docs with Copilot",
            f"{len(repos_without_docs)} repo(s) lack README/docs: [b]{names}[/b]. "
            "Copilot can generate READMEs, API docs, and architecture decision records.",
            priority=5, category="best-practice",
            how_to=(
                "Start here:\n"
                + "\n".join(
                    f"  → {rp.name}: 'Generate a README.md based on the code'"
                    for rp in repos_without_docs[:3]
                ) + "\n\n"
                "More doc prompts:\n"
                '  "Add docstrings to all exported functions"\n'
                '  "Write an ADR for our architecture choice"\n'
                '  "Generate a CONTRIBUTING.md with setup steps"'
            ),
        ))

    # ── CI/CD — per-repo ──
    repos_without_cicd = [
        rp for rp in profiles if not rp.has_cicd and rp.file_count >= 5
    ]
    if repos_without_cicd and habits.cicd_session_count < 3:
        names = ", ".join(_short(rp.name) for rp in repos_without_cicd[:3])
        tips.append(Tip(
            "🚀", "Add CI/CD with Copilot",
            f"{len(repos_without_cicd)} repo(s) lack CI/CD configs: [b]{names}[/b]. "
            "Copilot can generate GitHub Actions, Dockerfiles, and deploy configs.",
            priority=5, category="best-practice",
            how_to=(
                "Best candidates:\n"
                + "\n".join(
                    f"  → {rp.name} ({rp.primary_language or 'mixed'})"
                    for rp in repos_without_cicd[:3]
                ) + "\n\n"
                "Prompts:\n"
                '  "Create a GitHub Actions workflow that runs\n'
                '   tests on PR and deploys on merge to main"\n\n'
                '  "Write a multi-stage Dockerfile for this app"'
            ),
        ))

    # ── Session management ──
    tips.append(Tip(
        "🔄", "Master session management",
        "Start fresh sessions for new tasks. Copilot's context is per-session "
        "— a clean start avoids stale context from earlier conversations. "
        "Use long sessions for iterative work, short ones for quick lookups.",
        priority=6, category="best-practice",
        how_to=(
            "Session strategies:\n"
            "  • One session per feature/bug — keeps context focused\n"
            "  • Start with the goal: 'I need to build X that does Y'\n"
            "  • Reference previous work: 'like we did in auth module'\n"
            "  • If stuck, start fresh rather than fighting stale context\n"
            "  • Use /compact to summarize and free up context mid-session"
        ),
    ))

    # ── Code review with Copilot ──
    tips.append(Tip(
        "🔍", "Use Copilot for code review",
        "Copilot can review your code changes before you push. It catches "
        "bugs, security issues, and style inconsistencies — like a tireless "
        "reviewer that's always available.",
        priority=6, category="best-practice",
        how_to=(
            "Review prompts:\n"
            '  "Review my staged changes for bugs and\n'
            '   security issues"\n\n'
            '  "Look at the diff and suggest improvements\n'
            '   for readability and performance"\n\n'
            '  "Check this PR for any breaking changes\n'
            '   or missing edge cases"\n\n'
            "Copilot CLI even has a built-in code-review\n"
            "agent type for automated PR review."
        ),
    ))

    # ── Refactoring ──
    tips.append(Tip(
        "♻️", "Refactor with confidence",
        "Copilot is excellent at refactoring — renaming across files, "
        "extracting functions, converting patterns, migrating APIs. "
        "Describe the transformation and let it handle the tedious parts.",
        priority=5, category="best-practice",
        how_to=(
            "Refactoring prompts:\n"
            '  "Convert all callback-based functions in\n'
            '   src/api/ to async/await"\n\n'
            '  "Extract the validation logic from UserController\n'
            '   into a separate validation service"\n\n'
            '  "Replace all raw SQL queries with the ORM\n'
            '   equivalents, matching existing patterns"\n\n'
            "Copilot tracks all changed files and can run\n"
            "tests after to verify nothing broke."
        ),
    ))

    # ── Structured output ──
    tips.append(Tip(
        "📐", "Ask for structured output",
        "When asking Copilot for analysis or planning, request structured "
        "formats — tables, bullet lists, pros/cons. This makes outputs "
        "more actionable and easier to share with your team.",
        priority=4, category="best-practice",
        how_to=(
            "Structure prompts:\n"
            '  "Compare Redis vs Memcached for our use case\n'
            '   in a table with: feature, Redis, Memcached"\n\n'
            '  "List the steps to migrate from Express to\n'
            '   Fastify as a numbered checklist"\n\n'
            '  "Summarize the architecture decisions in\n'
            '   ADR format: context, decision, consequences"'
        ),
    ))

    # ═══════════════════════════════════════════════════════════════════════
    # HABIT TIPS — based on actual usage patterns
    # ═══════════════════════════════════════════════════════════════════════

    # ── Consistency ──
    if habits.max_streak < 3:
        tips.append(Tip(
            "🔥", "Build a streak",
            f"Your longest streak is {habits.max_streak} day(s). Try using Copilot "
            "3 days in a row — habits form with consistency. Even a quick Q&A counts!",
            priority=9, category="habit",
        ))
    elif habits.max_streak >= 5:
        tips.append(Tip(
            "🔥", "Streak champion!",
            f"Best streak: {habits.max_streak} consecutive days — great discipline!",
            priority=2, category="habit",
        ))

    # ── Session depth ──
    quick_pct = habits.session_size_dist.get("Quick (<5 turns)", 0) / max(n, 1)
    if quick_pct > 0.7:
        tips.append(Tip(
            "🏊", "Dive deeper",
            f"{quick_pct:.0%} of sessions are quick Q&As. Try a longer session: "
            "describe a full feature, let Copilot scaffold, iterate, and refine.",
            priority=8, category="habit",
        ))
    marathon_pct = habits.session_size_dist.get("Marathon (30+)", 0) / max(n, 1)
    if marathon_pct > 0.15:
        tips.append(Tip(
            "✂️", "Break up marathons",
            f"{marathon_pct:.0%} of sessions are 30+ turns. Long sessions lose "
            "context. Split into focused chunks — tests, impl, then docs.",
            priority=6, category="habit",
        ))

    # ── Breadth ──
    repo_count = len(habits.top_repos)
    if repo_count <= 2:
        tips.append(Tip(
            "🌍", "Explore new territory",
            f"Only {repo_count} repo(s) so far. Try Copilot in different projects "
            "— each context teaches new prompting patterns.",
            priority=7, category="habit",
        ))
    ext_set = {e for e, _ in habits.top_extensions[:5]}
    if len(ext_set) <= 2:
        tips.append(Tip(
            "🧬", "Try new languages",
            f"You mostly work with {', '.join(ext_set)}. Try shell scripts, YAML, "
            "SQL, or Markdown — Copilot handles them all.",
            priority=5, category="habit",
        ))

    # ── Timing ──
    total_tod = habits.morning + habits.afternoon + habits.evening + habits.night
    if total_tod > 0:
        if habits.night / total_tod > 0.3:
            tips.append(Tip(
                "🌙", "Night owl detected",
                f"{habits.night}/{total_tod} sessions after 10 PM. Complex tasks "
                "may benefit from fresher hours.",
                priority=4, category="habit",
            ))
        if habits.morning / total_tod > 0.5:
            tips.append(Tip(
                "☀️", "Morning power user",
                "Most sessions in the morning — great focus time! Try end-of-day "
                "reviews too: summarize changes, draft PRs.",
                priority=2, category="habit",
            ))

    # ── Prompt quality ──
    if habits.avg_msg_length < 80:
        tips.append(Tip(
            "📝", "Write richer prompts",
            f"Avg message: {habits.avg_msg_length} chars — short. More descriptive "
            "prompts get dramatically better results. Include what, why, and constraints.",
            priority=8, category="habit",
            how_to=(
                "Prompt formula:\n"
                "  WHAT: 'Add a password reset endpoint'\n"
                "  CONTEXT: 'in the auth module, using our JWT pattern'\n"
                "  CONSTRAINTS: 'with rate limiting, email notification'\n"
                "  STYLE: 'match the style of the login endpoint'\n\n"
                "This 4-part structure consistently produces better results."
            ),
        ))
    elif habits.avg_msg_length > 500:
        tips.append(Tip(
            "✨", "Master of context",
            f"Avg message: {habits.avg_msg_length} chars — very detailed! "
            "Consider using .context.md files or copilot-instructions.md to "
            "avoid repeating context in every prompt.",
            priority=3, category="habit",
        ))

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE TIPS — progression advice
    # ═══════════════════════════════════════════════════════════════════════

    if current_phase == Phase.EXPLORER:
        tips.append(Tip(
            "🚀", "Level up to Builder",
            "Explorer phase. To advance: try multi-file edits, scaffold a "
            "project, or write tests for existing code.",
            priority=10, category="phase",
        ))
    elif current_phase == Phase.BUILDER:
        tips.append(Tip(
            "🎯", "Aim for Orchestrator",
            "Builder phase! To reach Orchestrator: delegate entire features, "
            "try CI/CD configs, work across multiple repos per week.",
            priority=10, category="phase",
        ))
    elif current_phase == Phase.ORCHESTRATOR:
        tips.append(Tip(
            "🏛️", "Path to Architect",
            "Orchestrator! For Architect: use Copilot for system design, "
            "IaC, cross-project refactors. Think at the system level.",
            priority=10, category="phase",
        ))
    elif current_phase == Phase.ARCHITECT:
        tips.append(Tip(
            "🌟", "Share your mastery",
            "Architect level! Amplify impact: write about your journey, "
            "mentor colleagues, build custom skills & plugins.",
            priority=10, category="phase",
        ))

    # ── Delivery ──
    ref_sessions = sum(1 for s in sessions if s.has_refs)
    if ref_sessions == 0:
        tips.append(Tip(
            "🔗", "Connect to delivery",
            "No sessions link to PRs/commits yet. Push your Copilot-built "
            "work to track real impact and make your ROI tangible.",
            priority=7, category="habit",
        ))

    # ── Weekend warrior ──
    weekend = habits.day_distribution.get("Sat", 0) + habits.day_distribution.get("Sun", 0)
    if weekend > n * 0.2:
        tips.append(Tip(
            "🏖️", "Weekend warrior",
            f"{weekend} weekend sessions ({weekend/max(n,1):.0%}). "
            "Use weekends for bolder experiments — Copilot is perfect for hacking.",
            priority=3, category="habit",
        ))

    tips.sort(key=lambda t: t.priority, reverse=True)
    return tips

"""Data loading and analysis for Copilot Journey TUI."""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


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
class JourneyData:
    windows: list
    milestones: list
    roi: ROIEstimate
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
        sessions.append(Session(
            id=r["id"], cwd=r["cwd"], repo=r["repo"], branch=r["branch"],
            summary=r["summary"], created_at=created, updated_at=updated,
            turn_count=r["turn_count"], file_count=r["file_count"],
        ))

    # Load tool/extension diversity per session
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
            ext = Path(tr["file_path"]).suffix.lower()
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

    conn.close()
    return _analyze(sessions)


def _analyze(sessions: list[Session]) -> JourneyData:
    active_days_set: set[str] = set()
    repos: set[str] = set()
    total_turns = total_files = 0

    for s in sessions:
        total_turns += s.turn_count
        total_files += s.file_count
        active_days_set.add(s.created_at.strftime("%Y-%m-%d"))
        if s.repo:
            repos.add(s.repo)

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

    return JourneyData(
        windows=windows,
        milestones=_detect_milestones(sessions),
        roi=_calculate_roi(sessions),
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

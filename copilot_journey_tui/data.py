"""Data loading and analysis for Copilot Journey TUI."""

import sqlite3
from collections import Counter
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


@dataclass
class Tip:
    emoji: str
    title: str
    body: str
    priority: int = 0  # higher = more relevant


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

    conn.close()
    return _analyze(sessions, file_paths, checkpoint_topics)


def _analyze(sessions: list[Session], file_paths: list[str],
             checkpoint_topics: list[str]) -> JourneyData:
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
                             active_days_set, checkpoint_topics)
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
                    checkpoint_topics: list[str]) -> HabitsData:
    h = HabitsData()
    h.hour_distribution = dict(hour_counter)
    h.day_distribution = dict(day_counter)
    h.peak_hour = hour_counter.most_common(1)[0][0] if hour_counter else 9
    h.peak_day = day_counter.most_common(1)[0][0] if day_counter else "Mon"
    h.checkpoint_topics = checkpoint_topics[:15]

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

    # ── Consistency tips ──
    if habits.max_streak < 3:
        tips.append(Tip(
            "🔥", "Build a streak",
            "Your longest streak is just {0} day(s). Try using Copilot 3 days in a "
            "row — habits form fastest with consistency. Even a quick Q&A counts!".format(
                habits.max_streak),
            priority=9,
        ))
    elif habits.max_streak >= 5:
        tips.append(Tip(
            "🔥", "Streak champion!",
            f"Your best streak is {habits.max_streak} consecutive days — great "
            "discipline! Keep it going to reinforce muscle memory.",
            priority=2,
        ))

    # ── Session depth tips ──
    quick_pct = habits.session_size_dist.get("Quick (<5 turns)", 0) / max(n, 1)
    if quick_pct > 0.7:
        tips.append(Tip(
            "🏊", "Dive deeper",
            f"{quick_pct:.0%} of your sessions are quick Q&As. Try a longer session: "
            "describe a full feature and let Copilot scaffold it. "
            "You'll be surprised how much it can do in one go.",
            priority=8,
        ))
    marathon_pct = habits.session_size_dist.get("Marathon (30+)", 0) / max(n, 1)
    if marathon_pct > 0.15:
        tips.append(Tip(
            "✂️", "Break up marathons",
            f"{marathon_pct:.0%} of your sessions are 30+ turns. Long sessions can "
            "lose context. Try splitting into focused chunks — one session per "
            "concern (tests, then implementation, then docs).",
            priority=6,
        ))

    # ── Breadth tips ──
    repo_count = len(habits.top_repos)
    if repo_count <= 2:
        tips.append(Tip(
            "🌍", "Explore new territory",
            "You've only used Copilot in {0} repo(s). Try it in a different project — "
            "even personal or open-source ones. Each new context teaches you new "
            "prompting patterns.".format(repo_count),
            priority=7,
        ))
    ext_set = {e for e, _ in habits.top_extensions[:5]}
    if len(ext_set) <= 2:
        tips.append(Tip(
            "🧪", "Try new languages",
            "You mostly work with {0}. Copilot supports 20+ languages — try it for "
            "shell scripts, YAML configs, SQL, or even Markdown docs.".format(
                ", ".join(ext_set)),
            priority=5,
        ))

    # ── Timing tips ──
    total_tod = habits.morning + habits.afternoon + habits.evening + habits.night
    if total_tod > 0:
        if habits.night / total_tod > 0.3:
            tips.append(Tip(
                "🌙", "Night owl detected",
                f"{habits.night} of {total_tod} sessions start after 10 PM. "
                "Late-night coding can lead to less precise prompts. "
                "Consider batching complex tasks for when you're fresh.",
                priority=4,
            ))
        if habits.morning / total_tod > 0.5:
            tips.append(Tip(
                "☀️", "Morning power user",
                "Most of your sessions happen in the morning — great for focus! "
                "Try using Copilot for end-of-day reviews too: summarize changes, "
                "generate commit messages, or draft PRs.",
                priority=2,
            ))

    # ── Prompt quality tips ──
    if habits.avg_msg_length < 80:
        tips.append(Tip(
            "📝", "Write richer prompts",
            f"Your average message is {habits.avg_msg_length} chars — pretty short. "
            "Longer, more descriptive prompts get dramatically better results. "
            "Include: what you want, the context, constraints, and preferred style.",
            priority=8,
        ))
    elif habits.avg_msg_length > 500:
        tips.append(Tip(
            "✨", "Master of context",
            f"Your avg message is {habits.avg_msg_length} chars — very detailed! "
            "You might benefit from using reference files or pasting code snippets "
            "instead of describing everything from scratch.",
            priority=3,
        ))

    # ── Phase-specific tips ──
    if current_phase == Phase.EXPLORER:
        tips.append(Tip(
            "🚀", "Level up to Builder",
            "You're in the Explorer phase. To advance: try multi-file edits, "
            "ask Copilot to scaffold a project, or use it to write tests for "
            "existing code. Move from questions to building.",
            priority=10,
        ))
    elif current_phase == Phase.BUILDER:
        tips.append(Tip(
            "🎯", "Aim for Orchestrator",
            "You're a Builder — nice! To reach Orchestrator: try delegating entire "
            "features, use Copilot for CI/CD configs, and work across multiple "
            "repos in the same week.",
            priority=10,
        ))
    elif current_phase == Phase.ORCHESTRATOR:
        tips.append(Tip(
            "🏛️", "Path to Architect",
            "You're orchestrating well! To reach Architect: use Copilot for "
            "system design, infrastructure-as-code, and cross-project refactors. "
            "Think at the system level, not just the file level.",
            priority=10,
        ))
    elif current_phase == Phase.ARCHITECT:
        tips.append(Tip(
            "🌟", "Share your mastery",
            "You've reached Architect level! Consider: writing about your journey, "
            "mentoring colleagues, or building custom skills/plugins. "
            "You can amplify your impact by helping others level up too.",
            priority=10,
        ))

    # ── Delivery tips ──
    ref_sessions = sum(1 for s in sessions if s.has_refs)
    if ref_sessions == 0:
        tips.append(Tip(
            "🔗", "Connect to delivery",
            "None of your sessions link to PRs or commits yet. When you use "
            "Copilot to build something, push it! This tracks real impact "
            "and makes your ROI story tangible.",
            priority=7,
        ))

    # ── Weekend warrior ──
    weekend = habits.day_distribution.get("Sat", 0) + habits.day_distribution.get("Sun", 0)
    if weekend > n * 0.2:
        tips.append(Tip(
            "🏖️", "Weekend warrior",
            f"You have {weekend} weekend sessions ({weekend/max(n,1):.0%}). "
            "Great enthusiasm! If these are personal projects, try bolder "
            "experiments — Copilot is perfect for weekend hacking.",
            priority=3,
        ))

    tips.sort(key=lambda t: t.priority, reverse=True)
    return tips

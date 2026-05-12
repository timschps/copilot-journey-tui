import sqlite3, os
db = os.path.expanduser('~/.copilot/session-store.db')
conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
repo = conn.execute("SELECT repository FROM sessions WHERE repository IS NOT NULL AND repository != '' GROUP BY repository ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
print(f'Top repo: {repo}')
rows = conn.execute('SELECT id, summary, branch FROM sessions WHERE repository=? LIMIT 5', (repo,)).fetchall()
for r in rows:
    s = (r[1] or '')[:80]
    print(f'  Session: branch={r[2]} summary={s}')
files = conn.execute('SELECT DISTINCT sf.file_path FROM session_files sf JOIN sessions s ON sf.session_id=s.id WHERE s.repository=? ORDER BY sf.file_path', (repo,)).fetchall()
print(f'Files: {len(files)} unique')
for f in files[:15]:
    print(f'  {f[0]}')
cps = conn.execute('SELECT c.title, c.overview FROM checkpoints c JOIN sessions s ON c.session_id=s.id WHERE s.repository=? LIMIT 5', (repo,)).fetchall()
for c in cps:
    o = (c[1] or '')[:80]
    print(f'Checkpoint: {c[0]} | {o}')

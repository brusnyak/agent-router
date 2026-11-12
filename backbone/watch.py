import sqlite3


def latest_sha(repo, run=None):
    if run is None:
        import subprocess

        def run(args):
            return subprocess.check_output(["gh", *args], text=True, timeout=30, stderr=subprocess.DEVNULL)

    out = run(["api", f"repos/{repo}/commits/HEAD", "--jq", ".sha"])
    return out.strip()


def changed(con, repo, run=None):
    con.execute(
        "CREATE TABLE IF NOT EXISTS watch (repo TEXT PRIMARY KEY, sha TEXT)"
    )
    try:
        sha = latest_sha(repo, run=run)
    except Exception:
        return False

    row = con.execute(
        "SELECT sha FROM watch WHERE repo = ?", (repo,)
    ).fetchone()

    if row is None:
        con.execute(
            "INSERT OR REPLACE INTO watch (repo, sha) VALUES (?, ?)", (repo, sha)
        )
        con.commit()
        return True

    if row[0] != sha:
        con.execute(
            "UPDATE watch SET sha = ? WHERE repo = ?", (sha, repo)
        )
        con.commit()
        return True

    return False

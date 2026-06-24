import datetime
import fnmatch
import re
import subprocess
import sys

from atlas_notify import send_telegram

SCRIPTS_DIR = "/Users/yasser/scripts"

DISALLOWED_PATTERNS = [
    "*.db",
    "*.log",
    "*.zip",
    "*.tar.gz",
    "*.bak",
    ".env",
    "*.err",
    "*.out",
    "*.tmp",
]

def _run(cmd, *, check=True, capture=True):
    return subprocess.run(
        cmd,
        cwd=SCRIPTS_DIR,
        check=check,
        capture_output=capture,
        text=True,
    )


def _is_disallowed(path):
    normalized = path.replace("\\", "/")
    base = normalized.rsplit("/", 1)[-1]
    if "__pycache__/" in normalized or normalized.startswith("__pycache__/"):
        return True
    if "pycache/" in normalized or normalized.startswith("pycache/"):
        return True
    if "staging/" in normalized or normalized.startswith("staging/"):
        return True
    if "/backups/" in normalized or normalized.startswith("backups/"):
        return True
    if re.search(r"_20\d{6}_\d{6}\.py$", base):
        return True
    if re.search(r"_wo\d+[A-Za-z]*_20\d{6}_\d{6}\.py$", base):
        return True
    if any(fnmatch.fnmatch(base, pattern) or fnmatch.fnmatch(normalized, pattern) for pattern in DISALLOWED_PATTERNS):
        return True
    return False


def _remove_disallowed_from_index():
    result = _run(["git", "ls-files", "-z"])
    tracked = [p for p in result.stdout.split("\0") if p]
    disallowed = [p for p in tracked if _is_disallowed(p)]
    for i in range(0, len(disallowed), 100):
        chunk = disallowed[i:i + 100]
        _run(["git", "rm", "--cached", "--ignore-unmatch", "--", *chunk], check=False)
    return disallowed


def _changed_files_cached():
    result = _run(["git", "diff", "--cached", "--name-only"])
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def git_push():
    print("Starting GitHub code backup push...")

    _run(["git", "add", "--all"])
    removed = _remove_disallowed_from_index()
    changed = _changed_files_cached()

    if not changed:
        print("No code changes to commit.")
        push = _run(["git", "push", "origin", "main"], check=False)
        if push.returncode != 0:
            raise RuntimeError(f"GitHub push failed: {push.stderr.strip()[:300]}")
        head = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
        return head, [], removed

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit = _run(["git", "commit", "-m", f"Automated Code Backup: {timestamp}"], check=False)
    if commit.returncode != 0:
        err = commit.stderr.strip() or commit.stdout.strip()
        raise RuntimeError(f"Git commit failed: {err[:300]}")

    push = _run(["git", "push", "origin", "main"], check=False)
    if push.returncode != 0:
        raise RuntimeError(f"GitHub push failed: {push.stderr.strip()[:300]}")

    head = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    committed_files = _run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"]).stdout.splitlines()
    return head, committed_files, removed


if __name__ == "__main__":
    print(f"Starting Atlas GitHub code backup at {datetime.datetime.now()}")
    try:
        commit_hash, files, removed = git_push()
        print("GitHub push successful.")
        print(f"Commit: {commit_hash}")
        if files:
            print("Files included:")
            for name in files:
                print(f"- {name}")
        if removed:
            print(f"Disallowed tracked files removed from Git index: {len(removed)}")
        msg = f"✅ Atlas GitHub code backup complete\nCommit: {commit_hash}\nFiles included: {len(files)}"
        send_telegram(msg, label="atlas_backup")
    except Exception as exc:
        print(f"GitHub backup failed: {exc}")
        send_telegram(f"🚨 Atlas GitHub code backup failed: {exc}", label="atlas_backup")
        sys.exit(1)

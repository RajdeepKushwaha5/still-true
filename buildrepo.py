#!/usr/bin/env python3
"""Build a project whose ledger reaches every verdict.

Used twice, so the self-check asserts the shapes the demo shows: once at authoring time
to create the bundled demo project, and once per run by the self-check in a throwaway
directory it owns and removes.

The notes are written by the real recorder, not hand-written JSON, so a change to how a
claim is anchored breaks the fixture instead of silently diverging from it.
"""
import json
import os
import subprocess
import sys

NL = chr(10)
Q = chr(34)

HERE = os.path.dirname(os.path.abspath(__file__))


def git(args, cwd):
    e = dict(os.environ)
    e.update({
        "GIT_AUTHOR_NAME": "Demo", "GIT_AUTHOR_EMAIL": "demo@example.invalid",
        "GIT_COMMITTER_NAME": "Demo", "GIT_COMMITTER_EMAIL": "demo@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
    })
    p = subprocess.run(["git"] + args, cwd=cwd, env=e, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr.strip()[:300]))
    return p.stdout


def write(root, rel, text):
    path = os.path.join(root, rel)
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def rec(root, payload, handoff):
    """Record a note through the real recorder."""
    payload = dict(payload)
    payload["apply"] = True
    p = subprocess.run(["python3", handoff, "record", root, json.dumps(payload)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("record failed: %s" % p.stderr.strip()[:300])
    return json.loads(p.stdout)


def build(root, handoff=None):
    handoff = handoff or os.path.join(HERE, "notes.py")
    if not os.path.isdir(root):
        os.makedirs(root)
    git(["init", "-q", "-b", "main"], root)
    git(["config", "user.email", "demo@example.invalid"], root)
    git(["config", "user.name", "Demo"], root)
    git(["config", "commit.gpgsign", "false"], root)

    write(root, "billing.py", "def charge(amount):" + NL + "    return amount" + NL)
    write(root, "retry.py", "def retry(fn):" + NL + "    return fn()" + NL)
    write(root, "docs/billing-design.md",
          "# Billing design" + NL + NL + "Use the existing payment provider." + NL)
    write(root, ".gitignore", "__pycache__/" + NL)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "initial"], root)

    # 1. CURRENT: a decision resting on a document nobody has touched since
    rec(root, {
        "agent": "claude",
        "claim": "Use the existing payment provider; do not introduce another.",
        "evidence": ["docs/billing-design.md"],
    }, handoff)

    # 2. STALE: a verification recorded against retry.py, which then changes
    rec(root, {
        "agent": "claude",
        "claim": "Retry handling is covered: the targeted retry test passed.",
        "verified_by": "pytest tests/test_retry.py -k targeted",
        "evidence": ["retry.py"],
        "unfinished": "The integration test has not been run.",
    }, handoff)
    write(root, "retry.py",
          "def retry(fn, attempts=3):" + NL +
          "    for _ in range(attempts):" + NL +
          "        try:" + NL +
          "            return fn()" + NL +
          "        except Exception:" + NL +
          "            continue" + NL)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "retry: add attempts"], root)

    # 3. UNBACKED: an assertion with no evidence named at all
    rec(root, {
        "agent": "codex",
        "claim": "The billing module is thread safe.",
    }, handoff)

    # 4. CONFLICT: a second agent contradicts the first decision
    rec(root, {
        "agent": "codex",
        "claim": "Do not use the existing payment provider; introduce the new provider.",
        "evidence": ["docs/billing-design.md"],
    }, handoff)

    # 5. EVIDENCE_GONE: the file a claim rests on is deleted afterwards
    write(root, "legacy_gateway.py", "def send():" + NL + "    return True" + NL)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "add legacy gateway"], root)
    rec(root, {
        "agent": "claude",
        "claim": "The legacy gateway path is exercised by the smoke test.",
        "evidence": ["legacy_gateway.py"],
    }, handoff)
    os.remove(os.path.join(root, "legacy_gateway.py"))
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "drop legacy gateway"], root)

    # 6. ANCHORED_TO_A_DIRTY_TREE: the trap. The agent ran a test, kept editing, and
    #    then checkpointed. The commit it names is not the code it tested.
    write(root, "billing.py",
          "def charge(amount, currency=" + Q + "usd" + Q + "):" + NL +
          "    return (amount, currency)" + NL)
    rec(root, {
        "agent": "claude",
        "claim": "Charge path verified against the fixture suite.",
        "verified_by": "pytest tests/test_billing.py",
        "evidence": ["billing.py"],
    }, handoff)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "billing: add currency"], root)

    git(["add", "-A"], root)
    if git(["status", "--porcelain"], root).strip():
        git(["commit", "-q", "-m", "ledger"], root)
    return {"root": root}


if __name__ == "__main__":
    print(json.dumps(build(sys.argv[1],
                           sys.argv[2] if len(sys.argv) > 2 else None), indent=2))

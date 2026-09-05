#!/usr/bin/env python3
"""Run the real analyzer against a project built for the purpose, before it is trusted
with yours.

The assertions that prove an analyzer works normally live on the author's machine, where
nobody running the play can see them. This builds a throwaway project under the system
temp directory on every run, records notes through the SHIPPED recorder, judges them with
the SHIPPED analyzer, and the presentation withholds its verdict if any case fails.
Nothing is ever written to your project.

Five things a self-check of this play has to assert:

  EVERY VERDICT NEEDS A POSITIVE CASE, or a rule can be deleted unnoticed.

  THE ANCHOR IS PINNED. The whole claim of this play is that a commit id is not enough.
  A case reproduces the situation where HEAD is identical and the bytes are not, and
  fails unless the commit comparison and this play disagree.

  THE LEDGER DOES NOT LIE ABOUT THE TREE. Writing a note creates an untracked directory;
  counting it made the first note dirty the tree and every note after it inherit a
  warning about work nobody did.

  NOTHING IS SILENTLY LOST. Two notes recorded in the same second by the same agent
  collided on one filename and the second replaced the first, which cost four of six
  notes the first time this fixture was built.

  A FAILED TOOL IS NOT AN ANSWER. git that cannot run must not come back as "no notes".

    selfcheck.py  ->  JSON {passed, total, failures}
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ANALYZER = os.path.join(HERE, "notes.py")

MUST_COVER = {"STILL_MATCHES", "FILE_CHANGED_SINCE", "NO_FILES_NAMED", "FILE_IS_GONE",
              "UNSAVED_EDITS_AT_THE_TIME", "ANOTHER_BRANCH"}


def run_json(args, env=None):
    # spawned as a literal so the command can be checked against deps.toml
    p = subprocess.run(["python3"] + args, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "").strip()[:200] or "exit %d" % p.returncode)
    return json.loads(p.stdout)


def judge(root):
    c = run_json([ANALYZER, "collect", root])
    if c.get("status") != "ok":
        return c, None
    return c, run_json([ANALYZER, "judge", root, json.dumps(c)])


def record(root, payload):
    payload = dict(payload)
    payload.setdefault("apply", True)
    return run_json([ANALYZER, "record", root, json.dumps(payload)])


def git(args, root):
    e = dict(os.environ)
    e.update({"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t.t",
              "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.t"})
    return subprocess.run(["git", "-C", root] + args, capture_output=True, text=True, env=e)


def main():
    failures, total = [], 0
    seen = set()
    scratch = None

    try:
        sys.path.insert(0, HERE)
        import buildrepo
        scratch = tempfile.mkdtemp(prefix="still-true-selfcheck-")
        proj = os.path.join(scratch, "project")
        buildrepo.build(proj, ANALYZER)
    except Exception as e:
        print(json.dumps({"passed": 0, "total": 1, "failures": [
            {"case": "fixture-builds", "detail": str(e)[:200]}]}, separators=(",", ":")))
        return

    try:
        collected, out = judge(proj)
        rows = (out or {}).get("notes") or []
        by_verdict = {}
        for r in rows:
            by_verdict.setdefault(r["verdict"], []).append(r)
            seen.add(r["verdict"])

        # ---- one positive case per verdict the bundled project produces
        for v in ("STILL_MATCHES", "FILE_CHANGED_SINCE", "NO_FILES_NAMED", "FILE_IS_GONE",
                  "UNSAVED_EDITS_AT_THE_TIME"):
            total += 1
            if v not in by_verdict:
                failures.append({"case": "verdict:%s" % v,
                                 "detail": "the bundled project produced no %s note; "
                                           "counts were %r" % (v, (out or {}).get("counts"))})

        # FILE_CHANGED_SINCE must name the file, not merely flag the note
        total += 1
        stale = (by_verdict.get("FILE_CHANGED_SINCE") or [{}])[0]
        if "retry.py" not in (stale.get("changed") or []):
            failures.append({"case": "stale:names-the-file",
                             "detail": "the stale note did not name the file that "
                                       "changed, it named %r" % stale.get("changed")})

        # ---- NOTHING SILENTLY LOST: six notes were recorded, six must be readable
        total += 1
        n = len(rows)
        if n != 6:
            failures.append({
                "case": "ledger:keeps-every-note",
                "detail": "6 notes were recorded and %d came back. Two notes written in "
                          "the same second by the same agent must not collide on one "
                          "filename" % n})

        # ---- THE LEDGER MUST NOT DIRTY THE TREE
        #
        # Writing a note creates an untracked .agent-notes/. If that counts as the
        # project being dirty, every note after the first is permanently marked as
        # anchored to a dirty tree, which is the play reporting itself.
        total += 1
        clean = os.path.join(scratch, "clean")
        os.makedirs(clean)
        git(["init", "-q", "-b", "main"], clean)
        git(["config", "user.email", "t@t.t"], clean)
        git(["config", "user.name", "T"], clean)
        with open(os.path.join(clean, "a.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1" + chr(10))
        git(["add", "-A"], clean)
        git(["commit", "-q", "-m", "init"], clean)
        record(clean, {"agent": "claude", "claim": "first", "evidence": ["a.py"]})
        second = record(clean, {"agent": "claude", "claim": "second", "evidence": ["a.py"]})
        if second.get("note", {}).get("tree_dirty_at_record"):
            failures.append({
                "case": "ledger:does-not-dirty-the-tree",
                "detail": "recording a note made the tree look dirty to the next note, "
                          "so the play reports its own bookkeeping as your uncommitted "
                          "work"})

        # ---- THE ANCHOR. A commit id is not enough, and this proves it every run.
        #
        # Edit a file, record a claim while dirty, then discard the edit. HEAD never
        # moved, so a commit comparison says nothing changed. The bytes the claim was
        # made about are gone. If these two ever agree, the case is worthless.
        trap = os.path.join(scratch, "trap")
        os.makedirs(trap)
        git(["init", "-q", "-b", "main"], trap)
        git(["config", "user.email", "t@t.t"], trap)
        git(["config", "user.name", "T"], trap)
        with open(os.path.join(trap, "b.py"), "w", encoding="utf-8") as fh:
            fh.write("v = 1" + chr(10))
        git(["add", "-A"], trap)
        git(["commit", "-q", "-m", "init"], trap)
        head_before = git(["rev-parse", "HEAD"], trap).stdout.strip()
        with open(os.path.join(trap, "b.py"), "w", encoding="utf-8") as fh:
            fh.write("v = 2" + chr(10))
        record(trap, {"agent": "claude", "claim": "verified",
                      "verified_by": "pytest", "evidence": ["b.py"]})
        git(["checkout", "--", "b.py"], trap)
        head_after = git(["rev-parse", "HEAD"], trap).stdout.strip()

        total += 1
        if head_before != head_after:
            failures.append({
                "case": "anchor:commit-comparison-sees-nothing",
                "detail": "the fixture no longer holds HEAD still, so it stops proving "
                          "that a commit id is insufficient"})
        _, tout = judge(trap)
        trow = ((tout or {}).get("notes") or [{}])[0]
        total += 1
        if trow.get("verdict") == "STILL_MATCHES":
            failures.append({
                "case": "anchor:content-not-commit",
                "detail": "HEAD is unchanged and the file's bytes are not, and the claim "
                          "came back STILL_MATCHES. Anchoring on the commit id is exactly the "
                          "mistake this play exists to avoid"})
        total += 1
        if "b.py" not in (trow.get("changed") or []):
            failures.append({"case": "anchor:names-the-file",
                             "detail": "the changed file was not identified: %r"
                                       % trow.get("changed")})

        # ---- ANOTHER_BRANCH: a result from one branch is not a fact about another
        git(["checkout", "-q", "-b", "sidebranch"], trap)
        record(trap, {"agent": "codex", "claim": "branch-local finding",
                      "evidence": ["b.py"]})
        git(["checkout", "-q", "main"], trap)
        _, bout = judge(trap)
        total += 1
        verdicts = [r["verdict"] for r in (bout or {}).get("notes") or []]
        if "ANOTHER_BRANCH" in verdicts:
            seen.add("ANOTHER_BRANCH")
        else:
            failures.append({
                "case": "verdict:ANOTHER_BRANCH",
                "detail": "a note recorded on another branch was not marked as such; "
                          "got %r" % verdicts})

        # ---- competing claims are reported and NOT resolved
        total += 1
        competing = (out or {}).get("competing") or []
        if not competing:
            failures.append({
                "case": "competing:found",
                "detail": "two agents recorded claims about the same evidence file and "
                          "nothing was reported"})
        else:
            total += 1
            c = competing[0]
            if not c.get("left", {}).get("claim") or not c.get("right", {}).get("claim"):
                failures.append({
                    "case": "competing:both-sides-preserved",
                    "detail": "a disagreement was reported with only one side. Preferring "
                              "one is how a real disagreement disappears"})

        # ---- unfinished work survives into the report
        total += 1
        if not ((out or {}).get("open_items") or []):
            failures.append({"case": "open-items:reported",
                             "detail": "a note recorded unfinished work and none was "
                                       "carried into the report"})

        # ---- THE PAYLOAD. collect hands its result to judge as an argument, so a
        # ledger that grows kills the run at ARG_MAX long before rote's 65536 byte
        # preview cap applies. The first published version emitted 1,423,237 bytes on
        # 200 notes and died. Anything that puts raw material back on that boundary
        # must fail here.
        total += 1
        big = os.path.join(scratch, "big")
        os.makedirs(big)
        git(["init", "-q", "-b", "main"], big)
        git(["config", "user.email", "t@t.t"], big)
        git(["config", "user.name", "T"], big)
        names = []
        for i in range(30):
            rel = "f%d.py" % i
            names.append(rel)
            with open(os.path.join(big, rel), "w", encoding="utf-8") as fh:
                fh.write("x = %d%s" % (i, chr(10)))
        git(["add", "-A"], big)
        git(["commit", "-q", "-m", "init"], big)
        for i in range(60):
            record(big, {"agent": "claude",
                         "claim": "claim number %d about the system" % i,
                         "verified_by": "pytest -k case%d" % i,
                         "evidence": names})
        raw = run_json([ANALYZER, "collect", big])
        size = len(json.dumps(raw, separators=(",", ":")))
        dropped = raw.get("notes_omitted_for_size") or 0
        # Asserting only that the payload FITS is worthless: the budget guarantees that
        # by discarding notes. The property worth having is that a ledger this small
        # costs nothing to carry, so a regression shows up as notes going missing.
        if dropped:
            failures.append({
                "case": "payload:60-notes-cost-nothing-to-carry",
                "detail": "60 notes needed %d of them dropped to fit (%d bytes). Nothing "
                          "but the ANSWERS should cross the step boundary; shipping the "
                          "hashes cost 1,423,237 bytes and killed the run at ARG_MAX"
                          % (dropped, size)})
        total += 1
        if size > 65536:
            failures.append({
                "case": "payload:fits-through-the-step",
                "detail": "collect emitted %d bytes, handed to judge as an argument, so "
                          "this dies at ARG_MAX before rote's 65536 byte cap applies"
                          % size})
        total += 1
        if raw.get("status") == "ok":
            j = run_json([ANALYZER, "judge", big, json.dumps(raw)])
            if len(j.get("notes") or []) + (j.get("notes_omitted_for_size") or 0) != 60:
                failures.append({
                    "case": "payload:every-note-accounted-for",
                    "detail": "60 notes went in; %d came back and %d were reported as "
                              "left out. A note must never vanish without a count"
                              % (len(j.get("notes") or []),
                                 j.get("notes_omitted_for_size") or 0)})

        # ---- a failed tool is not an answer
        total += 1
        stub = os.path.join(scratch, "stubbin")
        os.makedirs(stub)
        with open(os.path.join(stub, "git"), "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh" + chr(10) + "exit 1" + chr(10))
        os.chmod(os.path.join(stub, "git"), 0o755)
        env = dict(os.environ)
        env["PATH"] = stub + os.pathsep + env.get("PATH", "")
        broken = run_json([ANALYZER, "collect", proj], env=env)
        if broken.get("status") != "git-unavailable":
            failures.append({
                "case": "git:failure-is-not-a-clean-report",
                "detail": "with git failing, collect reported %r. A tool that could not "
                          "run is not an answer about your notes"
                          % broken.get("status")})

        # ---- writes stay inside the ledger
        total += 1
        before = set(glob.glob(os.path.join(clean, "**", "*"), recursive=True))
        record(clean, {"agent": "claude", "claim": "third", "evidence": ["a.py"]})
        after = set(glob.glob(os.path.join(clean, "**", "*"), recursive=True))
        outside = [p for p in (after - before)
                   if ".agent-notes" not in os.path.relpath(p, clean)]
        if outside:
            failures.append({
                "case": "writes:confined-to-the-ledger",
                "detail": "recording a note created files outside .agent-notes/: %r"
                          % [os.path.relpath(p, clean) for p in outside[:4]]})

        # ---- relative root refused
        total += 1
        rel = subprocess.run(["python3", ANALYZER, "collect", "some/relative/path"],
                             capture_output=True, text=True)
        if rel.returncode == 0 or "ABSOLUTE" not in (rel.stderr or ""):
            failures.append({"case": "root:relative-path-refused",
                             "detail": "a relative root was not refused; a step runs "
                                       "inside rote's workspace, so it would read and "
                                       "write the wrong tree"})
    finally:
        if scratch and os.path.isdir(scratch):
            shutil.rmtree(scratch, ignore_errors=True)

    for verdict in sorted(MUST_COVER - seen):
        total += 1
        failures.append({"case": "coverage:%s" % verdict,
                         "detail": "no bundled case asserts this verdict, so removing the "
                                   "rule that produces it would not be noticed"})

    print(json.dumps({"passed": total - len(failures), "total": total,
                      "failures": failures[:10]}, separators=(",", ":")))


if __name__ == "__main__":
    main()

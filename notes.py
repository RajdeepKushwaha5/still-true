#!/usr/bin/env python3
"""still-true: which of the things your last agent told you are still true?

    notes.py record  <root> <note-json>     (the only writing mode)
    notes.py collect <root>
    notes.py judge   <root> <collect-json>

An agent finishes a session and leaves you sentences: a decision it made, a test it
says passed, work it did not finish. The next agent -- often a different one -- reads
those sentences and has no way to know which of them the code still supports.

THE TRAP THIS EXISTS BECAUSE OF. The obvious thing to record with a claim is the commit
id. It is worthless on its own, and worse than nothing when the tree is dirty: if an
agent runs a test, edits three more files, and then checkpoints at HEAD, the commit it
names identifies code that was never tested. Every later reader sees a commit and
believes the test covered it. So a claim here is anchored to the SHA-256 of the exact
bytes of each file it depends on, taken at the moment the claim is recorded, and a tree
that was dirty at that moment is recorded as dirty and reported as such forever after.

What this can and cannot do. It can tell you that a file behind a claim has changed
since the claim was made, which is a fact. It cannot tell you the claim is now false --
a change may be irrelevant to it -- so the verdict is FILE_CHANGED_SINCE, meaning "no longer
evidenced", never "wrong". It never re-runs a test to find out.

Writes: only ever inside <root>/.agent-notes/, only in `record` mode, and only when
the caller passes apply=true. Every other mode opens files for reading.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

sys.dont_write_bytecode = True

NOTES_ROOT = ".agent-notes"
NOTES_DIR = "notes"
MAX_NOTES = 200
MAX_EVIDENCE = 40
MAX_LIST = 12          # paths shown per note; the total is always reported beside it
BUDGET = 56000         # collect payload ceiling, under rote's 65536 with room to spare
HASH_CHARS = 16
MAX_BYTES = 4 * 1024 * 1024        # a file larger than this is hashed by size+mtime only

ALLOWED_GIT = frozenset([
    "rev-parse", "status", "log", "for-each-ref", "symbolic-ref", "ls-files", "diff",
])

GIT_OK, GIT_NO, GIT_DOWN, GIT_EXIT = "ok", "no", "down", "exit"

# There is deliberately no contradiction detector here. The first version looked for a
# negation word and compared the two sides, and the first real pair it met was
# "Use the existing provider; DO NOT introduce another" against
# "DO NOT use the existing provider; introduce the new one" -- the word appears on both
# sides, the test cancelled, and a genuine disagreement was reported as no disagreement.
# Deciding which of two English sentences contradicts the other is not something this
# play can do honestly, so it does not try. It reports that two claims are ABOUT THE
# SAME THING, prints both verbatim with their sources, and leaves the judgement to you.
STOPWORDS = frozenset("""
a an the and or but if then than that this these those for with without to from of on in
at by as is are was were be been being it its we you your our their his her they them
use using used should must can will would could may might do does did not no yes than
""".split())


def norm(path):
    """One Unicode form for every path this play compares or stores.

    macOS hands the same filename back decomposed from the filesystem and composed from
    git. Comparing them raw means an accented name never matches itself, so every path
    is normalised at the boundary rather than at each comparison, where one would be
    forgotten.
    """
    return unicodedata.normalize("NFC", path or "")


def git_run(args, root, timeout=20):
    """One read-only git query, reporting which of four things happened.

    A tool that could not run is not an answer. Folding a missing git, a timeout and a
    real non-zero exit into one None is how a broken machine reports a clean result.
    """
    if not args or args[0] not in ALLOWED_GIT:
        raise ValueError("refused non-query git subcommand: %r" % (args[0] if args else None,))
    try:
        p = subprocess.run(["git", "-c", "core.quotePath=false", "-C", root] + list(args),
                           capture_output=True, text=True, timeout=timeout)
    except Exception:
        return {"rc": None, "out": "", "err": "", "how": GIT_DOWN}
    if p.returncode == 0:
        return {"rc": 0, "out": p.stdout, "err": p.stderr, "how": GIT_OK}
    if "not a git repository" in (p.stderr or "").lower():
        return {"rc": p.returncode, "out": p.stdout, "err": p.stderr, "how": GIT_NO}
    return {"rc": p.returncode, "out": p.stdout, "err": p.stderr, "how": GIT_EXIT}


def git_out(args, root, timeout=20):
    r = git_run(args, root, timeout)
    return r["out"] if r["how"] == GIT_OK else None


def resolve_root(value):
    if value != "demo":
        return value
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo", "project")


def require_absolute(raw):
    if raw != "demo" and not os.path.isabs(raw):
        sys.stderr.write(
            "root must be an ABSOLUTE path, or the word demo. Got: " + raw + chr(10) +
            "A step runs inside rote's own workspace, not the directory you were "
            "standing in, so a relative path silently reads and writes the wrong tree. "
            "There is no correct fallback: the step cannot see your shell directory."
            + chr(10))
        sys.exit(2)


def hash_file(path):
    """SHA-256 of the exact bytes, which is the anchor a claim hangs from.

    A commit id would be cheaper and is what everything else records. It does not
    survive a dirty tree, and a dirty tree is the normal state of a session where an
    agent ran a test and then kept editing.
    """
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return {"state": "unreadable", "reason": type(e).__name__}
    if size > MAX_BYTES:
        return {"state": "too-large", "bytes": size,
                "note": "hashed by size only; content changes under this size are not seen"}
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError as e:
        return {"state": "unreadable", "reason": type(e).__name__}
    return {"state": "hashed", "sha256": h.hexdigest()[:HASH_CHARS], "bytes": size}


def repo_state(root):
    probe = git_run(["rev-parse", "--git-dir"], root)
    if probe["how"] in (GIT_DOWN, GIT_EXIT):
        return {"git": "unavailable"}
    if probe["how"] == GIT_NO:
        return {"git": "not-a-repo"}
    head = (git_out(["rev-parse", "HEAD"], root) or "").strip()
    branch = (git_out(["rev-parse", "--abbrev-ref", "HEAD"], root) or "").strip()
    porcelain = git_out(["status", "--porcelain"], root)
    dirty_paths = []
    if porcelain:
        for ln in porcelain.splitlines():
            if len(ln) <= 3:
                continue
            path = norm(ln[3:].strip().strip(chr(34)))
            # The ledger is this play's own bookkeeping. Counting it makes the first
            # note dirty the tree and every note after it inherit a warning about
            # work nobody did -- the play reporting itself as your uncommitted change.
            if path == NOTES_ROOT or path.startswith(NOTES_ROOT + "/"):
                continue
            dirty_paths.append(path)
    return {
        "git": "ok", "head": head, "branch": branch,
        "dirty": bool(dirty_paths), "dirty_paths": sorted(dirty_paths)[:60],
        "dirty_count": len(dirty_paths),
    }


def notes_dir(root):
    return os.path.join(root, NOTES_ROOT, NOTES_DIR)


def inside(root, path):
    """Refuse any path that leaves the ledger directory."""
    base = os.path.realpath(os.path.join(root, NOTES_ROOT))
    target = os.path.realpath(path)
    return target == base or target.startswith(base + os.sep)


# ------------------------------------------------------------------------- record

def record(root, payload):
    """Write one note. The only mode that writes, and it writes nowhere else.

    Writing is opt-in. Without apply=true this returns exactly what it WOULD record,
    including every hash, and touches nothing -- so the first run anyone makes, and
    every run a reviewer makes, is read-only.
    """
    if not (payload.get("claim") or "").strip():
        return {"status": "nothing-to-record"}
    state = repo_state(root)
    if state.get("git") == "unavailable":
        return {"status": "git-unavailable",
                "detail": "git could not be run, so a claim could not be anchored to a "
                          "repository state. Nothing was written."}

    evidence = []
    for rel in (payload.get("evidence") or [])[:MAX_EVIDENCE]:
        rel = rel.strip()
        if not rel:
            continue
        full = rel if os.path.isabs(rel) else os.path.join(root, rel)
        rec = hash_file(full)
        rec["path"] = norm(os.path.relpath(full, root)
                           if not os.path.isabs(rel) else rel)
        # Was this specific file modified but not committed at the moment of the claim?
        rec["dirty_at_record"] = rec["path"] in set(
            norm(d) for d in (state.get("dirty_paths") or []))
        evidence.append(rec)

    note = {
        "schema": 1,
        "recorded_at": int(time.time()),
        "agent": (payload.get("agent") or "unknown").strip()[:40],
        "claim": (payload.get("claim") or "").strip()[:2000],
        "verified_by": (payload.get("verified_by") or "").strip()[:400],
        "unfinished": (payload.get("unfinished") or "").strip()[:1000],
        "branch": state.get("branch", ""),
        "head": state.get("head", ""),
        # Recorded because a commit id does not identify what was tested when the tree
        # was dirty. Every later read is told this, permanently.
        "tree_dirty_at_record": bool(state.get("dirty")),
        "dirty_count_at_record": state.get("dirty_count", 0),
        "evidence": evidence,
    }

    if not payload.get("apply"):
        return {"status": "preview", "note": note,
                "detail": "nothing was written. This is exactly what would be recorded; "
                          "pass apply=true to write it."}

    d = notes_dir(root)
    if not inside(root, d):
        return {"status": "refused", "detail": "the ledger path escapes the project root"}
    try:
        os.makedirs(d, exist_ok=True)
        # A ledger that loses entries is worse than no ledger. Two notes recorded in
        # the same second by the same agent collided on <timestamp>-<agent>.json and
        # the second silently replaced the first, which cost four of the six notes in
        # the first fixture built with this. The digest makes the name a function of
        # the content, and the loop refuses to reuse a name that already exists.
        stem = re.sub("[^a-z0-9]+", "-", note["agent"].lower())[:20] or "agent"
        digest = hashlib.sha256(
            json.dumps(note, sort_keys=True).encode("utf-8", "replace")).hexdigest()[:8]
        path = None
        for n in range(100):
            suffix = "" if n == 0 else "-%d" % n
            cand = os.path.join(d, "%d-%s-%s%s.json"
                                % (note["recorded_at"], stem, digest, suffix))
            if not os.path.exists(cand):
                path = cand
                break
        if path is None:
            return {"status": "write-failed",
                    "detail": "could not find an unused note name; nothing was written"}
        if not inside(root, path):
            return {"status": "refused", "detail": "note path escapes the ledger directory"}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(note, fh, indent=2, sort_keys=True)
    except OSError as e:
        return {"status": "write-failed", "detail": "%s: %s" % (type(e).__name__, e)}

    return {"status": "ok", "written": os.path.relpath(path, root), "note": note}


# ------------------------------------------------------------------------ collect

def collect(root):
    state = repo_state(root)
    if state.get("git") == "unavailable":
        return {"status": "git-unavailable",
                "detail": "git could not be run, so no claim could be checked against a "
                          "repository state. This is not a statement about your notes."}

    d = notes_dir(root)
    if not os.path.isdir(d):
        return {"status": "no-ledger", "detail": os.path.relpath(d, root),
                "root": root, "state": state}

    notes, unreadable = [], []
    try:
        names = sorted(os.listdir(d))
    except OSError as e:
        return {"status": "no-ledger", "detail": "%s: %s" % (type(e).__name__, e),
                "root": root, "state": state}
    for name in names[:MAX_NOTES]:
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        try:
            with open(p, encoding="utf-8") as fh:
                note = json.load(fh)
        except (OSError, ValueError) as e:
            unreadable.append({"file": name, "reason": type(e).__name__})
            continue
        # Re-hash every piece of evidence as it is NOW, and decide here. The hashes
        # are the bulk and judge has no use for them: it needs to know which files
        # moved, not what they hash to. Shipping them cost 1,423,237 bytes on a
        # 200-note ledger and killed the run at ARG_MAX.
        changed, gone, unreadable_ev, paths = [], [], [], []
        for rec in note.get("evidence") or []:
            rel = norm(rec.get("path") or "")
            paths.append(rel)
            full = rel if os.path.isabs(rel) else os.path.join(root, rel)
            cur = hash_file(full)
            if rec.get("state") != "hashed":
                unreadable_ev.append(rel)
            elif cur.get("state") == "unreadable":
                gone.append(rel)
            elif cur.get("state") != "hashed":
                unreadable_ev.append(rel)
            elif cur.get("sha256") != rec.get("sha256"):
                changed.append(rel)

        notes.append({
            "file": name,
            "agent": note.get("agent", ""),
            "claim": (note.get("claim") or "")[:400],
            "verified_by": (note.get("verified_by") or "")[:200],
            "unfinished": (note.get("unfinished") or "")[:400],
            "branch": note.get("branch", ""),
            "recorded_at": note.get("recorded_at"),
            "tree_dirty_at_record": bool(note.get("tree_dirty_at_record")),
            "dirty_count_at_record": note.get("dirty_count_at_record", 0),
            "evidence_count": len(note.get("evidence") or []),
            "paths": paths[:MAX_LIST],
            "changed": changed[:MAX_LIST], "changed_total": len(changed),
            "gone": gone[:MAX_LIST], "gone_total": len(gone),
            "unreadable_ev": unreadable_ev[:MAX_LIST],
            "unreadable_ev_total": len(unreadable_ev),
        })

    # Last resort. Everything above ships answers rather than material; if a ledger is
    # still too large to hand on, the oldest notes are dropped and counted rather than
    # the run dying at ARG_MAX with nothing to show.
    omitted = 0
    notes.sort(key=lambda n: n.get("recorded_at") or 0, reverse=True)
    while len(json.dumps(notes)) > BUDGET and len(notes) > 1:
        notes.pop()
        omitted += 1

    return {
        "status": "ok", "root": root,
        "root_label": ("demo (bundled project)"
                       if root.endswith(os.path.join("demo", "project")) else root),
        "state": state, "notes": notes, "unreadable": unreadable,
        "notes_truncated": len(names) > MAX_NOTES,
        "notes_omitted_for_size": omitted,
    }


# -------------------------------------------------------------------------- judge

def terms(text):
    return set(w for w in re.split("[^a-z0-9]+", (text or "").lower())
               if len(w) > 3 and w not in STOPWORDS)


def evidence_paths(note):
    return set(p for p in (note.get("paths") or []) if p)


def find_competing(notes):
    """Claims that are about the same thing, presented side by side and never resolved.

    Two signals, both structural: the claims rest on a file in common, or they share
    enough distinctive words to be about one subject. Neither is evidence of a
    contradiction and this never says there is one -- a newer note is not a correction,
    it is a second opinion, and silently preferring it is how a real disagreement
    disappears. What the reader gets is both sentences and where each came from.
    """
    out = []
    for i in range(len(notes)):
        for j in range(i + 1, len(notes)):
            a, b = notes[i], notes[j]
            shared_files = evidence_paths(a) & evidence_paths(b)
            shared_terms = terms(a.get("claim")) & terms(b.get("claim"))
            if not shared_files and len(shared_terms) < 3:
                continue
            out.append({
                "left": {"file": a.get("file"), "agent": a.get("agent"),
                         "claim": (a.get("claim") or "")[:300],
                         "recorded_at": a.get("recorded_at")},
                "right": {"file": b.get("file"), "agent": b.get("agent"),
                          "claim": (b.get("claim") or "")[:300],
                          "recorded_at": b.get("recorded_at")},
                "shared_evidence": sorted(shared_files)[:5],
                "shared_terms": sorted(shared_terms)[:6],
                "same_agent": (a.get("agent") == b.get("agent")),
            })
    return out[:20]


def judge_note(note, state):
    """Decide from the comparison collect already made. No file is read here."""
    row = {
        "file": note.get("file"), "agent": note.get("agent"),
        "claim": note.get("claim") or "",
        "verified_by": note.get("verified_by") or "",
        "unfinished": note.get("unfinished") or "",
        "recorded_at": note.get("recorded_at"),
        "branch": note.get("branch", ""),
        "changed": note.get("changed") or [],
        "changed_total": note.get("changed_total", 0),
        "gone": note.get("gone") or [],
        "gone_total": note.get("gone_total", 0),
        "unreadable": note.get("unreadable_ev") or [],
    }
    ev = note.get("evidence_count") or 0

    # ---- verdict, most serious first
    if note.get("tree_dirty_at_record"):
        # The claim names a commit that does not identify what was actually examined.
        row["verdict"] = "UNSAVED_EDITS_AT_THE_TIME"
        row["detail"] = (
            "%d file(s) had unsaved changes when this was written, so the saved "
            "version this note points at is not the version it was written about"
            % note.get("dirty_count_at_record", 0))
        return row
    if state.get("branch") and note.get("branch") and state["branch"] != note["branch"]:
        row["verdict"] = "ANOTHER_BRANCH"
        row["detail"] = ("written on %s, you are on %s; what is true on one branch is "
                         "not automatically true on another"
                         % (note["branch"], state["branch"]))
        return row
    if row["gone_total"]:
        row["verdict"] = "FILE_IS_GONE"
        row["detail"] = ("the file(s) this note is about cannot be read now: %s"
                         % ", ".join(row["gone"][:3]))
        return row
    if row["changed_total"]:
        row["verdict"] = "FILE_CHANGED_SINCE"
        row["detail"] = ("%s has changed since this was written, so the code no longer "
                         "backs it up. That is not the same as it being wrong."
                         % ", ".join(row["changed"][:3]))
        return row
    if not ev:
        row["verdict"] = "NO_FILES_NAMED"
        row["detail"] = ("the agent named no files, so there is nothing to check this "
                         "against. Written down as its word, not held against it")
        return row
    row["verdict"] = "STILL_MATCHES"
    row["detail"] = ("every file this note is about is exactly as it was when the note "
                     "was written")
    return row


ORDER = ["UNSAVED_EDITS_AT_THE_TIME", "FILE_CHANGED_SINCE", "FILE_IS_GONE", "ANOTHER_BRANCH",
         "NO_FILES_NAMED", "STILL_MATCHES"]


def judge(data):
    notes = data.get("notes") or []
    state = data.get("state") or {}
    rows = [judge_note(n, state) for n in notes]
    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    open_items = [{"file": r["file"], "agent": r["agent"], "unfinished": r["unfinished"]}
                  for r in rows if r["unfinished"]]
    return {
        "status": "ok",
        "root_label": data.get("root_label", ""),
        "state": state,
        "notes": rows,
        "counts": counts,
        "open_items": open_items[:30],
        "competing": find_competing(notes),
        "unreadable": data.get("unreadable", []),
        "notes_truncated": data.get("notes_truncated", False),
        "notes_omitted_for_size": data.get("notes_omitted_for_size", 0),
    }


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: notes.py record|collect|judge <root> [args]" + chr(10))
        sys.exit(2)
    mode, raw = sys.argv[1], sys.argv[2]
    require_absolute(raw)
    root = resolve_root(raw)
    if not os.path.isdir(root):
        sys.stderr.write("error: no such directory: " + root + chr(10))
        sys.exit(2)

    if mode == "record":
        rest = sys.argv[3:]
        if len(rest) == 1 and rest[0].lstrip().startswith("{"):
            payload = json.loads(rest[0])
        else:
            # apply, agent, claim, evidence(csv), verified_by, unfinished
            def arg(n):
                return rest[n] if len(rest) > n else ""
            payload = {
                "apply": str(arg(0)).strip().lower() in ("1", "true", "yes", "on"),
                "agent": arg(1),
                "claim": arg(2),
                "evidence": [e for e in str(arg(3)).split(",") if e.strip()],
                "verified_by": arg(4),
                "unfinished": arg(5),
            }
        print(json.dumps(record(root, payload), separators=(",", ":")))
    elif mode == "collect":
        print(json.dumps(collect(root), separators=(",", ":")))
    elif mode == "judge":
        if len(sys.argv) < 4:
            sys.stderr.write("error: judge needs the collect json" + chr(10))
            sys.exit(2)
        data = json.loads(sys.argv[3])
        if data.get("status") != "ok":
            print(json.dumps(data, separators=(",", ":")))
            return
        print(json.dumps(judge(data), separators=(",", ":")))
    else:
        sys.stderr.write("unknown mode: " + mode + chr(10))
        sys.exit(2)


if __name__ == "__main__":
    main()

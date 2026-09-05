# still-true

**Which of the things your last agent told you are still true?**

```bash
rote play run https://play.modiqo.ai/rajdeepkushwaha/still-true
```

That reads a bundled project with nothing set up. For your own, pass an absolute
`root=`. **Reading is read-only.** Writing happens only when you pass a claim *and*
`apply=true`, only inside `.agent-notes/`, and only by adding a file.

## The problem

A session ends and leaves you sentences. *"Use the existing payment provider."* *"The
retry test passed."* *"The integration test has not run."* The next agent — often a
different one — reads those sentences and has no way to tell which ones the code still
supports.

## Six answers

| verdict | what is being claimed |
|---|---|
| `UNSAVED_EDITS_AT_THE_TIME` | **The one that matters.** The agent had uncommitted edits when it spoke, so the commit it named does not identify the code it was talking about. |
| `FILE_CHANGED_SINCE` | A file the claim rests on changed after the claim was made, so it is **no longer evidenced**. Not a claim that it is wrong. |
| `FILE_IS_GONE` | The file it rests on cannot be read any more. |
| `ANOTHER_BRANCH` | Recorded on a different branch. A result from one branch is not a fact about another. |
| `NO_FILES_NAMED` | The agent named no file at all. This is its word, recorded as exactly that. |
| `STILL_MATCHES` | Every file it rests on is byte-identical to when the claim was made. |

## Why a commit id is not enough

Everything in this space records the commit. Here is what that misses, reproduced by a
bundled case on every run:

```
An agent edits billing.py, runs its test, and checkpoints WITHOUT committing.
The uncommitted edit is later discarded.

  note.head == current HEAD  ->  a commit-based checker says "nothing changed"

  hash recorded with the claim : 85387e42a32a9883
  hash of the file right now   : f75afddc56331fdc
  identical?                   : False
```

HEAD never moved. The bytes the claim was made about are gone from the repository
entirely. So a claim here is pinned to the **SHA-256 of the actual file bytes**, taken
at the moment the claim is recorded, and a tree that was dirty at that moment is
recorded as dirty and reported as such for ever after.

## It does not resolve disagreements

The first version tried to detect contradictions with a negation pattern. The first real
pair it met was:

```
claude: Use the existing payment provider; DO NOT introduce another.
codex:  DO NOT use the existing payment provider; introduce the new provider.
```

The word appears on both sides, the test cancelled, and a genuine disagreement was
reported as no disagreement. Deciding which of two English sentences contradicts the
other is not something this can do honestly, so **it does not try**. It reports that two
claims rest on the same file, prints both verbatim with their sources, and leaves the
judgement to you. Preferring the newer one is how a real disagreement disappears.

## It checks itself in front of you

```
Self-check: PASSED (18/18 bundled analyzer cases)
```

Before reading your ledger it **builds a project of its own** in a temporary directory it
owns and removes, records notes through the shipped recorder, judges them with the
shipped analyzer, and prints the result. A failure withholds the findings.

Proved by mutation, each restored byte-identically by checksum:

```
THE NAIVE VERSION: anchor on the commit id, not the bytes  -> 15/19
note filenames collide again                              -> 10/20
the ledger counts itself as your uncommitted work         -> 14/20
dirty-at-record no longer recorded                        -> 17/19
branch is ignored                                         -> 17/19
competing claims no longer reported                       -> 16/17
git failure folded into a normal answer                   -> 17/18
relative root no longer refused                           -> 17/18
```

Two of those are bugs this actually had. Notes were named `<timestamp>-<agent>.json` and
two written in the same second collided, which cost **four of the six notes** the first
time the fixture was built. And writing a note creates an untracked `.agent-notes/`,
which made the tree look dirty to the *next* note — the play reporting its own
bookkeeping as your uncommitted work.

## Write discipline

Measured, not asserted:

```
default run                        tree digest unchanged, UNTOUCHED
claim without apply=true           tree digest unchanged, preview only
claim with apply=true              1 new file, 0 changes outside .agent-notes/
```

Notes are only ever **added**. Nothing here edits or deletes one.

## What it does not claim

`FILE_CHANGED_SINCE` means a file changed after the claim was made, not that the claim is now false —
the change may have nothing to do with it, and nothing here re-runs a test to find out.
`STILL_MATCHES` means nothing it rests on has moved, not that it was ever true. It cannot read
either agent's internal memory; it only holds what an agent chose to write down.

Neighbours, honestly: [`last-session-autopsy`](https://play.modiqo.ai/chetan/last-session-autopsy)
reconstructs one session's claims and verifies them **now**, which is a different
question from whether a claim has stopped being true since it was made;
[`claude-memory-sync`](https://play.modiqo.ai/dezloper/claude-memory-sync) carries project
knowledge into `CLAUDE.md` without checking any of it against the code; and
[`git-handoff-packet`](https://play.modiqo.ai/chetan/git-handoff-packet) photographs
repository state and records the commit.

## Licence

MIT

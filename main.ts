#!/usr/bin/env -S rote play run
/**
 * still-true
 *
 * Which of the things your last agent told you are still true?
 *
 * @rote-frontmatter
 * ---
 * name: still-true
 * description: 'Your last coding session left you notes. "Use the existing payment provider." "The retry test passed." "The integration test still needs running." This tells you which of those still match your code. When a note is saved it remembers the exact contents of the files it was about, and checks them again every time you read it back. If one of those files changed since, the note is marked as no longer backed up by the code -- not wrong, just not proven any more, and it never says wrong. If the agent named no files at all, it says so plainly: that one is only the agent''s word. If the file is gone, it says that too. If the agent had unsaved edits when it wrote the note, it warns you, because the saved version the note points at was never the version the agent was talking about, and checking the saved version alone would tell you everything is fine. A note written on another branch is kept separate, because a result on one branch is not a fact about another. When two agents write about the same file it shows you both and does not pick a side. Run it with no settings at all to see a small example project. It only reads your files. It writes a note only when you give it one and add apply=true, only into a folder called .agent-notes in your project, and it only ever adds -- it never edits or deletes a note. Before it reads anything of yours it builds a small project of its own, runs its own test cases through the same code, and shows you the result; if any fail it shows you that instead. Needs python3 and git. No network, no accounts, no keys.'
 * provenance:
 *   author: rajdeepkushwaha <rjdprocks9977@gmail.com>
 * source_url: https://github.com/RajdeepKushwaha5/still-true
 * tags:
 * - agents
 * - handoff
 * - memory
 * - evidence
 * - git
 * output:
 *   format: markdown
 * parameters:
 * - name: root
 *   param_type: string
 *   required: false
 *   default: demo
 *   description: Absolute path to the project, or the word demo for the bundled one
 * - name: claim
 *   param_type: string
 *   required: false
 *   default: ''
 *   description: A claim to record. Empty means read the ledger and change nothing
 * - name: evidence
 *   param_type: string
 *   required: false
 *   default: ''
 *   description: Comma-separated files the claim rests on. Without these it is NO_FILES_NAMED
 * - name: verified_by
 *   param_type: string
 *   required: false
 *   default: ''
 *   description: The command that was actually run, recorded verbatim and never re-run
 * - name: unfinished
 *   param_type: string
 *   required: false
 *   default: ''
 *   description: What is still open, carried into every later read
 * - name: agent
 *   param_type: string
 *   required: false
 *   default: unknown
 *   description: Who is recording this, for example claude or codex
 * - name: apply
 *   param_type: string
 *   required: false
 *   default: 'false'
 *   description: Writing is opt-in. Without apply=true a claim is previewed, not written
 * metadata:
 *   rote_version: 0.79.0
 *   version: 0.2.5
 *   status: released
 *   kind: atomic
 *   flow_type: sequential
 *   execution_model: steps_with_presentation
 *   format: typescript
 *   requires_sessions: false
 *   discoverability:
 *     tags:
 *     - agents
 *     - handoff
 *     - memory
 *     - evidence
 *     - git
 * presentation_fixtures:
 *   selfcheck: resources/presentation-fixtures/selfcheck/fixture.yaml
 *   record: resources/presentation-fixtures/record/fixture.yaml
 *   collect: resources/presentation-fixtures/collect/fixture.yaml
 *   judge: resources/presentation-fixtures/judge/fixture.yaml
 * steps:
 *   selfcheck:
 *     type: process.exec
 *     timeout_ms: 180000
 *     argv:
 *     - python3
 *     - '@resource{selfcheck.py}'
 *   record:
 *     type: process.exec
 *     timeout_ms: 120000
 *     argv:
 *     - python3
 *     - '@resource{notes.py}'
 *     - record
 *     - $root
 *     - $apply
 *     - $agent
 *     - $claim
 *     - $evidence
 *     - $verified_by
 *     - $unfinished
 *   collect:
 *     type: process.exec
 *     timeout_ms: 120000
 *     depends_on:
 *     - record
 *     argv:
 *     - python3
 *     - '@resource{notes.py}'
 *     - collect
 *     - $root
 *   judge:
 *     type: process.exec
 *     timeout_ms: 120000
 *     depends_on:
 *     - collect
 *     argv:
 *     - python3
 *     - '@resource{notes.py}'
 *     - judge
 *     - $root
 *     - '@collect{.stdout.text}'
 * ---
 */

const { FlowOutput, loadPresentationContext, stepName } =
  await import("__ROTE_PRESENTATION_SDK__");

const out = new FlowOutput();
const ctx = await loadPresentationContext();

type Row = {
  file: string;
  agent: string;
  claim: string;
  verified_by: string;
  unfinished: string;
  branch: string;
  verdict: string;
  detail: string;
  changed: string[];
  gone: string[];
};

type Degraded = { step: string; state: string; detail: string };
const degraded: Degraded[] = [];

// Takes the handle, not the name, so every stepName("...") stays a literal lint can verify.
function checkStep(name: string, step: ReturnType<typeof ctx.step>) {
  const o = step.outcome as { status: string; output?: Record<string, unknown> };
  if (o.status !== "completed" && o.status !== "restored") {
    degraded.push({
      step: name,
      state: o.status,
      detail: String(o.output?.reason ?? o.output?.message ?? "no detail recorded"),
    });
    return null;
  }
  return (o.output ?? {}) as { body?: Record<string, unknown> };
}

const selfStep = checkStep("selfcheck", ctx.step(stepName("selfcheck")));
const recStep = checkStep("record", ctx.step(stepName("record")));
const collectStep = checkStep("collect", ctx.step(stepName("collect")));
const judgeStep = checkStep("judge", ctx.step(stepName("judge")));

for (
  const [name, st] of [
    ["selfcheck", selfStep],
    ["record", recStep],
    ["collect", collectStep],
    ["judge", judgeStep],
  ] as const
) {
  if (!st) continue;
  const body = (st.body ?? {}) as { stdout?: { truncated?: boolean; bytes?: number } };
  if (body.stdout?.truncated === true) {
    degraded.push({
      step: name,
      state: "truncated",
      detail:
        `stdout was cut at rote's 64 KiB preview ceiling (${body.stdout?.bytes ?? "?"} bytes produced)`,
    });
  }
}

function textOf(st: { body?: Record<string, unknown> } | null): string {
  const body = (st?.body ?? {}) as { stdout?: { text?: string } };
  return body.stdout?.text ?? "";
}

const BLURB: Record<string, string> = {
  UNSAVED_EDITS_AT_THE_TIME:
    "The agent had edits it had not saved to git when it wrote this. So the saved version this note points at was never the version the agent was talking about — and checking that saved version alone would tell you everything is fine.",
  FILE_CHANGED_SINCE:
    "A file this note is about has changed since the note was written. The note is no longer backed up by the code. **That does not make it wrong** — the change may have nothing to do with it. Nothing was re-run to find out.",
  FILE_IS_GONE:
    "The file this note is about cannot be read any more, so there is nothing left to check it against.",
  ANOTHER_BRANCH:
    "Written on a different branch. What is true on one branch is not automatically true on another, so this is kept separate rather than quietly counted.",
  NO_FILES_NAMED:
    "The agent named no files, so there is nothing to check. This is the agent's word, written down as exactly that — not held against it.",
  STILL_MATCHES:
    "Every file this note is about is exactly as it was when the note was written. That does not mean the note was ever right, only that nothing it depends on has moved.",
};

const ORDER = [
  "UNSAVED_EDITS_AT_THE_TIME",
  "FILE_CHANGED_SINCE",
  "FILE_IS_GONE",
  "ANOTHER_BRANCH",
  "NO_FILES_NAMED",
  "STILL_MATCHES",
];

let selfPassed = 0;
let selfTotal = 0;
let selfFailures: { case: string; detail: string }[] = [];
if (selfStep) {
  try {
    const parsed = JSON.parse(textOf(selfStep)) as {
      passed: number;
      total: number;
      failures: { case: string; detail: string }[];
    };
    selfPassed = parsed.passed;
    selfTotal = parsed.total;
    selfFailures = parsed.failures ?? [];
  } catch {
    selfFailures = [{ case: "selfcheck", detail: "did not return JSON" }];
    selfTotal = 1;
  }
}
const selfResult = { passed: selfPassed, total: selfTotal, failures: selfFailures };
const selfOk = selfTotal > 0 && selfFailures.length === 0 && selfStep !== null;
const selfLine = selfOk
  ? `Self-check: PASSED (${selfPassed}/${selfTotal} bundled analyzer cases)`
  : `Self-check: FAILED (${selfPassed}/${selfTotal} bundled analyzer cases)`;

// what the record step did, if anything
let recLine = "";
let recStatus = "nothing-to-record";
const HOW_TO_RECORD =
  'claim="the retry test passed" evidence=retry.py verified_by="pytest -k retry" apply=true';
try {
  const r = JSON.parse(textOf(recStep)) as {
    status: string;
    written?: string;
    detail?: string;
    apply_requested?: boolean;
  };
  recStatus = r.status;
  if (r.status === "ok") {
    recLine = `\n\n**Recorded** to \`${r.written}\`.`;
  } else if (r.status === "preview") {
    recLine =
      `\n\n**Nothing was written.** That claim is shown below as it would be recorded; pass \`apply=true\` to write it.`;
  } else if (r.status === "nothing-to-record") {
    // A reader who passed apply=true and got nothing needs to know which half was
    // missing, rather than being left to work it out from the parameter list.
    recLine = r.apply_requested
      ? `\n\n**Nothing was written, because no claim was given.** \`apply=true\` says it is allowed to write; the claim is what there would be to write. Add one:\n\n\`${HOW_TO_RECORD}\``
      : `\n\nReading only. To add a note:\n\n\`${HOW_TO_RECORD}\``;
  } else {
    recLine = `\n\n**Not recorded** (${r.status}): ${r.detail ?? ""}`;
  }
} catch { /* record step produced no JSON; the read below still stands */ }

if (degraded.length > 0) {
  out.human(
    `# Run incomplete\n\nA step did not finish, so no verdict is offered. A partial read of a ledger must never look like a clean one.\n\n${
      degraded.map((d) => `- **${d.step}** (${d.state}) — ${d.detail}`).join("\n")
    }`,
  );
  out.summary(`incomplete: ${degraded.map((d) => d.step).join(", ")}`);
  out.result({ status: "incomplete", degraded, self_check: selfResult });
} else if (!selfOk) {
  out.human(
    `${selfLine}\n\n# Findings withheld\n\nThe shipped analyzer failed its own bundled cases, so nothing it would say about your ledger is trustworthy on this run.\n\n${
      selfFailures.map((f) => `- **${f.case}** — ${f.detail}`).join("\n")
    }`,
  );
  out.summary(`self-check failed: ${selfPassed}/${selfTotal}`);
  out.result({ self_check: selfResult, findings_withheld: true });
} else {
  let parsed: {
    status: string;
    detail?: string;
    root_label?: string;
    state?: { branch?: string; dirty?: boolean; dirty_count?: number };
    notes?: Row[];
    counts?: Record<string, number>;
    open_items?: { agent: string; unfinished: string }[];
    notes_omitted_for_size?: number;
    notes_truncated?: boolean;
    competing?: {
      left: { agent: string; claim: string };
      right: { agent: string; claim: string };
      shared_evidence: string[];
      shared_terms: string[];
      same_agent: boolean;
    }[];
    unreadable?: { file: string; reason: string }[];
  };
  try {
    parsed = JSON.parse(textOf(judgeStep) || textOf(collectStep));
  } catch (cause) {
    throw new Error("judge stdout was not valid JSON", { cause });
  }

  if (parsed.status !== "ok") {
    const why: Record<string, string> = {
      "no-ledger":
        "No ledger here yet. Record the first claim with `claim=\"...\" evidence=path/to/file apply=true`.",
      "not-a-git-repo":
        "That path is not inside a git repository, so a claim could not be anchored to one.",
      "git-unavailable":
        "git could not be run, so nothing could be checked. This says nothing about your notes.",
    };
    out.human(
      `${selfLine}${recLine}\n\n# Nothing to read back\n\n${why[parsed.status] ?? parsed.status}${
        parsed.detail ? `\n\n\`${parsed.detail}\`` : ""
      }`,
    );
    out.summary(`no ledger: ${parsed.status}`);
    out.result({ status: parsed.status, record: recStatus, self_check: selfResult });
  } else {
    const rows = parsed.notes ?? [];
    const counts = parsed.counts ?? {};
    const notCurrent = rows.length - (counts["STILL_MATCHES"] ?? 0);

    const sections: string[] = [];
    sections.push(
      `# ${rows.length} note(s) from your agents${
        String(parsed.root_label ?? "").startsWith("demo") ? " in the bundled example" : ""
      }, ${notCurrent} the code no longer backs up\n\nProject: ${parsed.root_label}. On branch \`${
        parsed.state?.branch ?? "?"
      }\`.`,
    );

    for (const v of ORDER) {
      const group = rows.filter((r) => r.verdict === v);
      if (group.length === 0) continue;
      const lines = group.map((r) => {
        let s = `- **${r.agent}**: ${r.claim}\n  ${r.detail}`;
        if (r.verified_by) s += `\n  claimed verification: \`${r.verified_by}\``;
        if (r.changed?.length) {
          s += `\n  changed since: ${r.changed.map((f) => `\`${f}\``).join(", ")}`;
        }
        if (r.gone?.length) {
          s += `\n  no longer readable: ${r.gone.map((f) => `\`${f}\``).join(", ")}`;
        }
        return s;
      });
      sections.push(`## ${v} (${group.length})\n${BLURB[v]}\n${lines.join("\n")}`);
    }

    const open = parsed.open_items ?? [];
    if (open.length > 0) {
      sections.push(
        `## Not finished (${open.length})\nWhat an agent said it had not finished. Carried forward on every read until the note is removed.\n${
          open.map((o) => `- **${o.agent}**: ${o.unfinished}`).join("\n")
        }`,
      );
    }

    const comp = parsed.competing ?? [];
    if (comp.length > 0) {
      sections.push(
        `## Two claims about the same thing (${comp.length})\nBoth are printed and neither is preferred. Deciding which of two English sentences contradicts the other is not something this can do honestly, so it does not try — it shows you that they are about the same subject and leaves the judgement to you.\n${
          comp.map((c) =>
            `- **${c.left.agent}**: ${c.left.claim}\n  **${c.right.agent}**: ${c.right.claim}\n  ${
              c.shared_evidence.length > 0
                ? `both rest on ${c.shared_evidence.map((f) => `\`${f}\``).join(", ")}`
                : `shared terms: ${c.shared_terms.join(", ")}`
            }${c.same_agent ? " — same agent, different sessions" : ""}`
          ).join("\n")
        }`,
      );
    }

    if ((parsed.notes_omitted_for_size ?? 0) > 0 || parsed.notes_truncated) {
      const bits: string[] = [];
      if ((parsed.notes_omitted_for_size ?? 0) > 0) {
        bits.push(
          `${parsed.notes_omitted_for_size} older note(s) were left out so the rest could fit through this step`,
        );
      }
      if (parsed.notes_truncated) {
        bits.push("there are more notes on disk than were read at all");
      }
      sections.push(
        `## Not all of your notes are here
${
          bits.join(", and ")
        }. This is a limit of this play, not a quieter project. The newest notes are the ones kept.`,
      );
    }

    if ((parsed.unreadable ?? []).length > 0) {
      sections.push(
        `## Notes that could not be read (${parsed.unreadable!.length})\nThese were not judged, so a short ledger does not mean a quiet project.\n${
          parsed.unreadable!.map((u) => `- \`${u.file}\` (${u.reason})`).join("\n")
        }`,
      );
    }

    sections.push(
      `## What this does not claim\nFILE_CHANGED_SINCE means a file changed after the claim was made, not that the claim is now false — the change may have nothing to do with it, and nothing here re-runs a test to find out. STILL_MATCHES means nothing the claim rests on has moved, not that the claim was ever true. A claim with no evidence is recorded as the agent's word and never scored against it. Notes are only ever added; nothing here edits or deletes one.`,
    );

    out.human(`${selfLine}${recLine}\n\n${sections.join("\n\n")}`);
    out.summary(
      `${rows.length} claim(s): ${
        ORDER.filter((v) => counts[v]).map((v) => `${counts[v]} ${v.toLowerCase()}`).join(", ")
      }`,
    );
    out.result({
      status: "ok",
      record: recStatus,
      counts,
      notes: rows,
      open_items: open,
      competing: comp,
      self_check: selfResult,
      // three views of one run. The listing is capped in the
      // human view, so which view is canonical is stated here
      // rather than left for a reader to discover.
      representations: {
        human:
          "complete for the notes that were read: every claim with its verdict, the files that changed under it, the open work and the claims that are about the same subject",
        json:
          "canonical superset: the same claims plus the self-check result, the repository state, the counts and the notes that could not be read",
        summary: "intentionally lossy: claim counts by verdict",
      },
    });
  }
}

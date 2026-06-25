# Agent Operating Instructions — Enterprise RAG Multi-Tenancy Migration

You are executing `IMPLEMENTATION_PLAN.md`, a 6-phase migration that adds multi-tenancy (Auth0, Postgres RLS, scoped RBAC, Qdrant, Redis, compliance tooling) to an existing single-tenant RAG platform repo. These instructions govern *how* you execute that plan. The plan file governs *what* you do. If the two ever conflict, these instructions win on process (sequencing, stopping, confirmation), and the plan file wins on technical content (schemas, file paths, code).

Read `IMPLEMENTATION_PLAN.md` in full before doing anything else, if you have not already done so this session.

---

## 0. State model — read this before touching any code

This migration may span multiple sessions. You cannot assume the conversation history in front of you is the complete record of what has already been done. Treat a file named `MIGRATION_STATE.md` in the repo root as the single source of truth for progress.

- **If `MIGRATION_STATE.md` does not exist**: this is session 1. Create it now, before any other action, using the template in Section 5. Set Phase 1 to `in_progress`, all others to `not_started`.
- **If `MIGRATION_STATE.md` exists**: read it first. Do not trust your own memory of "what we did last time" over what this file says. Resume from the first phase marked anything other than `complete`. If a phase is marked `in_progress`, re-verify its already-completed tasks before continuing — a previous session may have stopped mid-task.
- **Update `MIGRATION_STATE.md` after every task**, not just at phase boundaries. If your session ends unexpectedly, the next session must be able to tell exactly which tasks are done from this file alone, without re-reading your prior chat turns.

Never infer phase status from the branch name, the `depends_on` YAML in the plan file, or what "seems likely" — only from `MIGRATION_STATE.md`'s actual content.

---

## 1. Before Phase 1 ever starts — repo discovery

Even though you have live repo access, access is not the same as knowledge of the repo's actual structure. The plan file contains explicit placeholders like "locate the existing X before modifying" — these are not optional steps.

Run this discovery sequence once, before Phase 1's tasks, and record findings in `MIGRATION_STATE.md` under a `## Discovery Notes` section:

1. `git status` and `git log --oneline -10` — confirm working tree is clean and identify the current HEAD.
2. Confirm or create the tag: if `git tag --list pre-migration-v1` is empty, create it now on current HEAD. Never recreate or move this tag once it exists.
3. Map every file path referenced in the plan against what actually exists: auth module location, existing RBAC implementation, SQLite connection import sites, current session store implementation, current vector DB client usage, upload route location. Use `grep -r` and directory listing, not assumptions from the plan's prose.
4. Where the plan's assumed path doesn't match reality, record the real path in `MIGRATION_STATE.md`'s Discovery Notes and use the real path for every subsequent task referencing it. Do not silently rewrite the plan file itself.
5. If a referenced file or pattern cannot be found at all (e.g. no SQLite import exists where expected), stop and report this in your phase-boundary output (Section 3) rather than guessing or skipping silently.

---

## 2. Execution rules within a phase

- Work the tasks in a phase in the order listed. A task's file paths are exact *unless* Discovery Notes recorded a corrected path for that file — use the correction.
- Create a down-migration for every up-migration, as the plan requires. Do not skip this even if no one will run it soon.
- Do not delete a legacy code path (SQLite access, in-memory sessions, self-issued JWT) until the specific task that names it for removal. Earlier tasks run old and new paths side by side behind the stated feature flag — leaving the legacy path in place a task too long is always safer than removing it a task too early.
- If a task's instructions conflict with what Discovery actually found, stop and report the conflict in your next output rather than resolving it silently. Silent resolution of a conflict between plan and reality is the one thing you must never do unsupervised.
- Run each task's relevant tests as you complete it, not only at the end of the phase in a batch — catching a failure immediately after the task that caused it is much cheaper to diagnose than catching it after five more tasks have built on top of it.

---

## 3. Phase boundaries — hard stop, every time

This is the most important rule in this document. After completing all tasks in a phase:

1. Run every command in that phase's `Verification` section from the plan file.
2. If any command fails or any assertion is false: do not proceed. Report the failure, what you believe caused it, and stop. Do not attempt the next phase "to make progress anyway."
3. If all verification passes: update `MIGRATION_STATE.md` — mark this phase `complete`, record the commit hash of the merge to `main`, and set the next phase to `ready_to_start` (not `in_progress` — you do not start the next phase's tasks in the same turn).
4. Output a **Phase Complete Report** (template in Section 5) and then stop. Do not begin the next phase's tasks even if you have remaining context budget, even if the next phase seems straightforward, even if no human has responded yet. Waiting for explicit confirmation before starting the next phase is not optional caution — it is the operating mode you were configured for.
5. Resume only when the person operating this session explicitly says to proceed to the next phase.

The only exception to "stop after every phase" is if you are explicitly instructed at the start of the session to run autonomously through multiple phases — absent that explicit instruction, the default is one phase per stop, no exceptions.

---

## 4. Escalation gates — confirm even mid-phase, for these specific actions

Some actions inside an already-approved phase are still significant enough to need a second, explicit go-ahead before you execute them, separate from the phase-level approval. Pause and ask before:

- **Phase 2, task 2.4** — running the SQLite-to-Postgres data migration script against anything other than a local/dev database. Confirm the target `DATABASE_URL` is not a production value before running.
- **Phase 4, task 4.4** — the Milvus-to-Qdrant cutover decision (re-embed vs. export-and-migrate). State which path you're taking and why, and wait for acknowledgment if data volume is ambiguous from Discovery.
- **Phase 5, task 5.2** — removing the in-process TTL eviction loop. Confirm Redis-backed expiry (5.2's `ex=TTL_SECONDS`) is verified working *before* deleting the old eviction code, not after, even though the task ordering in the plan lists them together.
- **Phase 6, task 6.2** — the cascading org-deletion endpoint. Before marking this task complete, confirm the deletion-order test (`test_delete_org_leaves_zero_residue`) was run against a disposable test org, never against `default_org` or any org with real seeded data you'd want to keep.
- **Any action that touches Auth0 dashboard configuration, IdP secrets, or production environment variables** — these are typically outside version control and unrecoverable by `git revert`. Treat anything outside the repo's own files as higher-stakes than anything inside it.

When in doubt about whether something needs this kind of pause, the cost of asking unnecessarily is one wasted turn; the cost of not asking when it mattered could be unrecoverable. Default to asking.

---

## 5. Templates

### `MIGRATION_STATE.md` template (create this exact structure)

```markdown
# Migration State

Last updated: <ISO timestamp>
Current phase: <phase_id>

## Discovery Notes
<filled in once, before Phase 1, per Section 1 above>

## Phase Status

| Phase | Status | Branch | Merge commit | Notes |
|-------|--------|--------|---------------|-------|
| 1 — Auth0 | not_started / in_progress / complete | feature/auth0 | | |
| 2 — Postgres + RLS | not_started | feature/postgres-rls | | |
| 3 — RBAC v2 | not_started | feature/rbac-v2 | | |
| 4 — Qdrant + Storage | not_started | feature/qdrant-storage | | |
| 5 — Redis + Scale | not_started | feature/redis-scale | | |
| 6 — Compliance | not_started | feature/compliance-audit | | |

## Task-Level Log
<append one line per completed task, e.g.:>
- [phase_1 / 1.5] Created app/auth/auth0_verify.py — done, tests pass
- [phase_1 / 1.6] Added AUTH_PROVIDER flag — done
```

### Phase Complete Report (output this at every phase boundary, then stop)

```
PHASE <N> COMPLETE — <phase name>

Tasks completed: <list>
Verification run:
  <command> — PASS/FAIL
  <command> — PASS/FAIL
Deviations from plan (if any): <Discovery-driven path corrections, or "none">
Merge commit: <hash>
MIGRATION_STATE.md updated: yes

Next phase ready: Phase <N+1> — <name>
Waiting for confirmation to proceed.
```

---

## 6. What "optimized for this task" means here, stated explicitly

If you find yourself tempted to skip a discovery step because the plan's assumed path is "probably right," or to continue into the next phase because stopping "loses momentum," or to resolve a plan/reality conflict yourself because asking "would slow things down" — these are exactly the shortcuts this document exists to prevent. The plan file already contains the technical correctness (schemas, RLS policies, mandatory filters); your job in this session is process discipline around executing it safely across however many sessions it takes, not speed.

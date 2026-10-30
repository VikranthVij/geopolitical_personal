# Repository Git workflow

## Authority and destination

User-directed permanent policy, established 2026-10-30.
Repository: https://github.com/VikranthVij/geopolitical_personal.git
Default target: `origin/main`. Use a dedicated branch and pull request when separate review is required. Never force-push without a new explicit request and separate review.

Every completed, tested and accepted logical change to code, tests, migrations, configuration, architecture, documentation, verification or deployment assets must be committed, pushed and remotely verified before the task is reported complete. Intermediate edits do not require individual commits. This authorization covers synchronization, not deployment, data repair, source ingestion or live migrations. Explicit task instructions can prohibit or defer pushing.

## Required sequence

1. **Inspect:** run `git status --short`, `git branch --show-current`, `git log -3 --oneline`, `git remote -v`; inspect HEAD/upstream, staged/unstaged/untracked changes and relevant project instructions. Confirm the intended repository and branch before editing.
2. **Preserve and isolate:** identify pre-existing work. Keep unrelated modifications and untracked files intact. Never reset/clean/discard someone else's work, delete evidence, overwrite migrations or reformat unrelated source. Stage explicit paths or reviewed hunks; never use indiscriminate `git add .` on a dirty tree. Include reviewed prerequisites only when necessary for a self-contained change, and identify them in the report.
3. **Implement:** complete the requested scope. Keep coherent, reviewable units. Do not bundle unrelated work merely to make the working tree clean.
4. **Test:** run meaningful checks for the changed behavior. Integration fixtures must use a confirmed isolated disposable DB/API, never development intelligence data. Report discovered, executed, passed, failed, errored, skipped and blocked counts separately. Include standalone function tests that unittest discovery omits. Validate migration chains in isolation when relevant. A passing local tree does not validate an incomplete staged subset: test the exact candidate tree when isolating changes from a dirty workspace.
5. **Review:** inspect `git diff`, `git diff --cached`, `git diff --check`, `git status --short`. Exclude credentials, .env, database dumps/volumes, private logs, temporary test runners, personal configuration, .DS_Store, node_modules and generated build output. Inspect newly added files; do not rely solely on .gitignore. Redact sensitive information before reporting errors.
6. **Reconcile:** fetch origin; compare `HEAD...origin/main`, inspect missing commits on both sides. Never force-push or reset to reconcile history. Preserve uncommitted work before any merge/rebase. Use a non-destructive merge or rebase only after understanding the history and applicable task permission. If conflicts cannot be resolved safely, stop and explain the blocker without discarding work.
7. **Commit:** create meaningful scoped messages, e.g. `fix: ground incident relationships and distinguish military escalation`. Commit documentation alongside directly related work, or separately for an independently verified documentation unit. Do not create empty commits or amend/rewrite history without explicit reason/authorization.
8. **Push:** push the reviewed commit(s) to `origin/main`, or the approved review branch. A successful local commit is not synchronization.
9. **Verify:** inspect `git status` and `git log -3 --oneline`; fetch/inspect the remote and verify the pushed SHA with `git ls-remote origin refs/heads/main` (or the chosen branch). Confirm committed files exist on GitHub. Distinguish local tracking refs from the actual remote. Preserve remaining unrelated dirty files and report them clearly.
10. **Report:** summarize changes/files, checks and limitations, commit messages/SHAs, push status/remote branch and remaining issues. Do not claim push completion on authentication/network/conflict failure.

## Conditions that prohibit pushing

- User explicitly requests no push or requires review first.
- Serious unresolved regression, incomplete implementation, or missing mandatory acceptance.
- Unrelated/sensitive changes cannot be safely isolated from the intended commit.
- Remote/branch identity is wrong or unknown.
- Divergent history/conflicts cannot be reconciled without risking existing work.
- Authentication/network restrictions prevent verified synchronization.

In these cases preserve work, explain the precise blocker and the evidence needed to proceed. Never print tokens, passwords or private keys; never bypass a rejected approval or force-push to hide a conflict.

## Live data and deployment

Committing/pushing never authorizes changing historical assignments, deleting relationships/material changes, backfills, live image rollout, service restart or migrations. Follow the task's separate runtime/data permissions. Read-only shadow audits must enforce server read-only mode and reject mutating SQL. Normal independent collector activity must be recorded separately from audit/test effects.

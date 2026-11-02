Continue the Registry V2 build (drop 1 backend, then drop 2 UI).

1. Read `docs/tasks/v2/progress.md` and pick the first task that is not `done`. If one is `in-review`, resume it instead of starting a new one.
2. Read `docs/tasks/v2/conventions.md` and `docs/tasks/conventions.md`, then that task file, then only the `docs/specs/v2.md` sections the task file lists. Do not read the whole spec.
3. Work test-first, inside the task's file list. Do not start the next task.
4. When the task's "Done when" is met and tests pass, set the task to `in-review` in `docs/tasks/v2/progress.md`, then stop and tell me what changed (files, tests run, open questions). Do not commit.
5. I review the diff and ask questions. Address them.
6. When I say it looks good, commit (task id in the message), set the task to `done` in `progress.md` with the commit hash, and commit that progress update together with the task. Then stop. I will clear context and re-run this prompt for the next task.

If `docs/specs/v2.md` and a task file disagree, the spec wins; tell me and fix the task file. If V2 contradicts `docs/specs/v1.md`, V2 wins for the parts it changes.

Continue the Registry V1 build.

1. Read `docs/tasks/progress.md` and pick the first task that is not `done`. If one is `in-review`, resume it instead of starting a new one.
2. Read `docs/tasks/conventions.md`, then that task file, then only the spec sections the task file lists from `docs/specs/v1.md`. Do not read the whole spec.
3. Work test-first, inside the task's file list. Do not start the next task.
4. When the task's "Done when" is met and tests pass, set the task to `in-review` in `progress.md`, then stop and tell me what changed (files, tests run, open questions). Do not commit.
5. I review the diff and ask questions. Address them.
6. When I say it looks good, commit (task id in the message), set the task to `done` in `progress.md` with the commit hash, and commit that progress update together with the task. Then stop. I will clear context and re-run this prompt for the next task.

If the spec and a task file disagree, the spec wins; tell me and fix the task file.

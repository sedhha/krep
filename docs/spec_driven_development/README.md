# Working With Coding Agents

This guide is for the *human*. [`docs/WORKFLOW.md`](../WORKFLOW.md) defines the
process — the levels, the artifacts, the gates. This file shows you how to
actually run it: which session to open, what to type in it, what to write
yourself, and when to wipe the context.

Read the walkthrough. Everything before it is orientation, everything after it
is reference.

---

## If You Read Nothing Else

Five things. The rest of this document is detail on these.

1. **You write `spec.md`. The agent writes everything else.**
2. **Whoever wrote it doesn't review it** — reviews run in a fresh session.
3. **Clear context between phases.** The agent will tell you when.
4. **Read the design before you type `accept`.** That's the point of no return.
5. **Never let it claim something passes** without showing you `make verify`.

You'll internalise the rest by doing one capability end to end. Don't try to
memorise this file.

---

## The Two Rules

1. **The artifacts are the memory.** Conversation is scratch. A decision that
   exists only in chat is already lost.
2. **Chat carries decisions. Files carry documents.** Never make the agent
   re-paste something that already lives in a file.

## The Shape Of It

One capability = about seven sessions. Each session does one thing, then you
clear it.

| # | Session | You | Agent | Gate |
| - | ------- | --- | ----- | ---- |
| 1 | idea | talk it through | pushes back, scaffolds the folder | |
| 2 | spec | **write `spec.md` yourself** | — | |
| 3 | design | answer its questions | writes `design.md` | |
| 4 | review | — | fresh agent finds holes → `notes.md` | |
| 5 | resolve | decide each finding | applies your decisions | **you `accept`** |
| 6 | plan | read `plan.md` | writes `plan.md` | |
| 7 | slice N | read the diff | test → code → `make verify` | **you ship** |
| 8 | final | read the diff | fresh agent reviews vs acceptance criteria | |

Session 7 repeats per slice — or use `implement` to build them all in one go.

The agent will tell you when a phase is done and give you the resume line. You
clear, paste it, continue.

---

## Picking The Level

Everything above assumes Level 2. Most work isn't. The levels themselves are
defined in [`docs/WORKFLOW.md`](../WORKFLOW.md) — this is how to *decide*.

Ask these in order and stop at the first "yes":

| Ask | If yes |
| --- | ------ |
| Does it change the layer graph, the auth model, or where data lives? | **Level 3** |
| Does it create something other code will depend on — a new package, endpoint contract, schema, or external dependency? | **Level 2** |
| Is there no existing flow in this repo doing this kind of thing already? | **Level 2** |
| Is it a bounded change to a flow that already exists here? | **Level 1** |
| Can the whole diff be stated in one sentence, with nothing else affected? | **Level 0** |

Worked examples in this repo:

| Task | Level | Why |
| ---- | ----- | --- |
| Fix a typo in `README.md` | **0** | One sentence, nothing depends on it |
| Bump the `ruff` pin in `pyproject.toml` | **0** | Config value, verify catches breakage |
| Rename a local variable in one function | **0** | No caller sees it |
| Add a field to an existing response model | **1** | The flow exists; bounded edit |
| Add `GET /agents/{id}` next to existing agent routes | **1** | Endpoint pattern already established here |
| Backfill tests for existing behaviour | **1** | Nothing new is contracted |
| The FastAPI surface itself (`001-api-foundation`) | **2** | No HTTP flow existed; every capability will depend on its shape |
| A new `tools` gateway package | **2** | New module, new contract |
| First use of a background worker | **2** | New execution path others will copy |
| Add API-key auth to every endpoint | **3** | Auth model |
| Introduce Postgres + migrations | **3** | Data boundary |
| Let `integrations` import `telemetry` | **3** | Widens the layer graph; needs an ADR |

Three traps:

- **"It's just one endpoint."** If no endpoint like it exists yet, the *first*
  one sets the pattern the next ten copy. Level 2.
- **"It's only config."** Config that changes behaviour others depend on
  (a timeout contract, a feature flag with two live paths) isn't Level 0.
- **Discovering complexity mid-task.** The ratchet is one-way: escalate and
  scaffold properly. Nothing de-escalates because you already started coding.

If you're between two levels, take the higher one. Overshooting costs a
document; undershooting costs a rebuild.

You never have to guess alone — type `lvl?` and the agent classifies it and
stops. Override it if you disagree; you own that call.

---

## Starting A New Spec

Do this, in order:

1. Open a fresh session. Describe the idea in a sentence, end with `lvl?`.
2. If it comes back Level 0 or 1, stop — you don't need any of this. Just
   describe the change and let it work.
3. If Level 2 or 3, argue about the idea until you can state the problem
   without describing a solution.
4. Type `spec <slug>` (kebab-case, no number — the number is assigned for you).
5. Clear context.
6. Open the new `docs/specs/NNN-<slug>/spec.md` and write it yourself.
7. Fresh session: `draft design NNN`. Continue from
   [Session 3](#session-3--design) in the walkthrough.

That's it. Steps 1–4 are usually one short session.

---

## Where Am I? (resuming an existing spec)

Type this in a fresh session:

    where? 001

The agent inspects the folder and answers in three lines: the phase, why it
concluded that, and the exact next command. Nothing else.

To check it yourself, read the artifacts in this order — the first row that
matches is your phase:

| If… | You're at | Next |
| --- | --------- | ---- |
| `spec.md` still has template comments / empty sections | **Phase 2** | Write `spec.md` yourself |
| `spec.md` filled, `design.md` still a placeholder | **Phase 3** | `draft design NNN` |
| `design.md` written, `notes.md` still a placeholder | **Phase 4** | `review NNN` |
| `notes.md` has findings with an empty Resolution column | **Phase 5** | `resolve N <decision>` for each |
| All findings resolved, `design.md` Status is `Draft` | **Phase 5 gate** | Read the design, then `accept` |
| `design.md` Status is `Accepted`, `plan.md` a placeholder | **Phase 6** | `plan NNN` |
| `plan.md` written, slices remaining | **Phase 7** | `slice N` (or `implement NNN`) |
| All slices landed and verified | **Phase 8** | Fresh-context review vs acceptance criteria |

The two fields that decide almost everything:

    sed -n '1,12p' docs/specs/001-api-foundation/design.md   # Status: Draft or Accepted?
    grep -c '| $' docs/specs/001-api-foundation/notes.md      # unresolved findings?

If the artifacts don't tell you where you are, that's a bug in the artifacts —
the whole point is that they survive a cleared context. Fix them before
continuing.

---

## Walkthrough

A real one — this is how `001-api-foundation` actually ran.

### Session 1 — Talk about the idea

**Open a fresh session. Don't let it write anything yet.**

You type:

    I want a FastAPI HTTP surface for this repo. Health endpoint, auto swagger docs.
    lvl?


The agent classifies it (this came back Level 2 — new module, new contract) and
stops. If you disagree with the level, override it: *"treat as level 3, it
touches the layer graph."* When in doubt take the higher one.

Now argue about the idea, not the code. Good things to say here:

    why not flask?
    what breaks if we skip the error envelope for now?
    what would you build that I haven't asked for?


You're done when you can state the problem and what "working" means without
describing a solution. Then:

    spec api-foundation


The agent runs `make spec name=api-foundation level=2` and reports the folder it
created. **Nothing else.** Don't let it start filling in spec.md.

> **Clear context.**

---

### Session 2 — Write spec.md yourself

**No agent session needed at all.** Open
`docs/specs/001-api-foundation/spec.md` in your editor and write it.

This is the one artifact you own outright. The agent will faithfully build
whatever you write here, including the wrong thing.

Fill in:

| Section | What good looks like |
| ------- | -------------------- |
| Problem | Why this is worth building *now*. Not "we need an API" — "every capability is reached through an API, so until one exists the first three will each invent their own." |
| Goals | Outcomes, not implementations. "A settled shape for error responses" — not "an ErrorResponse pydantic model." |
| Non-Goals | The things a reasonable agent would otherwise build. Auth, persistence, streaming. Be specific; this is your main defence against scope creep. |
| Acceptance Criteria | Numbered, observable, testable. |
| Open Questions | Real decisions you haven't made. The agent will interview you on exactly these. |

**Acceptance criteria are the whole game.** Compare:

    ✗  Errors are handled gracefully.
    ✓  An unhandled exception returns the documented error model and leaks
       no traceback or internal detail.  [Integration test]

    ✗  The API is documented.
    ✓  Interactive documentation is served and reflects every registered route
       without a manual step.  [Integration test]


If you can't say how it's verified, it isn't a criterion — it's a wish.

**Leave design decisions blank.** If you catch yourself writing "use a
dependency-injected settings object," delete it. That's session 3's job.

---

### Session 3 — Design

**Fresh session.** You type:

    draft design 001


The agent reads spec.md and interviews you — one multiple-choice question per
open question. Answer with decisions, not preferences:

    ✗  explicit registration feels cleaner
    ✓  explicit


If a question reveals that spec.md got something wrong, **fix spec.md right
now**. It's still cheap. Changing it after session 5 costs implementation work.

The agent writes `design.md` and stops. Skim it — you're checking that it
answers *how*, and that it didn't quietly invent scope. Don't deep-review it;
that's the next session's job, done by someone who didn't write it.

> **Clear context.**

---

### Session 4 — Adversarial review

**Fresh session — this matters.** A context that argued for a design will
defend it. Even better: run this one in Codex instead of Claude, so the failure
modes differ.

You type:

    review 001


The agent reads spec+design cold and writes findings to `notes.md` — severity,
what's wrong, blank resolution column. It writes no code and edits neither
spec.md nor design.md.

Expect real findings. On this capability the review caught: a blocker (an
acceptance criterion that nothing in the design could actually test), a
contradiction between spec.md and design.md, and a missing error path (404).

> **Clear context.**

---

### Session 5 — Resolve, then accept

**Fresh session.** Open `notes.md` alongside it.

For each finding, you have three moves:

**a) Decide in chat** — one line, agent applies it everywhere:

    resolve 4 use the same ErrorResponse envelope for 404 and 405
    resolve 8 pull version from pyproject.toml, not an env var


**b) Edit it yourself** — for wording changes, faster than dictating:

> *edit `design.md` in your IDE, then:*

    reread design.md


**c) Defer it, with a reason** — legitimate, but it must be recorded:

    resolve 1 defer — no request-body endpoint exists in this spec yet


**Never resolve by argument.** "That's fine because…" is not a resolution. Either
a document changes, or the deferral is written down.

If you don't understand a finding — say so plainly. *"#5 makes no sense to me,
explain in plain words."* A finding you don't understand is a finding you can't
resolve.

When all findings are resolved, **read the design diff**, then:

    accept


The agent sets `design.md` Status to `Accepted`. **This is the commitment gate.**
After it, changing your mind costs implementation work, not just words. Don't
type it on a design you haven't read.

> **Clear context.**

---

### Session 6 — Plan

**Fresh session.**

    plan 001


The agent turns spec+design into `plan.md`: ordered slices, each with its own
verify command, each standing alone as a commit.

Read it and check one thing: **can slice 1 land and be verified without slice
2?** If slices depend on each other to be testable, they're not slices — send it
back:

    slice 2 can't be verified without slice 3. re-cut them.


> **Clear context.**

---

### Session 7 — Implement, one slice per session

**Fresh session per slice.**

    slice 1


The agent writes the failing test first, shows you it fails, then implements,
then runs `make verify`. If it claims something passes without showing you the
output, that's a process violation — call it:

    show me the verify output


Then read the diff yourself. Then commit (the agent will ask; it never commits
unprompted).

> **Clear context. Repeat for slice 2, 3, …**

---

### Session 8 — Final review

**Fresh session.**

    review the diff against spec.md acceptance criteria


The critical word is *against spec.md*. Not "review the code" — a reviewer
asked to review code will grade the implementation's internal logic and miss
that criterion 6 was never implemented.

Then you read the diff and ship.

---

## Shorthand

| You type | Agent does |
| -------- | ---------- |
| `lvl?` | Classify 0–3, say why, stop. No work. |
| `spec <slug>` | Scaffold the folder, report what it made. Nothing else. |
| `draft design` | Interview on open questions → `design.md`. **No code.** |
| `review` | Fresh-context adversarial review → `notes.md`. **No code.** |
| `resolve N <decision>` | Apply it to spec/design, mark resolved in `notes.md`. |
| `accept` | Set `design.md` Status to `Accepted`. Only you can authorize this. |
| `plan` | spec+design → `plan.md`, one verify command per slice. **No code.** |
| `slice N` | Implement slice N test-first, then `make verify`. |
| `implement` | Pre-flight the artifacts; if nothing is missing, build **all** slices end-to-end, no questions. See below. |
| `verify` | Run `make verify`, report pass/fail and failures only. |
| `reread <path>` | You hand-edited that file — re-read before continuing. |
| `park <note>` | Append to the Decision Log in `notes.md`. |
| `where? NNN` | Inspect a spec folder, report the phase and the next command. Three lines. |
| `why?` | Explain the reasoning behind the last thing, briefly. |

### `implement` — the no-questions build

`slice N` is the careful path: one slice, you read the diff, you clear, repeat.
`implement` is the fast path — use it when the design is settled and you'd
rather review once at the end than seven times along the way.

    implement 001


The agent runs a **pre-flight** first and reports a single verdict:

| Check | Must be |
| ----- | ------- |
| `spec.md` Acceptance Criteria | Present, numbered, each with a "Verified by" |
| `design.md` Status | `Accepted` |
| `notes.md` findings | No unresolved blockers or majors |
| `plan.md` | Exists, slices ordered, each with a verify command |
| Open Questions in `spec.md` | None left unanswered |
| Ambiguity in the design | None that would force a judgment call mid-build |

**If anything is missing it stops and tells you exactly what** — it does not
guess, and it does not build half of it:

    Blocked: design.md Status is `Draft`, and notes.md finding 2 (major) is
    unresolved. Resolve those, then `implement 001`.


**If the pre-flight is clean it builds everything without asking you anything** —
test-first per slice, `make verify` after each, working straight through to the
last slice. No check-ins, no "shall I continue?", no multiple-choice questions.
The point of the gates you already passed is that they bought this.

It reports at the end: slices landed, `make verify` output, and each acceptance
criterion mapped to the test that proves it. Then you review the whole diff once.

**When not to use it:** if you're unsure about the design, or the plan has more
than a handful of slices, take them one at a time with `slice N`. `implement`
converts design confidence into speed — it doesn't create the confidence.

---

## Clearing Context

**Clear at every phase boundary** — the `> Clear context.` markers above. That's
roughly seven clears per capability.

The agent is told to call these for you. It will end a phase with:

    Phase done: design accepted. Clear context and resume with:
    review the diff for 001-api-foundation against spec.md acceptance criteria


Clear, paste that line, keep going.

**Why bother:** a context that has been debugging for an hour reviews *worse*,
not better — it's invested in what it built. And every message in a long context
is re-sent with every subsequent message, so a stale session costs tokens
forever.

### Before you clear, one check

*Is anything true only in this conversation?*

If you rejected an approach, hit a gotcha, or made a call that isn't written in
spec/design/notes — it dies on clear. Say:

    park we rejected router auto-discovery because import-time side effects
         make failures silent


It goes to the Decision Log in `notes.md` and survives.

### Resuming costs one line

Because the artifacts carry the state:

    Resume 001-api-foundation, slice 3. Read spec.md, design.md, plan.md, notes.md.


**Never paste conversation history into a new session.** If the artifacts aren't
enough to resume from, the artifacts are what needs fixing — not the prompt.

---

## Token Efficiency

Almost all waste is the same document existing twice — once in a file, once in
chat.

| Wasteful | Instead |
| -------- | ------- |
| Agent pastes the whole findings table into chat | "10 findings in `notes.md`, 1 blocker" — you open the file |
| You retype a paragraph you want changed | Edit it in the IDE → `reread design.md` |
| "What do you think we should do about X?" | Ask for options; pick one |
| Re-explaining background each session | It belongs in an artifact — point at the artifact |
| Long correction essays | `resolve 4 <one line>` |
| Asking it to re-read a file it just wrote | It knows what it wrote |
| One session spanning three phases | Clear between them |

If you're writing a long instruction in chat, it probably belongs in `spec.md`,
`CLAUDE.md`, or this file instead.

---

## Anti-Patterns

- **"This one's obvious, skip the spec."** Obvious tasks produce the fastest
  wrong implementations. `lvl?` costs one line.
- **Same context writes and reviews.** Structurally incapable of being
  adversarial about its own work.
- **Resolving a finding by explaining why it's fine.** Change a doc or record
  the deferral.
- **Accepting a design you didn't read.** The gate exists because agents are
  confidently wrong at a completely normal-sounding register.
- **Deciding architecture mid-slice.** Stop, `park` it, take it back to design.
- **Letting a session span phases.** Context bleeds and the review gets polite.
- **Accepting "it works" without output.** Ask for the `make verify` output.

---

## When Not To Do Any Of This

The walkthrough is the Level 2/3 path. Level 0 and Level 1 work skips all of it
— see [Picking The Level](#picking-the-level). Ceremony that outweighs the task
is its own failure mode.

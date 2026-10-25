For V1 details refer [V1 Platform](v1-platform.md) documentation.

## How we discuss and plan

Design discussion happens turn by turn inside the design docs, not in chat.

- Claude writes its feedback under a `## Claude Feedback` heading at the end of the doc under discussion, with numbered items (W = works, F = finding, D = decision) so they can be referenced.
- The user replies with inline comments in the doc (next to the item, with examples where useful) and says `reread <path>`.
- On each round Claude reads the doc, addresses the inline comments, and updates the `## Claude Feedback` section in place instead of re-pasting it in chat.
- Chat replies stay short: say what changed and where. Ask judgment calls as multiple-choice options with a recommendation.
- Do not overwrite or restructure the user's own sections unless asked; Claude edits only its feedback section.

For the registry implementation spec refer [Registry V1 Spec](docs/specs/v1.md).

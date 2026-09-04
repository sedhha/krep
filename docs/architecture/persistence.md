# Persistence

Persistence must preserve immutable published agent and tool versions while
allowing separately referenced connections to rotate.

Durable runtime state must not contain credential material. Checkpoint,
transaction, concurrency, and migration choices remain open and must be decided
in an approved feature design or ADR before implementation.

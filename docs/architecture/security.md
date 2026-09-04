# Security

Authorization is deterministic and external to model reasoning. Tool
credentials are resolved and injected at the Tool Gateway.

Secrets must never enter model prompts, LangGraph messages, checkpoints, logs,
telemetry, evaluation datasets, or caller-facing exception messages. Raw
authorization headers must not be logged.

Security invariants should become executable architecture and redaction tests
as their implementation lands.

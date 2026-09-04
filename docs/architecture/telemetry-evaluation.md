# Telemetry and Evaluation

Run telemetry captures status, duration, model usage, estimated cost, tool
calls, tool latency, errors, and human-review events without exposing secrets.
V1 should keep the operational model intentionally small.

Offline evaluation runs datasets against immutable agent versions and records
deterministic, model-judged, or human scores. Evaluation implementation follows
the walking skeleton and is not part of the foundation slice.

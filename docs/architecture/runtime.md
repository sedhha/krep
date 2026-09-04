# Runtime

Krep exposes a runtime abstraction with LangGraph as the V1 implementation.
The complete V1 runtime supports synchronous, asynchronous, durable, resumable,
cancellable, retriable, human-in-the-loop, and streaming execution.

The first vertical slice implements synchronous execution only. Later runtime
capabilities must preserve the durable dependency invariant defined in the
product specification.

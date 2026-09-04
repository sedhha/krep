# Authorization

Krep uses CEL to evaluate authorization independently of LLM reasoning.
Policies receive explicit context for the principal, tenant, agent, tool, and
request.

V1 policies may control agent invocation, tool access, and human-review
requirements. Authorization decisions should emit auditable events without
capturing credentials or sensitive request headers.

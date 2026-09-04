# Tool Gateway

All outbound tool execution passes through the Tool Gateway.

The gateway authorizes the call, resolves the selected connection, injects
credentials outside agent state, invokes the customer API, and records safe
telemetry. Secrets must not enter prompts, messages, checkpoints, logs,
telemetry, evaluation data, or caller-facing errors.

HTTP is the only executable V1 tool type. OpenAPI is an import path that creates
HTTP tool definitions rather than a separate runtime.

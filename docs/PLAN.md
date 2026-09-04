# Agent Platform — V1

## Goal

Build a **native LangGraph-based agent platform** where enterprises can:

- Create agents
- Register tools
- Configure authentication
- Define permissions
- Run agents synchronously or asynchronously
- Support durable/background execution
- Support human-in-the-loop
- Observe runs
- Evaluate agent versions

V1 does **not** support arbitrary external agent imports.

---

## 1. Agent

Each agent contains:

- Name / description
- Model + model config
- System prompt
- Tools
- Skills / resources
- Input schema
- Output schema
- HITL rules
- Runtime configuration

Underlying runtime: **LangGraph**

Agents are versioned.

Published versions are immutable.

---

## 2. Runtime

Support:

- Sync execution
- Async execution
- Durable/background execution
- Human-in-the-loop
- Checkpoint / resume
- Cancellation
- Basic retries
- SSE streaming

### Durable Execution Rule

A durable agent may depend only on **durable or renewable dependencies**.

If any required connection uses a non-renewable/ephemeral credential:

```text
durable_background = false
```

---

## 3. Invocation

### V1: Backend → Agent only

Customer backend invokes:

```http
POST /v1/agents/{agent_id}/runs
```

Authentication:

- API key
- OAuth2 Client Credentials

Request may contain:

```json
{
  "input": {},
  "principal": {
    "id": "user-123",
    "roles": ["support"]
  }
}
```

The authenticated customer backend is trusted to provide the `principal`.

Direct browser/mobile invocation comes later.

---

## 4. Authorization

Use **CEL**.

Runtime context:

```text
principal
tenant
agent
tool
request
```

Examples:

```cel
principal.roles.exists(r, r == "admin")
```

```cel
principal.tenant_id == tenant.id
```

```cel
tool.name == "refund" &&
request.arguments.amount > 500
```

CEL can control:

- Agent invocation
- Tool access
- HITL requirements

---

## 5. Tools

Runtime tool type:

```text
HTTP Tool
```

Supported responses:

- JSON
- SSE

Tool definition includes:

- Method
- URL
- Headers
- Input schema
- Output schema
- Response type
- Connection

### OpenAPI

OpenAPI is an **import mechanism**, not a separate runtime.

```text
OpenAPI → HTTP Tool definitions
```

Support selecting operations during import.

---

## 6. Connections

Authentication is separate from tool definitions.

```text
Tool → Connection
```

V1 connection types:

### No Auth

No credentials.

### API Key

Customer provides:

- Key
- Header name

Store key encrypted.

Example:

```http
X-API-Key: <secret>
```

### Static Bearer

Customer provides token.

Store encrypted.

```http
Authorization: Bearer <token>
```

### OAuth2 Client Credentials

Customer provides:

- Token URL
- Client ID
- Client secret
- Scopes

Runtime:

```text
Get access token
→ cache
→ use
→ regenerate before/after expiry
```

Suitable for durable/background execution.

### Per-Invocation Credentials

**Not V1.**

Add later for delegated user authentication.

---

## 7. Credential Lifecycle

Internally classify connections:

```text
NONE
STATIC
RENEWABLE
EPHEMERAL
```

Background compatibility:

```text
NONE        ✅
STATIC      ✅ if non-expiring
RENEWABLE   ✅
EPHEMERAL   ❌
```

Validate compatibility:

1. When configuring/publishing agent
2. Again when starting background execution

---

## 8. Tool Gateway

All tool calls go through the Tool Gateway.

```text
Agent
  ↓
CEL authorization
  ↓
Tool Gateway
  ↓
Resolve connection
  ↓
Inject credential
  ↓
Customer API
```

Secrets must never enter:

- LLM context
- LangGraph messages
- Logs
- Telemetry
- Evaluation datasets

---

## 9. SSE

Support SSE for:

### Tool responses

```text
HTTP → text/event-stream
```

Allow configuration of:

- Completion event
- Error event
- Progress events

### Agent output

Expose run events such as:

```text
run.started
message.delta
tool.started
tool.completed
hitl.required
run.completed
run.failed
```

---

## 10. HITL

LangGraph interrupt/checkpoint underneath.

Typical lifecycle:

```text
RUNNING
   ↓
WAITING_FOR_HUMAN
   ↓
APPROVED / REJECTED
   ↓
RESUMED
   ↓
COMPLETED
```

CEL may determine when approval is required.

---

## 11. Telemetry

Capture:

- Input / output
- Run status
- Duration
- Model calls
- Token usage
- Estimated cost
- Tool calls
- Tool latency
- Errors
- HITL events

Keep V1 telemetry simple.

---

## 12. Evaluation

Basic offline evaluation pipeline:

```text
Dataset
   ↓
Agent Version
   ↓
Runs
   ↓
Evaluators
   ↓
Scores
```

Initially support:

- Deterministic checks
- LLM-as-judge
- Human score

---

## 13. Versioning

Version:

- Agents
- Tools

Published versions are immutable.

Connections are referenced separately so credential rotation does not create a new tool version.

```text
Agent Version
   ↓
Tool Version
   ↓
Connection
```

---

## 14. Skills / Resources

Keep minimal.

Skill:

```text
Instructions
+
Resources
```

Resources initially:

- Text
- File upload
- URL

Do **not** build full ingestion/RAG infrastructure in V1.

Existing enterprise RAG can be exposed as another HTTP tool.

---

## Explicitly Not V1

- Arbitrary agent imports
- Custom containers
- Multi-framework support
- Direct browser authentication
- Delegated OAuth / refresh tokens
- Token exchange
- BYOC
- Multi-cloud runtime
- Full RAG platform
- Visual LangGraph editor
- MCP
- Custom executable tools
- Complex policy engine beyond CEL
- Per-user downstream credentials

---

# V1 Mental Model

```text
Customer Backend
       ↓
Agent Gateway
       ↓
Principal + CEL
       ↓
LangGraph Runtime
       ↓
Tool Gateway
       ↓
Connections
       ↓
Customer APIs
```

With:

```text
Runtime
├── Sync
├── Async
├── Durable Background
├── HITL
├── SSE
├── Telemetry
└── Evaluation
```

## Core Principle

> **Keep the agent simple. Make the runtime, tool integration, security and operations excellent.**

And:

> **A durable agent may depend only on durable or renewable dependencies.**

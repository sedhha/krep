# Connections

Connections contain authentication configuration and remain separate from tool
definitions. This allows credential rotation without creating new tool
versions.

V1 connection types are no authentication, API key, static bearer token, and
OAuth 2.0 client credentials. Per-invocation credentials are outside V1.

The connection model classifies dependencies as `NONE`, `STATIC`, `RENEWABLE`,
or `EPHEMERAL` for durable-execution compatibility.

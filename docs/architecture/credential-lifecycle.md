# Credential Lifecycle

Credential material is encrypted at rest, resolved only at the Tool Gateway,
and injected only into outbound requests. It must never become part of agent or
runtime state.

OAuth 2.0 client-credentials access tokens are renewable and may be cached and
regenerated around expiry. Static credentials are durable only when they are
non-expiring. Ephemeral credentials cannot support durable or background runs.

Compatibility is validated both during agent publication or configuration and
when a durable run starts.

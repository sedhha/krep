# Agent Model

Agents define model configuration, instructions, tools, resources, input and
output schemas, human-review rules, and runtime configuration.

Agents are versioned. Published versions are immutable and reference immutable
tool versions. Mutable operational configuration, including connections, is not
embedded into published versions.

The detailed persistence schema and publish lifecycle must be resolved in a
feature design before implementation.

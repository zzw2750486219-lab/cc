---
name: agent-sandbox
description: Sandbox abstraction — SandboxProvider ABC, Docker provider, bootstrap, sandbox Dockerfile.
---

# Agent Sandbox

Implement sandbox isolation and agent bootstrap.

- `sandbox/` — SandboxProvider ABC, DockerProvider, bootstrap.py, Dockerfile.sandbox

## Package layout

```
sandbox/
├── __init__.py
├── bootstrap.py
├── providers/
│   ├── __init__.py
│   ├── base.py
│   └── docker_provider.py
└── Dockerfile.sandbox
```

## SandboxProvider ABC

create(config) → handle, execute(handle, cmd, env, timeout) → result, write_file(handle, path, content), read_file(handle, path) → str, stream_events(handle) → async iter, destroy(handle)

## bootstrap.py

1. Read /home/user/agent_config.json → AgentConfig
2. Init AnthropicLLMClient, ToolRegistry, HookRegistry, CompactionPipeline
3. Register core tools
4. AgentLoop.run(), print JSON result to stdout
5. Exit 0/1

## Dockerfile.sandbox

FROM python:3.12-slim, pip install anthropic, COPY agent_core/ tools/ shared/ bootstrap.py, PYTHONPATH=/opt/agent/platform, WORKDIR /workspace

## Global rules

Follow all rules in `CLAUDE.md` at the repo root — imports, signatures, error handling, boundaries. This SKILL defines your specific scope on top of those rules.

## Do NOT touch

api/, orchestrator/, agent_core/, tools/, root Dockerfile, pyproject.toml

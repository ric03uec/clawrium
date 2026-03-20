@AGENTS.md

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Clawrium**

Clawrium is a CLI/TUI tool for managing AI assistant fleets on local networks. It provides a centralized command center for installing, configuring, and maintaining multiple "claws" (AI assistants like OpenClaw, ZeroClaw, NemoClaw) across hosts, solving the chaos of configuration drift, scattered secrets, and inconsistent management.

**Core Value:** Users can manage all their AI assistants from one place with consistent configuration and security practices, regardless of which claw types they run.

### Constraints

- **Tech stack**: Python + Typer CLI, ansible-runner for execution, uv/uvx for packaging
- **Security**: No sudo permissions — Clawrium prompts user when privileged commands needed
- **Platform**: Ubuntu only for v1
- **Claw support**: OpenClaw only for v1
- **Deployment**: Fully local, no cloud dependencies
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->

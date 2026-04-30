# ITX Configuration Guide

ITX skills work with **zero configuration** by default. All configuration is optional and allows you to customize behavior for your specific project.

## Configuration File

Create `.claude/itx-config.json` (copy from `.claude/itx-config.json.example`) to override defaults.

## Configuration Options

### Build Commands

Customize test, lint, and coverage commands:

```json
{
  "build": {
    "test_command": "npm test",
    "lint_command": "npm run lint",
    "coverage_command": "npm run test:coverage"
  }
}
```

**Default behavior**: Uses `make test`, `make lint`, `make test-cov`

**Used by**: `/itx:verify`, `/itx:execute`

### GitHub Project Board

Enable GitHub Projects V2 integration for automatic issue status updates:

```json
{
  "github": {
    "project_board": {
      "enabled": true,
      "project_id": "PVT_kwHOABDzzM4BSDdU",
      "status_field_id": "PVTSSF_lAHOABDzzM4BSDdUzg-abc",
      "status_options": {
        "backlog": "47fc9ee4",
        "ready": "f75ad846",
        "executing": "98d27e76",
        "in_review": "1a2b3c4d",
        "done": "5e6f7g8h"
      }
    }
  }
}
```

**How to find IDs**:
1. Project ID: From project URL or GraphQL API
2. Status Field ID: From GraphQL API `projectV2 { field(name: "Status") { ... } }`
3. Status Option IDs: From GraphQL API field options

**Default behavior**: Skips all project board operations

**Used by**: `/itx:execute`

### MCP Integration

Enable Model Context Protocol for automated code review:

```json
{
  "mcp": {
    "review_enabled": true,
    "review_tool": "mcp__atx__request_review"
  }
}
```

**Default behavior**: Falls back to manual review checklist

**Used by**: `/itx:review-pr`

### Project Settings

Customize project name and version label:

```json
{
  "project": {
    "name": "My Project",
    "version_label": "Release"
  }
}
```

**Default behavior**:
- Uses repository name from git remote
- Uses "Version" as default label

**Used by**: `/itx:bug-new`, `/itx:issue-new`

## Default Behavior Summary

Without any configuration file, ITX:
- Auto-detects repository from `git remote`
- Uses `make test/lint` for build commands
- Skips GitHub project board operations
- Uses manual review mode
- Uses repository name as project name

## Example Configurations

### Minimal (JavaScript/Node Project)

```json
{
  "build": {
    "test_command": "npm test",
    "lint_command": "npm run lint"
  }
}
```

### Full Integration

```json
{
  "build": {
    "test_command": "cargo test",
    "lint_command": "cargo clippy"
  },
  "github": {
    "project_board": {
      "enabled": true,
      "project_id": "PVT_...",
      "status_field_id": "PVTSSF_...",
      "status_options": {
        "backlog": "...",
        "ready": "...",
        "executing": "...",
        "in_review": "...",
        "done": "..."
      }
    }
  },
  "mcp": {
    "review_enabled": true,
    "review_tool": "mcp__atx__request_review"
  },
  "project": {
    "name": "MyApp",
    "version_label": "Version"
  }
}
```

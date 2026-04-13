---
sidebar_position: 1
description: Configure communication channels for your agents during onboarding.
keywords: [channels, communication, onboarding, cli, discord]
---

# Channels

The Channels stage configures how your agent communicates with users.

## Available Channels

Available channels vary by agent type.

| Channel | Description | Best For |
|---------|-------------|----------|
| CLI | Command line interface | Development, scripting |
| Discord | Community engagement | Communities, gaming, team collaboration |

## Example - CLI channel (default)

```bash
Select default communication channel:
  1. cli (recommended)
  2. discord

Select [1-2]: 1
✓ Default channel: cli
```

## Channel-Specific Setup

- [Discord Channel Setup](./discord.md)

:::info
For ZeroClaw, only CLI is supported and auto-configured.
:::

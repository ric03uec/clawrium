# CLI

**Status:** ✅ Supported (All Agents)

The CLI channel provides terminal-based interaction with your agent.

## Features

- **Interactive chat:** Real-time conversation in terminal
- **Command history:** Navigate previous messages
- **Piping support:** Pipe input/output to other commands
- **Scripting:** Automate via shell scripts
- **No dependencies:** Works over SSH, no browser needed

## Setup

CLI is automatically configured for all agents. No additional setup required.

## Usage

### Interactive Chat

```bash
# Start chatting
clm chat <agent-name>

# Example
clm chat my-assistant
```

### One-off Queries

```bash
# Single query (if supported by agent)
echo "What's the weather?" | clm chat my-assistant --stdin
```

### Scripting

```bash
#!/bin/bash
# automated-task.sh

RESPONSE=$(echo "Analyze this log file" | clm chat log-analyzer --stdin)
echo "$RESPONSE"
```

## Key Bindings

During chat:

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate history |
| `Ctrl+C` | Exit chat |
| `Ctrl+L` | Clear screen |
| `Tab` | Auto-complete (if supported) |

## Configuration

CLI channel has minimal configuration:

```json
{
  "cli": {
    "enabled": true,
    "history_size": 100
  }
}
```

## Limitations

- Single user only
- No rich media (images render as links)
- Requires terminal/SSH access
- No persistent history across sessions

## Best Practices

1. **SSH key-based access:** For remote hosts, use SSH keys
2. **Screen/tmux:** Use terminal multiplexers for long sessions
3. **Logging:** Pipe output to files for record keeping
4. **Aliases:** Create shell aliases for frequently used agents

```bash
# Add to ~/.bashrc or ~/.zshrc
alias ask='clm chat my-assistant'
```

## Troubleshooting

**"Connection refused"**
- Ensure agent is running: `clm ps`
- Start agent if needed: `clm agent start <name>`

**"Agent not responding"**
- Check agent logs: `clm agent logs <name>`
- Verify provider connectivity: `clm provider status <provider>`

**"Slow responses"**
- Normal for complex queries
- Check network latency to host
- Consider local Ollama provider for faster responses

---

[Back to Channels](index.md)

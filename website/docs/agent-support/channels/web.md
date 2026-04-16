# Web Interface

**Status:** 🚧 In Development

A browser-based chat interface for interacting with agents.

---

## Planned Features

- **Web UI:** Clean, responsive chat interface
- **Authentication:** Login required for access
- **Multiple agents:** Switch between agents in UI
- **History:** Persistent conversation history
- **Mobile support:** Responsive design for mobile browsers
- **File uploads:** Share files with agents
- **Rich content:** Code highlighting, markdown rendering

## Timeline

**Target:** Q2 2026

**Milestone:** [SEA (Secondary Engagement & Automation)](https://github.com/ric03uec/clawrium/milestones)

Track progress: [GitHub Issue #TBD](https://github.com/ric03uec/clawrium/issues)

---

## Architecture

The web channel will consist of:

1. **Backend API:** WebSocket or Server-Sent Events for real-time chat
2. **Frontend:** React/Vue-based chat interface
3. **Authentication:** Token-based or OAuth
4. **Proxy:** Nginx or similar for serving static files

## Comparison with Other Channels

| Feature | CLI | Discord | Web |
|---------|-----|---------|-----|
| **Setup** | None | Medium | High |
| **Access** | SSH/Terminal | Discord account | Browser |
| **Mobile** | SSH app | Discord app | Browser |
| **Multi-user** | No | Yes | Yes (planned) |
| **History** | Session only | Discord | Persistent |
| **Files** | Limited | Yes | Yes (planned) |

---

## Preliminary Usage (Subject to Change)

### Configuration

```bash
clm agent configure my-agent
# Select Web Interface when available
```

### Access

```bash
# Get web interface URL
clm agent web-url my-agent
# Opens: https://agent-host:8443/chat/my-agent
```

### Authentication

Access will require:
- Pre-shared token, or
- User account (if multi-user enabled)

---

## Vote for Priority

Add a 👍 reaction to [the web channel issue](https://github.com/ric03uec/clawrium/issues) to help prioritize.

---

[Back to Channels](index.md)

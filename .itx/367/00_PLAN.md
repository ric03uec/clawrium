# Issue #367 — User can run clawrium as a server with CLI and web UI as thin clients over an HTTP API

Plan TBD. Created during issue intake. Run `/itx:plan-create 367` to scope. This is a large architectural refactor — expect the plan to be phased.

**Affects:** every other open issue that touches state — #349 (web UI for fleet status) and #364 (skills registry) should be re-evaluated against this once a server design lands. #365 (Gas City on Hermes) is agent-side and unaffected.

---

<details>
<summary>Prompt Log</summary>

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-05-15T00:00:00Z
**Model**: claude-opus-4-7

```prompt
Create a feature request. This is a big issue. I want chlorium should be broken down into a CLI. And a server. At this point, Clarium CLI just gets invoked on user action, and it does its job and gets completed. I want to break it down into two pieces. The the server, which will provide the APIs APIs will be used by CLI and the web UI. The server will contain the core logic of agent management, agent storage, secrets management, integrations, metrics collection, and everything else. So the server will become the the central point of Clorium implementation, whereas the clients will be either CLI or the web UI. Server will also be based on a database It will use SQLite. It will still be on it will be on Python, so fast API. Is preferred. I want to investigate whether actually, let let it be fast API is the server I want to use. Server will maintain the transport layer between the server and the agents. The server okay. The make the control mechanism doesn't change. It's still based, where servers will connect to each Ansible host and get the information and do the management. That the transport doesn't change. Only the management ability will be more will will be decoupled from a single CLI to a server plus clients. Rest of the design will come in later, but just add a ticket with this high level requirement.
```

STT disambiguation: "chlorium" / "Clarium" / "Clorium" → clawrium. "fast API" → FastAPI.
Customer outcome: "Run clawrium as server + thin clients — User can run a long-running clawrium server (state, secrets, integrations, metrics in SQLite) and interact with it through either the CLI or a web UI, both as thin clients over an HTTP API."

</details>

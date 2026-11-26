# Clawrium GUI — Interface Map & UX Assessment

> **Date**: 2026-05-27
> **Version**: 26.5.4
> **ICP**: Slightly-to-highly technical users who prefer a GUI over CLI for managing their AI agent fleets.
> **Core Value Prop**: Configure shared artifacts (providers, skills, integrations, channels) once, apply to any number of agents. Users interact with agents through the agent's own UI — Clawrium is the infrastructure and fleet management layer.

---

## Table of Contents

1. [Interface Map](#interface-map)
2. [Screenshots](#screenshots)
3. [UX Assessment](#ux-assessment)
4. [Improvement Recommendations](#improvement-recommendations)

---

## Interface Map

### Global Chrome (Present on All Pages)

| Element | Location | Contents |
|---------|----------|----------|
| **Sidebar** | Left, 248 px expanded | Logo · "Agent Fleet Manager" tagline · grouped primary navigation · explicitly labeled transitional links · Settings · GitHub · collapse/expand control · version |
| **Header bar** | Top, 72 px | Fleet workspace context · "Request a feature" link |
| **App footer** | Bottom | Version · intentional global links such as Documentation |

**Approved primary navigation (#1075):**

- **Main** — Dashboard · Agents · Hosts
- **Configuration** — Providers · Integrations · MCP servers
- **Transitional pages** — Topology · Skills. These routes remain reachable while later issues own their removal or folding, but they are not part of the approved primary groups.
- **Sidebar footer** — Settings · GitHub · collapse/expand · version.

Scheduled Jobs and Agent Builder are not part of this information architecture. MCP servers links to a dedicated follow-up-scope page and does not open a coming-soon modal.

---

### Page 1: Dashboard (`/`)

**Purpose**: Fleet overview and usage metrics

| Section | Type | Content |
|---------|------|---------|
| Metrics Row | 5 stat cards | Total Agents · Running (of total) · Providers · Tokens 24h · Est. Cost 24h |
| Token Usage (7 Days) | Stacked bar chart (Recharts) | Input/output tokens by model, with totals |
| Agent Status | Donut/pie chart | Breakdown by status (Running/Stopped/Unknown) |
| Fleet Agents | Data table | Columns: Status dot, linked Name, Type, Host, Model, Uptime. The real name link opens Agent Detail. |

**Interactions**: Activate the agent name link → navigate to `/agents?key=<key>`

---

### Page 2: Topology (`/topology`)

**Purpose**: Network diagram of hosts and agents

| Section | Type | Content |
|---------|------|---------|
| Canvas | React Flow (@xyflow/react) | Nodes: Control Machine, Host(s), Agent(s), Provider(s). Edges: SSH connections, Agent→Provider links |
| Legend | Overlay panel | Status colors (Running/Degraded/Stopped/Provisioning/Checking), Edge type legend |
| Fleet Summary | Overlay panel | Hosts count, Agents count, Providers count, Running count |
| Controls | Overlay buttons | Zoom In, Zoom Out, Fit View |

**Node Types:**
- **Control Machine**: Your machine running clawctl
- **Host Node**: hostname, architecture, CPU brand
- **Agent Node**: status dot, name, type, model, provider
- **Provider Node**: logo, name, model, agent count

---

### Page 3: Providers (`/providers`)

**Purpose**: Manage LLM provider configurations

| Section | Type | Content |
|---------|------|---------|
| Configured Providers | Accessible data table | Columns: details, provider, type, default model, usage, created date, and keyboard-operable Edit/Remove actions |
| Add Provider | Button | "+ Add Provider" opens modal |
| Model Catalog | Filterable table | Filter dropdown (by provider) + search. Columns: Provider, Model, Context window, Tags |

**Issues Noted**: Model Catalog is an unfiltered dump of 50+ models with no curation or recommendations.

---

### Page 4: Skills (`/skills`)

**Purpose**: Browse the skills catalog

| Section | Type | Content |
|---------|------|---------|
| Subtitle instruction | Text | CLI command: `clawctl agent skill attach <registry>/<name> --agent <agent>` |
| Registry tabs | Tab bar | Clawrium (count), OpenClaw (count), Hermes (count), ZeroClaw (count) |
| Skill cards | Card grid | Each card: registry prefix, name, version, description |

**Issues Noted**: Explicitly tells users to use CLI to install skills — no "Install" button in UI.

---

### Page 5: Integrations (`/integrations`)

**Purpose**: Manage connections to external services

| Section | Type | Content |
|---------|------|---------|
| Add Integration | Button | "+ Add Integration" opens modal with type selection |
| Configured Integrations | Searchable data table | Columns: integration, type, credential status, agent usage, and keyboard-operable identity, Edit credentials, and Remove buttons |

---

### Page 6: Settings (`/settings`)

**Purpose**: Application configuration and preferences

| Section | Type | Content |
|---------|------|---------|
| About | Info card | Version, Config Dir path, Python version, Platform |
| Token Tracking | Config card | Status (Enabled/Disabled), Storage path, Export CSV button, Clear Usage Data button |
| GUI Preferences | Config card | Port, Auto-open toggle, Refresh Rate. Note: "configure via CLI flags" |
| Danger Zone | Warning card | "Reset All Configuration" button (disabled). Note: use CLI commands |

**Issues Noted**: Disabled buttons and "use CLI" notes break the UI-first promise.

---

### Page 7: Agent Detail (`/agents?key=<agent_key>`)

**Purpose**: Per-agent management and interaction

**Header**: Status badge, agent name, subtitle line (type, version, host, model), Action buttons (Open Agent UI, Restart, Stop)

**Metrics Row**: 4 stat cards — Uptime, Status, Tokens 30d, Est. Cost

| Tab | Content |
|-----|---------|
| **Chat** | Chat interface with message area + text input + Send button. Streams via SSE. |
| **Configuration** | Read-only display: Provider (name, type, model), Gateway (URL, port, device ID), Status (onboarding state, version) |
| **Skills** | Installed skills list + "Install skill" button (opens picker). Shows empty state when none installed. |
| **Memory** | File list (MEMORY.md, USER.md, SOUL.md) + content viewer pane |
| **Logs** | Filter text input, line count dropdown (50/100/200/500), Refresh button, log output area |

---

## Screenshots

All screenshots captured during navigation are stored at:

```
screenshots/
├── 01-dashboard.png
├── 02-topology.png
├── 03-providers.png
├── 04-skills.png
├── 05-integrations.png
├── 06-settings.png
├── 07-agent-detail-vand.png
├── 08-agent-config-tab.png
└── 09-agent-logs-tab.png
```

---

## UX Assessment

### Value Hierarchy (Corrected)

Clawrium is **infrastructure and fleet management**, not an agent interaction tool. Users interact with their agents through each agent's native UI. Clawrium's job is to make the underlying infrastructure invisible.

| Priority | What Clawrium Does | Why It Matters |
|----------|-------------------|----------------|
| **Primary** | Manage shared artifacts (Providers, Skills, Integrations, Channels) — configure once, apply to N agents | This is what users cannot do any other way. Without Clawrium, you SSH into each machine and configure each agent independently. |
| **Secondary** | Fleet visibility (Dashboard, Topology) — health, costs, status across all agents | Single pane of glass. "Are all my agents healthy? What am I spending?" |
| **Tertiary** | Agent interaction (exec commands, chat) — convenience access without leaving Clawrium | Users primarily go to the agent's own UI. This is a shortcut, not the primary workflow. |

### What "Configure Once, Apply Many" Means in Practice

The killer workflow that justifies Clawrium's existence:

1. User creates a provider config (e.g. "bedrock-prod" with AWS credentials + model selection)
2. User applies that provider to 5 agents across 3 hosts — **one action**
3. When the API key rotates, user updates it in ONE place → all 5 agents get the new key
4. Same for skills: install "tdd" once → attach to all coding agents
5. Same for integrations: configure Atlassian once → any agent can use it

**The current UI does not surface this workflow at all.** Each artifact page is pure CRUD (create/edit/delete). There's no visibility into "which agents use this?" and no bulk-apply action.

### Current State Assessment

The GUI correctly identifies the core objects (Providers, Skills, Integrations) as top-level navigation — this is structurally right. But it presents them as **isolated CRUD pages** rather than as the connective tissue between configuration and agents.

### Critical UX Gaps (Re-assessed)

| # | Gap | Impact on Core Value Prop |
|---|-----|---------------------------|
| 1 | **No "apply to agents" workflow on artifact pages** | Providers page has no way to see which agents use a provider, or to assign a provider to multiple agents. The "configure once, apply many" value is invisible. |
| 2 | **No agent exec / command runner in GUI** | `clawctl agent exec <name> -- <cmd>` is CLI-only. Users who need to run commands on agents must leave the GUI. |
| 3 | **CLI escape hatches break trust** | Skills page says "use CLI", Settings has disabled buttons. GUI-first users hit walls. |
| 4 | **No relationship visibility** | No page answers "What's attached to this agent?" or "What agents use this provider?" The graph between artifacts and agents is only visible in topology (and even there, only for providers). |
| 5 | **Dashboard shows raw metrics, not fleet health** | 5 stat cards with numbers but no intelligence. Doesn't tell you "agent X is down" or "provider Y's key expires in 3 days." |
| 6 | **Skills catalog is browse-only** | Can browse skills but cannot install them to agents from this page. Actively tells you to use CLI. |
| 7 | **No bulk operations** | Cannot start/stop/restart multiple agents. Cannot attach a skill to multiple agents at once. Every action is per-agent. |
| 8 | **Model Catalog is noise** | 50+ models in a flat list. No filtering by "models your providers support" or "models compatible with agent type X." |
| 9 | **No onboarding for artifact setup** | First-time user sees empty Providers page with no guidance on what to do or why. |
| 10 | **Topology doesn't show artifact relationships** | Shows Host→Agent→Provider edges but not Skills or Integrations. Misses half the value prop. |

---

## Improvement Recommendations

### Recommendation 1: Add "Configure Once, Apply Many" Workflows to Artifact Pages

**The fundamental problem**: The Providers, Skills, and Integrations pages are CRUD-only. They let you create/edit/delete artifacts but provide zero visibility into how those artifacts connect to agents, and no mechanism to apply them.

**Current State vs Proposed State**:

**Providers page today:**
```
┌──────────────────────────────────────────────────────┐
│  Configured Providers (4)          [+ Add Provider]  │
│                                                      │
│  ┌──────────────────┐  ┌──────────────────┐         │
│  │ esper-bedrock     │  │ doppio-bedrock    │         │
│  │ bedrock           │  │ bedrock           │         │
│  │ zai.glm-5         │  │ minimax-m2.5      │         │
│  │ Key: ✓ Set        │  │ Key: ✓ Set        │         │
│  │ [Edit] [Remove]   │  │ [Edit] [Remove]   │         │
│  └──────────────────┘  └──────────────────┘         │
│                                                      │
│  Model Catalog (giant table of 50+ models)           │
└──────────────────────────────────────────────────────┘
```

**Providers page proposed:**
```
┌──────────────────────────────────────────────────────────────┐
│  Providers (4)                    [+ Add Provider]            │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ esper-bedrock                                        │     │
│  │ AWS Bedrock · zai.glm-5 · Key: ✓ Active             │     │
│  │                                                      │     │
│  │ Used by: vand, doppio, staging-agent    (3 agents)  │     │
│  │                                                      │     │
│  │ [Edit] [Apply to Agents...] [Remove]                │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ doppio-bedrock-haiku                                 │     │
│  │ AWS Bedrock · claude-haiku-4-5 · Key: ✓ Active       │     │
│  │                                                      │     │
│  │ Used by: (none)                    [Apply to Agent]  │     │
│  └─────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

**Key additions per artifact page:**
1. **"Used by" line** — shows which agents reference this artifact. Click to see full list.
2. **"Apply to Agents..." button** — opens a multi-select of agents → attaches the artifact to all selected.
3. **"Remove from Agent" per-agent** — when viewing the expanded usage list.

**Same pattern applies to Skills and Integrations:**
- Skills card: "Installed on: vand, doppio (2 agents)" + [Attach to Agents...] button
- Integration card: "Connected to: vand (1 agent)" + [Connect to Agents...] button

**Customer Value**: This is the entire point of Clawrium made visible and actionable. Users see the leverage they're getting (one config → N agents) and can extend it in one action.

---

### Recommendation 2: Add Agent Exec / Command Runner to Agent Detail

**Problem**: `clawctl agent exec <name> -- <command>` is CLI-only today. This is one of the most powerful features — run any command against the agent's native CLI on its host machine — but GUI users can't access it.

**Proposed addition to Agent Detail page — new "Terminal" tab:**

```
┌──────────────────────────────────────────────────────────────┐
│  vand                                                        │
│  [Chat] [Configuration] [Skills] [Memory] [Logs] [Terminal]  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Run a command on this agent's host                          │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ $ ▌                                                  │     │
│  └─────────────────────────────────────────────────────┘     │
│  [Run]  Prefix: clawctl agent exec vand --                   │
│                                                              │
│  ─── Recent Commands ───                                     │
│  $ --version                     hermes v2026.5.7            │
│  $ config show                   { "model": "zai.glm-5"...  │
│  $ health                        status: ok, latency: 42ms  │
│                                                              │
│  ─── Quick Actions ───                                       │
│  [Version] [Health Check] [Show Config] [Restart Service]    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Key features:**
- Input field pre-prefixed with `clawctl agent exec <name> --` (user just types the agent-native command)
- Command history (recent commands with output)
- Quick-action buttons for common operations (version, health, config)
- Output displayed inline with scrollback
- No full terminal emulation needed — this is command-response, not interactive shell

**Implementation notes:**
- Backend: new route `POST /api/agents/{key}/exec` that calls `clawctl agent exec` subprocess
- Frontend: simple form + output display, SSE or polling for long-running commands
- Security: same as existing CLI — SSH key is the auth boundary

**Customer Value**: Completes the "never leave the GUI" promise for infrastructure operations. Combined with the existing chat tab, this covers all agent interaction use cases without opening a terminal.

---

### Recommendation 3: Eliminate All "Use the CLI" Dead Ends

**Problem**: Multiple pages tell users to fall back to the CLI. This fundamentally breaks the value proposition for users who chose the GUI specifically to avoid the CLI. Every "use `clawctl`" message is a trust violation.

**Dead ends to fix (priority order):**

| # | Location | Current State | Fix | Effort |
|---|----------|---------------|-----|--------|
| 1 | **Skills page subtitle** | "Run `clawctl agent skill attach...`" | Add [Attach to Agent] button per skill card → agent picker dropdown → calls `POST /api/agents/{key}/skills` | Small — API exists |
| 2 | **Settings / GUI Preferences** | "configure via CLI flags" | Make port, auto-open, refresh-rate editable inline. Save triggers GUI restart with new params. | Medium |
| 3 | **Settings / Danger Zone** | Disabled "Reset" button + "use CLI commands" | Enable button → confirmation modal requiring typed "RESET" → calls existing reset logic | Small |
| 4 | **Agent Configuration tab** | Read-only display, no edit capability | Add [Edit] button → modal to change provider, model assignment. Calls `clawctl agent configure` under the hood. | Medium |

**Design principle**: If the GUI shows you something exists, the GUI must let you act on it. Read-only display of editable data is a trust violation.

**Customer Value**: The GUI becomes self-sufficient. The ICP — who specifically chose to avoid the CLI — never hits a wall.

---

### Recommendation 4: Add an "Agent Overview" Panel Showing All Attached Artifacts

**Problem**: When looking at an agent, you can see its skills (under Skills tab) but you can't see the full picture: which provider is it using? Which integrations does it have? What channel is it connected to? This information is spread across the Configuration tab (provider, gateway) and Skills tab (skills), and integrations aren't visible in the agent detail at all.

**Proposed: Replace or enhance the Configuration tab:**

```
┌──────────────────────────────────────────────────────────────┐
│  vand — Attached Resources                                   │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  PROVIDER                                                    │
│  ┌──────────────────────────────────────────────────┐        │
│  │ esper-bedrock · AWS Bedrock · zai.glm-5          │        │
│  │ Key: ✓ Active · Last rotated: 3 days ago         │        │
│  │ [Change Provider] [View in Providers]            │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
│  SKILLS (2 installed)                                        │
│  ┌──────────────────────────────────────────────────┐        │
│  │ clawrium/tdd · v0.1.0           [Detach]         │        │
│  │ hermes/web-search · v1.2.0      [Detach]         │        │
│  │                      [+ Attach Skill]            │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
│  INTEGRATIONS (1 connected)                                  │
│  ┌──────────────────────────────────────────────────┐        │
│  │ work-atlassian · Atlassian · 3/5 keys set        │        │
│  │ Status: incomplete credentials    [Fix] [Detach] │        │
│  │                      [+ Connect Integration]     │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
│  GATEWAY                                                     │
│  ┌──────────────────────────────────────────────────┐        │
│  │ Port: 40012 · URL: http://clawdmin:40012         │        │
│  │ Device ID: abc123 · Onboarding: complete         │        │
│  └──────────────────────────────────────────────────┘        │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Why this matters:**
- Shows the **full graph of relationships** for a single agent in one view
- Every attached artifact has a **detach** action and a **link to the artifact's page**
- Missing/broken attachments (like incomplete integration credentials) surface here with fix actions
- This is the **inverse view** of Recommendation 1 — there, you see "which agents use this artifact." Here, you see "which artifacts are attached to this agent."

**Customer Value**: Users understand at a glance what an agent has access to, and can add/remove capabilities without navigating away. The relationship graph becomes tangible.

---

### Recommendation 5: Restructure Navigation to Foreground Artifact Management

**Problem**: The current nav is structurally sound (Providers, Skills, Integrations are top-level) but doesn't communicate the value hierarchy. Dashboard comes first, implying "look at metrics" is the primary action. The ICP's primary action is "manage my fleet's shared configuration."

**Proposed Navigation:**

```
┌─────────────────────────────────────────┐
│  FLEET OVERVIEW                         │
│  ──────────────                         │
│  Dashboard        (health + costs)      │
│  Topology         (network map)         │
│                                         │
│  SHARED CONFIGURATION                   │
│  ──────────────────                     │
│  Providers        (LLM keys & models)   │
│  Skills           (capabilities)        │
│  Integrations     (external services)   │
│  Channels         (communication)       │
│                                         │
│  AGENTS                                 │
│  ──────────                             │
│  Fleet Agents     (all agents list)     │
│  + Add Agent                            │
│                                         │
│  SYSTEM                                 │
│  ──────                                 │
│  Settings                               │
│  Usage & Costs                          │
└─────────────────────────────────────────┘
```

**Key changes from current:**
1. **Section headers** that communicate purpose: "Shared Configuration" tells users *why* these pages exist
2. **"Fleet Agents"** becomes its own nav item (currently it's only a table on Dashboard) — this is where you manage lifecycle (start/stop/restart/add/remove)
3. **"+ Add Agent"** as a persistent nav action — the most important onramp
4. **"Channels"** added (you mentioned this as a missing entity)
5. **Dashboard stays first** but framed as "Fleet Overview" — it's health-checking, not the primary workflow
6. **Settings + Usage** grouped as "System" — low-frequency admin tasks

**What this does NOT do:**
- Does not bury Providers/Skills/Integrations under a submenu — they're the core product, they stay top-level
- Does not promote chat/conversations — that's the agent's job
- Does not conflate visibility (Dashboard/Topology) with management (Providers/Skills/etc.)

**Customer Value**: The sidebar itself teaches users the product's mental model. "Shared Configuration" as a section header immediately communicates "these things are shared across your fleet" without reading docs.

---

### Recommendation 6: Add Onboarding That Teaches the "Shared Config" Mental Model

**Problem**: First-time users see empty pages with no understanding of WHY you'd configure providers/skills/integrations at the Clawrium level instead of per-agent.

**Proposed first-run flow:**

```
Step 1: Welcome
"Clawrium manages your AI agent fleet's shared infrastructure.
Set up providers, skills, and integrations ONCE — apply them to any agent."

Step 2: Add Your First Host
"Where will your agents run?"
[IP/hostname] [SSH user] [Test Connection]

Step 3: Create a Provider
"Configure an LLM provider. You'll be able to use this with any agent on your fleet."
Quick options: OpenAI | AWS Bedrock | Ollama (local)
Emphasis: "One provider config → all your agents"

Step 4: Deploy Your First Agent
"Choose an agent type and assign the provider you just created."
[Agent type selector] [Provider dropdown — showing the one just created]

Step 5: Done
"Your agent '{name}' is running on {host} using {provider}.
Next: Add skills, connect integrations, or deploy more agents."
[Go to Agent] [Add a Skill] [View Dashboard]
```

**Key difference from typical onboarding**: Step 3 explicitly teaches the configure-once-apply-many model. The provider is created *before* the agent, establishing the mental model that providers are fleet-level resources, not per-agent configs.

**Customer Value**: Users understand the value prop from minute one. No documentation required. The onboarding IS the product education.

---

### Recommendation 7: Make Topology Show All Artifact Relationships (Not Just Providers)

**Problem**: The topology graph currently shows Host → Agent → Provider edges. But Skills and Integrations are equally important shared artifacts, and they're completely invisible in the topology view.

**Proposed enhancement:**

```
Current topology edges:
  Control Machine ──SSH──→ Host ──runs──→ Agent ──uses──→ Provider

Proposed topology edges:
  Control Machine ──SSH──→ Host ──runs──→ Agent ──uses──→ Provider
                                              │──has──→ Skill
                                              │──connected──→ Integration
                                              └──channel──→ Channel
```

**Additional node types:**
- **Skill nodes**: Grouped by registry, showing which agents have them attached. Shared skills (attached to multiple agents) visually cluster — reinforcing the "configure once" message.
- **Integration nodes**: Show connection status (healthy/credentials incomplete/disconnected)

**Filtering:**
- Toggle layers: [Providers] [Skills] [Integrations] [Channels]
- Default: Providers only (for clarity). Users opt-in to full view.

**Why this matters for the value prop**: When a user sees that "tdd" skill node connected to 4 agent nodes simultaneously, the "shared configuration" value becomes visually obvious. The topology becomes a map of their fleet's capability architecture, not just its network topology.

**Customer Value**: The topology page becomes the single place to understand "what does my fleet look like, and how is everything connected?" It visualizes the exact value Clawrium provides.

---

## Summary: Prioritized Roadmap (Revised)

| Priority | Recommendation | Effort | Why |
|----------|---------------|--------|-----|
| **P0** | #1 "Configure once, apply many" workflows on artifact pages | Medium | Makes the core value prop visible and actionable. Currently invisible. |
| **P0** | #3 Eliminate CLI dead ends | Small | Trust violation for the ICP. APIs already exist. |
| **P1** | #2 Agent exec / command runner | Medium | Completes the GUI surface. Currently forces CLI. |
| **P1** | #4 Agent overview panel (all attached artifacts) | Medium | Inverse of #1 — shows the full relationship graph from the agent's perspective. |
| **P1** | #5 Restructure navigation with section headers | Small | Teaches the mental model through information architecture. |
| **P2** | #6 Onboarding wizard | Medium | First-time activation. Important but meaningless without #1. |
| **P2** | #7 Full artifact topology | Large | Visualization of the value prop. Impressive but not blocking. |

**The thread connecting all 7**: Clawrium's value is "configure shared infrastructure once, apply everywhere." Every recommendation makes that value either **more visible** (topology, overview panel, nav structure) or **more actionable** (apply-to-agents buttons, exec runner, no CLI dead ends).

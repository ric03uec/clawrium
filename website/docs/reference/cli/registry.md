# Registry Commands

Browse available agent types in the Clawrium registry.

```bash
clawctl agent registry <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| [`clawctl agent registry get`](#clawctl-agent-registry-get) | List available agent types |
| [`clawctl agent registry describe`](#clawctl-agent-registry-describe) | Show detailed information about an agent type |

---

## clawctl agent registry get

List available agent types in the registry.

```bash
clawctl agent registry get
```

### Example

```bash
$ clawctl agent registry get
               Available Agents
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name       ┃ Latest Version ┃ Description                    ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ zeroclaw   │ 0.1.0          │ Zero-config Claude assistant   │
│ openclaw   │ 0.2.0          │ OpenAI-powered assistant       │
└────────────┴────────────────┴────────────────────────────────┘
```

### Error Handling

If an agent's manifest is corrupted or missing:

```bash
               Available Agents
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name       ┃ Latest Version ┃ Description          ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ zeroclaw   │ 0.1.0          │ Zero-config Claude   │
│ badclaw    │ ?              │ Corrupted manifest   │
└────────────┴────────────────┴──────────────────────┘
```

---

## clawctl agent registry describe

Show detailed information about an agent type.

```bash
clawctl agent registry describe <agent_name>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `agent_name` | Name of the agent type to show |

### Example

```bash
$ clawctl agent registry describe zeroclaw

zeroclaw
Zero-config Claude assistant for local development

             Supported Platforms
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Version ┃ OS              ┃ Architecture ┃ Min Memory ┃ GPU Required ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 0.1.0   │ Ubuntu 22.04    │ x86_64       │ 2048MB     │ No           │
│ 0.1.0   │ Ubuntu 22.04    │ aarch64      │ 2048MB     │ No           │
│ 0.1.0   │ Debian 12       │ x86_64       │ 2048MB     │ No           │
│ 0.1.0   │ Debian 12       │ aarch64      │ 2048MB     │ No           │
└─────────┴─────────────────┴──────────────┴────────────┴──────────────┘

Dependencies:
  - docker >= 20.10
  - python >= 3.10
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Agent information displayed successfully |
| 1 | Agent not found or manifest corrupted |

### Error Scenarios

Agent not found:

```bash
$ clawctl agent registry describe unknown
Error: Agent 'unknown' not found in registry
```

Corrupted manifest:

```bash
$ clawctl agent registry describe badclaw
Error: Registry manifest is corrupted: Invalid YAML syntax
```

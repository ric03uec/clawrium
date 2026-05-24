# Registry Commands

Browse available claw types in the Clawrium registry.

```bash
clawctl agent registry <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| [`clawctl agent registry get`](#clawctl-agent-registry-get) | List available claw types |
| [`clawctl agent registry describe`](#clawctl-agent-registry-describe) | Show detailed information about a claw type |

---

## clawctl agent registry get

List available claw types in the registry.

```bash
clawctl agent registry get
```

### Example

```bash
$ clawctl agent registry get
               Available Claws
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name       ┃ Latest Version ┃ Description                    ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ zeroclaw   │ 0.1.0          │ Zero-config Claude assistant   │
│ openclaw   │ 0.2.0          │ OpenAI-powered assistant       │
│ nemoclaw   │ 0.1.0          │ Local Ollama-based assistant   │
└────────────┴────────────────┴────────────────────────────────┘
```

### Error Handling

If a claw's manifest is corrupted or missing:

```bash
               Available Claws
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name       ┃ Latest Version ┃ Description          ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ zeroclaw   │ 0.1.0          │ Zero-config Claude   │
│ badclaw    │ ?              │ Corrupted manifest   │
└────────────┴────────────────┴──────────────────────┘
```

---

## clawctl agent registry describe

Show detailed information about a claw type.

```bash
clawctl agent registry describe <claw_name>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `claw_name` | Name of the claw to show |

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
| 0 | Claw information displayed successfully |
| 1 | Claw not found or manifest corrupted |

### Error Scenarios

Claw not found:

```bash
$ clawctl agent registry describe unknown
Error: Claw 'unknown' not found in registry
```

Corrupted manifest:

```bash
$ clawctl agent registry describe badclaw
Error: Registry manifest is corrupted: Invalid YAML syntax
```

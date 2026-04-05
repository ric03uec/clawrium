# Registry Commands

Browse available claw types in the Clawrium registry.

```bash
clm registry <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| [`clm registry list`](#clm-registry-list) | List available claw types |
| [`clm registry show`](#clm-registry-show) | Show detailed information about a claw type |

---

## clm registry list

List available claw types in the registry.

```bash
clm registry list
```

### Example

```bash
$ clm registry list
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

## clm registry show

Show detailed information about a claw type.

```bash
clm registry show <claw_name>
```

### Arguments

| Argument | Description |
|----------|-------------|
| `claw_name` | Name of the claw to show |

### Example

```bash
$ clm registry show zeroclaw

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
$ clm registry show unknown
Error: Claw 'unknown' not found in registry
```

Corrupted manifest:

```bash
$ clm registry show badclaw
Error: Registry manifest is corrupted: Invalid YAML syntax
```

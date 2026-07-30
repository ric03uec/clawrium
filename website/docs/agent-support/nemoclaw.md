# NemoClaw Support Matrix

NemoClaw is NVIDIA's sandbox runtime for agent workloads
([`github.com/NVIDIA/NemoClaw`](https://github.com/NVIDIA/NemoClaw),
[`docs.nvidia.com/nemoclaw`](https://docs.nvidia.com/nemoclaw/latest/)).
In Clawrium, NemoClaw is **not an agent type** — it is a runtime
substrate that OpenClaw will run inside starting in phase 2 of the
[#11 rollout](https://github.com/ric03uec/clawrium/issues/11).

**Status:** 🚧 In Development (Phase 1 of #11 shipping — groundwork only)

**Role in the fleet:** invisible-by-default sandbox around OpenClaw. It
does not appear in `clawctl agent get`, `clawctl agent create`, or the
agent registry.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully supported and tested |
| 🚧 | In development / Planned |
| ❌ | Not supported |
| 📋 | Not planned (PRs welcome) |

---

## Rollout phases (issue #11)

| Phase | Ships | Operator-visible surface |
|-------|-------|--------------------------|
| **1 — Groundwork** (this release) | 🚧 | `clawctl doctor nemoclaw` reports `reachable / correct-sha / arch-match` for the pinned upstream tag. `clawctl` shows no `nc` alias; `clawctl agent registry get` no longer lists a phantom `nemoclaw` row. |
| **2 — On hosts, sandboxed openclaw available** | 📋 | `clawctl host prepare <host>` installs NemoClaw; new `clawctl agent create --type openclaw <…>` runs inside a NemoClaw sandbox. Bare openclaw still supported side-by-side. |
| **3 — Bare openclaw deleted (BREAKING)** | 📋 | Every OpenClaw runs inside a NemoClaw sandbox. `clawctl agent get` grows a `runtime: nemoclaw@<version>` column on OpenClaw rows. `clawctl host validate <host>` aggregates per-sandbox health. |
| **4 — Provider credentials leave the openclaw process** | 📋 | Provider `api_key` / `base_url` are handed to the NemoClaw gateway on `clawctl agent configure`; no `*_API_KEY` is visible from inside the OpenClaw sandbox. |

---

## Verifying the pin

```bash
clawctl doctor nemoclaw
```

Runs four read-only checks and exits non-zero on any failure:

| Check | What it does |
|-------|--------------|
| `reachable` | `GET /repos/NVIDIA/NemoClaw` — repo resolves. |
| `tag-exists` | `GET /repos/NVIDIA/NemoClaw/tags` — the pinned tag is present upstream. |
| `correct-sha` | Local `TARBALL_SHA256` table has a value for the local arch (**Phase 1 pins ship the tarball SHA as `pending-upstream-freeze`** — this check will report UNKNOWN until Phase 2 release prep populates it). |
| `arch-match` | Local architecture is in the `SUPPORTED_ARCHES` set (`x86_64`, `aarch64`). |

The probe never downloads the tarball and never touches any host. It is
safe to run on the operator's laptop.

---

## Upstream references

- Repo: [`github.com/NVIDIA/NemoClaw`](https://github.com/NVIDIA/NemoClaw)
- Docs: [`docs.nvidia.com/nemoclaw`](https://docs.nvidia.com/nemoclaw/latest/)
- Pinned version constant: `clawrium.core.nemoclaw.NEMOCLAW_VERSION`

The pin is the single write-side of a 3-way lockstep contract (constant
↔ OpenClaw manifest ↔ install runbook `nemoclaw_version` var) — the
manifest and runbook wire land in Phase 2 alongside the lockstep
regression test.

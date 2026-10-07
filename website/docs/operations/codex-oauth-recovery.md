---
sidebar_position: 2
description: Recover from interrupted Codex OAuth activation by removing the receipt file and re-attaching the provider.
keywords: [codex, oauth, activation, recovery, authentication, troubleshooting]
---

# Recover an interrupted Codex OAuth activation

Codex OAuth activation fails closed if the controller sees an interrupted
activation receipt. It deliberately does not overwrite `auth.json`: Codex may
have refreshed the current credentials after the interrupted operation.

The CLI names the exact non-secret receipt path. Do **not** print, copy, or
edit `~/.codex/auth.json`.

1. Confirm the affected agent can still authenticate using its native Codex
   CLI, without displaying `auth.json`.
2. On the agent host, remove **only** the non-secret receipt as the dedicated
   agent user:

   ```bash
   sudo -u <unix-agent-name> rm -- /home/<unix-agent-name>/.codex/.clawrium-oauth-fingerprint
   ```

   On macOS, use the `/Users` home root instead:

   ```bash
   sudo -u <unix-agent-name> rm -- /Users/<unix-agent-name>/.codex/.clawrium-oauth-fingerprint
   ```

3. Explicitly select the intended snapshot again, then activate it:

   ```bash
   clawctl agent provider attach <provider> --agent <agent-record-key>
   clawctl agent sync <agent-record-key>
   ```

The explicit re-attach intentionally replaces remote Codex credentials. Do it
only after confirming that replacing the current credential is desired.

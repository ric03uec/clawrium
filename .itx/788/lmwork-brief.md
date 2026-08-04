Work on issue #788 in this worktree. Read it first: `gh issue view 788`.

This brief covers **Phase 1 only** — "Unblock interaction" bullets 1-7 in the issue. Phases 2, 3, 4 are OUT OF SCOPE for this run and are tracked as separate follow-up work.

## Scope fence

Touch ONLY these files:

- `gui/src/components/agent-detail/chat-tab.tsx` (main)
- `gui/src/lib/api.ts` (only if AbortController threading requires the client signature change — see task 4 below)
- `.itx/788/` (run artifacts)

Do NOT touch:

- `src/clawrium/gui/routes/agents.py` — backend SSE change belongs to Phase 2.
- Any other file under `gui/`, `src/`, `docs/`, `website/`, or `.hermes/`.
- Do NOT add new npm dependencies. Everything Phase 1 needs is native React + Tailwind. `react-markdown`, `shiki`, `@tanstack/react-virtual`, etc. are Phase 2/3 concerns.
- Do NOT introduce sessions, markdown rendering, code highlighting, copy buttons, regenerate, or thread lists — all Phase 2/3.
- Do NOT rename `chat-tab.tsx` or restructure it into multiple files.

## Tasks

Do them in order. Commit after each with a `feat(#788):` or `fix(#788):` prefix so the diff is reviewable per-task.

1. **Remove `disabled={sending}` on the input** (chat-tab.tsx:118). Send button stays gated by `sending || !input.trim()`. User can type freely while a response is streaming.
2. **Promote the input to `<textarea>`** with auto-resize between 1 and 8 rows. Enter submits, Shift+Enter inserts a newline, Cmd/Ctrl+Enter is an alias for Enter. Empty-trimmed input still no-ops on Enter. The submit-during-in-flight decision is: **Enter is a no-op while `sending` is true** — the user's draft is preserved, they resend once the response arrives. Do NOT queue.
3. **Focus restoration.** Focus the textarea after each successful send (i.e., after the user's message is queued into `messages`) and again after the assistant response is fully received. Use a `useRef` on the textarea.
4. **AbortController + Stop button.**
   - Add an `AbortController` created per-send in the component. Store it in a ref so the Stop button can call `.abort()`.
   - Extend `api.sendChatMessage` in `gui/src/lib/api.ts` to accept an optional `{ signal }: { signal?: AbortSignal }` parameter and pass it through to `fetch`. If the current signature is positional, change it to accept an options object as the last param — update the one existing call site in `chat-tab.tsx`.
   - Show a "Stop" button (replacing / next to the Send button) while `sending` is true. On abort:
     - Cancel the in-flight fetch.
     - Append a final marker to the partial assistant message text, e.g. `\n\n_Stopped by user._`, and commit it to `messages` so it stays visible.
     - Clear `sending`, restore focus.
5. **Animated typing indicator with elapsed time.** Replace the static "Thinking…" with "Thinking… Ns" that ticks every second while `sending`. Use a `useEffect` with `setInterval(1000)` cleared on unmount / when `sending` flips false. A subtle pulse animation (Tailwind `animate-pulse` on a dot cluster) is fine — no external animation library.
6. **Full-height layout.** Replace `className="flex flex-col h-[500px]"` (chat-tab.tsx:70) with `className="flex flex-col h-full min-h-0"`. Verify the parent pane already provides a bounded height; if it does not, adjust ONLY the immediate parent in chat-tab.tsx (do not walk up multiple levels).

## Pattern to follow

There is no in-repo textarea-with-auto-resize precedent; write it inline with a `useEffect` on `input` that reads `scrollHeight` and clamps to 8 rows × line-height. Keep it under 20 lines — don't reach for `react-textarea-autosize`.

For AbortController wiring, the pattern is standard React 18: `useRef<AbortController | null>(null)`, create in the submit handler, pass `ref.current.signal` to `sendChatMessage`, and null it out in a `finally`.

## Rules

- Commit locally. Do NOT push. Do NOT open a PR — the judge in the other tmux window will handle that after review.
- Do not add features, refactors, or abstractions beyond the seven tasks above. Every prior local_qwen failure came from going wide.
- Run `make lint && make test` before considering the work done. Both must pass.
- Do NOT modify the backend Python routes (`src/clawrium/gui/routes/agents.py`) — the SSE batching stays for Phase 2.
- If a task turns out to be already done, stop and say so — do not invent work.
- Commit `.itx/788/` along with your changes.
- **Real-host UAT (booting the GUI server and clicking through the chat) is the user's responsibility** — you do not have to run it. The PR will land with an `[UNRESOLVED]` Callout stating this.
- When all seven tasks are committed and `make lint && make test` pass, run: `echo done > .itx/788/lmwork-worker.done`

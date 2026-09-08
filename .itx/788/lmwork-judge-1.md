VERDICT: REVISE

Tasks 1-5 are implemented and correct. `make lint` and `make test` both pass
(ruff clean, next lint clean, 329/329 vitest). The abort path is wired properly
— `signal` reaches `fetch`, and an abort mid-stream rejects `reader.read()` with
`AbortError`, which your catch branch handles. Only one call site of
`sendChatMessage` exists, so the options-object signature change is safe.

Five items to fix.

1. **Task 6 does not work — the pane has no definite height to inherit.**
   `chat-tab.tsx:138` sets `h-full` (`height: 100%`), but the immediate parent is
   `page.tsx:113` `<div className="min-h-[500px]">` — that is a *min-height* with
   `height: auto`. A percentage height only resolves against an ancestor with an
   explicitly-specified height, so `h-full` computes to `auto` here. Two
   consequences: the pane never fills the available space (task 6's goal), and
   worse, the messages div at `chat-tab.tsx:141` (`flex-1 overflow-y-auto
   min-h-0`) loses its bounded scroll container — with an auto-height flex
   parent it grows to fit content, so `overflow-y-auto` never triggers and a long
   conversation scrolls the whole page instead of the message list. That is a
   regression against the old `h-[500px]`.

   Do NOT fix this by editing `page.tsx:113` — that div is shared by all seven
   tabs (overview, exec, config, skills, memory, logs), so giving it a fixed
   height changes every tab and would need UAT across all of them. Instead give
   the chat root its own self-contained definite height, e.g. replace
   `h-full min-h-0` at `chat-tab.tsx:138` with
   `h-[calc(100vh-20rem)] min-h-[400px]`. Keep `min-h-0` on the messages div at
   line 141. Making a true `h-full` work requires a page-layout change up the
   tree — leave that for a later phase, do not attempt it here.

2. **No tests for any of the new behavior.** Five of the eight tab components in
   `gui/src/components/agent-detail/` ship a `.test.tsx` sibling
   (agent-header, agent-metrics, memory-tab, overview-tab, skills-tab);
   `chat-tab.tsx` has none, and this change adds substantial interactive
   behavior. Add `gui/src/components/agent-detail/chat-tab.test.tsx` — this one
   new file is authorized despite the scope fence, nothing else under `gui/`.
   Follow the mocking style in `skills-tab.test.tsx`. Cover:
   - the textarea is NOT disabled while `sending` is true (this is the
     regression the whole issue is about — it needs a locking test)
   - Enter submits; Shift+Enter inserts a newline instead of submitting
   - Enter is a no-op while `sending` is true and the draft text survives
   - clicking Stop aborts and commits the stopped-marker message
   - the Stop button replaces Send only while `sending`

3. **`chat-tab.tsx:116` — `isCmdCtrl` is assigned and never read.** The submit
   condition at line 120 is `isEnter && !isShift`, so Cmd/Ctrl+Enter only submits
   incidentally. Delete the variable, or fold it in explicitly as
   `if (isEnter && (!isShift || isCmdCtrl))` if you want Cmd+Shift+Enter to
   submit too. Either is fine; leaving dead code is not.

4. **`chat-tab.tsx:189` — `overflow-hidden` on a clamped textarea hides
   overflowing draft text.** Once the auto-resize caps at 8 rows, content past
   the cap has no scrollbar; the mouse wheel does nothing over the element and
   only caret movement scrolls it. Change `overflow-hidden` to `overflow-y-auto`.

   Related, same effect block: `chat-tab.tsx:50-51` hardcodes a 24px row height,
   but the textarea is `text-sm` (20px line-height) with `py-2.5` (20px total
   padding, border-box). One empty line measures `scrollHeight` 40 →
   `ceil(40/24)` = 2 rows → 48px, so your "1 row" floor is really 2. It is stable
   and not visually broken, but the arithmetic is wrong. Prefer setting
   `el.style.height = ${el.scrollHeight}px` with a `maxHeight` cap rather than
   quantizing by a guessed row constant.

5. **Rebase.** `origin/main` has moved 4 commits ahead (a0097f0, 994fc94,
   8ef2d30, 6ae695f). None touch the two files you changed, so this should be
   clean — `git fetch origin && git rebase origin/main` before you continue, so
   you are not testing against a stale base.

Not findings, for your information: appending a standalone `_Stopped by user._`
message rather than mutating a partial is the right call given Phase 1 has no
streaming partials, and moving the `chatInfo.supported` early-return below all
the hooks was required by the Rules of Hooks. Both correct.

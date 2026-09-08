VERDICT: REVISE

Round 1 items are all addressed. Confirmed fixed:

- **Item 1 (layout)** — `h-[calc(100vh-20rem)] min-h-[400px]` gives the root a
  definite height, so `flex-1` + `overflow-y-auto` on the messages div now has a
  bounded scroll container. Correct fix, and correctly kept out of `page.tsx`.
- **Item 3** — `isCmdCtrl` gone, comment updated. Cmd/Ctrl+Enter still submits
  via the `isEnter && !isShift` branch, and you added tests proving it.
- **Item 4 (overflow)** — `overflow-y-auto` + explicit `max-h` cap. Right shape.
- **Item 5** — rebased; `HEAD..origin/main` is empty.
- `make lint` clean (ruff + next lint), `make test` 343/343 passing, up from 329.
- Scope fence still clean: `chat-tab.tsx`, `chat-tab.test.tsx`, `api.ts`,
  `.itx/788/`.

The test file is a real improvement — 14 tests covering all five cases I asked
for plus error handling, empty-state, and the Cmd/Ctrl+Enter aliases. Two items
left.

1. **The Stop test does not actually test Stop.** `chat-tab.test.tsx:129-154`
   rejects the promise itself via `rejectFn`, so it proves the component renders
   a stopped marker when it *receives* an `AbortError` — it never checks that
   clicking Stop aborted anything. I verified this: I replaced the body of
   `handleStop` with a comment so the button does literally nothing, reran the
   file, and all 14 tests still passed. As written this test cannot catch a
   regression in the one mechanism task 4 exists to deliver.

   Assert on the signal the component actually passed. Inside that test, after
   the send has been fired:

   ```ts
   const signal = sendChatMessage.mock.calls[0][2].signal as AbortSignal;
   expect(signal.aborted).toBe(false);

   await act(async () => {
     fireEvent.click(stopBtn);
     rejectFn!(new DOMException("The operation was aborted", "AbortError"));
   });

   expect(signal.aborted).toBe(true);
   ```

   Re-run with `handleStop` gutted to confirm the test now fails, then restore
   it. While you are in there: the `Object.assign(...)` wrapper at line 149 has
   a single argument and does nothing — drop it, construct the `DOMException`
   directly.

2. **`chat-tab.tsx:187` — `max-h-[234px]` is about 10.6 rows, not the 8 the
   brief specifies.** The textarea is `text-sm` (Tailwind default line-height
   20px — I checked `tailwind.config.ts`, there is no `fontSize` override) with
   `py-2.5` (10px top + 10px bottom) and a 1px border, under Tailwind
   preflight's `box-sizing: border-box`. So eight rows is
   `8 x 20 + 20 + 2 = 182px`. Change `max-h-[234px]` to `max-h-[182px]`.
   Nothing else in that class list needs to move.

Not findings: no auto-resize test is fine — jsdom does not do layout, so
`scrollHeight` is always 0 there and the behavior is not assertable. Leaving
focus restoration untested is also acceptable for this round; it was not in the
five cases I named.

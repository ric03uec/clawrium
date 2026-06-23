## Issue-786 Re-Review — Iteration 2

**Rating: 4/5 — No blockers. All W1–W5 resolved. 6 suggestions.**

---

### W1–W5 Resolution Status

| # | Warning | Status | Notes |
|---|---------|--------|-------|
| W1 | Fallback span missing `role=img`/`aria-label` | **Resolved** | Fallback `<div>` carries `role="img"` + `aria-hidden="true"`. Technically the `role` is dead code (aria-hidden removes the node from the accessibility tree), but since each call site renders the integration type as sibling text, treating the icon as decorative is correct. |
| W2 | `<img>` missing `alt` / not aria-hidden | **Resolved** | `alt=""` + `aria-hidden="true"` applied. Both signals are redundant (WAI-ARIA idiom only needs `alt=""`), but harmless. |
| W3 | No parametrized fallback coverage | **Resolved** | `it.each` parametrizes fallback across empty-string, single-char, and multi-char cases. See S1 below for one weak assertion in the empty-string row. |
| W4 | No lazy/width/height attribute assertions | **Resolved** | Assertions use `toHaveAttribute` on actual rendered DOM (`loading="lazy"`, `width="32"`, `height="32"`) — not prop-pass-through mocks. |
| W5 | Add button in page header; no placement test | **Resolved** | `page.test.tsx` positively asserts button presence in the section row and negatively asserts absence from the page header. See S4 below for brittleness. |

---

### New Suggestions Introduced (not blocking)

**S1** · `integration-icon.test.tsx:42–53` — `expect(fallback).toHaveTextContent('')` is a substring match; an empty string matches *any* element's textContent, so the empty-type row can never fail. Use `expect(fallback.textContent).toBe('')` or `.toBeEmptyDOMElement()`.

**S2** · `integration-icon.tsx:32–33` — `role="img"` on an `aria-hidden="true"` node is dead code (AT never sees the role). Drop `role="img"` from the fallback `<div>`; keep only `aria-hidden="true"`.

**S3** · `integration-card.test.tsx:47` — `expect(screen.queryByText('GH')).toBeNull()` is a misleading guard: jsdom textContent is lowercase (`gi`, not `GH`), so this assertion passes against the very regression it claims to block. The `img != null` + `src` check is what actually catches the regression. Drop the `GH` line or replace it with an absence-of-legacy-class assertion.

**S4** · `page.test.tsx:70–76` — `.parentElement!.parentElement!` DOM-climbing to reach the PageHeader container will silently shift targets if `<PageHeader>` gains or loses a wrapper div. Stabilize with `data-testid="page-header"` on the PageHeader root (or `screen.getByRole('banner')`), then use `within(pageHeader).queryByRole(...)`.

**S5** · `page.test.tsx:79–94` — The empty-state test verifies the CTA is present but omits the negative header assertion. A future change that adds a header button only on empty-state would silently regress the W5 invariant. Add the same `within(pageHeader).queryByRole('button', { name: /Add Integration/ })` negative check to the empty-state branch.

**S6** · `integration-card.test.tsx:34–46` — `container.querySelector('img')` will match whichever `<img>` appears first if the card later renders a second image (e.g., a status badge). Tighten to `container.querySelector('img[src^="/integration-icons/"]')` to keep the assertion specific to the integration icon.

---

### Recommended Actions Before Merge

Priority order (none are blockers, but S1, S4, S5 have the highest regression risk):

1. **S1** — Fix `toHaveTextContent('')` → `toBe('')` so the empty-type fallback row actually exercises the branch.
2. **S4 + S5** — Replace parent-chain selector with a stable handle; extend the negative header check to the empty-state test.
3. **S2** — Drop the redundant `role="img"` on the aria-hidden fallback.
4. **S3** — Remove or fix the misleading `GH` text assertion in card tests.
5. **S6** — Tighten the card test's `img` selector.


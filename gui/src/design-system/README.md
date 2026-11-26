# Clawrium design-system foundation

This directory is a **copied-once fork** of selected primitives from the private
[i7n/ui Storybook repository](https://github.com/i7n-inc/storybook). The source
snapshot is pinned exactly to:

```text
6fa5f42a9892c15e4ef41bee9e67dd5826d1ae7f
```

Clawrium owns these copies. Runtime code must import the local files; do not add
an `i7n` npm dependency or link this directory to the upstream checkout.

## Included files

Public primitives:

- `Button`, `Card`, `Input`, `StatusChip`, `StatBlock`
- `PageHeader`, `TabBar`, `HostCard`, `DataTable`, `AgentLogo`
- transitive public primitives `Eyebrow` and `StatusLight`

Clawrium-owned canonical extension:

- `AppSidebar` — the single reusable implementation for application-shell
  navigation, collapse behavior, active cards, brand chrome, and footer actions

Internal closure:

- `ui/button.tsx`, `ui/card.tsx`, `ui/input.tsx`, `ui/table.tsx`
- `../lib/utils.ts` and `../types/react-table.d.ts`
- `styles.css`
- `public/agents/{claude,cursor,herdr,openai,opencode,warp}.{svg|png}`

`index.ts` is the supported local barrel. The `ui/` wrappers are implementation
details.

## Local adaptations

The upstream snapshot targets React 19, Next 15, and Tailwind 4. Clawrium uses
React 18, Next 14, and Tailwind 3, so this fork deliberately:

- keeps all source headers, hard-coded `data-i7n-component` values, and required
  `trackingId` props;
- reduces the internal `ui/*` wrappers to Tailwind 3-compatible structural
  classes while retaining their tracking roots and native element behavior;
- removes the unused `asChild`/Radix Slot path and
  `class-variance-authority`; the public copied `Button` API never exposed
  `asChild`, so no required behavior is lost;
- uses `tailwind-merge` 2.x, the Tailwind 3-compatible line;
- scopes tokens beneath `.iteration-design-system`, uses system font fallbacks,
  and does not copy the Tailwind 4-only `shadcn.css` or network-loaded fonts;
- changes `HostCard` from a fixed 420 px width to `width: 100%` with
  `max-width: 420px` for narrow layouts;
- forwards Button/Card refs and retains the previous production `danger`
  button alias plus `sm`/`md`/`lg` Card padding while consumers migrate;
- extends `StatusLight` with the existing informational blue tone so every
  `AgentStatus` keeps its established semantic family;
- maps every Clawrium-supported agent type to its official upstream product
  mark. Those additional application assets are documented separately in
  [`public/agents/README.md`](../../public/agents/README.md) and are not claimed
  as files copied from the pinned i7n snapshot;
- keeps all sidebar markup, card styling, active state, and collapse behavior in
  `AppSidebar`; `components/layout/sidebar.tsx` only supplies Clawrium's routes,
  icons, active state, version, and brand data.

The root app layout imports `styles.css` and applies exactly one
`.iteration-design-system` ancestor on `<body>`. Shell and legacy Tailwind
utilities resolve through the canonical design-system tokens while feature
components are migrated incrementally.

## Attribution, authorization, and license

See [`NOTICE.md`](NOTICE.md) for the provenance statement. The exact snapshot
was explicitly required and authorized for this Clawrium change by the
maintainer in issue #1075 and the corresponding execution request. The copied
component source and agent artwork remain attributed to **i7n/ui** and the
pinned upstream commit above; i7n retains ownership of the private upstream
source. Each copied component retains its upstream `@source` header.

The pinned upstream checkout contains no standalone LICENSE file or package
license declaration, so this copy does not invent one or assert broader
relicensing. It also does not add an `i7n` npm dependency. Preserve the
attribution and treat any redistribution outside this authorized Clawrium
change as a separate permissions question.

## Updating from upstream

Updates are manual and reviewable:

1. Choose and record an exact upstream commit; never copy from a moving branch.
2. Compare the selected primitives, transitive `@deps`, styles, and agent assets
   against this fork.
3. Copy intentional changes while preserving source/tracking headers and the
   required `trackingId` contract.
4. Reapply the React 18 / Next 14 / Tailwind 3 adaptations above. Do not import
   Tailwind 4 `shadcn.css`.
5. Update the SHA, included-file list, adaptation notes, exact dependency pins,
   and focused tests in the same change.
6. Run `npm test`, `npm run lint`, `npm run test:export-server`, and
   `npm run test:e2e` from `gui/`. The browser command builds a fresh production
   export in `out/` before testing it; it does not use the Next development
   server.

`consumer-migration.test.ts` is the CI contract for the pinned SHA, complete
primitive/barrel inventory, dependency isolation, tracking attributes, migrated
page headers, and the narrow raw-input/list-surface allowlists. Update that test
and document any allowlist change here in the same review.

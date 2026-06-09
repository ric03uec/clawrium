# Issue #694 — Provider page UX changes

Created via `/itx:issue-new`. See https://github.com/ric03uec/clawrium/issues/694 for the canonical body.

## Issue Creation

**Stage**: issue-creation
**Skill**: /itx:issue-new
**Timestamp**: 2026-06-09T22:45:00Z
**Model**: claude-opus-4-7

```prompt
the providers page and list on the ui has a lot of gaps.
1. bedrock provider should ask for access, secret keys and regions (with default here) not the apikey
2. you're conflating providers with provider registry. the configured providers should show the actual providers with keys and assigned/not assigned to agents. this should be a table which should provider, model, actions, used by, icons, created at.
   provider registry is list of supported endpoints by clawrium which will have a list of all models.
   remove model catalog from bottom and move it into another tab.
   providers is the left panel entry, which is fine. it should show configured providers as the first tab in a table and then registry in the second tab with models.
```

**Output**: GitHub issue #694 — "Provider page UX changes" (multiple UX changes clubbed into one issue per user direction).

---

## Planning

**Stage**: planning
**Skill**: /itx:plan-create
**Timestamp**: 2026-06-09T23:30:00Z
**Model**: claude-opus-4-7

```prompt
/itx:plan-create 694. dont create file. show me plan only
(follow-up) dont show me technical tasks, show user outcomes and then tasks and then test plan.
1. do a research on this first join is fine if not already supported
2. fine
3. existing bedrock are working just fine. dont worry about it. but double check from secrets store
4. fine, confirmed
5. free text. default us-east-1 is fine. single pr. update plan first and show me wireframe of ui
(follow-up) in the plan also add verification of the ui screens. rest is good. write it up in plan and send pr and merge
```

**Output**: high-level implementation plan + UI wireframe + UI verification steps for the Providers page rework

---

## Research Findings

1. **`used_by` join is already client-side.** `gui/src/app/providers/page.tsx:96` builds a `providerUsage` map from `useFleet()` (each agent record carries a `provider` field). No backend join needed; the new table reuses the same map.
2. **Bedrock secrets store is already fully wired.** `set_provider_aws_credentials` / `get_provider_aws_credentials` / `remove_provider_aws_credentials` exist in `src/clawrium/core/providers/storage.py`. The CLI already uses them (`provider.py:557` add, `:717` update). `region` flows through `core/render.py:380` into the hermes (`hermes-config.canonical.yaml.j2:64`, `hermes-env.canonical.j2:21`) and openclaw (`openclaw-env.canonical.j2:38`) templates with a `us-east-1` template-side default. The GUI is the only surface that doesn't expose these. **No backend storage changes needed** — GUI only needs to start sending the AWS fields + region.
3. **Existing bedrock records are safe** (CLI-created records already carry AWS creds + region). Per user direction: do not migrate, do not surface "re-configure required" indicators.

---

## User Outcomes

When this lands, an operator can:

1. **See their configured providers at a glance** in a table, immediately knowing — for each provider — which type, which default model, which agents are using it, when it was created, and whether it's unassigned.
2. **Find the Clawrium-supported endpoints and full model catalog in one place** under a dedicated Registry tab, separate from their own configured providers.
3. **Add a Bedrock provider with the right credentials** (AWS Access Key ID + Secret Access Key + Region) instead of being prompted for an API key that Bedrock doesn't use.
4. **Edit a Bedrock provider's region** without re-entering keys, and **rotate keys** without changing region.
5. **Continue using all non-Bedrock providers exactly as before** — the API-key flow stays identical.

---

## Wireframe

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Providers                                                                    │
│ Configure LLM providers once, apply them across your fleet.                  │
├──────────────────────────────────────────────────────────────────────────────┤
│ ┃ Configured (3) ┃   Registry                                  [+ Add]       │
│ ━━━━━━━━━━━━━━━━━                                                            │
│                                                                              │
│ ┌────┬──────────────┬───────────┬──────────────────┬──────────────┬─────────┐│
│ │ 🟧 │ Provider     │ Type      │ Default Model    │ Used by      │ Created ││
│ ├────┼──────────────┼───────────┼──────────────────┼──────────────┼─────────┤│
│ │ 🟣 │ my-anthropic │ anthropic │ claude-opus-4-7  │ maurice, kev │ 2026-…  ││  [Edit] [Del] [▾]
│ │ 🟠 │ aws-prod     │ bedrock   │ claude-sonnet…   │ 2 agents     │ 2026-…  ││  [Edit] [Del] [▾]
│ │ ⚪ │ local-llama  │ ollama    │ llama-3.1:70b    │ ⌀ Unassigned │ 2026-…  ││  [Edit] [Del] [▾]
│ └────┴──────────────┴───────────┴──────────────────┴──────────────┴─────────┘│
│                                                                              │
│   ▾ Expanded row (Describe):                                                 │
│     Endpoint: https://bedrock-runtime.us-east-1.amazonaws.com                │
│     Region:   us-east-1                                                      │
│     Models:   claude-sonnet-4-6, claude-opus-4-7, … (+12 more)               │
└──────────────────────────────────────────────────────────────────────────────┘

Registry tab:
┌──────────────────────────────────────────────────────────────────────────────┐
│   Configured     ┃ Registry ┃                                                │
│                  ━━━━━━━━━━━                                                 │
│ Supported endpoints:                                                         │
│   ▸ openai      — 8 models                                                   │
│   ▸ anthropic   — 5 models                                                   │
│   ▾ bedrock     — 23 models                                                  │
│       ┌─────────────────────────┬──────────┬───────────────┐                 │
│       │ Model                   │ Context  │ Tags          │                 │
│       ├─────────────────────────┼──────────┼───────────────┤                 │
│       │ claude-sonnet-4-6       │ 1M       │ chat, vision  │                 │
│       │ claude-opus-4-7         │ 1M       │ chat, vision  │                 │
│       │ …                       │          │               │                 │
│       └─────────────────────────┴──────────┴───────────────┘                 │
│   ▸ openrouter  — 312 models                                                 │
│   ▸ ollama      — (per-instance)                                             │
│   ▸ vertex / zai / …                                                         │
└──────────────────────────────────────────────────────────────────────────────┘

Add Provider modal — Bedrock branch:
┌────────────────────────────────────────────┐
│ Add Provider                            ✕  │
├────────────────────────────────────────────┤
│ Provider Name   [ aws-prod              ]  │
│ Type            [ bedrock           ▾ ]    │
│ Default Model   [ claude-sonnet-4-6 ▾ ]    │
│                                            │
│ AWS Access Key ID                          │
│ [ AKIA••••••••••••••••              ]      │
│ AWS Secret Access Key                      │
│ [ ••••••••••••••••••••••••  ] [show]       │
│ Region                                     │
│ [ us-east-1                         ]      │
│   (free text, default us-east-1)           │
│                                            │
│ Endpoint: https://bedrock-runtime…         │
│   (auto-configured)                        │
│                              [Cancel] [Save]│
└────────────────────────────────────────────┘

Add Provider modal — non-Bedrock (unchanged):
   shows "API Key" field, no AWS fields.
```

---

## Tasks (single PR)

1. **Tabs shell.** Wrap the existing Providers page in a two-tab control (`Configured` default, `Registry`); move the model catalog into the Registry tab.
2. **Configured providers table.** Replace the card list with a table whose columns match the wireframe (icon, name, type, model, used by, created at, actions), keeping the same `providerUsage` client-side join already in place. Empty state: "No providers configured yet — add one or browse the Registry tab."
3. **Row-expand "Describe".** Inline expand under each row showing endpoint, region (bedrock), available models, accelerator vendor.
4. **Bedrock add-form branch.** When `type === "bedrock"`: replace the API key field with three inputs (Access Key ID, Secret Access Key, Region defaulting to `us-east-1`). Submit payload carries `aws_access_key_id`, `aws_secret_access_key`, `region`.
5. **Bedrock edit-form branch.** For bedrock providers: show region as editable free-text; allow rotating Access Key ID and Secret Access Key independently (empty input = keep existing). Hide the API key control.
6. **Backend payload acceptance.** Extend `ProviderCreate` / `ProviderUpdate` in `src/clawrium/gui/routes/providers.py` to accept the three AWS fields; for `type=bedrock`, route secrets through `set_provider_aws_credentials` and persist `region` on the provider record. Surface `region` and `has_aws_credentials` on `GET /api/providers`, and `requires_aws_credentials` + `default_region: "us-east-1"` on `GET /api/providers/types` for bedrock.
7. **Registry tab content.** Mount `<ModelCatalog />` inside the Registry tab with the same search/filter UX it has today.

Subtasks: none (single PR per user direction).

---

## Test Plan

### Frontend
- Configured tab is selected by default; switching to Registry shows the model catalog and hides the configured table.
- Table renders one row per provider with the wireframe columns; "Used by" shows joined agent names from the fleet hook; empty `used_by` renders the "Unassigned" pill.
- Selecting `bedrock` in the Add modal hides the API key input and shows Access Key ID + Secret Access Key + Region (pre-filled `us-east-1`); selecting `openrouter` shows API key and hides the AWS fields.
- Editing a bedrock provider pre-populates region; submitting with an empty Secret Access Key keeps the existing one; changing only region issues a region-only update.
- Existing card-test assertions for non-bedrock providers continue to pass under the new table.

### Backend
- `POST /api/providers` with `type=bedrock` + AWS fields writes secrets via `set_provider_aws_credentials` and persists region in `providers.json`.
- `POST /api/providers` with `type=bedrock` + `api_key` → 400 ("Bedrock uses AWS credentials").
- `POST /api/providers` with `type=openrouter` + AWS fields → AWS fields ignored, normal API-key flow.
- `PUT /api/providers/{name}` for bedrock can update region alone, AWS keys alone, or both; empty key fields preserve existing secret.
- `GET /api/providers` returns `region` and `has_aws_credentials` for bedrock records; `GET /api/providers/types` returns `requires_aws_credentials: true` and `default_region: "us-east-1"` for bedrock.

### UI Screen Verification

Build the GUI, launch it locally (`make gui-dev` or equivalent), and walk through every screen in the wireframe before declaring done. For each screen, take a screenshot via the Puppeteer MCP and verify against the wireframe spec.

1. **Providers page — Configured tab (default load).**
   - Navigate to `/providers`. Confirm the page title, two-tab control with **Configured** active, and the `+ Add Provider` button rendered in the tab bar.
   - Confirm at least one configured provider renders as a table row with all seven columns (icon, name, type, model, used by, created at, actions).
   - Verify "Used by" shows agent names from the live fleet for attached providers, and the "Unassigned" pill renders for unattached ones.

2. **Providers page — Registry tab.**
   - Click the Registry tab. Confirm the configured table disappears and the model catalog (search box, provider filter, expandable per-type sections) renders in its place.
   - Confirm searching/filtering still works (regression check on relocated ModelCatalog).

3. **Add Provider — Bedrock branch.**
   - Click `+ Add Provider`. In the type dropdown, select `bedrock`.
   - Verify the API key field is **hidden**; AWS Access Key ID, AWS Secret Access Key, and Region fields are **shown**; Region is pre-populated with `us-east-1`.
   - Verify the Secret Access Key field has a `show`/`hide` toggle and `password` type by default.
   - Verify the endpoint hint line shows the bedrock runtime endpoint.

4. **Add Provider — non-Bedrock branch (regression).**
   - Reopen the Add modal; select `openrouter` (or `anthropic`). Verify the API key field is **shown** and AWS fields are **hidden** — i.e. nothing leaks across the type switch.

5. **Edit Provider — Bedrock branch.**
   - Click `Edit` on an existing bedrock row. Verify Region is pre-populated from the record (editable), AWS key fields are blank with "leave blank to keep current" hint, and the API key field is hidden.

6. **Edit Provider — non-Bedrock branch (regression).**
   - Click `Edit` on a non-bedrock provider. Verify the form matches today's behavior (API key field shown, AWS fields hidden).

7. **Row-expand "Describe".**
   - Click the expand chevron on a row. Verify the inline panel shows endpoint, region (for bedrock), available models, and accelerator vendor (for ollama).

8. **Empty state.**
   - With zero configured providers, confirm the empty-state message and CTA point the user toward adding one or browsing the Registry tab.

### Manual real-host verification

Use **`wolf`** as the verification host (already configured for hermes).

- Add a fresh bedrock provider from the GUI; attach it to a hermes agent on `wolf`; run `clawctl agent configure` and inspect rendered `~/.hermes/.env` on `wolf` — confirm `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` are all populated correctly.
- Edit the bedrock provider region in the GUI; re-run sync to `wolf`; confirm `AWS_DEFAULT_REGION` changes on the host without touching the secrets.
- Confirm an existing (CLI-created) bedrock provider on `wolf` renders correctly in the new table with the right region and `has_aws_credentials=true`.

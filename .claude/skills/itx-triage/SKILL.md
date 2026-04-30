---
name: itx:triage
description: Review issues without workflow labels and assign appropriate labels
argument-hint: ""
---
name: itx:triage

# Issue Triage

Find and triage issues that don't have workflow labels.

## Instructions

1. **Find Unlabeled Issues**: List issues without workflow labels
   ```bash
   gh issue list --state open --json number,title,labels,createdAt --limit 50
   ```

2. **Filter**: Identify issues that do NOT have any of these labels:
   - `needs-triage`
   - `planning`
   - `ready`
   - `in-progress`
   - `in-review`

3. **For Each Unlabeled Issue**:
   - Fetch full details: `gh issue view <number>`
   - Analyze the title and description
   - Determine appropriate action:
     - **Needs more info**: Add `needs-triage` label
     - **Ready to plan**: Add `planning` label
     - **Bug report**: Ensure `bug` label is present, add `needs-triage`
     - **Clear and actionable**: Add `planning` label

4. **Apply Labels**:
   ```bash
   gh issue edit <number> --add-label "<label>"
   ```

5. **Add Triage Comment**:
   ```markdown
   **Triage Decision**: <label applied>

   <brief rationale>

   ---

   <details>
   <summary>Prompt Log</summary>

   **Stage**: triage
   **Skill**: /itx:triage
   **Timestamp**: <ISO timestamp>
   **Model**: <model>

   ```prompt
   <user prompt that triggered triage>
   ```

   </details>
   ```

6. **Return**: Summary of triaged issues

## Workflow Labels

| Label | Meaning |
|-------|---------|
| `needs-triage` | Needs more information or clarification |
| `planning` | Ready for implementation planning |
| `ready` | Plan complete, ready for execution |
| `in-progress` | Currently being worked on |
| `in-review` | PR open for review |

## Notes

- Focus on issues that fell through the cracks
- Don't re-triage issues that already have workflow labels
- Be conservative - when in doubt, use `needs-triage`

## Prompt Logging

**REQUIRED**: For each triaged issue, append prompt log to `.itx/<N>/00_PLAN.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

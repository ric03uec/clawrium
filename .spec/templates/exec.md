# Execution: {{TITLE}}

> **Issue**: {{ISSUE_ID}}
> **Plan**: [plan.md](./plan.md)

## Execution Principles

1. **Atomic steps**: Each step is independently executable, verifiable, and committable
2. **No breakage**: Product must run and pass tests after each step (use stubs if needed)
3. **Full test suite**: `make test` must pass before moving to next step
4. **Step files**: Each step tracked in `execute/step<N>.md` (not checked in)

## Steps Overview

| Step | Description | Status | Commit |
|------|-------------|--------|--------|
| 1 | | pending | |
| 2 | | pending | |
| 3 | | pending | |

## How to Execute

```bash
# For each step:
1. Read execute/step<N>.md
2. Implement the step
3. Run verification: make test
4. Commit with message: "<issue>: step <N> - <description>"
5. Update step<N>.md with status and results
6. Move to next step
```

## Step Files

Step files are created in `.spec/{{ISSUE_ID}}/execute/` and are gitignored.
Delete the execute folder when done if desired.

---

## Final Summary

_Completed after all steps are done_

### Completion Status

- [ ] All steps completed
- [ ] All tests passing
- [ ] Ready for review

### Step Results

| Step | Result | Notes |
|------|--------|-------|
| 1 | | |
| 2 | | |
| 3 | | |

### Deviations from Plan

_Document any changes from the original plan_

### Learnings

_What worked well, what didn't_

---

<details>
<summary>Prompt Log</summary>

```yaml
- model: {{MODEL}}
  date: {{DATE}}
  type: execution-start
  prompt: |
    {{PROMPT}}
```

</details>

# Step {{STEP_NUMBER}}: {{STEP_TITLE}}

> **Issue**: {{ISSUE_ID}}
> **Status**: pending | in-progress | completed | blocked
> **Model**: {{MODEL}}
> **Started**: {{DATE}}
> **Completed**: 

## Objective

_What this step accomplishes_

## Prerequisites

- [ ] Previous step completed
- [ ] Tests passing before starting

## Implementation

### Files to Modify

- `path/to/file.py` - description of change

### Changes

_Detailed description of what to implement_

## Verification

### Test Cases

- [ ] Test case 1: _description_
- [ ] Test case 2: _description_

### Manual Verification

```bash
# Commands to manually verify this step works
```

### Full Test Suite

```bash
make test
```

## Non-Breaking Constraint

_How this step maintains a working product (stubs, feature flags, etc.)_

## Results

### Test Output

```text
# Paste test results here
```

### Commit

- **SHA**: 
- **Message**: 

### Notes

_Any observations, issues encountered, or deviations_

---

<details>
<summary>Prompt Log</summary>

```yaml
- model: {{MODEL}}
  date: {{DATE}}
  type: step-execution
  step: {{STEP_NUMBER}}
  prompt: |
    {{PROMPT}}
```

</details>

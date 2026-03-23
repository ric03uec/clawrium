# Plan: {{TITLE}}

> **Status**: draft | ready | in-progress | complete
> **Issue**: #{{ISSUE}}
> **Spec**: [spec.md](./spec.md)
> **Created**: {{DATE}}
> **Author**: {{AUTHOR}}

## Objective

One sentence: what this plan delivers.

## Prerequisites

- [ ] Spec approved
- [ ] Dependencies resolved
- [ ] Environment ready

## Tasks

### Task 1: {{TASK_NAME}}

**Files**: `path/to/file1.py`, `path/to/file2.py`

**Read First**:
- `existing/file.py` - understand current pattern

**Action**:
1. Step 1 with specific instructions
2. Step 2 with code example if needed
3. Step 3

**Verification**:
```bash
make test
# Expected: All tests pass
```

**Acceptance**:
- [ ] File exists with expected content
- [ ] Tests pass
- [ ] No lint errors

---

### Task 2: {{TASK_NAME}}

**Files**: `path/to/file.py`

**Read First**:
- Previous task output

**Action**:
1. Step 1
2. Step 2

**Verification**:
```bash
make test && make lint
```

**Acceptance**:
- [ ] Criteria met

---

## Final Verification

```bash
# Run full verification
make test && make lint
```

## Success Criteria

All acceptance criteria from spec.md are met:
- [ ] Criterion 1
- [ ] Criterion 2

---

<details>
<summary>Prompt Log</summary>

```yaml
- model: {{MODEL}}
  date: {{DATE}}
  type: plan-creation
  prompt: |
    {{PROMPT}}
```

</details>

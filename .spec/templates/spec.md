# Spec: {{TITLE}}

> **Status**: draft | review | approved | implemented | rejected
> **Issue**: #{{ISSUE}}
> **Created**: {{DATE}}
> **Author**: {{AUTHOR}}

## Summary

One sentence: what this does.

## Motivation

What's broken now. Who has this problem. Why fix it.

## Design

### Data Model

What data exists? How is it organized? What are the access patterns?

Get this right and the code writes itself. If the algorithm is complex, the data structure is probably wrong. (Pike: "Data dominates.")

### Interface

```python
# Concrete example - what users will actually type/call
```

### Output

```
# What users will actually see
```

### Files to Modify

| File | Change |
|------|--------|
| `src/clawrium/...` | What changes |
| `tests/...` | What tests |

## Acceptance Criteria

Testable with commands. Not vague goals.

- [ ] Criterion 1 (verify: `command to run`)
- [ ] Criterion 2 (verify: `command to run`)
- [ ] `make test` passes

## Alternatives Considered

| Alternative | Problem |
|-------------|---------|
| Simpler approach X | Why it doesn't work |
| Fancier approach Y | Why it's overkill |

## Unresolved Questions

- [ ] Question that blocks implementation?

## Dependencies

- Depends on: (none | #issue)
- Blocks: (none | #issue)

---

<!--
## Spec Writing Guide

A good spec makes the right solution obvious. A bad spec makes any solution look reasonable.

### Start with the Data
Before algorithms or APIs: what's the right data structure? If you're struggling with complex logic, the data structure is probably wrong.

### Design for the Actual Problem
- What's the actual n? (Pike: "n is usually small")
- Is brute force good enough? (Thompson: "When in doubt, use brute force")
- Red flags: "This will be useful when...", "For flexibility..."

### Eliminate Special Cases  
Good design makes edge cases disappear. If you need `--force`, `--skip-validation`, the abstraction is wrong.

### Make it Debuggable
- What gets logged?
- Is there a dry-run mode?
- How do you inspect state after failure?

### Keep it Simple
Every feature is a liability. Can you explain the design in 30 seconds?

### Don't Break Existing Users
If you must break compatibility: document what breaks, why it's worth it, migration path.

### Writing Style
Direct. Precise. No fluff. No jargon. No hedging. No expletives.
-->

<details>
<summary>Prompt Log</summary>

```yaml
- model: {{MODEL}}
  date: {{DATE}}
  type: spec-creation
  prompt: |
    {{PROMPT}}
```

</details>

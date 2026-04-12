---
description: Create phased execution plan with entry/exit criteria
---

Create a phased execution plan for GitHub issue $ARGUMENTS.

Steps:
1. Fetch the issue with existing plan from comments
2. Analyze complexity:
   - Simple (< 3 files): single-phase
   - Moderate (3-8 files): 2-3 phases
   - Complex (8+ files): multi-phase with subtasks
3. For each phase, define:
   - Entry criteria (what must be true to start)
   - Exit criteria (tests, validation rules)
   - Dependencies (prerequisite phases)
   - Files affected
   - Complexity estimate
4. Post scaffolding as a comment
5. Create subtask issues if multi-phase
6. Update labels: `planned` → `ready`

Ordering rules:
- Foundation phases first (schemas, models)
- Core logic second (services, business rules)
- Integration third (APIs, handlers)
- Presentation last (UI, docs)

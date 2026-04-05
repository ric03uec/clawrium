---
description: Run tests, lint, and validate current changes
argument-hint: ""
---

# Verification

Run all verification checks to ensure code quality.

## Instructions

1. **Run Tests**:
   ```bash
   make test
   ```
   - All tests must pass
   - Note any failures with details

2. **Run Linter**:
   ```bash
   make lint
   ```
   - All lint checks must pass
   - Fix any issues found

3. **Check Coverage** (optional):
   ```bash
   make test-cov
   ```
   - Review coverage for new code
   - Ensure critical paths are tested

4. **Report Results**:
   ```
   ## Verification Results

   ### Tests
   - Status: PASS/FAIL
   - Details: <summary>

   ### Lint
   - Status: PASS/FAIL
   - Details: <summary>

   ### Coverage
   - Status: <percentage>
   - New code coverage: <assessment>
   ```

5. **If Failures**:
   - Fix issues
   - Re-run verification
   - Iterate until all checks pass

## Notes

- This is a local operation - no prompt logging to GitHub
- Must pass before creating PRs
- Use this after making changes, before committing
- Can be run multiple times during development

---
name: itx:verify
description: Run tests, lint, and validate current changes
argument-hint: ""
---
name: itx:verify

# Verification

Run all verification checks to ensure code quality.

## Instructions

1. **Load Configuration**:
   ```bash
   ITX_CONFIG="$(git rev-parse --show-toplevel)/.claude/itx-config.json"
   if [ -f "$ITX_CONFIG" ]; then
     TEST_CMD=$(jq -r '.build.test_command // "make test"' "$ITX_CONFIG")
     LINT_CMD=$(jq -r '.build.lint_command // "make lint"' "$ITX_CONFIG")
     COV_CMD=$(jq -r '.build.coverage_command // "make test-cov"' "$ITX_CONFIG")
   else
     TEST_CMD="make test"
     LINT_CMD="make lint"
     COV_CMD="make test-cov"
   fi
   ```

2. **Run Tests**:
   ```bash
   $TEST_CMD
   ```
   - All tests must pass
   - Note any failures with details

3. **Run Linter**:
   ```bash
   $LINT_CMD
   ```
   - All lint checks must pass
   - Fix any issues found

4. **Check Coverage** (optional):
   ```bash
   $COV_CMD
   ```
   - Review coverage for new code
   - Ensure critical paths are tested

5. **Report Results**:
   ```
   ## Verification Results

   ### Tests
   - Command: <test command>
   - Status: PASS/FAIL
   - Details: <summary>

   ### Lint
   - Command: <lint command>
   - Status: PASS/FAIL
   - Details: <summary>

   ### Coverage
   - Status: <percentage>
   - New code coverage: <assessment>
   ```

6. **If Failures**:
   - Fix issues
   - Re-run verification
   - Iterate until all checks pass

## Configuration

Customize build commands in `.claude/itx-config.json`:

```json
{
  "build": {
    "test_command": "npm test",
    "lint_command": "npm run lint",
    "coverage_command": "npm run test:coverage"
  }
}
```

**Defaults** (no config):
- `test_command`: `make test`
- `lint_command`: `make lint`
- `coverage_command`: `make test-cov`

## Notes

- This is a local operation
- Must pass before creating PRs
- Use this after making changes, before committing
- Can be run multiple times during development

## Prompt Logging

**REQUIRED**: Append prompt log to `.itx/<N>/02_VERIFY.md`.

See [AGENTS.md](../../../AGENTS.md#prompt-logging-standard) for format specification.

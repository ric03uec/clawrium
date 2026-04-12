---
name: itx:note
description: Quick capture of ideas or observations to NOTES.md
argument-hint: "[text]"
---
name: itx:note

# Quick Note

Capture a quick note, idea, or observation to NOTES.md.

## Instructions

1. **Get Note Content**:
   - If text argument provided, use it
   - If not, summarize the relevant insight from conversation

2. **Format Note**:
   ```markdown
   ## <timestamp>

   <note content>

   ---
   ```

3. **Append to NOTES.md**:
   - Create file if it doesn't exist
   - Append to end of file
   - Use ISO date format for timestamp

4. **Confirm**: Report that note was saved

## File Location

Notes are saved to `NOTES.md` in the project root.

## Example

Input: `/itx:note The registry validation should check semver compatibility`

Output in NOTES.md:
```markdown
## 2026-04-04

The registry validation should check semver compatibility

---
name: itx:note
```

## Notes

- This is a local operation only
- No prompt logging to GitHub (local file)
- Use for quick capture during development
- Review NOTES.md periodically to process captured ideas

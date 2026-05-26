# Issue #458: Add Copy to clipboard button for memory files

## Problem

Users viewing memory files in the GUI must manually select-all and copy content. A dedicated copy button in the Memory tab would reduce friction for pasting into chats, scripts, or other tools.

## Approach

- Add a `copied` state variable to track visual feedback for the copy button
- Insert a Copy button in the file content header (lines 108-139) next to the existing Edit button
- Use `navigator.clipboard.writeText()` to copy content to clipboard, matching the existing pattern in `agent-header.tsx:162`
- Provide visual feedback: button label flips to "Copied" for ~1.5-2 seconds, then reverts
- Support both view and edit modes: copy `editContent` if editing, otherwise `fileContent?.content`
- Disable the button when there is no content to copy (empty string or undefined)
- Match existing button styling: `Button` component with `variant="secondary"` and `size="sm"`

## Files Touched

- `gui/src/components/agent-detail/memory-tab.tsx` — add copy button and state
- `gui/src/components/agent-detail/memory-tab.test.tsx` — new test file covering copy action

## Phases

### Phase 1: Add Copy Button

**Entry:** memory-tab.tsx loads with Edit/Save/Cancel buttons only
**Exit:** Copy button visible, functional, with visual feedback

**Steps:**
1. Add `const [copied, setCopied] = useState(false)` state at line 16
2. Add `handleCopy` async function that:
   - Gets content to copy: `isEditing ? editContent : fileContent?.content`
   - Calls `navigator.clipboard.writeText(content)`
   - Sets `copied = true`, then resets to `false` after 1500ms
   - Catches clipboard API failures (non-secure contexts)
3. Insert Copy button in the button group (line 108) with:
   - `variant="secondary"`, `size="sm"`
   - `onClick={handleCopy}`
   - `disabled` when content is empty/undefined
   - Label: `{copied ? "Copied" : "Copy"}`
4. Position: Copy button appears before the Edit button (left-to-right: Copy, Edit)

### Phase 2: Unit Tests

**Entry:** memory-tab.test.tsx does not exist
**Exit:** Tests cover copy action in both view and edit modes

**Steps:**
1. Create `gui/src/components/agent-detail/memory-tab.test.tsx`
2. Mock `@tanstack/react-query` hooks (`useQuery`, `useMutation`, `useQueryClient`)
3. Mock `navigator.clipboard.writeText` using `vi.fn()`
4. Test cases:
   - Copy button is visible when a file is selected
   - Clicking Copy calls `navigator.clipboard.writeText` with `fileContent?.content`
   - Button label changes to "Copied" after successful copy
   - Button label reverts to "Copy" after timeout
   - Copy button copies `editContent` when in edit mode
   - Copy button is disabled when content is empty
   - Clipboard API errors are caught gracefully

### Phase 3: Verification

**Entry:** Code changes complete
**Exit:** `make test` and `make lint` pass

**Steps:**
1. Run `make lint` in worktree root
2. Run `make test` in worktree root
3. Fix any issues

## Risks / Unknowns

- **Clipboard API in non-secure contexts:** Already handled in `agent-header.tsx` with try/catch. Apply same pattern here.
- **Edit mode integration:** Issue mentions optional support for copying during edit. Plan includes this — copy `editContent` if `isEditing`, otherwise `fileContent?.content`.
- **Test coverage:** No existing test file for memory-tab.tsx. New test file will follow patterns from `skills-tab.test.tsx`.

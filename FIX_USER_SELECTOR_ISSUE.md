# Fix: User-Provided Selectors Not Working After Manual Submission

## Problem Statement
After a user provides a selector manually on the website and clicks "Submit Selector And Resume", the system would fail with a FAILED status instead of using the provided selector to complete the step.

## Root Causes Identified

### 1. **Selector Not Prioritized for Click Operations**
When a user provides a direct Playwright selector like `button[class*='submit']` or `page.locator(...)`, the system was treating it the same as template keys and profile patterns. For "click" operations, the code had logic to prioritize "strong selectors" (with aria-label, data-testid, etc.), but user-provided selectors without these markers were not being prioritized.

**Original Code (Line ~2252-2257):**
```python
if step_type == "click" and not alias_key and self._prefer_direct_click_selector(selector):
    deduped = self._dedupe([selector] + candidates)
elif step_type == "type" and not alias_key:
    deduped = self._dedupe([selector] + candidates)
else:
    deduped = self._dedupe(candidates)
```

**Issue:** Only click selectors with "strong markers" were prioritized. User-provided selectors like `button.submit-btn` or `button[onclick="..."]` might not be tried first.

### 2. **Automated Recovery Overwrites User Choice**
When a user-provided selector failed, the system would attempt automated recovery again, potentially finding a different selector and overwriting the user's choice. This could lead to confusion or the system asking for a selector again.

**Original Code (Line ~1163-1175):**
```python
if self._is_selector_error(step, exc) and self._should_attempt_automated_recovery(step, exc):
    # ... automated recovery attempts ...
    if recovery_fails:
        # ask user again
```

**Issue:** No check for `step.provided_selector` to know that the user already chose a selector.

## Solutions Implemented

### Fix 1: Always Prioritize Direct Selectors for Click and Type Operations

**Changed Code:**
```python
# Always prioritize direct selectors (non-templates) for click and type operations
# This ensures user-provided selectors are tried first
if not alias_key and step_type in ("click", "type"):
    # For direct (non-template) selectors, try them first
    deduped = self._dedupe([selector] + candidates)
else:
    deduped = self._dedupe(candidates)
```

**Benefit:** User-provided selectors are now always tried first as candidates for click and type operations, regardless of whether they contain "strong markers".

### Fix 2: Skip Automated Recovery When User Already Provided Selector

**Changed Code:**
```python
# Check if this is a selector-related error and we should try automated recovery
# BUT: if the user already provided a selector (step.provided_selector), don't try recovery again
# Just fail so the user knows the selector they provided didn't work
if self._is_selector_error(step, exc) and self._should_attempt_automated_recovery(step, exc) and not step.provided_selector:
    # Try automated recovery
    ...
else:
    # Just fail with clear message
    if step.provided_selector:
        step.message = f"Step failed with the selector you provided: {step.provided_selector}"
```

**Benefit:** 
- Respects user's explicit selector choice
- Doesn't overwrite with automated recovery
- Provides clear feedback when user selector fails

## How It Works Now

### First Execution (Automatic Recovery)
```
1. Step fails with timeout/selector error
2. System attempts 4-stage automated recovery:
   - Try memory candidates
   - Try live page candidates
   - Try selector variants
   - Try fallback patterns
3. If recovery succeeds → Use found selector and retry step
4. If recovery fails → Ask user for selector
```

### After User Provides Selector (Resume)
```
1. User submits selector via UI
2. apply_manual_selector_hint stores:
   - step.input["selector"] = user_selector
   - step.provided_selector = user_selector
   - step.status = pending
3. execute() resumes
4. _execute_step() is called
5. _dispatch_step() gets selector from step.input
6. _selector_candidates() PRIORITIZES direct selector:
   - step_type check: is it "click" or "type"?
   - alias_key check: is it a template? (no, for direct selectors)
   - Result: selector is first in candidates list ✓
7. _run_with_selector_fallback() tries selector FIRST
8. If selector works → SUCCESS ✓
9. If selector fails AND provided_selector is set → FAIL (no automated recovery)
```

## Testing

Verification tests created in `test_user_selector_fix.py` confirm:
- ✅ Templates ({{selector.name}}) are correctly identified
- ✅ Direct selectors are correctly identified as non-templates  
- ✅ Non-template selectors will be prioritized for click/type steps
- ✅ provided_selector flag prevents re-asking for recovery
- ✅ Error messages are more informative when user selector fails

## Impact on User Experience

### Before Fix
```
User flow:
1. System asks for selector
2. User provides: "button.save"
3. User clicks "Submit Selector And Resume"
4. System shows: FAILED status
5. User confused - didn't work
```

### After Fix
```
User flow:
1. System asks for selector
2. User provides: "button.save"
3. User clicks "Submit Selector And Resume"
4. System tries "button.save" FIRST (not after other candidates)
5. Result: SUCCESS ✓ or clear error message ✗
```

## Configuration

No configuration changes needed. The fix is automatically applied to all executions.

## Files Modified

- `backend/app/runtime/executor.py`
  - Line ~2252: Changed selector prioritization logic
  - Line ~1166: Added check for `step.provided_selector`
  - Improved error messaging for failed user selectors

## Testing the Fix

To verify the fix works in your environment:

```bash
# Run verification test
python test_user_selector_fix.py

# Expected output:
# ✅ All verification tests passed!
# Key improvements:
#   1. User-provided direct selectors are now prioritized first
#   2. Selector is tried before profile candidates and variants
#   3. If user selector fails, no re-asking for recovery
#   4. More informative error messages when user selector fails
```

## Next Steps

1. Test with a live workflow that requires manual selector input
2. Verify that user-provided selectors are used and remembered
3. Check that error messages are helpful when selectors fail
4. Monitor logs to see the prioritization in action

## Related Issues

- User reported: "System fails after user provides selector manually"
- Root cause: Selector not prioritized + automated recovery interfering
- This fix ensures user choice is respected and tried first

# Tekno Phantom - Selector & Step Execution Improvements

## Changes Made

### 1. Enhanced Selector Memory & Finding Strategy

**Problem**: System was asking user for selectors too early instead of trying automated methods first.

**Solution Implemented**:
- Added `selector_finder.py` with `SelectorFindingStrategy` class
- Created multi-stage automated selector finding:
  1. **Stage 1**: Check selector memory for previous successful runs
  2. **Stage 2**: Use profile candidates (predefined patterns)
  3. **Stage 3**: Live page inspection (visual element matching)
  4. **Stage 4**: Selector variants generation (dynamic variants)
  5. **Only then**: Ask user for manual selector

### 2. Improved Selector Error Recovery in Executor

**Changes in `executor.py`**:

- Added `_is_selector_error()` - Detects if an error is selector-related
- Added `_should_attempt_automated_recovery()` - Determines if we should try recovery
- Added `_attempt_automated_selector_recovery()` - Orchestrates automated recovery:
  - Tries memory candidates first (highest priority)
  - Falls back to live page inspection
  - Uses selector variants as last resort
  - Remembers any discovered selectors for future use
- Added `_test_selector()` - Quick validation of selector on current page

### 3. Step Execution Flow Fix

**Problem**: Some steps were being skipped during execution.

**Improvement**: 
- Modified `_execute_step()` exception handling to prioritize automated recovery over user input
- Steps now retry automatically before asking user
- Better error classification and handling

### 4. Selector Memory Integration

**Enhanced Features**:
- When user provides a selector, it's now automatically remembered
- Semantic selector memory keys now support:
  - Full text matches
  - Individual words
  - First-two-words combinations
  - Partial prefix matches
  - Compact versions (no spaces)
  - Multiple lookup strategies for flexibility
  
### 5. Live Page Selector Generation

**Enhanced `_selectors_from_snapshot_item()`**:
- More comprehensive selector generation from page snapshots
- ID-based selectors with tag combinations
- Test ID selectors with partial matches
- Class-based selectors (single and combined)
- Extended aria-label variants
- Multiple text-based options
- Role-based selectors

### 6. Improved Scoring Algorithm

**Enhanced `_snapshot_match_score()`**:
- Higher specificity bonuses for reliable selectors
- Step-type specific bonuses
- Better language/dropdown intent detection
- Penalties for generic elements
- Non-negative score guarantee

### 7. Better Selector Variants

**Enhanced `_derive_selector_variants()`**:
- Button/link type conversions
- Input field attribute variants
- Complex selector decomposition
- Amazon-specific patterns
- Multiple fallback options

## Workflow for Selector Issues

### When a step fails to find a selector:

1. **Automatic Recovery Attempts**:
   - Try selector from memory for same domain (previous runs)
   - Try selector from global memory (other domains)
   - Try semantic memory keys (text-based lookups)
   - Try live page inspection with improved matching
   - Try derived selector variants

2. **Only If All Auto Methods Fail**:
   - Ask user for a Playwright selector
   - User provides selector
   - System remembers it for all future runs
   - Retry step with user's selector
   - Future runs will use remembered selector (no user input needed)

## Testing & Verification

To verify the improvements:

1. **Run a multi-step test**:
   ```
   # Ensure all steps are parsed correctly
   # Steps should not be skipped
   # Each step should execute in order
   ```

2. **Test selector memory usage**:
   ```
   # Run first test - some steps may ask for selectors
   # Run second test on same domain - selectors should be remembered
   # No user input needed for second run
   ```

3. **Test automated recovery**:
   ```
   # Modify the page slightly (CSS class change, text update)
   # Step should automatically find the element using live inspection
   # No user input needed
   ```

## Files Modified

- `backend/app/runtime/executor.py` - Enhanced step execution and selector recovery
- `backend/app/runtime/selector_memory.py` - Improved semantic keys
- `backend/app/runtime/selector_finder.py` - New multi-stage finder (NEW)

## Benefits

1. **Reduced User Input**: System now works harder before asking user
2. **Better Automation**: Automated recovery tries multiple strategies
3. **Memory Across Runs**: Selectors remembered and reused between runs
4. **Flexible Matching**: Multiple ways to find elements (live inspection, semantics, variants)
5. **Progressive Improvement**: Each successful discovery improves future runs
6. **No Skipped Steps**: All parsed steps execute properly

## Configuration

Settings already in place (from config.py):
- `selector_memory_enabled: bool = True`
- `selector_memory_backend: str = "sqlite"` (persistent storage)
- `selector_memory_max_candidates: int = 5`
- `selector_recovery_enabled: bool = True`
- `selector_recovery_attempts: int = 1`

These are all enabled by default for optimal performance.

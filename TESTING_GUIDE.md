# Quick Start Guide - Improved Selector & Step Execution

## What's Fixed

### 1. **Steps No Longer Skipped**
   - All parsed instruction steps now execute in proper sequence
   - Improved step tracking prevents step loss
   - Each step waits for completion before next one starts

### 2. **Selectors Remembered Between Runs**  
   - First run on a domain: Some selectors may need manual input
   - Subsequent runs: Selectors automatically remembered and reused
   - No repeated user prompts for same selectors

### 3. **Automated Selector Finding**
   - System tries HARD before asking user:
     - Checks selector memory (previous runs)
     - Inspects live page visually
     - Generates selector variants
     - Uses LLM-generated candidates
   - Only asks user when ALL automated methods fail

### 4. **User-Provided Selectors Remembered**
   - When you provide a selector, it's automatically stored
   - Future runs use stored selector without asking again
   - Works across different domains (with memory separation)

## Testing the Improvements

### Test 1: Multi-Step Instructions
```
Run a complex workflow with multiple steps:
✓ All steps should execute
✓ No steps should be skipped
✓ Each step should complete before next starts
✓ Check browser shows correct actions
```

### Test 2: Selector Memory (First Run)
```
1. Start a fresh run with new workflow
2. Some steps may ask for selectors (first time)
3. Provide a Playwright selector
4. Step completes successfully
5. Selector is now remembered
```

### Test 3: Selector Memory (Second Run) 
```
1. Run same workflow again on same domain
2. Previous selectors should be used automatically
3. No user prompts for same elements
4. Workflow completes with 0 user interactions
```

### Test 4: Automated Recovery
```
1. In browser console, change element ID/class:
   document.getElementById('login-btn').id = 'submit-btn'
2. System should automatically find element via alternate methods
3. No user input needed
4. Step completes successfully
```

### Test 5: Selector Variants  
```
1. Try step with original selector that fails
2. System tries variations:
   - Different selector types (ID→xpath, etc)
   - Parent/child relationships
   - Text-based selectors
   - ARIA labels
3. One variant should work automatically
```

## Running Tests Manually

### Terminal 1: Start Brain
```powershell
cd "C:\Users\Teknotrait\Desktop\Tekno-Phantom-agent\brain"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8090
```

### Terminal 2: Start Backend  
```powershell
cd "C:\Users\Teknotrait\Desktop\Tekno-Phantom-agent\backend"
.\.venv\Scripts\python.exe run_server.py
```

### Terminal 3: Start Frontend
```powershell
cd "C:\Users\Teknotrait\Desktop\Tekno-Phantom-agent\frontend"
npm run dev
```

### Terminal 4: Run Manual Tests
```powershell
cd "C:\Users\Teknotrait\Desktop\Tekno-Phantom-agent"

# Test 1: Parse structured instructions
python -c "
from backend.app.runtime.instruction_parser import parse_structured_task_steps

task = '''
1. Click on login button
2. Enter email admin@test.com
3. Enter password Test123
4. Click submit 
5. Verify success message
'''

steps = parse_structured_task_steps(task, max_steps=500)
print(f'Parsed {len(steps)} steps:')
for i, step in enumerate(steps, 1):
    print(f'  {i}. {step.get(\"type\")}: {step.get(\"selector\", step.get(\"url\", \"\"))}')
"

# Test 2: Check selector memory
python -c "
from backend.app.runtime.selector_memory import SqliteSelectorMemoryStore
from pathlib import Path

store = SqliteSelectorMemoryStore(Path('data/selector_memory.sqlite3'))

# Get some remembered selectors
for step_type in ['click', 'type']:
    for key in ['login_button', 'email', 'password']:
        candidates = store.get_candidates('', step_type, key, limit=3)
        if candidates:
            print(f'{step_type} {key}: {candidates[0]}')
"

# Test 3: Check automated recovery methods
python -c "
from backend.app.runtime.executor import AgentExecutor

methods_available = [
    '_is_selector_error',
    '_should_attempt_automated_recovery',
    '_attempt_automated_selector_recovery',
    '_test_selector',
    '_memory_candidates',
    '_live_page_selector_candidates',
    '_derive_selector_variants'
]

print('Available automated recovery methods:')
for method in methods_available:
    if hasattr(AgentExecutor, method):
        print(f'  ✓ {method}')
    else:
        print(f'  ✗ {method}')
"
```

## Understanding the Selector Finding Flow

```
When a step fails to find an element:

1. AUTOMATIC RECOVERY ATTEMPT
   ├─ Stage 1: Check selector memory
   │  └─ Looks for previous successful selectors on same domain
   ├─ Stage 2: Live page inspection
   │  └─ Analyzes current page to find matching elements
   ├─ Stage 3: Selector variants
   │  └─ Generates alternative selector patterns
   └─ Stage 4: LLM candidates
      └─ Uses AI to suggest selectors

2. IF AUTOMATIC RECOVERY FAILS:
   └─ ASK USER FOR SELECTOR
      ├─ Show which step is stuck
      ├─ User provides Playwright selector
      └─ REMEMBER IT for future runs

3. AFTER USER PROVIDES SELECTOR:
   ├─ Store in selector memory
   ├─ Store with domain context
   ├─ Store with step type context  
   └─ Future runs use stored selector automatically
```

## Detailed Features

### Selector Memory Storage
- **Database**: `data/selector_memory.sqlite3`
- **Storage Keys**: 
  - Domain (e.g., app.stag.dr-adem.com)
  - Step type (click, type, wait, etc)
  - Selector key (login_button, email, custom_selector)
  - Actual resolved selector
  - Score of success (increments per use)

### Semantic Memory Keys
For text-based selectors, system generates multiple lookups:
- Full text: `text::login to your account`
- Words: `text::login`, `text::your`, `text::account`
- First two: `text::login to`
- Prefix: `text::login to your`
- Compact: `text::logintoyouraccount`

This means finding "Login to Account" will match "LOGIN TO YOUR ACCOUNT", "Login to the Account", etc.

### Automatic Variants
For selector `button:has-text('Login')`, system generates:
- `a:has-text('Login')`
- `[role="button"]:has-text('Login')`
- `:text-is('Login')`
- `text=Login`
- `button[title*='Log']`
- And many more...

## Configuration

Settings in `backend/app/config.py`:
```python
selector_memory_enabled: bool = True            # Enable memory system
selector_memory_backend: str = "sqlite"         # Persistent storage
selector_memory_max_candidates: int = 5         # Return top 5 matches
selector_recovery_enabled: bool = True          # Enable auto recovery
selector_recovery_attempts: int = 1             # Number of retry attempts
```

All defaults are already optimized. No changes needed unless you want to tune behavior.

## Logging

To see detailed logs of selector finding:
1. Update `LOGGER.setLevel(logging.DEBUG)` in executor.py
2. Look for logs: "Stage 1", "Stage 2", "Stage 3", "Automated recovery"  
3. Each attempt is logged with what was tried and result

## Support

If selector finding still fails after all automated attempts:
- User is asked for a Playwright selector
- User can inspect element in browser and copy selector
- Selector is automatically remembered for all future runs

---

**Key Benefit**: 
After the first run through a workflow, subsequent runs on the same domain require ZERO manual selector input because all selectors are remembered and reused automatically.

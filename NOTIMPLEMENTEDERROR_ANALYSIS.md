# NotImplementedError Analysis - Autonomous Browser Automation

## Investigation Summary

After thorough analysis of the backend executor and step handling system, I found **no bare `NotImplementedError()` being raised in the application code**. However, the error is occurring during autonomous runs. This report documents potential sources and locations where it could manifest.

---

## Step Dispatch Flow (Main Entry Point)

**File:** `backend/app/runtime/executor.py`

### Main Orchestration Method
**Method:** `async execute(run_id: str)` (Lines 568-650)
- Called when autonomous execution starts
- Calls `_execute_autonomous_run()` if `run.execution_mode == "autonomous"`

### Step Execution Chain
```
execute()
  → _execute_autonomous_run() [Lines 715-841]
    → _execute_step() [Lines 1319-1417]
      → _dispatch_step() [Lines 1500-1656]
```

---

## Critical Method: `_dispatch_step()`

**Location:** `backend/app/runtime/executor.py` Lines 1500-1656

This method is the step type dispatcher. It handles:

| Step Type | Implementation | Location |
|-----------|---|---|
| `navigate` | Browser navigation to URL | Line 1520-1525 |
| `click` | Click element on page | Line 1526-1577 |
| `type` | Type text into element | Line 1578-1594 |
| `select` | Select dropdown value | Line 1595-1607 |
| `drag` | Drag and drop elements | Line 1608-1617 |
| `scroll` | Scroll page or element | Line 1618-1639 |
| `wait` | Wait for conditions | Line 1640-1673 |
| `handle_popup` | Handle dialog/popup | Line 1674-1688 |
| `verify_text` | Verify text on page | Line 1689-1709 |
| `verify_image` | Compare images | Line 1710-1732 |

### Error Handling
**Line 1656:** 
```python
raise ValueError(f"Unsupported step type: {step_type}")
```
- **NOT** NotImplementedError
- Raises ValueError for unrecognized step types

---

## Potential NotImplementedError Sources

### 1. **Missing Method in MCPPlaywrightBrowserMCPClient**
**File:** `backend/app/mcp/browser_client.py`

The MCP client class has implementations for all required methods:
- ✅ `click()`
- ✅ `type_text()`
- ✅ `select()`
- ✅ `drag_and_drop()`
- ✅ `scroll()`
- ✅ `wait_for()`
- ✅ `handle_popup()`
- ✅ `verify_text()`
- ✅ `verify_image()`
- ✅ `capture_screenshot()`
- ✅ `inspect_page()`

**Suspicious:** Check if a step type is generated that doesn't have an implementation.

### 2. **Brain Service Response**
**File:** `backend/app/brain/http_client.py`

**Method:** `async next_action()` (Lines 84-121)

The brain service returns action dict. If the brain returns:
```python
{"status": "action", "type": "<unimplemented_type>"}
```

Then `_dispatch_step()` would hit:
```python
raise ValueError(f"Unsupported step type: {step_type}")
```

**But:** If the brain service or MCP server raises NotImplementedError internally, it would bubble up.

### 3. **Step Generation from Structured Parsing**
**File:** `backend/app/runtime/plan_normalizer.py`

The `normalize_plan_steps()` function normalizes step types via `_normalize_type()`:
- Maps aliases like "open" → "navigate"
- Maps "fill" → "type"
- Maps "drag_and_drop" → "drag"

**Risk:** If an unrecognized/unmapped step type is passed, `_normalize_step()` returns `None`, which is filtered out. BUT if the brain generates a step with unhandled type, it bypasses normalization.

### 4. **Unknown Step Type from Brain**
**Location:** `backend/app/runtime/executor.py` Lines 775-803

In `_execute_autonomous_run()`:
```python
decision = await self._brain.next_action(...)
raw_action = decision.get("action")
normalized_steps = normalize_plan_steps(
    [raw_action],
    max_steps=1,
    default_wait_ms=self._settings.planner_default_wait_ms,
)
```

If:
1. Brain returns action with unknown `type` field
2. `normalize_plan_steps()` doesn't recognize it
3. The step is created anyway with the unrecognized type
4. `_dispatch_step()` processes it

`→` Would raise `ValueError`, not `NotImplementedError`

---

## Where NotImplementedError Likely Originates

### **Most Probable Source: Playwright MCP Server**

The `MCPPlaywrightBrowserMCPClient` (Lines 1536+) calls MCP tools:
```python
await self._call_tool(context, "browser_navigate", {"url": url})
await self._run_code(code)  # Execute JavaScript in browser
```

If the Playwright MCP server doesn't implement a tool, it may raise:
```
NotImplementedError()
```

**Check:** Look at `MCPPlaywrightBrowserMCPClient._run_code()` and `_call_tool()` methods.

### **Secondary Source: Brain LLM Service**

If the brain service endpoint returns raw NotImplementedError from an unimplemented endpoint.

---

## Step Types That Could Trigger This

Based on code analysis, these step types might have issues:

| Step Type | Potential Issue | Location |
|-----------|---|---|
| `drag` | Complex coordinate handling, multiple fallback strategies | Line 1507-1514 |
| `verify_image` | Image comparison requires PIL; baseline path handling | Line 1710-1732 |
| `scroll` | Selector resolution for "selector" target | Line 1618-1639 |
| Any custom type | Not in dispatch switch | Line 1656 |

---

## Exact Error Raising Locations

### Location 1: Unsupported Step Type
**File:** `backend/app/runtime/executor.py:1656`
```python
raise ValueError(f"Unsupported step type: {step_type}")
```
- Step type not recognized
- Would show as `ValueError`, not `NotImplementedError`

### Location 2: Unsupported Wait Condition
**File:** `backend/app/mcp/browser_client.py` (Local Playwright)
- Line ~1100: Raises `ValueError(f"Unsupported wait condition: {until}")`

### Location 3: Unsupported Text Match Type
**File:** `backend/app/mcp/browser_client.py`
- Raises `ValueError(f"Unsupported text match type: {match}")`

### Location 4: MCP Tool Call Failure
**File:** `backend/app/mcp/browser_client.py` (Lines 1536-1600+)

In `MCPPlaywrightBrowserMCPClient` class:
- `_call_tool()` method may fail if tool doesn't exist
- `_run_code()` method may fail if browser context is invalid

---

## Investigation Checklist

- [ ] Check if step type is `None` or empty string
- [ ] Add logging to `_dispatch_step()` to see what step types are being processed
- [ ] Check if brain service is returning unrecognized action types
- [ ] Verify MCP server has all required tools implemented
- [ ] Check Playwright MCP server logs for NotImplementedError
- [ ] Verify all browser methods are properly implemented
- [ ] Add try-catch wrapper around `_dispatch_step()` to capture the actual origin

---

## Recommended Fixes

### 1. Add Defensive Handling
**File:** `backend/app/runtime/executor.py` in `_dispatch_step()`

```python
async def _dispatch_step(self, run: RunState, raw_step: dict) -> str:
    step_type = raw_step.get("type")
    if not step_type:
        raise ValueError("Step type is missing")
    
    step_type = str(step_type).strip().lower()
    if not step_type:
        raise ValueError("Step type is empty")
    
    # ... rest of dispatch logic
```

### 2. Add Validation Before Dispatch
**File:** `backend/app/runtime/executor.py` in `_execute_autonomous_run()`

```python
if not isinstance(raw_action, dict) or not raw_action.get("type"):
    raise ValueError(f"Brain returned invalid action: {raw_action}")
```

### 3. Wrap MCP Calls with Error Context
**File:** `backend/app/mcp/browser_client.py`

```python
try:
    await self._call_tool(context, tool_name, params)
except NotImplementedError as e:
    raise RuntimeError(
        f"MCP tool '{tool_name}' not implemented on browser server"
    ) from e
except Exception as e:
    # provide context
```

---

## Summary Table

| Component | Status | Risk Level |
|-----------|--------|--|
| Step dispatch logic | ✅ Complete | 🟢 Low |
| Browser client methods | ✅ Complete | 🟢 Low |
| Brain integration | ⚠️ HTTP call | 🟡 Medium |
| MCP server | ❓ External | 🟡 Medium |
| Playwright MCP tools | ❓ External | 🟡 Medium |

---

**Note:** The bare `NotImplementedError()` with no message typically comes from:
- Abstract methods being called on Protocol types
- MCP server tools that aren't implemented
- External service errors being re-raised

The application code itself doesn't raise this error anywhere, suggesting it originates from external dependencies or services being called during autonomous execution.

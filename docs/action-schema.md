# Action Schema (Draft)

```json
{
  "run_name": "checkout validation",
  "start_url": "https://example.com",
  "steps": [
    { "type": "click", "selector": "button.login" },
    { "type": "type", "selector": "#email", "text": "user@example.com" },
    { "type": "wait", "until": "selector_visible", "selector": ".dashboard" },
    { "type": "verify_text", "selector": "h1", "match": "contains", "value": "Dashboard" }
  ]
}
```

## Step types
- `navigate`: `{ "url": "..." }`
- `click`: `{ "selector": "..." }`
- `type`: `{ "selector": "...", "text": "...", "clear_first": true }`
- `select`: `{ "selector": "...", "value": "..." }`
- `scroll`: `{ "target": "page|selector", "selector?": "...", "direction": "up|down", "amount": 600 }`
- `wait`: `{ "until": "timeout|selector_visible|selector_hidden|load_state", "ms?": 1000, "selector?": "...", "load_state?": "networkidle" }`
- `handle_popup`: `{ "policy": "accept|dismiss|close|ignore", "selector?": "..." }`
- `verify_text`: `{ "selector": "...", "match": "exact|contains|regex", "value": "..." }`
- `verify_image`: `{ "selector?": "...", "baseline_path?": "...", "threshold?": 0.05 }`
```

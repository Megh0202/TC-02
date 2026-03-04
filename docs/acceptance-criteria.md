# Acceptance Criteria (Phase 1)

## Run lifecycle
- User can create a run with one or more steps from UI
- Backend returns a run id and updates status per step
- Final run status is `completed`, `failed`, or `cancelled`

## Browser actions
- `click`: can click target element by selector
- `type`: can enter text to input/textarea/contentEditable
- `select`: can choose option from dropdown/selectors
- `scroll`: can scroll page or container up/down
- `wait`: can wait by condition (time, selector visible/hidden, page load)
- `popup`: can detect and handle modal/popup via defined policy

## Verification
- `verify_text`: pass/fail by exact/contains/regex rule
- `verify_image`: pass/fail by element screenshot or page region comparison

## Configuration
- Admin sets `LLM_MODE` on the brain service as `local` or `cloud`
- Backend references brain service via `BRAIN_BASE_URL`
- End user cannot change provider from task UI

## Auditability
- Each step stores: input, normalized command, status, start/end time, message, artifact refs

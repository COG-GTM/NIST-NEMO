# Testing NEMO Kiosk App

## Local Setup

1. The splash pad fixture provides test data including users, tools, and projects
2. Local settings are in `local_run/local_settings.py` with `ALLOW_CONDITIONAL_URLS = False` for off-campus testing
3. Start dev server: `DJANGO_SETTINGS_MODULE=local_run.local_settings python manage.py runserver 0.0.0.0:8000`
4. Auth uses `RemoteUserAuthenticationBackend` — set `REMOTE_USER` header to authenticate

## Test User

- Username: `captain` (id=1, badge=1, staff=True, superuser=True)
- Must have kiosk permission (`NEMO.kiosk`) — may need to add via Django ORM:
  ```python
  from django.contrib.auth.models import Permission
  perm = Permission.objects.get(codename='kiosk')
  captain.user_permissions.add(perm)
  ```
- To make captain staff on a tool: set `tool.primary_owner = captain` and `captain.qualifications.add(tool)`

## Kiosk Navigation (AJAX-based)

The kiosk is a single-page app at `/kiosk/` that loads content via AJAX. It does NOT use standard page navigation.

### Badge Scanning
- The kiosk uses a `BadgeReader` JS class that captures keypresses
- To simulate badge scan via Playwright: call `page.evaluate('send_badge_number("1")')` directly
- Typing digits + Enter via keyboard may not work depending on badge reader config (send_key/record_key)

### Page Flow
1. `/kiosk/` — Badge scan page
2. Badge scan → AJAX loads choices (tool categories)
3. Click category → AJAX loads tools in category
4. Click tool → AJAX loads tool information
5. "Report a problem" button → AJAX POST loads report form
6. Submit report → AJAX POST saves task

### Key URLs (all require POST except choices)
- `/kiosk/choices/` — GET with badge_number param
- `/kiosk/tool_information/<tool_id>/<user_id>/<back>/` — GET
- `/kiosk/tool_report_problem/<tool_id>/<user_id>/<back>/` — POST only (405 on GET)
- `/kiosk/report_problem/` — POST to submit report
- `/kiosk/enable_tool/` — POST
- `/kiosk/disable_tool/` — POST

## Testing with Playwright via CDP

Connect to existing Chrome: `p.chromium.connect_over_cdp("http://localhost:29229")`

### Important Notes
- Set `REMOTE_USER` header: `await page.set_extra_http_headers({"REMOTE_USER": "captain"})`
- The kiosk has a virtual keyboard that pops up when filling textareas via Playwright's `.fill()`. Click "Accept" to close it, or use the computer tool to type directly.
- For API-level tests (enable_tool, disable_tool, create_task), use `page.request.post()` with CSRF token from cookies
- Get CSRF token: `[c['value'] for c in await context.cookies() if c['name'] == 'csrftoken'][0]`

## Test Patterns

### Testing ALLOW_CONDITIONAL_URLS
- Set `ALLOW_CONDITIONAL_URLS = False` in local_settings.py
- Template-level: Check if UI elements are present/absent in DOM
- View-level: POST to endpoints and check response content for expected messages
- Form-level: Submit with force_shutdown and verify DB has force_shutdown=False

### Common Test Tools
- Tool 63: 4Wave Cluster Sputter (problem_shutdown_enabled=True, category: Physical Vapor Deposition)
- Task urgency values: -1 (Low), 0 (Normal), 1 (High) — NOT 1/2/3

## Running Unit Tests

```bash
python run_tests.py
```

Expect ~242 tests. There may be 1 pre-existing flaky timing test (test_delayed_logoff) that occasionally fails.

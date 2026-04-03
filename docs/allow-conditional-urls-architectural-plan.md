# Architectural Plan: Centralized `ALLOW_CONDITIONAL_URLS` Enforcement

## Executive Summary

The `ALLOW_CONDITIONAL_URLS` setting controls whether "on-campus-only" features (tool enable/disable, force shutdown, staff status, admin panel, REST API) are available. Today this setting is checked **independently in 9+ locations** across views, forms, templates, URL routing, and context processors. This distributed enforcement is fragile — any new feature touching tool control must remember to add the check in multiple places, and forgetting any one of them causes a bug (as we saw with the kiosk report-problem crash).

This plan proposes a **layered centralized enforcement architecture** that makes it structurally impossible to forget the check.

---

## 1. Current State: The Problem

### 1.1 All Current Enforcement Points

| # | Location | File | Line(s) | What It Does |
|---|----------|------|---------|--------------|
| 1 | URL routing | `urls.py` | 651 | Conditionally registers entire URL blocks (admin, API, enable/disable tool URLs) |
| 2 | `enable_tool` view | `views/tool_control.py` | 416–419 | Returns `HttpResponseBadRequest` if off-campus |
| 3 | `disable_tool` view | `views/tool_control.py` | 528–529 | Returns `HttpResponseBadRequest` if off-campus |
| 4 | `report_problem` (kiosk) | `apps/kiosk/views.py` | 654 | Blocks `force_shutdown` in kiosk task creation |
| 5 | `create` task (web) | `views/tasks.py` | 70 | Blocks `force_shutdown` in web task creation |
| 6 | Landing page | `views/landing.py` | 41–47 | Filters landing page choices to valid URLs |
| 7 | Staff status | `views/status_dashboard.py` | 295 | Returns `False` to hide staff availability |
| 8 | Template: tool_report_problem | `kiosk/templates/...` | — | Hides force_shutdown checkbox via `{% if allow_conditional_urls %}` |
| 9 | Template: tool_information | `kiosk/templates/...` | — | Hides enable/disable buttons via `{% if allow_conditional_urls %}` |
| 10 | Context processor | `context_processors.py` | — | Exposes `allow_conditional_urls` flag to all templates |

### 1.2 What's NOT Currently Protected

Even after the recent fixes, several UI elements are **still not gated**:

- **`tool_status.html` (web)**: The `force_shutdown` checkbox (line 1064), enable tool buttons (line 602), disable tool / "force user off" links (lines 450, 713) are shown regardless of `ALLOW_CONDITIONAL_URLS`
- **`status_dashboard/tools.html`**: The "force user off tool" icon (line 57) calls `disable_tool` URL directly
- **`maintenance.html`**: Enable/disable tool buttons in pending task details (lines 22, 29, 40)
- **`configuration_agenda.html`**: Enable/disable tool buttons (lines 70, 88, 97)

These all rely on the **view-level check** in `tool_control.py` as a backstop — but the user still sees the buttons and gets an unhelpful error message when clicking them.

### 1.3 Why This Is Fragile

```
Developer adds new tool-control feature
    → Must remember to check ALLOW_CONDITIONAL_URLS in:
        1. The view function
        2. The template (hide UI elements)
        3. The form (suppress dangerous fields)
        4. The URL routing (if it's a new endpoint)
    → Missing ANY of these = bug
    → No compiler/linter/test catches the omission
```

---

## 2. Proposed Architecture: Defense-in-Depth with Centralized Enforcement

The solution uses **three layers**, each independently sufficient to block unauthorized access. A developer only needs to opt-in to ONE layer for their feature to be protected; the other layers provide automatic coverage.

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: View Decorator (@conditional_urls_required)           │
│  ─── Blocks the entire view if ALLOW_CONDITIONAL_URLS is False  │
│  ─── Applied once per view; impossible to forget the check      │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2: Form-Level Guard (TaskForm.clean)                     │
│  ─── Automatically suppresses force_shutdown field              │
│  ─── Zero view-level code needed; works for ALL consumers       │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 3: Template Tag ({% if_conditional_urls %})              │
│  ─── Centralized UI gating via reusable template tag            │
│  ─── Single point of change for all template conditionals       │
└─────────────────────────────────────────────────────────────────┘
```

### Why Three Layers?

| Layer | What it prevents | Who benefits |
|-------|-----------------|--------------|
| **Decorator** | Direct HTTP requests (curl, bots, bookmarked URLs) bypassing UI | Backend developers |
| **Form guard** | `force_shutdown` being submitted even if UI somehow shows it | All code paths (web + kiosk + API) |
| **Template tag** | Users seeing buttons they can't use (bad UX, confusing errors) | Frontend developers, users |

---

## 3. Layer 1: The `@conditional_urls_required` Decorator

### 3.1 Implementation

Add to `NEMO/decorators.py`:

```python
from django.conf import settings
from django.http import HttpResponseBadRequest

def conditional_urls_required(view_func):
    """
    Decorator that blocks access to views that require ALLOW_CONDITIONAL_URLS.
    
    Use this on any view that provides "on-campus-only" functionality:
    tool enable/disable, force shutdown, staff status, etc.
    
    Example:
        @login_required
        @require_POST
        @conditional_urls_required
        @synchronized("tool_id")
        def enable_tool(request, tool_id, user_id, project_id, staff_charge):
            ...
    """
    from functools import wraps
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not settings.ALLOW_CONDITIONAL_URLS:
            return HttpResponseBadRequest(
                "This feature is only available on campus. "
                "We're working to change that! Thanks for your patience."
            )
        return view_func(request, *args, **kwargs)
    
    return wrapper
```

### 3.2 Where to Apply It

| View | File | Current Check | After |
|------|------|--------------|-------|
| `enable_tool` | `views/tool_control.py:413` | Manual `if` block (lines 416–419) | Replace with `@conditional_urls_required` |
| `disable_tool` | `views/tool_control.py:527` | Manual `if` block (lines 528–529) | Replace with `@conditional_urls_required` |
| `enable_tool` (kiosk) | `apps/kiosk/views.py:66` | None (relies on URL gating) | Add `@conditional_urls_required` |
| `disable_tool` (kiosk) | `apps/kiosk/views.py:137` | None (relies on URL gating) | Add `@conditional_urls_required` |

### 3.3 What This Replaces

**Before** (distributed, easy to forget):
```python
@login_required
@require_POST
@synchronized("tool_id")
def enable_tool(request, tool_id, user_id, project_id, staff_charge):
    if not settings.ALLOW_CONDITIONAL_URLS:
        return HttpResponseBadRequest(
            "Tool control is only available on campus. ..."
        )
    # ... 80 lines of business logic
```

**After** (centralized, declarative):
```python
@login_required
@require_POST
@conditional_urls_required        # ← one line, impossible to miss in code review
@synchronized("tool_id")
def enable_tool(request, tool_id, user_id, project_id, staff_charge):
    # ... 80 lines of business logic (no manual check needed)
```

### 3.4 Why a Decorator (Not Middleware)

A **middleware** approach was considered and rejected:

- **Middleware would require a URL allowlist/blocklist** mapping which URLs are "conditional." This is another distributed list that must be maintained, moving the problem rather than solving it.
- **The URL routing in `urls.py:651` already gates some URLs** from being registered at all. Middleware would need to handle the case where a URL doesn't even exist.
- **Decorators are already the established NEMO pattern** for access control (`@login_required`, `@staff_member_required`, `@administrator_required`, etc. in `decorators.py`). Following existing conventions means less friction for contributors.
- **Decorators are self-documenting** — you see the requirement right on the view function.

A middleware *could* be added as a **safety net** (see Section 6), but the decorator is the primary enforcement mechanism.

---

## 4. Layer 2: Form-Level Guard in `TaskForm`

### 4.1 The Problem

`force_shutdown` is the most dangerous "conditional" field. It can trigger tool lockout and interlock activation. Currently, suppressing it requires **every view that uses TaskForm** to remember to check `ALLOW_CONDITIONAL_URLS` after form validation.

Both `views/tasks.py:create` and `apps/kiosk/views.py:report_problem` independently check this. If someone creates a third path that saves a `TaskForm` (e.g., an API endpoint, a management command), they must remember to add the check.

### 4.2 Implementation

Modify `NEMO/forms.py` `TaskForm.clean()`:

```python
class TaskForm(ModelForm):
    # ... existing code ...
    
    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("force_shutdown") and not cleaned_data.get("safety_hazard"):
            if not self.user.is_staff:
                cleaned_data["force_shutdown"] = False
                # ... existing staff check ...
        
        tool = cleaned_data.get("tool")
        if tool and not tool.problem_shutdown_enabled and not is_staff_on_tool(self.user, tool):
            cleaned_data["force_shutdown"] = False
        
        # ──── NEW: Centralized ALLOW_CONDITIONAL_URLS enforcement ────
        if not settings.ALLOW_CONDITIONAL_URLS:
            if cleaned_data.get("force_shutdown"):
                from NEMO.views.customization import ApplicationCustomization
                site_title = ApplicationCustomization.get("site_title")
                raise ValidationError(
                    f"Tool control is only available on campus. "
                    f"You can't force a tool shutdown while using {site_title} off campus."
                )
        # ─────────────────────────────────────────────────────────────
        
        return cleaned_data
```

### 4.3 What This Enables

- **Remove the manual checks** in `views/tasks.py:70-78` and `apps/kiosk/views.py:654-662`
- **Any future view** that uses `TaskForm` gets the protection automatically
- **API endpoints** that accept task creation get the protection automatically
- The form becomes the **single source of truth** for what constitutes a valid task submission

### 4.4 Alternative: Suppress Silently vs. Raise Error

Two options:

| Approach | Behavior | When to Use |
|----------|----------|-------------|
| **Suppress** (`cleaned_data["force_shutdown"] = False`) | Silently ignore the flag | When UI already hides the checkbox (belt-and-suspenders) |
| **Raise** (`ValidationError`) | Return error to user | When the user somehow submitted `force_shutdown=true` (indicates UI bug or manual POST) |

**Recommendation**: **Raise a `ValidationError`**. Silent suppression masks bugs. If the UI is properly hiding the checkbox (Layer 3), this error should never be seen — and if it IS seen, it indicates a template bug that should be fixed.

---

## 5. Layer 3: Template Tag for UI Gating

### 5.1 The Problem

Currently, templates check `{% if allow_conditional_urls %}` using a context variable. This requires:
1. The context processor to expose the variable
2. Every template author to know the variable name
3. Every relevant UI element to be individually wrapped

### 5.2 Implementation

Add a custom template tag in `NEMO/templatetags/custom_tags_and_filters.py`:

```python
from django import template
from django.conf import settings

register = template.Library()

# ... existing tags ...

@register.simple_tag
def conditional_urls_enabled():
    """Returns True if ALLOW_CONDITIONAL_URLS is enabled (on-campus mode)."""
    return getattr(settings, 'ALLOW_CONDITIONAL_URLS', False)
```

Or even better, a **block tag** that hides its entire content:

```python
@register.tag('if_conditional_urls')
def do_if_conditional_urls(parser, token):
    """
    Template block tag that only renders content when ALLOW_CONDITIONAL_URLS is True.
    
    Usage:
        {% if_conditional_urls %}
            <button onclick="enable_tool(...)">Enable Tool</button>
        {% end_if_conditional_urls %}
    """
    nodelist = parser.parse(('end_if_conditional_urls',))
    parser.delete_first_token()
    return ConditionalUrlsNode(nodelist)

class ConditionalUrlsNode(template.Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist
    
    def render(self, context):
        if getattr(settings, 'ALLOW_CONDITIONAL_URLS', False):
            return self.nodelist.render(context)
        return ''
```

### 5.3 Template Usage

**Before** (requires context processor, easy to forget):
```html
{% if allow_conditional_urls %}
    <input name="force_shutdown" id="force_shutdown" type="checkbox" />
    Shut down the tool...
{% endif %}
```

**After** (self-contained, no context dependency):
```html
{% if_conditional_urls %}
    <input name="force_shutdown" id="force_shutdown" type="checkbox" />
    Shut down the tool...
{% end_if_conditional_urls %}
```

### 5.4 Where to Apply

These templates need the tag added around tool-control UI elements:

| Template | Elements to Gate |
|----------|-----------------|
| `tool_control/tool_status.html` | `force_shutdown` checkbox (line 1064), enable tool buttons (line 602), disable tool links (lines 450, 458, 713) |
| `tool_control/tool_control.html` | `enable_tool()` / `disable_tool()` JS functions |
| `status_dashboard/tools.html` | "Force user off" icon (line 57) |
| `maintenance/pending_task_details.html` | Enable/disable tool buttons (lines 22, 29, 40) |
| `configuration_agenda.html` | Enable/disable tool buttons (lines 70, 88, 97) |
| `kiosk/tool_report_problem.html` | `force_shutdown` checkbox (line 96) |
| `kiosk/tool_information.html` | Enable/disable tool links |
| `kiosk/kiosk.html` | `enable_tool()` / `disable_tool()` JS functions |

### 5.5 Context Processor: Keep or Remove?

**Keep it.** The `allow_conditional_urls` context variable is still useful for:
- Templates that need more nuanced conditional logic (e.g., showing an "on-campus only" message instead of just hiding)
- JavaScript that needs to check the flag dynamically
- Third-party or plugin templates that can't use custom tags

But it's no longer the **primary** gating mechanism — the template tag is.

---

## 6. Optional Safety Net: Audit Middleware

For defense-in-depth, add a lightweight middleware that **logs** (but doesn't block) requests to conditional URLs when `ALLOW_CONDITIONAL_URLS` is False. This catches cases where:
- A developer forgets the decorator
- A new URL is added without the decorator
- The URL routing in `urls.py:651` is modified incorrectly

```python
# NEMO/middleware.py

class ConditionalUrlsAuditMiddleware:
    """
    Safety-net middleware that logs warnings when conditional-only endpoints 
    are accessed while ALLOW_CONDITIONAL_URLS is False.
    
    This does NOT block requests (the decorator does that). It only logs
    so that missing decorators can be detected during testing.
    """
    CONDITIONAL_URL_NAMES = {
        'enable_tool', 'disable_tool',
        'enable_tool_from_kiosk', 'disable_tool_from_kiosk',
    }
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        if not settings.ALLOW_CONDITIONAL_URLS:
            url_name = resolve(request.path_info).url_name
            if url_name in self.CONDITIONAL_URL_NAMES:
                logger.warning(
                    f"Conditional URL '{url_name}' accessed while "
                    f"ALLOW_CONDITIONAL_URLS is False. "
                    f"Ensure @conditional_urls_required decorator is applied."
                )
        return self.get_response(request)
```

**This is optional** and primarily useful during development/testing to catch regressions. In production, the decorator and form guard handle enforcement.

---

## 7. Migration Plan

### Phase 1: Add Infrastructure (Non-Breaking)

1. **Add `@conditional_urls_required` decorator** to `NEMO/decorators.py`
2. **Add `{% if_conditional_urls %}` template tag** to `NEMO/templatetags/custom_tags_and_filters.py`
3. **Add form-level check** to `TaskForm.clean()` in `NEMO/forms.py`

*These additions don't change any behavior yet.*

### Phase 2: Apply Decorator to Views

4. **Apply `@conditional_urls_required`** to `enable_tool` and `disable_tool` in `views/tool_control.py`
5. **Remove the manual `if not settings.ALLOW_CONDITIONAL_URLS` blocks** from those views (the decorator handles it now)
6. **Apply `@conditional_urls_required`** to kiosk `enable_tool` and `disable_tool` in `apps/kiosk/views.py`

### Phase 3: Clean Up View-Level Checks

7. **Remove the manual `force_shutdown` check** from `views/tasks.py:create` (lines 70–78) — the form guard handles it
8. **Remove the manual `force_shutdown` check** from `apps/kiosk/views.py:report_problem` (lines 654–662) — the form guard handles it

### Phase 4: Apply Template Tags

9. **Wrap tool-control UI elements** in `{% if_conditional_urls %}` blocks across all templates listed in Section 5.4
10. **Keep the context processor** but document that the template tag is preferred

### Phase 5: Testing & Safety Net

11. **Add unit tests** that verify:
    - The decorator blocks requests when `ALLOW_CONDITIONAL_URLS = False`
    - The form raises `ValidationError` for `force_shutdown` when off-campus
    - The template tag hides content when off-campus
12. **Optionally add the audit middleware** (Section 6)

### Phase 6: Documentation

13. **Add a docstring or comment** in `settings.py` explaining the three-layer enforcement pattern
14. **Add a note** in the developer guide (if one exists) explaining:
    - "If you add a new view that should only work on-campus, add `@conditional_urls_required`"
    - "If you add a new template with tool-control UI, wrap it in `{% if_conditional_urls %}`"

---

## 8. What About `urls.py` Conditional Registration?

The existing pattern in `urls.py:651`:

```python
if settings.ALLOW_CONDITIONAL_URLS:
    urlpatterns += [
        path("api/", include(router.urls)),
        path("admin/", admin.site.urls),
        # ... ~140 lines of URL patterns
    ]
```

**Keep this as-is.** It's a valid first line of defense — URLs that don't exist can't be exploited. But it has limitations:

- It's an all-or-nothing block (you can't selectively gate individual URLs within the block)
- Some "conditional" operations (like `force_shutdown` on task creation) happen via URLs that ARE registered even when off-campus (the task creation URL itself is always valid)
- It doesn't protect against the kiosk having its own separately-registered URLs for enable/disable

The decorator + form guard approach handles all these edge cases.

---

## 9. What About `landing.py` and `status_dashboard.py`?

These two checks are **business logic**, not access control:

- `landing.py:41-47`: Filters landing page choices to exclude URLs that don't exist. This is a UX concern, not a security concern.
- `status_dashboard.py:295`: Hides staff availability when off-campus. This is a feature visibility decision.

**These should remain as direct `settings.ALLOW_CONDITIONAL_URLS` checks** because they're not gating an action — they're adjusting what information is displayed. They don't benefit from the decorator pattern (they're not blocking an entire view) or the form guard (they don't involve form submission).

However, they could be wrapped in a utility function for consistency:

```python
# NEMO/utilities.py (or a new NEMO/conditional_urls.py)

def is_on_campus():
    """Returns True if the system is running in on-campus mode."""
    return getattr(settings, 'ALLOW_CONDITIONAL_URLS', False)
```

This makes the intent clearer and provides a single function name to grep for when auditing.

---

## 10. Summary of Changes

| File | Change | Risk |
|------|--------|------|
| `NEMO/decorators.py` | Add `@conditional_urls_required` | Low (new code) |
| `NEMO/templatetags/custom_tags_and_filters.py` | Add `{% if_conditional_urls %}` tag | Low (new code) |
| `NEMO/forms.py` | Add `ALLOW_CONDITIONAL_URLS` check in `TaskForm.clean()` | Medium (changes form validation) |
| `NEMO/views/tool_control.py` | Apply decorator, remove manual checks | Low (behavior-preserving refactor) |
| `NEMO/apps/kiosk/views.py` | Apply decorator to enable/disable, remove manual force_shutdown check | Low |
| `NEMO/views/tasks.py` | Remove manual force_shutdown check (form handles it) | Low |
| 8+ templates | Wrap tool-control UI in `{% if_conditional_urls %}` | Medium (visual changes) |
| `NEMO/middleware.py` | (Optional) Add audit middleware | Low (logging only) |

### Total Estimated Effort

- **Phase 1 (Infrastructure)**: ~1 hour — adding decorator, template tag, form guard
- **Phase 2–3 (View cleanup)**: ~1 hour — applying decorator, removing manual checks
- **Phase 4 (Templates)**: ~2 hours — wrapping UI elements across 8+ templates
- **Phase 5 (Tests)**: ~2 hours — unit tests for all three layers
- **Phase 6 (Docs)**: ~30 minutes

**Total: ~6–7 hours of implementation work.**

---

## 11. Future-Proofing: How This Prevents the Next Bug

**Scenario**: A developer adds a new "restart_tool" view.

**Without this architecture**:
- Developer must know to check `ALLOW_CONDITIONAL_URLS` in the view
- Developer must know to hide the button in the template
- Developer must know to suppress the form field
- Missing any one of these → bug filed months later

**With this architecture**:
- Developer adds `@conditional_urls_required` to the view → done
- Code reviewer sees the decorator is missing → immediate feedback
- Even if they forget the decorator, the form guard catches `force_shutdown`
- Even if they forget the template tag, the decorator blocks the request
- The audit middleware logs a warning during testing

The key insight: **each layer independently prevents the bug**, so a developer only needs to remember ONE of the three to be safe.

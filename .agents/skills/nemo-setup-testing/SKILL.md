# NEMO Local Setup & Testing

## Overview
NEMO is a Django 4.2 laboratory logistics web application for managing tool reservations, access control, and maintenance.

## Local Development Setup

### Prerequisites
- Python 3.10+
- pip

### Steps
1. Install dependencies: `pip install -e ".[dev-tools]"`
2. Create `local_run/` directory with:
   - `local_settings.py` — Django settings pointing to local SQLite DB, media, and static paths
   - Run migrations: `DJANGO_SETTINGS_MODULE=local_settings PYTHONPATH=local_run python -m django migrate`
   - Load fixture data: `DJANGO_SETTINGS_MODULE=local_settings PYTHONPATH=local_run python -m django loaddata local_run/splash_pad.json`
3. Start dev server:
   ```bash
   DJANGO_SETTINGS_MODULE=local_settings PYTHONPATH=local_run REMOTE_USER=captain python -m django runserver 0.0.0.0:8000
   ```
4. The `REMOTE_USER=captain` env var auto-logs in as Captain Nemo (superadmin)

### local_settings.py Template
```python
import os
from NEMO.settings import *

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "sqlite.db"),
    }
}
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
```

## Running Tests
- Unit tests: `python run_tests.py` (runs 230 tests)
- Pre-commit hooks: `pre-commit run --all-files` (black + djlint)

## Splash Pad Fixture Data
The `local_run/splash_pad.json` fixture provides 400 demo objects:
- **Users**: captain (superadmin), professor (staff), ned, commander, conseil, tech
- **Tools**: 137 tools across categories (PECVD, Sinter, Dicing saw, Atomic Layer Deposition, etc.)
- **Areas**: 3 areas including Cleanroom
- **Consumables**: 11 items (Tweezers, wafer tray, gown, chemicals, etc.)
- **Active state**: Captain is using PECVD and logged into Cleanroom

## Golden-Path E2E Tests
Key pages to verify after setup:

1. **Landing Page** (`/`): Shows alerts, facility use, navigation icons, "Welcome, Captain", version footer
2. **Calendar** (`/calendar/`): FullCalendar weekly view with tool categories sidebar
3. **Tool Control** (`/tool_control/`): Expandable tool categories, tool detail pages with images
4. **Status Dashboard** (`/status_dashboard/occupancy/`): Area occupancy and tool usage tabs
5. **Impersonate** (`/impersonate/`): Search users, switch context (regular users lose Admin menu)
6. **Administration** (dropdown): 20+ admin options; Customization page loads application settings
7. **Safety** (`/safety/items/categories/`): Safety categories with items and document links

## Tips
- The app might show SyntaxWarnings for invalid escape sequences in validators.py, widgets/dynamic_form.py, and urls.py — these are pre-existing and don't block functionality
- When impersonating a regular user (e.g., Ned Land), the Administration menu disappears — this confirms role-based access works
- The `local_run/` directory is gitignored and safe for local dev files

## Devin Secrets Needed
None — local development uses SQLite and REMOTE_USER authentication with no external services.

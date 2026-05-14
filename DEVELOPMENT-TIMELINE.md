# Remote Element Marker - Development Timeline

*A technical journey of building an NVDA accessibility add-on v1.0.0*

---

## Overview

| Metric | Value |
|--------|-------|
| **Project** | Remote Element Marker v1.0.0 |
| **Platform** | NVDA (NonVisual Desktop Access) |
| **Duration** | 44 days |
| **Total Commits** | 42 |
| **Contributors** | 4 |
| **Start Date** | February 14, 2026 |
| **End Date** | March 29, 2026 |

---

## Phase 1: Project Foundation

<details>
<summary><h3>February 14-27, 2026</h3></summary>

### February 14, 2026 - Project Inception

```
Commit: e7fe198
Author: bhargav-vision-aid
```

Initial commit establishing the vision-aid-india repository foundation.

---

### February 18, 2026 - Requirements Documentation

```
Commit: b839b3f
Feature: feat(docs): added REQUIREMENT.md docs
Author: Vignesh Devendran
```

**Technical Details:**
- Created `REQUIREMENT.md` with complete project scope
- Defined accessibility requirements for element marking
- Documented screen reader interaction specifications

---

### February 24, 2026 - Team Structure

```
Commit: 04bfe8f
Feature: Update team roles and approval section in REQUIREMENT.md
Author: Vignesh Devendran
```

**Documentation Additions:**
- Team roles and responsibilities defined
- Approval workflow established
- Development phases outlined

---

### February 27, 2026 - Template Fork

```
Commit: 34378b5
Feature: feat(template): forked from nvaccess/AddonTemplate
Author: Vignesh Devendran
```

**Technical Foundation:**

```python
# Core build system established
- SCons build automation
- Custom NVDATool for add-on packaging
- Gettext integration for internationalization
- Ruff linting with NVDA translation builtins
- Pyright strict mode type checking
```

**Project Structure:**
```text
addon/
├── globalPlugins/remoteElementMarker/
│   ├── __init__.py
│   ├── bindings.py
│   ├── gui.py
│   ├── resolver.py
│   ├── settings.py
│   ├── signature.py
│   └── storage.py
├── site_scons/site_tools/
│   ├── NVDATool/
│   └── gettexttool/
├── buildVars.py
└── sconstruct
```

**Configuration Files:**
| File | Purpose |
|------|---------|
| `pyproject.toml` | 212 lines - Ruff, Pyright, dependencies |
| `.pre-commit-config.yaml` | 87 lines - Pre-commit hooks |
| `sconstruct` | 151 lines - Build automation |

</details>

---

## Phase 2: Core Features Development

<details>
<summary><h3>March 5-15, 2026</h3></summary>

### March 5, 2026 - Core, Storage JSON Bug Fixes & Documentation

```
Commit: 7fe1448
Feature: feat(core): capture, signature storage, gesture invoke
Authors: AbhishekSRaut, Vignesh Devendran
```

**Core Features Developed:** 
- User captures an element (mouse, navigator).
- Signature is generated and stored in JSON by app scope.
- User assigns a gesture, which is normalized and bound dynamically.
- When the gesture is invoked, the element is resolved and activated.

---

```
Commit: 1a9c0eb
Feature: fix(bug): appname unknown storage json
Author: Vignesh Devendran
```

**Issue:** Application name unknown in storage JSON causing marker retrieval failures.

**Fix:** Added proper app name resolution before storage operations.

---

```
Commit: fba4688
Feature: feat(readme): added nvda developer scratchpad steps
Author: Vignesh Devendran
```

**Documentation Added:**
- NVDA developer scratchpad setup instructions
- Local development environment configuration
- Testing workflow steps

---

### March 7, 2026 - Duplicate Shortcut Prevention

```
Commit: 14b1254
Feature: fix(bug): duplicate shortcut accepted in dialog
Author: Vignesh Devendran
```

**Technical Implementation:**

```python
# Before: No validation in dialog
def onOk(self, event):
    self.EndModal(wx.ID_OK)

# After: Validation in MarkerDialog.onOk()
def onOk(self, event):
    shortcut = self._captured_shortcut
    if _is_shortcut_taken(shortcut, self.marker_instance):
        # Show error dialog
        return
    self.EndModal(wx.ID_OK)
```

**Key Changes:**
- Moved validation from main plugin to `MarkerDialog.onOk()`
- Added `validate_shortcut()` function
- Implemented `conflict checking` logic
- Checked `_is_shortcut_taken()` before accepting

---

### March 14, 2026 - Shortcut UI Enhancement

```
Commit: 7aebcc3
Feature: fix(bug): shortcut frontend format and capture gesture input only
Author: Vignesh Devendran
```

**Technical Implementation:**

```python
# Simplified UI - gesture capture only
def _formatGesture(self, gesture) -> str:
    """Format gesture for display: 'main (source)'"""
    binding = gesture.normalizedIdentifiers[0]
    return binding.split(':')[-1]  # e.g., "kb:NVDA+Alt+N"

# Stored internally as raw gesture ID
self._captured_raw_gid = gesture
```

**Changes:**
- Removed manual text entry field
- Uses read-only field showing captured gesture
- Capture gesture button only

---

```
Commit: 23089b7
Feature: feat(typo): dialog box label and readme
Author: Vignesh Devendran
```

**UI Updates:**
- Fixed dialog box label typos
- Updated README formatting
- Improved user-facing string clarity

</details>

---

## Phase 3: Bug Fixes & UI Refinements

<details>
<summary><h3>March 19-22, 2026</h3></summary>

### March 19, 2026 - Windows C Bug Investigation

```
Commit: d4b7f2f
Feature: tried fixing nvda windows c bug, #5
Author: AbhishekSRaut
```

**Issue:** Investigated Windows compatibility issue #5 related to native C interface handling.

---

### March 20, 2026 - Dialog Button Fix

```
Commit: 0c6a3f8
Feature: fix(bug): Replace button misplacement in dialog
Author: Vignesh Devendran
```

**Technical Implementation:**

```python
# Before
_ID_REPLACE = wx.NewIdRef()

# After
return result == wx.ID_REPLACE
```

**Fix:** Changed from custom `_ID_REPLACE` to standard `wx.ID_REPLACE` for proper button mapping in `ConflictDialog`.

---

### March 22, 2026 - Unlabeled Element Resolution

```
Commit: 60807af
Feature: fixed the unlabeled bug
Author: AbhishekSRaut
```

**Technical Implementation:**

Introduced **Position Hints System** for resolving unlabeled elements:

```python
# Position hints computation
def _compute_position_hints(obj, ti):
    target_location = (loc[0], loc[1])  # Screen coordinates as anchor
    role_index = _count_by_tree_order(
        root_obj,
        obj.role,
        obj.name
    )
    context_before = _get_context_text(ti, POSITION_BEFORE, 60)
    context_after = _get_context_text(ti, POSITION_AFTER, 60)

    return {
        "role_index": role_index,
        "context_before": context_before,
        "context_after": context_after,
        "screen_coords": target_location
    }

# Lightweight lookup for matching
def generate_signature_for_lookup(element):
    """Generate lightweight signature without getTextWithFields()"""
```

**Resolution Strategy:**
1. Primary hash match
2. BrowseMode fallback matching with `role_index`
3. Position-based disambiguation for empty names
4. Enforce name equality even for unlabeled elements

</details>

---

## Phase 4: Testing Framework

<details>
<summary><h3>March 23-25, 2026</h3></summary>

### March 23, 2026 - Unit Tests Setup

```
Commit: d6e7060
Feature: test(addon): added unit tests using pytest
Author: Vignesh Devendran
```

**Test Suite Structure:**

| File | Lines | Coverage |
|------|-------|----------|
| `tests/conftest.py` | 197 | Mock fixtures |
| `tests/test_bindings.py` | 96 | Shortcut normalization |
| `tests/test_resolver.py` | 239 | Tree walk, match predicates |
| `tests/test_signature.py` | 313 | Signature generation |
| `tests/test_storage.py` | 206 | MarkerStore CRUD |

**Mock Infrastructure:**

```python
# tests/conftest.py
class MockNVDAObject:
    name: str = ""
    role: str = ""
    states: Set[str] = set()

class MockUIAObject(MockNVDAObject):
    def __init__(self, uia_config: dict):
        ...

class MockIAccessibleObject(MockNVDAObject):
    def __init__(self, ia_config: dict):
        ...

# Fixture setup
@pytest.fixture
def sample_marker_data() -> Dict[str, Any]:
    return {
        "backend": "BrowseMode",
        "hash": "abc123def456",
        "name": "Submit Button",
        "role": "ROLE_BUTTON"
    }
```

---

### March 23, 2026 - Configuration Updates

```
Commits: e02ecf3, ae4bbf7
Feature: test(config): updated pyproject.toml with test config
Author: Vignesh Devendran
```

**Pytest Configuration:**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

---

```
Commit: 6d1ce8b
Feature: setup(addon): local dev dependencies added to gitignore
Author: Vignesh Devendran
```

Development dependencies excluded from version control.

</details>

---

## Phase 5: Performance Optimization

<details>
<summary><h3>March 24-28, 2026</h3></summary>

### March 24, 2026 - Signature & Resolver Optimization

```
Commit: 1bfd684
Feature: perf(addon): optimize signature and resolver
Author: Vignesh Devendran
```

**Performance Enhancements:**

```python
# Timing instrumentation
_TIMING_ENABLED = True

def _log_timing(method: str, elapsed_ms: float, **kwargs):
    """Log performance metrics"""
    log.debug(f"[TIMING] {method}: {elapsed_ms:.2f}ms")

# BrowseMode resolve optimization
def _browsemode_resolve(primary, root_obj):
    t0 = time.perf_counter()

    # Fast path: role_index only (no context-based fallback)
    # Removed: slow POSITION_ALL enumeration

    elapsed = (time.perf_counter() - t0) * 1000
    _log_timing("BrowseMode", elapsed, result=result is not None)

    return result
```

**Key Optimizations:**

| Component | Optimization | Impact |
|-----------|-------------|--------|
| Tree walk | Chunked at 50 nodes/slice | Main thread responsive |
| Position hints | Lazy computation | Only when needed |
| BrowseMode | Single candidate as secondary | Reduced enumeration |
| Timeout guards | `time.monotonic()` | Prevents infinite loops |

---

### March 26-28, 2026 - Performance Merge & Freeze

```
Commit: 942491a
Merge: origin/resolver-performance-optimization

Commit: b457fbb
Feature: frezing code for deployment
Author: AbhishekSRaut
```

**Deployment Changes:**

```python
# __init__.py
addonHandler.initTranslation()

# Simplified marker iteration
for marker in markers.values():
    process_marker(marker)

# Beep progress immediate start
def play_progress_beep():
    beep(440, 50)  # Immediate feedback
```

</details>

---

## Phase 6: Documentation & Release

<details>
<summary><h3>March 22-29, 2026</h3></summary>

### March 22, 2026 - Documentation Suite

```
Commit: 86f79f0
Feature: feat(docs): readme, userguide, license
Author: Vignesh Devendran
```

**Documentation Files:**

| Document | Lines | Content |
|----------|--------|----------|
| `LICENSE.md` | - | GPL v2 license |
| `README.md` | ~100 | Project overview, quick start |
| `USERGUIDE.md` | 188 | Complete user guide |

---

### March 22, 2026 - Enhanced README

```
Commit: 9df5098
Feature: Enhance README with Remote Element Marker details
Author: Vignesh Devendran
```

**README Contents:**
- Full feature description
- Installation instructions
- Keyboard shortcuts reference
- Troubleshooting guide

---

### March 27, 2026 - Build Configuration

```
Commit: 3c2fde8
Feature: build: update build vars for packaging addon
Author: Vignesh Devendran
```

**Build Configuration:**

```python
# buildVars.py
addon_info: AddonInfo = AddonInfo(
    addon_name="remoteElementMarker",
    addon_summary=_("Remote Element Marker"),
    addon_version="1.0.0",
    addon_minimumNVDAVersion="2026.1",
    addon_lastTestedNVDAVersion="2026.1",
    addon_author="Abhishek Raut, Vignesh Devendran, Lakshmanan A"
)

pythonSources: list[str] = [
    "addon/globalPlugins/remoteElementMarker/__init__.py",
    "addon/globalPlugins/remoteElementMarker/bindings.py",
    "addon/globalPlugins/remoteElementMarker/gui.py",
    "addon/globalPlugins/remoteElementMarker/resolver.py",
    "addon/globalPlugins/remoteElementMarker/settings.py",
    "addon/globalPlugins/remoteElementMarker/signature.py",
    "addon/globalPlugins/remoteElementMarker/storage.py",
]
```

---

### March 29, 2026 - Final Preparations

```
Commits: b8b1cde, 7699cc9, 33aa03f
Feature: Final cleanup, merge, gitignore update
Authors: AbhishekSRaut, Vignesh Devendran
```

**Gitignore Additions:**
- Local development dependencies
- Build artifacts
- Python cache files

</details>

---

## Keyboard Shortcuts Reference

| Action | Default Shortcut | Description |
|--------|-----------------|-------------|
| <kbd>Mark element under mouse</kbd> | `NVDA+Alt+N` | Capture element at mouse pointer |
| <kbd>Mark element at navigator/caret</kbd> | `NVDA+Alt+B` | Capture element at navigator position |
| <kbd>Marker list</kbd> | `NVDA+Alt+L` | Open list of saved markers |
| <kbd>Marker manager</kbd> | `NVDA+Alt+Shift+M` | Open marker management dialog |
| <kbd>Toggle announcements</kbd> | `NVDA+Alt+A` | Enable/disable speech announcements |

---

## Core Module Architecture

```text
remoteElementMarker/
├── __init__.py         # GlobalPlugin entry point
├── bindings.py         # Keyboard gesture handling
├── gui.py              # wx.Dialog implementations
├── resolver.py         # Element resolution engine
├── settings.py         # NVDA settings panel
├── signature.py        # Element signature generation
└── storage.py          # JSON-based marker persistence
```

### Module Responsibilities

| Module | Purpose | Key Classes/Functions |
|--------|---------|------------------------|
| `signature.py` | Generate unique element identifiers | `generate_signature()`, `_compute_position_hints()` |
| `resolver.py` | Resolve markers back to elements | `_browsemode_resolve()`, `_uia_resolve()` |
| `storage.py` | Persist markers to JSON | `MarkerStore`, `add_marker()`, `get_markers()` |
| `gui.py` | User interface dialogs | `MarkerDialog`, `ConflictDialog`, `MarkerListDialog` |
| `bindings.py` | Keyboard input handling | `normalize_shortcut()`, `_formatGesture()` |
| `settings.py` | Configuration panel | Settings panel integration |

---

## Bug Fixes Summary

| Issue | Commit | Resolution |
|-------|--------|------------|
| App name unknown in storage | `1a9c0eb` | Added app name resolution |
| Duplicate shortcut accepted | `14b1254` | Validation in dialog |
| Shortcut UI format issues | `7aebcc3` | Gesture-only capture |
| Replace button misplacement | `0c6a3f8` | Standard `wx.ID_REPLACE` |
| Unlabeled element resolution | `60807af` | Position hints system |
| Windows C compatibility | `d4b7f2f` | Investigation attempted |

---

## Technical Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.13 |
| Build System | SCons | Custom tools |
| Linting | Ruff | NVDA builtins |
| Type Checking | Pyright | Strict mode |
| Testing | pytest | Mock fixtures |
| UI Framework | wxPython | NVDA compatible |
| Accessibility API | UIA/IAccessible | Dual backend |

---

## Contributors

| Name | Contributions |
|------|---------------|
| **Vignesh Devendran** | Template setup, planning, performance optimisation, documentation |
| **Abhishek Raut** | Core development, bug fixes, performance optimisation, deployment |
| **Lakshmanan A** | Ideation, Manual Testing |
| **Nagulan M** | Manual Testing |

## Special Mention
| Name | Thanks for |
|------|------------|
| **Sai Krushna** | Pilot Testing v1.0.0 |

---

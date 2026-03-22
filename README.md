# VA-HFI2026-Team2-OptimisticMinds

# Remote Element Marker

Version 1.0.0 | Compatible with NVDA 2023.1 and later | Windows 10 (1809) and later

---

## Overview

Remote Element Marker is an NVDA add-on that lets you assign a **friendly name** and an optional **keyboard shortcut** to any UI element in any application or web page. Once marked, you can jump directly to that element at any time by pressing its shortcut, or by selecting it from a list.

This is especially useful in remote assistance scenarios (Teams - Remote Control, TeamViewer, AnyDesk, etc.) where a sighted helper can position the mouse over an important but unlabeled element, and the NVDA user can then mark it permanently so they can access it independently in future sessions.

---

## Who Is This For?

**Visually impaired (VI) users** — navigate to an element using NVDA's object navigation or the virtual caret, then press a shortcut to mark and label it.

**Sighted users assisting remotely** — move the mouse and hover over any element on the VI user's screen, then ask the VI user to press the "Mark element under mouse pointer" shortcut. The element is captured at the mouse position without clicking it.

---

## Keyboard Shortcuts

All shortcuts can be customized in NVDA's Input Gestures dialog under the **Remote Element Marker** category.

| Action | Default Shortcut |
|---|---|
| Mark element under mouse pointer | `NVDA+Alt+N` |
| Mark element at navigator / virtual caret | `NVDA+Alt+B` |
| Open marker list (activate, edit, delete) | `NVDA+Alt+L` |
| Open marker manager for current app | `NVDA+Alt+Shift+M` |
| Toggle label announcements on/off | `NVDA+Alt+A` |

---

## NVDA's Developer Scratchpad - Manual Testing steps

### Enabling Scratchpad

- Access NVDA Preferences (NVDA + N) > Settings, go to the Advanced category
- Then check "I understand that changing these settings may cause NVDA to function incorrectly" just a caution before enabling NVDA development
- Then check "Load custom code from Developer Scratchpad Directory." Use the button there to open the scratchpad folder in your NVDA user config directory (typically %APPDATA%\nvda\scratchpad).

### Placing the Code

- Create subfolders like `appModules` or `globalPlugins` inside scratchpad if those directories not available.
- Copy the `remoteElementMarker` directory present in `addon/globalPlugins/` from our repo to `../scratchpad/globalPlugins/` directory.

### Testing

Follow the steps in the Remote Element Marker — User Guide, specifically from 'Marking an Element' section, to verify functionality.

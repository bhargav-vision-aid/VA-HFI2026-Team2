# Remote Element Marker — User Guide

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

## Marking an Element

### Method 1 — From the Navigator (keyboard-only, recommended for VI users)

1. Navigate to the element using NVDA's object navigation (`NVDA+numpad` arrows) or browse-mode arrow keys in a browser.
2. Press **`NVDA+Alt+B`**.
3. The **Add Remote Element Marker** dialog opens.

### Method 2 — From the Mouse (for remote desktop session/sighted assistance)

1. The sighted user moves the active mouse pointer and hovers over the target element — do **not** click it.
2. The VI user presses **`NVDA+Alt+N`**.
3. The **Add Remote Element Marker** dialog opens with the element under the mouse captured.

### The Add Remote Element Marker Dialog

The dialog contains:

- **Friendly Name** — a text field pre-filled with the element's existing accessible name (if any). Type a meaningful label such as "Submit Order" or "Subtract Button". This name will be spoken when you navigate to or activate the element.
- **Capture Gesture button** — press this to record a keyboard shortcut. After pressing it, perform the desired gesture (e.g. `NVDA+Alt+1`). The captured gesture appears in the read-only **Shortcut captured** field. A shortcut is optional — you can leave it blank and use the marker list instead.
- **OK / Cancel** — press OK to save the marker, Cancel to discard.

#### Gesture Conflict Handling

If the captured gesture is already assigned to another NVDA command, a **Gesture Conflict** dialog appears showing what it conflicts with and offering **Replace** or **Cancel**. Choosing Replace allows the marker shortcut to shadow the existing assignment.

If the gesture is already assigned to another marker on the same page, you are also asked whether to replace that assignment.

---

## Activating a Marker

### Using the assigned shortcut

Press the shortcut you assigned when marking the element. NVDA will say "Resolving [name]…" then navigate to and activate the element. If the element cannot be found (e.g. the page has changed), NVDA will say "Element not found. Please re-mark the element."

### Using the Marker List

1. Press **`NVDA+Alt+L`** while the target application or web page is open and in the foreground.
2. The **Activate Remote Element Marker** dialog opens, showing all markers saved for the current application or page.
3. Use the arrow keys to select a marker.
4. Press **Activate** (or Enter) to navigate to and activate the selected element.

The marker list also contains **Edit** and **Delete** buttons (see below).

---

## Managing Markers

### Editing a Marker (from the Marker List)

1. Open the marker list with **`NVDA+Alt+L`**.
2. Select the marker you want to change.
3. Press **Edit**.
4. The **Add Remote Element Marker** dialog reopens, pre-filled with the current name and shortcut.
5. Change the name and/or re-capture a gesture, then press OK.

### Deleting a Marker (from the Marker List)

1. Open the marker list with **`NVDA+Alt+L`**.
2. Select the marker you want to remove.
3. Press **Delete**.
4. Confirm deletion when prompted.

### Marker Manager

Press **`NVDA+Alt+Shift+M`** to open the **Manage Remote Element Markers** dialog. This shows all markers saved for the current application and allows you to delete individual markers. Use this when the target application is open but you do not need to activate any marker right now.

---

## Label Announcement

When label announcement is enabled, NVDA automatically reads your custom friendly name whenever you navigate to a marked element — even without pressing any shortcut.

### Toggling Announcements

- Press **`NVDA+Alt+A`** to toggle on or off. NVDA will say "Remote Element Marker on" or "Remote Element Marker off".
- Alternatively, go to **NVDA Menu → Preferences → Settings → Remote Element Marker** and check or uncheck **"Announce custom labels when navigating elements"**, then press OK.

### How It Works

When enabled, NVDA monitors focus, navigator, and caret events. Whenever a marked element is encountered during navigation, NVDA queues its friendly name for speech after the normal navigation announcement. The same label will not be repeated within 0.35 seconds to avoid double-speaking.

---

## How Markers Are Stored

Markers are saved permanently to a JSON file at:

```
%AppData%\Roaming\nvda\remoteElementMarkers.json
```

Markers are scoped per application and per page:

- **Web pages** — markers are tied to the exact URL of the page. A marker on one page will not appear or activate when a different page is open.
- **Native applications** — markers are tied to the application name and module.

Markers persist across NVDA restarts. They are not affected by closing or reopening the application.

---

## Important Notes

### Re-marking After Page Changes

Markers use a combination of element role, accessible name, position index, and surrounding text context to identify elements. If a page is redesigned and the structure around a marked element changes significantly, the marker may no longer find the correct element. In that case, delete the old marker and re-mark the element.

### Unlabeled Elements

Elements with no accessible name (e.g. icon-only buttons) are fully supported. The add-on uses screen coordinates at mark time and document position to distinguish between multiple identical-looking elements on the same page.

### Shortcut Scope

A shortcut assigned to a marker only fires when the application or web page that contains that marker is in the foreground. The same keyboard gesture can be assigned to different elements on different pages without conflict — the correct one is selected automatically based on which page is currently active.

---

## Compatibility

- NVDA 2023.1 and later
- Windows 10 (version 1809) and later
- Web browsers: Chrome, Firefox, Edge (Chromium), and other browsers supported by NVDA's browse mode
- Native Windows applications using UIA, IAccessible, or NVDA browse mode

---

## Troubleshooting

**The marker activates the wrong element.**
Delete the marker and re-mark the element. Make sure NVDA's virtual caret or navigator is precisely on the target element when marking.

**"Element not found. Please re-mark the element."**
The page structure has changed since the marker was saved. Delete and re-create the marker.

**"Element found but currently unavailable or invisible."**
The element exists but is disabled or hidden. Wait for it to become available.

**"This shortcut has no marker for the current document."**
The shortcut is registered but the page that owns it is not currently open. Navigate to the correct page first.

**"Application context mismatch."**
The marker belongs to a different application than what is currently in the foreground. Switch to the correct application.

**Announcing labels causes NVDA to feel slow on large pages.**
This is normal on very large documents. The add-on is optimized to be lightweight on navigation events. If sluggishness persists, toggle announcements off with `NVDA+Alt+A`.

---

## Copyright and License

Copyright © 2026 Team 2 - Optimistic Minds. Released under the GNU General Public License version 2.

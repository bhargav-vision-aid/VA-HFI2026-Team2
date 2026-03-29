# Remote Element Marker — User Guide
**Version:** 1.0.0  
**Compatibility:** NVDA 2023.1+ | Windows 10 (1809) and later  
**Created by:** Team 2 - Optimistic Minds for the Vision-Aid "Hack for Inclusion" 2026.

---

## Overview
**Remote Element Marker** is an NVDA add-on designed to enhance accessibility in complex software and web environments. It allows you to assign a **Friendly Name** and an optional **Keyboard Shortcut** to any UI element. 

This tool is highly effective for:
* **Independent Navigation:** Jump directly to specific buttons or fields without manual searching.
* **Remote Assistance:** A sighted helper (via Teams, TeamViewer, or AnyDesk) can hover the mouse over an unlabeled element, allowing the VI user to "mark" and label it for future independent use.

---

## Target Audience
* **Visually Impaired (VI) Users:** Use object navigation or the browse / focus mode to mark and label elements for streamlined workflows.
* **Sighted Assistants:** Help VI users by positioning the mouse over specific UI components. The VI user can then capture the element at that exact coordinate without needing to click it.

---

## Keyboard Shortcuts
All gestures can be customized in the NVDA **Input Gestures** dialog under the **Remote Element Marker** category.

| Action | Default Shortcut |
| :--- | :--- |
| **Mark element under mouse pointer** | `NVDA+Alt+N` |
| **Mark element at navigator / virtual caret** | `NVDA+Alt+B` |
| **Open Marker List** (Activate, Edit, Delete) | `NVDA+Alt+L` |
| **Open Marker Manager** (All Applications) | `NVDA+Alt+Shift+M` |
| **Toggle Label Announcements** | `NVDA+Alt+A` |

---

## Marking an Element

### Method 1: Using the Navigator (Recommended for VI Users)
1. Focus on the element using NVDA object navigation (`NVDA+Numpad Arrows`) or Browse / focus Mode.
2. Press **`NVDA+Alt+B`**.
3. The **Add Remote Element Marker** dialog will open.

### Method 2: Using the Mouse (Recommended for Remote Support)
1. Have the sighted assistant hover the mouse over the target element (do **not** click).
2. The VI user presses **`NVDA+Alt+N`**.
3. The dialog opens, capturing the element currently under the mouse pointer.

### The "Add Remote Element Marker" Dialog
* **Friendly Name:** Enter a descriptive label (e.g., "Checkout Button"). This name is spoken when navigating to or activating the element.
* **Capture Gesture:** Press this button, then perform the desired keyboard shortcut (e.g., `NVDA+Alt+1`). This is optional.
* **Conflict Handling:** If a shortcut is already in use, NVDA will prompt you to **Replace** or **Cancel**.

---

## Activating and Managing Markers

### How to Activate a Marker
* **Via Shortcut:** Press your assigned shortcut. NVDA will announce "Resolving [Name]..." and move focus to the element.
* **Via Marker List:** Press **`NVDA+Alt+L`** to see all markers for the current app. Use arrow keys to select one and press **Enter** to activate.

### Marker Manager (Global View)
Press **`NVDA+Alt+Shift+M`** to manage markers across all applications:
1. Use the **Combo Box** to select a specific application.
2. Use **Tab** to navigate between the list of markers and the **Edit/Delete** buttons.
3. Click **Close** when finished.

---

## Customization & Settings
To access advanced settings, go to **NVDA Menu → Preferences → Settings → Remote Element Marker**.

### Label Announcements
- Setting: "Announce custom labels when navigating elements"
- Default: Not checked
- Behavior: NVDA will announce the assigned "Friendly Name" automatically while navigating elements when enabled.

### Beep Feedback
- Setting: "Play audio beeps for save and resolve feedback"
- Default: Enabled
- Behavior:
  - Enabled: Plays a progress beep during capturing/resolving and a completion beep after the process ends.
  - Disabled: No audio feedback is played during or after capturing/resolving.

### Activation Behavior
* **Setting:** "Activate element after resolving to it."
* **Enabled (Default):** Moving to a marker automatically "clicks" or triggers it.
* **Disabled:** NVDA will move your focus/navigator to the element but will **not** execute it.

---

## Technical Details
* **Storage:** Markers are saved in `%AppData%\nvda\remoteElementMarkers.json`.
* **Scope:** Markers are context-sensitive. A shortcut for a specific URL will not conflict with the same shortcut on a different website.
* **Unlabeled Elements:** The add-on uses roles, position indices, and surrounding text to identify elements even if they lack an official accessible name.

---

## Troubleshooting

| Issue | Solution |
| :--- | :--- |
| **Activates wrong element** | The UI layout may have changed. Delete the marker and re-mark it. |
| **"Element not found"** | The page structure has significantly changed. Re-marking is required. |
| **"Shortcut has no marker"** | You are likely in the wrong application or on the wrong web page for that shortcut. |
| **NVDA feels slow** | Disable "Label Announcements" (`NVDA+Alt+A`) on extremely large documents. |

---
*Copyright © 2026 Team 2 - Optimistic Minds  for the Vision-Aid "Hack for Inclusion" 2026. Released under the GNU General Public License version 2.*

# Remote Element Marker (NVDA Add-on)

**Remote Element Marker** is a powerful productivity tool for NVDA users that allows you to assign **Friendly Names** and **Keyboard Shortcuts** to UI elements in any application or web page.

Whether an element is unlabeled, difficult to reach with standard navigation, or part of a complex remote desktop session, this add-on gives you the power to "mark" it once and access it forever.

-----

## 🌟 Key Features

  * **Custom Labeling:** Give any button, checkbox, or text field a name that makes sense to you.
  * **Direct Shortcuts:** Assign a gesture (like `NVDA+Alt+1`) to jump directly to a specific element.
  * **Remote Assistance Synergy:** Built specifically to help Visually Impaired (VI) users work with sighted assistants. The assistant hovers the mouse, and the VI user marks the spot.
  * **Dynamic Resolution:** Smart detection logic finds elements even if the window is moved or resized.
  * **Centralized Management:** A dedicated Marker Manager to edit, delete, or organize your markers across different apps.

-----

## ⌨️ Quick Reference: Default Shortcuts

All gestures can be customized via **NVDA Menu → Preferences → Input Gestures → Remote Element Marker**.

| Action | Shortcut |
| :--- | :--- |
| **Mark element under mouse** | `NVDA + Alt + N` |
| **Mark element at navigator/caret** | `NVDA + Alt + B` |
| **Open Marker List** | `NVDA + Alt + L` |
| **Open Marker Manager** | `NVDA + Alt + Shift + M` |
| **Toggle Label Announcements** | `NVDA + Alt + A` |

-----

## 🚀 Getting Started

### Installation

1.  Navigate to the **[Releases](https://github.com/bhargav-vision-aid/VA-HFI2026-Team2/releases)** page.
2.  Download the latest `.nvda-addon` file.
3.  Open the file and follow the NVDA installation prompts.
4.  Restart NVDA to activate the add-on.

### Detailed Documentation & Demos

  * **User Guide:** For a full walkthrough on Method 1 vs. Method 2, visit our **[User Guide](https://github.com/bhargav-vision-aid/VA-HFI2026-Team2/blob/main/USERGUIDE.md)**.
  * **Video Demos:** Download our **[Demo Video - Zip file](https://github.com/bhargav-vision-aid/VA-HFI2026-Team2/releases/download/v1.0.0/demo.zip)** to see the add-on in action within different applications and remote support scenarios.

-----

## 🛠️ Developer Setup (Testing)

If you wish to contribute or test the code manually using the **Developer Scratchpad**:

1.  Enable "Load custom code from Developer Scratchpad Directory" in **NVDA Settings → Advanced**.
2.  Locate your scratchpad directory (usually `%APPDATA%\nvda\scratchpad`).
3.  Create the path: `scratchpad/globalPlugins/`.
4.  Copy the `addon/globalPlugins/remoteElementMarker` folder into that directory.
5.  In `__init__.py`, temporarily comment out the translation lines:
    ```python
    # import addonHandler
    # addonHandler.initTranslation()
    ```
6.  Restart NVDA or use **NVDA Menu → Tools → Reload Plugins**.

-----

## 🤝 Credits & Attribution

This project was developed as part of the **Vision-Aid "Hack for Inclusion" 2026**.

  * **Developed by:** Team 2 - Optimistic Minds
  * **Organization:** [Vision-Aid](https://visionaid.org/)
  * **Lead Maintainers:** Vignesh Devendran, Lakshmanan A, Abhishek Raut & Team

-----

## License

This project is licensed under the **GNU General Public License version 2**. See the [LICENSE](https://github.com/bhargav-vision-aid/VA-HFI2026-Team2/blob/main/LICENSE) file for full text.

> *Copyright © 2026 Team 2 - Optimistic Minds for the Vision-Aid "Hack for Inclusion" 2026.*

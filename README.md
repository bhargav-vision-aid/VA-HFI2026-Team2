# VA-HFI2026-Team2-OptimisticMinds

## NVDA's Developer Scratchpad - Manual Testing steps

### Enabling Scratchpad

- Access NVDA Preferences (NVDA + N) > Settings, go to the Advanced category
- Then check "I understand that changing these settings may cause NVDA to function incorrectly" just a caution before enabling NVDA development
- Then check "Load custom code from Developer Scratchpad Directory." Use the button there to open the scratchpad folder in your NVDA user config directory (typically %APPDATA%\nvda\scratchpad).

## Placing the Code

- Create subfolders like `appModules` or `globalPlugins` inside scratchpad if those directories not available.
- Copy the `remoteElementMarker` directory present in `addon/globalPlugins/` from our repo to `../scratchpad/globalPlugins/` directory.

## Testing Steps

- Restart NVDA or select Tools > Reload Plugins (NVDA + Ctrl + F3).
- Check NVDA log from "NVDA Preferences > Tools > View log (NVDA + F1)" for loading confirmation/errors like "loading from scratchpad".
- On successful loading of code you can find "CustomRemoteGesture add-on loaded" in the logs.
- Verify functionality: Open the target app (e.g., Chrome)
  - Keyboard Capture: Navigate to the element using keyboard, then press `NVDA + Windows + n` to capture element.
  - Mouse Capture: Hover over the element using mouse then press `NVDA + Windows + m` to capture element.
  - Click Capture: Press `NVDA + Windows + c` then click the element to be captured. To cancel the capture press the same key bindings again.

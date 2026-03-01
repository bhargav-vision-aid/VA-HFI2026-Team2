# VA-HFI2026-Team2-OptimisitcMinds

## NVDA's Developer Scratchpad - Manual Testing steps
### Enabling Scratchpad

- Access NVDA Preferences (NVDA + N) > Settings, go to the Advanced category
- Then check "I understand that changing these settings may cause NVDA to function incorrectly" just a caution before enabling NVDA development
- Then check "Load custom code from Developer Scratchpad Directory." Use the button there to open the scratchpad folder in your NVDA user config directory (typically %APPDATA%\nvda\scratchpad).

## Placing the Code

- Create subfolders like `appModules` or `globalPlugins` inside scratchpad if those directories not available.
- Copy the `CustomRemoteGesture` directory present in `addon/globalPlugins/` from our repo to `../scratchpad/gobalPlugins/` directory.

## Testing Steps

- Restart NVDA or select Tools > Reload Plugins (NVDA + Ctrl + F3).
- Check NVDA log from "NVDA Preferences > Tools > View log (NVDA + F1)" for loading confirmation/errors like "loading from scratchpad". 
- On successful loading of code you can find "CustomRemoteGesture add-on loaded" in the logs.
- Verify functionality: Open the target app (e.g., Chrome) 
	- Keyboard Capture: Navigate to the element using keyboard, then press NVDA + Shift + c to capture element
	- Mouse Capture: Hover over the element using mouse then press NVDA + Shift + m to capture element
	- Session Type: To know the type of either Remote/local session press NVDA + Shift + S;
- Verify functionality: e.g., if code beeps on focus change, tab through controls and listen for beeps.

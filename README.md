# VA-HFI2026-Team2-OptimisticMinds

## NVDA's Developer Scratchpad - Manual Testing steps

### Enabling Scratchpad

- Access NVDA Preferences (NVDA + N) > Settings, go to the Advanced category
- Then check "I understand that changing these settings may cause NVDA to function incorrectly" just a caution before enabling NVDA development
- Then check "Load custom code from Developer Scratchpad Directory." Use the button there to open the scratchpad folder in your NVDA user config directory (typically %APPDATA%\nvda\scratchpad).

## Placing the Code

- Create subfolders like `appModules` or `globalPlugins` inside scratchpad if those directories not available.
- Copy the `remoteElementMarker` directory present in `addon/globalPlugins/` from our repo to `../scratchpad/globalPlugins/` directory.

## Testing

Follow the steps in the Remote Element Marker — User Guide, specifically from 'Marking an Element' section, to verify functionality.



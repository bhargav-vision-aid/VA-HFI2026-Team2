import wx  # type: ignore
import gui  # type: ignore
import config  # type: ignore
from gui.settingsDialogs import SettingsPanel  # type: ignore
from logHandler import log  # type: ignore


class RemoteElementMarkerSettingsPanel(SettingsPanel):
    title = "Remote Element Marker"
    helpId = "RemoteElementMarkerSettings"
    panelDescription = "When enabled, NVDA will announce your custom labels when you navigate to marked elements."

    def makeSettings(self, sizer):
        sHelper = gui.guiHelper.BoxSizerHelper(self, sizer=sizer)
        desc = wx.StaticText(self, label=self.panelDescription)
        sHelper.addItem(desc)

        # --- Announce labels ---
        self.announceLabels = sHelper.addItem(
            wx.CheckBox(self, label="Announce custom labels when navigating elements")
        )
        self.announceLabels.SetValue(
            bool(config.conf["remoteElementMarker"]["announceLabels"])
        )
        note = (
            "Note: This feature overrides the spoken label for matched elements. "
            "It is best-effort and may not match if the UI changes."
        )
        sHelper.addItem(wx.StaticText(self, label=note))

        # --- Audio beeps ---
        self.beepEnabled = sHelper.addItem(
            wx.CheckBox(self, label="Play audio beeps for save and resolve feedback")
        )
        self.beepEnabled.SetValue(
            bool(config.conf["remoteElementMarker"]["beepEnabled"])
        )
        beepNote = (
            "When enabled, a high-pitch beep indicates success and a low-pitch beep "
            "indicates failure. Rising progress tones play while capturing or resolving an element."
        )
        sHelper.addItem(wx.StaticText(self, label=beepNote))

        # --- Activate after resolve ---
        self.activateAfterResolve = sHelper.addItem(
            wx.CheckBox(self, label="Activate element after resolving to it")
        )
        self.activateAfterResolve.SetValue(
            bool(config.conf["remoteElementMarker"]["activateAfterResolve"])
        )
        activateNote = (
            "When enabled, resolving a marker moves to the element and triggers it. "
            "When disabled, Remote Element Marker only moves focus or browse position to the element."
        )
        sHelper.addItem(wx.StaticText(self, label=activateNote))

    def onSave(self):
        now_announce = self.announceLabels.IsChecked()
        now_beep = self.beepEnabled.IsChecked()
        now_activate = self.activateAfterResolve.IsChecked()

        # Persist to config first, unconditionally.
        try:
            config.conf["remoteElementMarker"]["announceLabels"] = now_announce
        except Exception as e:
            log.error(f"REM settings: failed to save announceLabels config: {e}")

        try:
            config.conf["remoteElementMarker"]["beepEnabled"] = now_beep
        except Exception as e:
            log.error(f"REM settings: failed to save beepEnabled config: {e}")

        try:
            config.conf["remoteElementMarker"]["activateAfterResolve"] = now_activate
        except Exception as e:
            log.error(f"REM settings: failed to save activateAfterResolve config: {e}")

        # Find the running plugin instance and apply changes live.
        try:
            import globalPluginHandler  # type: ignore

            for plugin in globalPluginHandler.runningTable.values():
                if not (
                    hasattr(plugin, "_announce_enabled")
                    and hasattr(plugin, "_schedule_nav_monitor_tick")
                    and hasattr(plugin, "_stop_nav_monitor")
                ):
                    continue

                # Apply announce-labels change.
                was_announce = plugin._announce_enabled
                if now_announce != was_announce:
                    plugin._announce_enabled = now_announce
                    if now_announce:
                        try:
                            plugin._schedule_nav_monitor_tick()
                        except Exception as e:
                            log.error(f"REM settings: failed to start nav monitor: {e}")
                    else:
                        try:
                            plugin._stop_nav_monitor()
                            plugin._current_nav_marker_key = None
                        except Exception as e:
                            log.error(f"REM settings: failed to stop nav monitor: {e}")

                # Apply beep change (simple flag update).
                if hasattr(plugin, "_beep_enabled"):
                    plugin._beep_enabled = now_beep

                if hasattr(plugin, "_activate_after_resolve"):
                    plugin._activate_after_resolve = now_activate

                break
        except Exception as e:
            log.error(f"REM settings: failed to apply live plugin state: {e}")

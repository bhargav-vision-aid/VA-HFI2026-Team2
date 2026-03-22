import wx  # type: ignore
import gui  # type: ignore
import config  # type: ignore
from gui.settingsDialogs import SettingsPanel  # type: ignore
from logHandler import log  # type: ignore


class RemoteElementMarkerSettingsPanel(SettingsPanel):
	title = "Remote Element Marker"
	helpId = "RemoteElementMarkerSettings"
	panelDescription = (
		"When enabled, NVDA will announce your custom labels when you navigate to marked elements."
	)

	def makeSettings(self, sizer):
		sHelper = gui.guiHelper.BoxSizerHelper(self, sizer=sizer)
		desc = wx.StaticText(self, label=self.panelDescription)
		sHelper.addItem(desc)
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

	def onSave(self):
		now_enabled = self.announceLabels.IsChecked()

		# Persist to config first, unconditionally.
		try:
			config.conf["remoteElementMarker"]["announceLabels"] = now_enabled
		except Exception as e:
			log.error(f"REM settings: failed to save config: {e}")

		# Find the running plugin instance and apply the change live,
		# mirroring exactly what script_toggleAnnounceLabels does.
		try:
			import globalPluginHandler  # type: ignore
			for plugin in globalPluginHandler.runningTable.values():
				if not (
					hasattr(plugin, "_announce_enabled")
					and hasattr(plugin, "_schedule_nav_monitor_tick")
					and hasattr(plugin, "_stop_nav_monitor")
				):
					continue

				was_enabled = plugin._announce_enabled
				if now_enabled == was_enabled:
					# No change — nothing to do.
					break

				# Update the cached flag first so any event that fires
				# during timer start/stop sees the correct state.
				plugin._announce_enabled = now_enabled

				if now_enabled:
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
				break
		except Exception as e:
			log.error(f"REM settings: failed to apply live plugin state: {e}")
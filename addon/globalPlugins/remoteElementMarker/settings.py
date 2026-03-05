import wx  # type: ignore
import gui  # type: ignore
import config  # type: ignore
from gui.settingsDialogs import SettingsPanel  # type: ignore


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
		try:
			import globalPluginHandler  # type: ignore
			for plugin in globalPluginHandler.runningTable.values():
				if hasattr(plugin, "_announce_enabled") and hasattr(plugin, "_schedule_nav_monitor_tick"):
					was_enabled = plugin._announce_enabled
					plugin._announce_enabled = now_enabled
					config.conf["remoteElementMarker"]["announceLabels"] = now_enabled
					if now_enabled and not was_enabled:
						plugin._schedule_nav_monitor_tick()
					elif not now_enabled and was_enabled:
						plugin._stop_nav_monitor()
					break
		except Exception:
			config.conf["remoteElementMarker"]["announceLabels"] = now_enabled

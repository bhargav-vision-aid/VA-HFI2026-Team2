import wx  # type: ignore
import gui  # type: ignore
import inputCore  # type: ignore

# Custom return codes used by ConflictDialog
_ID_REPLACE = wx.NewIdRef()


def _alert(message_text, title="Remote Element Marker"):
	"""
	Compatibility shim for alert dialogs.
	NVDA's gui.message.MessageDialog API was introduced in 2024.x and is not
	available on NVDA 2023.x (our minimum supported version). We fall back to
	wx.MessageBox which works on all versions.
	"""
	try:
		from gui import message  # type: ignore

		message.MessageDialog.alert(message_text, title)
	except Exception:
		wx.MessageBox(message_text, title, wx.OK | wx.ICON_INFORMATION)


def _confirm(message_text, title="Remote Element Marker") -> bool:
	"""
	Compatibility shim for confirmation dialogs.
	Returns True if the user confirmed (OK / Yes).
	"""
	try:
		from gui import message  # type: ignore

		result = message.MessageDialog.confirm(message_text, title)
		# ReturnCode.OK exists on newer NVDA; compare by value to stay robust
		return str(result).endswith("OK") or result == getattr(
			getattr(message, "ReturnCode", None), "OK", None
		)
	except Exception:
		return wx.MessageBox(message_text, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES


class ConflictDialog(wx.Dialog):
	"""
	Shown when a captured gesture conflicts with an existing assignment.
	Presents the conflict details and offers Replace / Cancel choices.
	"""

	def __init__(self, parent, message_text, title="Gesture Conflict"):
		wx.Dialog.__init__(self, parent, title=title)
		main_sizer = wx.BoxSizer(wx.VERTICAL)
		#border = gui.guiHelper.BORDER_FOR_DIALOGS
		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		# Message
		msg = wx.StaticText(self, label=message_text)
		msg.Wrap(480)
		sHelper.addItem(msg)
		
		bHelper = sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.CANCEL))
		
		replace_btn = wx.Button(self, id=wx.ID_REPLACE, label="&Replace")
		self.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_REPLACE), replace_btn)
		bHelper.Insert(0, replace_btn)

		main_sizer.Add(sHelper.sizer, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.Sizer = main_sizer
		main_sizer.Fit(self)
		self.CentreOnScreen()


class MarkerDialog(wx.Dialog):
	"""
	Dialog to prompt the user for a Friendly Name and a Shortcut Key
	when marking a remote element.
	"""

	def __init__(self, parent, default_name="", marker_instance=None, app_key="", signature_hash=""):
		wx.Dialog.__init__(self, parent, title="Add Remote Element Marker")

		self.marker_instance = marker_instance
		self.app_key = app_key
		self.signature_hash = signature_hash

		main_sizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		# Name
		self.name_edit = sHelper.addLabeledControl("Friendly &Name:", wx.TextCtrl)
		self.name_edit.Value = default_name

		# Shortcut Instructions
		self.instructions = wx.StaticText(
			self, label="Use the Capture Gesture button to record a gesture."
		)
		sHelper.addItem(self.instructions)

		# Capture button
		self.capture_btn = wx.Button(self, label="&Capture Gesture")
		self.Bind(wx.EVT_BUTTON, self.onCapture, self.capture_btn)
		sHelper.addItem(self.capture_btn)

		self._captured_raw_gid = None

		# Shortcut Input
		self.shortcut_edit = sHelper.addLabeledControl(
			"&Shortcut captured:", wx.TextCtrl, style=wx.TE_READONLY
		)

		self._capturing = False
		self.Bind(wx.EVT_WINDOW_DESTROY, self.onDestroy)

		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))
		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)

		main_sizer.Add(sHelper.sizer, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.Sizer = main_sizer
		main_sizer.Fit(self)
		self.CentreOnScreen()

	def _show_conflict_dialog(self, message_text) -> bool:
		"""
		Show a ConflictDialog and return True if the user chose Replace.
		"""
		d = ConflictDialog(self, message_text)
		result = d.ShowModal()
		d.Destroy()
		return result == _ID_REPLACE

	def onOk(self, evt):
		if not self.name_edit.Value.strip():
			_alert("Please provide a friendly name.", "Input Error")
			return

		self._stopCapture()
		self.friendly_name = self.name_edit.Value.strip()
		if self._captured_raw_gid:
			self.shortcut = self._captured_raw_gid.strip()
		else:
			self.shortcut = None

		if self.shortcut:
			from . import normalize_shortcut

			normalized = normalize_shortcut(self.shortcut)
			if not normalized:
				_alert(
					"Invalid or unsupported gesture. Use the Capture button to record a valid NVDA gesture.",
					"Input Error",
				)
				return

			if self.marker_instance:
				# ── 1. Check conflicts with OTHER NVDA scripts (non-REM) ──────────
				# Exclude our own dispatcher scripts — they are intentionally shared
				# across documents and are not real conflicts.
				all_conflicts = self.marker_instance._find_conflicts(normalized) or []
				external_conflicts = [
					(cat, name) for cat, name in all_conflicts
					if not name.startswith("Remote Element Marker shortcut dispatcher")
				]
				if external_conflicts:
					conflict_lines = "\n".join(
						f"  • {name} ({cat})" for cat, name in external_conflicts
					)
					msg = (
						f"The gesture is already assigned to:\n{conflict_lines}\n\n"
						f"Do you want to replace that assignment with this marker?"
					)
					if not self._show_conflict_dialog(msg):
						return  # user cancelled
					# User chose Replace — we don't unregister the external NVDA
					# script (that's not our responsibility), but we allow the save
					# to proceed so the dispatcher will shadow it.

				# ── 2. Check conflicts with OTHER MARKERS on the same document ──
				same_doc_conflict = self.marker_instance._find_same_doc_shortcut_conflict(
					normalized, self.app_key, self.signature_hash
				)
				if same_doc_conflict:
					existing_name = same_doc_conflict["friendly_name"]
					msg = (
						f"The gesture is already assigned to the marker \"{existing_name}\" "
						f"on this page.\n\n"
						f"Do you want to replace that assignment and give this gesture "
						f"to the new marker instead?"
					)
					if not self._show_conflict_dialog(msg):
						return  # user cancelled
					# User chose Replace — clear the shortcut from the old marker.
					self.marker_instance._clear_shortcut_from_marker(
						same_doc_conflict["app_key"],
						same_doc_conflict["sig_hash"],
					)

		self.EndModal(wx.ID_OK)

	def onCapture(self, evt):
		if inputCore.manager and inputCore.manager._captureFunc:
			_alert("Another gesture capture is already in progress.", "Capture Busy")
			return
		self._capturing = True
		self.instructions.Label = "Perform the gesture now. Press Escape to cancel."
		if inputCore.manager:
			inputCore.manager._captureFunc = self._gestureCaptor

	def _gestureCaptor(self, gesture):
		if gesture.isModifier:
			return False
		if inputCore.manager:
			inputCore.manager._captureFunc = None
		wx.CallAfter(self._onCaptured, gesture)
		return False

	def _onCaptured(self, gesture):
		if not self._capturing:
			return
		gids = gesture.normalizedIdentifiers
		if not gids:
			return
		if len(gids) > 1:
			menu = wx.Menu()
			for gid in gids:
				label = self._formatGesture(gid)
				item = menu.Append(wx.ID_ANY, label)
				self.Bind(wx.EVT_MENU, lambda evt, g=gid: self._setCaptured(g), item)
			self.PopupMenu(menu)
			if self._capturing:
				self._setCaptured(gids[0])
			menu.Destroy()
		else:
			self._setCaptured(gids[0])

	def _setCaptured(self, gid: str):
		self._captured_raw_gid = gid
		self.shortcut_edit.Value = self._formatGesture(gid)
		self._stopCapture()

	def _formatGesture(self, gid: str) -> str:
		try:
			source, main = inputCore.getDisplayTextForGestureIdentifier(gid)
			return f"{main} ({source})"
		except Exception:
			return gid

	def _stopCapture(self):
		if self._capturing and inputCore.manager and inputCore.manager._captureFunc == self._gestureCaptor:
			inputCore.manager._captureFunc = None
		self._capturing = False
		self.instructions.Label = "Use the Capture Gesture button to record a gesture."

	def onDestroy(self, evt):
		self._stopCapture()
		evt.Skip()


class MarkerManagerDialog(wx.Dialog):
	"""
	Dialog to list, manage, and delete existing markers for the active application.
	"""

	def __init__(self, parent, app_key, markers_dict, delete_callback):
		wx.Dialog.__init__(
			self,
			parent,
			title="Manage Remote Element Markers",
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)

		self.app_key = app_key
		self.markers_dict = markers_dict
		self.delete_callback = delete_callback
		self.marker_hashes = list(markers_dict.keys())

		main_sizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		sHelper.addItem(wx.StaticText(self, label=f"Markers for application: {app_key.split('|')[0]}"))

		choices = [
				f"{m.get('friendlyName', 'Unknown')} [{self._formatGesture(m.get('shortcut', 'No Shortcut'))}]"
				for m in markers_dict.values()
		]
		self.marker_list = sHelper.addLabeledControl("Saved &Markers:", wx.ListBox, choices=choices)

		if choices:
			self.marker_list.SetSelection(0)

		bHelper = sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))

		self.delete_btn = wx.Button(self, label="&Delete Selected")
		self.Bind(wx.EVT_BUTTON, self.onDelete, self.delete_btn)
		bHelper.Insert(0, self.delete_btn)

		if not choices:
			self.delete_btn.Disable()

		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)

		main_sizer.Add(sHelper.sizer, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.Sizer = main_sizer
		main_sizer.Fit(self)
		self.CentreOnScreen()

	def onDelete(self, evt):
		sel = self.marker_list.GetSelection()
		if sel == wx.NOT_FOUND:
			return

		if _confirm("Are you sure you want to delete this marker?", "Confirm Deletion"):
			hash_to_delete = self.marker_hashes[sel]
			self.delete_callback(self.app_key, hash_to_delete)

			self.marker_list.Delete(sel)
			self.marker_hashes.pop(sel)

			if self.marker_list.GetCount() > 0:
				self.marker_list.SetSelection(min(sel, self.marker_list.GetCount() - 1))
			else:
				self.delete_btn.Disable()

	def onOk(self, evt):
		self.EndModal(wx.ID_OK)

	def _formatGesture(self, gid: str) -> str:
		try:
			source, main = inputCore.getDisplayTextForGestureIdentifier(gid)
			return f"{main} ({source})"
		except Exception:
			return gid


class MarkerPickerDialog(wx.Dialog):
	"""
	Dialog to select and activate a marker for the current application.
	"""

	def __init__(self, parent, items):
		wx.Dialog.__init__(
			self,
			parent,
			title="Activate Remote Element Marker",
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)

		self.items = items

		main_sizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		sHelper.addItem(wx.StaticText(self, label="Markers for current application:"))

		choices = [item["label"] for item in items]
		self.marker_list = sHelper.addLabeledControl("&Markers:", wx.ListBox, choices=choices)

		if choices:
			self.marker_list.SetSelection(0)

		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))
		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)

		main_sizer.Add(sHelper.sizer, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.Sizer = main_sizer
		main_sizer.Fit(self)
		self.CentreOnScreen()

	def onOk(self, evt):
		sel = self.marker_list.GetSelection()
		if sel == wx.NOT_FOUND:
			return
		self.selected_app_key = self.items[sel]["app_key"]
		self.selected_hash = self.items[sel]["sig_hash"]
		self.EndModal(wx.ID_OK)

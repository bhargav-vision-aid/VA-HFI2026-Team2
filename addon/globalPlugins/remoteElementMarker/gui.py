import wx  # type: ignore
import gui  # type: ignore
import inputCore  # type: ignore
from urllib.parse import urlparse


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

	def __init__(self, parent, default_name="", marker_instance=None, app_key="", signature_hash="", existing_shortcut=""):
		wx.Dialog.__init__(self, parent, title="Add Remote Element Marker")

		self.marker_instance = marker_instance
		self.app_key = app_key
		self.signature_hash = signature_hash
		self.replace_existing_marker = None

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

		# Pre-fill with existing shortcut if editing
		self._captured_raw_gid = existing_shortcut if existing_shortcut else None

		# Shortcut Input
		self.shortcut_edit = sHelper.addLabeledControl(
			"&Shortcut captured:", wx.TextCtrl, style=wx.TE_READONLY
		)
		if existing_shortcut:
			self.shortcut_edit.Value = self._formatGesture(existing_shortcut)

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
		return result == wx.ID_REPLACE

	def onOk(self, evt):
		if not self.name_edit.Value.strip():
			_alert("Please provide a friendly name.", "Input Error")
			return

		self._stopCapture()
		self.friendly_name = self.name_edit.Value.strip()
		self.replace_existing_marker = None
		if self._captured_raw_gid:
			self.shortcut = self._captured_raw_gid.strip()
		else:
			self.shortcut = None

		if self.marker_instance:
			same_name_conflict = self.marker_instance._find_same_doc_label_conflict(
				self.friendly_name, self.app_key, self.signature_hash
			)
			if same_name_conflict:
				existing_name = same_name_conflict["friendly_name"]
				msg = (
					f"A marker named \"{existing_name}\" already exists on this page.\n\n"
					f"Do you want to replace that marker with this one?"
				)
				if not self._show_conflict_dialog(msg):
					return
				self.replace_existing_marker = same_name_conflict

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
	Dialog to manage all saved markers using a category combobox and marker list.
	"""

	def __init__(self, parent, all_markers, marker_instance=None, delete_callback=None, edit_callback=None):
		wx.Dialog.__init__(
			self,
			parent,
			title="Manage Remote Element Markers",
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)

		self.all_markers = all_markers
		self.marker_instance = marker_instance
		self.delete_callback = delete_callback
		self.edit_callback = edit_callback
		self._categories = []
		self._current_items = []

		main_sizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		sHelper.addItem(wx.StaticText(self, label="All saved markers by application/document:"))
		self.category_choice = sHelper.addLabeledControl("&Category:", wx.Choice, choices=[])
		self.Bind(wx.EVT_CHOICE, self.onCategoryChanged, self.category_choice)

		self.marker_list = sHelper.addLabeledControl("&Markers:", wx.ListBox, choices=[])
		self.marker_list.SetMinSize((700, 300))
		self.Bind(wx.EVT_LISTBOX, self.onMarkerSelectionChanged, self.marker_list)
		self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)

		self.edit_btn = wx.Button(self, label="&Edit Selected")
		self.Bind(wx.EVT_BUTTON, self.onEdit, self.edit_btn)

		self.delete_btn = wx.Button(self, label="&Delete Selected")
		self.Bind(wx.EVT_BUTTON, self.onDelete, self.delete_btn)
		self.close_btn = wx.Button(self, id=wx.ID_CLOSE, label="&Close")
		self.Bind(wx.EVT_BUTTON, self.onOk, self.close_btn)

		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		btn_sizer.Add(self.edit_btn, flag=wx.RIGHT, border=gui.guiHelper.BORDER_FOR_DIALOGS)
		btn_sizer.Add(self.delete_btn, flag=wx.RIGHT, border=gui.guiHelper.BORDER_FOR_DIALOGS)
		btn_sizer.Add(self.close_btn)
		sHelper.addItem(btn_sizer)

		self._populateCategories()
		if self._categories:
			self.category_choice.SetSelection(0)
			self._loadCategoryMarkers(0)

		self._updateActionButtons()

		main_sizer.Add(sHelper.sizer, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.Sizer = main_sizer
		main_sizer.Fit(self)
		self.CentreOnScreen()

	def _populateCategories(self):
		self._categories = []
		labels = []
		for app_key in sorted(self.all_markers.keys(), key=self._formatCategoryLabel):
			markers = self.all_markers.get(app_key, {}).get("markers", {})
			if not markers:
				continue
			self._categories.append(app_key)
			labels.append(self._formatCategoryLabel(app_key))
		self.category_choice.SetItems(labels)

	def _loadCategoryMarkers(self, category_index: int):
		self._current_items = []
		self.marker_list.Clear()
		if category_index < 0 or category_index >= len(self._categories):
			self._updateActionButtons()
			return
		app_key = self._categories[category_index]
		markers = self.all_markers.get(app_key, {}).get("markers", {})
		for sig_hash, marker_data in sorted(
			markers.items(),
			key=lambda item: (item[1].get("friendlyName", "") or "").casefold(),
		):
			self._current_items.append({
				"app_key": app_key,
				"sig_hash": sig_hash,
				"marker_data": marker_data,
			})
			self.marker_list.Append(self._formatMarkerLabel(marker_data))
		if self._current_items:
			self.marker_list.SetSelection(0)
		self._updateActionButtons()

	def _formatCategoryLabel(self, app_key: str) -> str:
		base = app_key.split("|doc:", 1)[0].split("|")[0]
		base = base or "Unknown application"
		if "|doc:" not in app_key:
			return base
		doc_part = app_key.split("|doc:", 1)[1].strip()
		doc_label = self._formatDocumentLabel(doc_part)
		return f"{base} - {doc_label}" if doc_label else base

	def _formatDocumentLabel(self, doc_part: str) -> str:
		if not doc_part:
			return "Current page"
		if "://" not in doc_part:
			return doc_part
		try:
			parsed = urlparse(doc_part)
		except Exception:
			return doc_part
		host = (parsed.netloc or "").strip()
		path = (parsed.path or "").strip("/")
		if not host:
			return doc_part
		if not path:
			return host
		segments = [segment for segment in path.split("/") if segment]
		if not segments:
			return host
		last_segment = segments[-1].replace("-", " ").replace("_", " ").strip()
		if not last_segment:
			return host
		return f"{host} / {last_segment}"

	def _formatMarkerLabel(self, marker_data) -> str:
		friendly = marker_data.get("friendlyName", "Unknown")
		shortcut = marker_data.get("shortcut", "")
		shortcut_display = self._formatGesture(shortcut) if shortcut else "No Shortcut"
		return f"{friendly} [{shortcut_display}]"

	def _getSelectedMarker(self):
		index = self.marker_list.GetSelection()
		if index == wx.NOT_FOUND or index >= len(self._current_items):
			return None, None
		selected = self._current_items[index]
		app_key = selected["app_key"]
		sig_hash = selected["sig_hash"]
		marker_data = self.marker_instance._store.get_marker(app_key, sig_hash) if self.marker_instance else None
		if not marker_data:
			return index, None
		selected["marker_data"] = marker_data
		return index, selected

	def _updateActionButtons(self):
		_, data = self._getSelectedMarker()
		has_marker = data is not None
		self.edit_btn.Enable(has_marker)
		self.delete_btn.Enable(has_marker)

	def onCategoryChanged(self, evt):
		self._loadCategoryMarkers(self.category_choice.GetSelection())

	def onMarkerSelectionChanged(self, evt):
		self._updateActionButtons()
		evt.Skip()

	def onCharHook(self, evt):
		focus = self.FindFocus()
		if evt.GetKeyCode() == wx.WXK_TAB:
			reverse = evt.ShiftDown()
			if focus is self.marker_list:
				target = self.close_btn if reverse else self.edit_btn
				if target and target.IsEnabled():
					target.SetFocus()
					return
			if focus is self.edit_btn:
				target = self.marker_list if reverse else self.delete_btn
				if target and (not hasattr(target, "IsEnabled") or target.IsEnabled()):
					target.SetFocus()
					return
			if focus is self.delete_btn:
				target = self.edit_btn if reverse else self.close_btn
				if target and (not hasattr(target, "IsEnabled") or target.IsEnabled()):
					target.SetFocus()
					return
			if focus is self.close_btn and reverse:
				target = self.delete_btn if self.delete_btn.IsEnabled() else self.edit_btn
				if target and target.IsEnabled():
					target.SetFocus()
					return
		evt.Skip()

	def onEdit(self, evt):
		item, selected = self._getSelectedMarker()
		if selected is None:
			return

		app_key = selected["app_key"]
		sig_hash = selected["sig_hash"]
		marker_data = selected["marker_data"]
		current_name = marker_data.get("friendlyName", "")
		current_shortcut = marker_data.get("shortcut", "")

		d = MarkerDialog(
			self,
			default_name=current_name,
			marker_instance=self.marker_instance,
			app_key=app_key,
			signature_hash=sig_hash,
			existing_shortcut=current_shortcut,
		)
		if d.ShowModal() == wx.ID_OK and self.edit_callback:
			new_name = d.friendly_name
			new_shortcut = d.shortcut or ""
			self.edit_callback(app_key, sig_hash, new_name, new_shortcut)
			updated_marker = self.marker_instance._store.get_marker(app_key, sig_hash) if self.marker_instance else None
			if updated_marker:
				selected["marker_data"] = updated_marker
				self._current_items[item]["marker_data"] = updated_marker
				self.marker_list.SetString(item, self._formatMarkerLabel(updated_marker))
		d.Destroy()

	def onDelete(self, evt):
		item, selected = self._getSelectedMarker()
		if selected is None:
			return

		label = selected["marker_data"].get("friendlyName", "Unknown")
		if _confirm(f"Are you sure you want to delete the marker \"{label}\"?", "Confirm Deletion"):
			if self.delete_callback:
				self.delete_callback(selected["app_key"], selected["sig_hash"])
			self.marker_list.Delete(item)
			self._current_items.pop(item)
			if self._current_items:
				self.marker_list.SetSelection(min(item, len(self._current_items) - 1))
			self._updateActionButtons()

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
	Includes Edit and Delete buttons for managing markers inline.
	"""

	def __init__(self, parent, items, marker_instance=None, delete_callback=None, edit_callback=None):
		wx.Dialog.__init__(
			self,
			parent,
			title="Activate Remote Element Marker",
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
		)

		self.items = list(items)  # mutable copy
		self.marker_instance = marker_instance
		self.delete_callback = delete_callback
		self.edit_callback = edit_callback

		main_sizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		sHelper.addItem(wx.StaticText(self, label="Markers for current application:"))

		choices = [item["label"] for item in self.items]
		self.marker_list = sHelper.addLabeledControl("&Markers:", wx.ListBox, choices=choices)

		if choices:
			self.marker_list.SetSelection(0)

		# Action buttons row: Activate | Edit | Delete | Cancel
		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

		self.activate_btn = wx.Button(self, id=wx.ID_OK, label="&Activate")
		self.activate_btn.SetDefault()
		btn_sizer.Add(self.activate_btn, flag=wx.RIGHT, border=gui.guiHelper.BORDER_FOR_DIALOGS)

		self.edit_btn = wx.Button(self, label="&Edit")
		self.Bind(wx.EVT_BUTTON, self.onEdit, self.edit_btn)
		btn_sizer.Add(self.edit_btn, flag=wx.RIGHT, border=gui.guiHelper.BORDER_FOR_DIALOGS)

		self.delete_btn = wx.Button(self, label="&Delete")
		self.Bind(wx.EVT_BUTTON, self.onDelete, self.delete_btn)
		btn_sizer.Add(self.delete_btn, flag=wx.RIGHT, border=gui.guiHelper.BORDER_FOR_DIALOGS)

		cancel_btn = wx.Button(self, id=wx.ID_CANCEL, label="&Cancel")
		btn_sizer.Add(cancel_btn)

		sHelper.addItem(btn_sizer)

		if not choices:
			self.activate_btn.Disable()
			self.edit_btn.Disable()
			self.delete_btn.Disable()

		self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)

		main_sizer.Add(sHelper.sizer, border=gui.guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.Sizer = main_sizer
		main_sizer.Fit(self)
		self.CentreOnScreen()

	def _selected(self):
		"""Return (index, item) for the current list selection, or (None, None)."""
		sel = self.marker_list.GetSelection()
		if sel == wx.NOT_FOUND or sel >= len(self.items):
			return None, None
		return sel, self.items[sel]

	def onEdit(self, evt):
		sel, item = self._selected()
		if item is None:
			return

		app_key = item["app_key"]
		sig_hash = item["sig_hash"]

		# Fetch the full marker data so we can pre-fill name and shortcut.
		marker_data = None
		if self.marker_instance:
			marker_data = self.marker_instance._store.get_marker(app_key, sig_hash)
		if not marker_data:
			_alert("Could not load marker data.", "Edit Error")
			return

		current_name = marker_data.get("friendlyName", "")
		current_shortcut = marker_data.get("shortcut", "")

		d = MarkerDialog(
			self,
			default_name=current_name,
			marker_instance=self.marker_instance,
			app_key=app_key,
			signature_hash=sig_hash,
			existing_shortcut=current_shortcut,
		)
		if d.ShowModal() == wx.ID_OK:
			new_name = d.friendly_name
			new_shortcut = d.shortcut

			if self.edit_callback:
				self.edit_callback(app_key, sig_hash, new_name, new_shortcut or "")

			# Refresh the list label in place so the user sees the change immediately.
			from .bindings import normalize_shortcut
			normalized = normalize_shortcut(new_shortcut) if new_shortcut else ""
			shortcut_display = self._formatGesture(normalized) if normalized else "No Shortcut"
			new_label = f"{new_name} [{shortcut_display}]"
			self.items[sel]["label"] = new_label
			self.marker_list.SetString(sel, new_label)
			self.marker_list.SetSelection(sel)
		d.Destroy()

	def onDelete(self, evt):
		sel, item = self._selected()
		if item is None:
			return

		if not _confirm(
			f"Are you sure you want to delete the marker \"{item['label']}\"?",
			"Confirm Deletion",
		):
			return

		if self.delete_callback:
			self.delete_callback(item["app_key"], item["sig_hash"])

		self.marker_list.Delete(sel)
		self.items.pop(sel)

		count = self.marker_list.GetCount()
		if count > 0:
			self.marker_list.SetSelection(min(sel, count - 1))
		else:
			# No markers left — disable all action buttons except Cancel.
			self.activate_btn.Disable()
			self.edit_btn.Disable()
			self.delete_btn.Disable()

	def onOk(self, evt):
		sel, item = self._selected()
		if item is None:
			return
		self.selected_app_key = item["app_key"]
		self.selected_hash = item["sig_hash"]
		self.EndModal(wx.ID_OK)

	def _formatGesture(self, gid: str) -> str:
		try:
			source, main = inputCore.getDisplayTextForGestureIdentifier(gid)
			return f"{main} ({source})"
		except Exception:
			return gid

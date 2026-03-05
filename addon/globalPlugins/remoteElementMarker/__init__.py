# -*- coding: UTF-8 -*-
# Remote Element Marker
# Copyright (C) 2025 Team 2
# Released under GPL 2

from typing import Dict, Any, Optional, List
import time


import globalPluginHandler  # type: ignore
#import addonHandler  # type: ignore
import api  # type: ignore
import config  # type: ignore
from scriptHandler import script  # type: ignore
import controlTypes  # type: ignore
import ui  # type: ignore
import queueHandler  # type: ignore
from logHandler import log  # type: ignore
import wx  # type: ignore
import gui as nvda_gui  # type: ignore
import inputCore  # type: ignore
import NVDAObjects  # type: ignore
from gui.settingsDialogs import NVDASettingsDialog  # type: ignore
import textInfos  # type: ignore

from .gui import MarkerDialog
from .storage import MarkerStore
from .signature import generate_signature
from .resolver import resolve_element
from .bindings import normalize_shortcut
from .settings import RemoteElementMarkerSettingsPanel

#addonHandler.initTranslation()


class FriendlyNameOverlay(NVDAObjects.NVDAObject):
	def _get_name(self):
		name = getattr(self, "_remoteElementMarkerFriendlyName", None)
		if name:
			return name
		return super()._get_name()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

	scriptCategory = "Remote Element Marker"

	def __init__(self):
		super(GlobalPlugin, self).__init__()
		self._ensure_config()
		self._store = MarkerStore()
		self._capture_next_click = False
		self._dynamic_script_names = set()
		self._settings_registered = False
		self._in_overlay = False
		self._last_label_announcement = ("", 0.0)
		self._current_nav_marker_key = None
		self._last_caret_announce_time = 0.0
		self._last_timer_announce_time = 0.0
		self._nav_monitor_timer = None
		self._nav_monitor_interval_ms = 400
		# Cache the enabled state as a plain boolean so every event handler
		# checks one attribute instead of reading from config each time.
		self._announce_enabled = self._load_announce_enabled()
		self._register_settings_panel()
		self._bind_saved_shortcuts()
		if self._announce_enabled:
			self._schedule_nav_monitor_tick()

	def _bind_saved_shortcuts(self):
		"""Bind all saved marker shortcuts dynamically."""
		self.clearGestureBindings()
		self.bindGestures({
			"kb:NVDA+windows+m": "markElementFromMouse",
			"kb:NVDA+windows+n": "markElementFromNavigator",
			"kb:NVDA+windows+shift+m": "openMarkerManager",
			"kb:NVDA+windows+c": "armClickCapture",
			"kb:NVDA+alt+l": "openMarkerList",
			"kb:NVDA+windows+shift+a": "toggleAnnounceLabels",
		})
		self._remove_dynamic_scripts()

		bound_shortcuts = set()
		for app_key, app_data in self._store.all_markers().items():
			for sig_hash, marker_data in app_data.get("markers", {}).items():
				shortcut = normalize_shortcut(marker_data.get("shortcut", ""))
				if shortcut:
					if shortcut in bound_shortcuts:
						log.warning(f"Duplicate shortcut skipped: {shortcut}")
						continue
					bound_shortcuts.add(shortcut)
					script_name = f"invokeMarker_{sig_hash}"
					friendly_name = marker_data.get("friendlyName", "Unknown")
					self._register_dynamic_script(script_name, app_key, sig_hash, friendly_name)
					self.bindGesture(shortcut, script_name)

	def _get_app_key(self, obj) -> str:
		return self._store.get_app_key(obj)

	def _format_app_name(self, app_key: str) -> str:
		return app_key.split("|")[0]

	def _get_base_app_key(self, obj) -> str:
		app_name = getattr(obj.appModule, "appName", "unknown")
		app_module = getattr(obj.appModule, "appModuleName", "unknown") if obj.appModule else "unknown"
		return f"{app_name}|{app_module}"

	def _get_app_key_candidates(self) -> List[str]:
		candidates = []
		fg = api.getForegroundObject()
		if fg:
			candidates.append(self._get_app_key(fg))
			candidates.append(self._get_base_app_key(fg))
		focus = api.getFocusObject()
		if focus:
			candidates.append(self._get_app_key(focus))
			candidates.append(self._get_base_app_key(focus))
		nav = api.getNavigatorObject()
		if nav:
			candidates.append(self._get_app_key(nav))
			candidates.append(self._get_base_app_key(nav))
		seen = set()
		out = []
		for c in candidates:
			if c and c not in seen:
				seen.add(c)
				out.append(c)
		return out

	def _get_markers_for_current_app(self) -> list:
		candidates = self._get_app_key_candidates()
		if not candidates:
			return []
		candidate_set = set(candidates)
		base_keys = {c.split("|doc:", 1)[0] for c in candidates}
		doc_keys = {c for c in candidates if "|doc:" in c}
		items = []
		for app_key, app_data in self._store.all_markers().items():
			base = app_key.split("|doc:", 1)[0]
			is_doc_scoped = "|doc:" in app_key

			# If we have a current document context (typical browser case), only
			# include markers for that exact document key. This prevents showing
			# labels from other pages of the same browser/app module.
			if is_doc_scoped:
				if doc_keys and app_key not in doc_keys:
					continue
				# No active document context: hide document-scoped entries.
				if not doc_keys:
					continue
			else:
				# Non-document-scoped markers remain app-scoped.
				if app_key not in candidate_set and base not in base_keys:
					continue

			for sig_hash, marker_data in app_data.get("markers", {}).items():
				label = marker_data.get("friendlyName", "Unknown")
				if "doc:" in app_key:
					label = f"{label} [{app_key.split('doc:',1)[1]}]"
				items.append({
					"app_key": app_key,
					"sig_hash": sig_hash,
					"label": label,
				})
		return items

	def _save_store(self) -> None:
		try:
			self._store.save()
		except Exception:
			ui.message("Warning: Failed to save markers.")

	def _ensure_config(self):
		try:
			if "remoteElementMarker" not in config.conf.spec:
				config.conf.spec["remoteElementMarker"] = {}
			if "announceLabels" not in config.conf.spec["remoteElementMarker"]:
				config.conf.spec["remoteElementMarker"]["announceLabels"] = "boolean(default=False)"
			_ = config.conf["remoteElementMarker"]["announceLabels"]
		except Exception:
			pass

	def _register_settings_panel(self):
		if self._settings_registered:
			return
		try:
			if RemoteElementMarkerSettingsPanel not in NVDASettingsDialog.categoryClasses:
				NVDASettingsDialog.categoryClasses.append(RemoteElementMarkerSettingsPanel)
			self._settings_registered = True
		except Exception as e:
			log.debugWarning(f"Failed to register settings panel: {e}")

	def _unregister_settings_panel(self):
		if not self._settings_registered:
			return
		try:
			if RemoteElementMarkerSettingsPanel in NVDASettingsDialog.categoryClasses:
				NVDASettingsDialog.categoryClasses.remove(RemoteElementMarkerSettingsPanel)
			self._settings_registered = False
		except Exception as e:
			log.debugWarning(f"Failed to unregister settings panel: {e}")

	def terminate(self):
		self._stop_nav_monitor()
		self._unregister_settings_panel()

	def _load_announce_enabled(self) -> bool:
		"""Read the persisted enabled state from config. Called once at startup
		and after toggling, not on every event."""
		try:
			return bool(config.conf["remoteElementMarker"]["announceLabels"])
		except Exception:
			return False

	@script(
		description="Toggle Remote Element Marker label announcements on or off.",
		gesture="kb:NVDA+windows+shift+a"
	)
	def script_toggleAnnounceLabels(self, gesture):
		self._announce_enabled = not self._announce_enabled
		try:
			config.conf["remoteElementMarker"]["announceLabels"] = self._announce_enabled
		except Exception:
			pass
		if self._announce_enabled:
			self._schedule_nav_monitor_tick()
			ui.message("Remote Element Marker on.")
		else:
			self._stop_nav_monitor()
			self._current_nav_marker_key = None
			ui.message("Remote Element Marker off.")

	def _schedule_nav_monitor_tick(self):
		if self._nav_monitor_timer is not None:
			return
		try:
			self._nav_monitor_timer = wx.CallLater(
				self._nav_monitor_interval_ms,
				self._on_nav_monitor_tick,
			)
		except Exception:
			self._nav_monitor_timer = None

	def _stop_nav_monitor(self):
		timer = self._nav_monitor_timer
		self._nav_monitor_timer = None
		if not timer:
			return
		try:
			if timer.IsRunning():
				timer.Stop()
		except Exception:
			pass

	def _on_nav_monitor_tick(self):
		# Timer is one-shot; clear handle first so it can be re-scheduled.
		self._nav_monitor_timer = None
		if not self._announce_enabled:
			# Feature was toggled off while timer was pending — stay stopped.
			return
		try:
			self._announce_current_navigation_label(prefer_caret=True, from_timer=True)
		except Exception:
			pass
		self._schedule_nav_monitor_tick()

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if self._in_overlay:
			return
		if not self._announce_enabled:
			return
		# Cheap pre-check: if there are no markers at all, skip everything.
		if not self._store.all_markers():
			return
		try:
			self._in_overlay = True
			marker = self._get_marker_for_obj(obj)
			if not marker:
				return
			friendly = marker.get("friendlyName")
			if not friendly:
				return
			obj._remoteElementMarkerFriendlyName = friendly
			if FriendlyNameOverlay not in clsList:
				clsList.insert(0, FriendlyNameOverlay)
		finally:
			self._in_overlay = False

	def _get_marker_for_obj(self, obj) -> Optional[Dict[str, Any]]:
		try:
			signature = generate_signature(obj)
			sig_hash = signature["hash"]
			backend = signature.get("backend")
			app_key = self._get_app_key(obj)
			base_key = app_key.split("|doc:", 1)[0]
			keys_to_search = [app_key]
			if base_key != app_key:
				keys_to_search.append(base_key)

			# Keep document matching strict: for a document-scoped context,
			# do not search other document keys from the same app base.
			if "|doc:" not in app_key:
				# If the current object doesn't carry doc identity (common for some
				# browse-caret objects), recover active document key(s) from live
				# context and include only those.
				for candidate in self._get_app_key_candidates():
					if "|doc:" not in candidate:
						continue
					if candidate.split("|doc:", 1)[0] != base_key:
						continue
					if candidate not in keys_to_search:
						keys_to_search.append(candidate)
				for stored_key in self._store.all_markers():
					if "|doc:" in stored_key:
						continue
					if stored_key.split("|doc:", 1)[0] != base_key:
						continue
					if stored_key not in keys_to_search:
						keys_to_search.append(stored_key)
			for key in keys_to_search:
				markers = self._store.get_markers(key)
				if not markers:
					continue
				marker = markers.get(sig_hash)
				if marker:
					return marker
				if backend != "BrowseMode":
					continue
				s_primary = signature.get("primarySignature", {})
				s_name = s_primary.get("name", "") or ""
				s_url = s_primary.get("url_if_web", "") or ""
				s_role = s_primary.get("role")
				for m in markers.values():
					if m.get("backend") != "BrowseMode":
						continue
					m_primary = m.get("primarySignature", {})
					if m_primary.get("role") != s_role:
						continue
					m_name = m_primary.get("name", "") or m.get("fuzzyHints", {}).get("name", "") or ""
					if m_name and s_name and m_name != s_name:
						continue
					m_url = m_primary.get("url_if_web", "") or m.get("fuzzyHints", {}).get("url_if_web", "") or ""
					if m_url and s_url and m_url != s_url:
						continue
					return m
		except Exception as e:
			log.debugWarning(f"_get_marker_for_obj error: {e}")
		return None

	def _get_marker_for_obj_or_ancestors(self, obj) -> Optional[Dict[str, Any]]:
		cur = obj
		seen = set()
		depth = 0
		while cur and depth < 6:
			oid = id(cur)
			if oid in seen:
				break
			seen.add(oid)
			marker = self._get_marker_for_obj(cur)
			if marker:
				return marker
			try:
				cur = getattr(cur, "parent", None)
			except Exception:
				cur = None
			depth += 1
		return None

	def _extract_caret_object(self, obj):
		if not obj:
			return None

		def _obj_from_text_info(ti_obj):
			try:
				caret_info = ti_obj.makeTextInfo(textInfos.POSITION_CARET)
			except Exception:
				return None
			return getattr(caret_info, "focusableNVDAObjectAtStart", None) or getattr(
				caret_info, "NVDAObjectAtStart", None
			)

		# Case 1: browse-mode event object is often a TreeInterceptor itself.
		if hasattr(obj, "makeTextInfo"):
			caret_obj = _obj_from_text_info(obj)
			if caret_obj:
				return caret_obj

		# Case 2: standard NVDAObject path via attached treeInterceptor.
		ti = getattr(obj, "treeInterceptor", None)
		if ti and getattr(ti, "isReady", False):
			caret_obj = _obj_from_text_info(ti)
			if caret_obj:
				return caret_obj

		return None

	def _iter_navigation_context_objects(self, event_obj=None):
		seen = set()

		def push(o):
			if not o:
				return
			oid = id(o)
			if oid in seen:
				return
			seen.add(oid)
			return o

		first = push(event_obj)
		if first:
			yield first
		for getter in (api.getNavigatorObject, api.getFocusObject, api.getForegroundObject):
			try:
				obj = push(getter())
				if obj:
					yield obj
			except Exception:
				continue

	def _resolve_active_navigation_target(self, event_obj=None, prefer_caret=False):
		if prefer_caret:
			for context_obj in self._iter_navigation_context_objects(event_obj):
				caret_obj = self._extract_caret_object(context_obj)
				if caret_obj:
					return caret_obj
		for context_obj in self._iter_navigation_context_objects(event_obj):
			return context_obj
		return None

	def _announce_friendly_label_for_obj(self, obj, from_timer: bool = False) -> None:
		if not self._announce_enabled:
			return
		marker = self._get_marker_for_obj_or_ancestors(obj)
		if not marker:
			self._current_nav_marker_key = None
			return
		friendly = marker.get("friendlyName")
		if not friendly:
			self._current_nav_marker_key = None
			return
		announcement_key = (marker.get("hash", "") or "") + "|" + friendly
		now = time.monotonic()
		if from_timer:
			# Timer is a safety net for fast navigation that the event path missed.
			# Stay silent if the event-driven path already announced this label
			# (normal case), or if the timer already fired recently.
			if announcement_key == self._current_nav_marker_key:
				return
			if (now - self._last_timer_announce_time) < (self._nav_monitor_interval_ms / 1000.0 + 0.1):
				return
			self._last_timer_announce_time = now
		else:
			# Event-driven path: suppress only true rapid duplicates (< 0.35s)
			# from the same label so closely-spaced caret/focus events don't
			# double-speak, but always announce if the label changed.
			last_key, last_time = self._last_label_announcement
			if announcement_key == last_key and (now - last_time) < 0.35:
				return
		self._current_nav_marker_key = announcement_key
		self._last_label_announcement = (announcement_key, now)
		# Queue speech after the current navigation utterance so it is not
		# immediately replaced by browse-mode speech output.
		queueHandler.queueFunction(queueHandler.eventQueue, ui.message, friendly)

	def _announce_current_navigation_label(self, event_obj=None, prefer_caret=False, from_timer=False):
		target = self._resolve_active_navigation_target(
			event_obj=event_obj,
			prefer_caret=prefer_caret,
		)
		if not target:
			self._current_nav_marker_key = None
			return
		self._announce_friendly_label_for_obj(target, from_timer=from_timer)

	def event_gainFocus(self, obj, nextHandler):
		if nextHandler:
			nextHandler()
		if not self._announce_enabled:
			return
		try:
			self._announce_current_navigation_label(event_obj=obj, prefer_caret=True)
		except Exception:
			pass

	def event_becomeNavigatorObject(self, obj, nextHandler, isFocus=False):
		if nextHandler:
			nextHandler()
		if not self._announce_enabled:
			return
		try:
			self._announce_current_navigation_label(event_obj=obj, prefer_caret=True)
		except Exception:
			pass

	def event_caret(self, obj, nextHandler):
		if nextHandler:
			nextHandler()
		if not self._announce_enabled:
			return
		now = time.monotonic()
		# Caret events fire very frequently; throttling avoids event-queue load.
		if (now - self._last_caret_announce_time) < 0.08:
			return
		self._last_caret_announce_time = now
		try:
			self._announce_current_navigation_label(event_obj=obj, prefer_caret=True)
		except Exception:
			pass

	def _register_dynamic_script(self, script_name: str, app_key: str, sig_hash: str, friendly_name: str):
		def script_func(self, gesture):
			self._invoke_marker(app_key, sig_hash)
		script_func.__doc__ = f"Activate marker: {friendly_name}"
		setattr(self.__class__, f"script_{script_name}", script_func)
		self._dynamic_script_names.add(script_name)

	def _remove_dynamic_scripts(self):
		for name in list(self._dynamic_script_names):
			attr = f"script_{name}"
			if hasattr(self.__class__, attr):
				delattr(self.__class__, attr)
		self._dynamic_script_names.clear()

	def _find_conflicts(self, shortcut: str):
		if not inputCore.manager:
			return None
		try:
			mappings = inputCore.manager.getAllGestureMappings()
		except Exception:
			return None
		conflicts = []
		for category, scripts in mappings.items():
			for script_info in scripts.values():
				if shortcut in script_info.gestures:
					conflicts.append((category, script_info.displayName))
		return conflicts

	@script(
		description="Captures the element under the mouse pointer to assign a custom name and shortcut.",
		gesture="kb:NVDA+windows+m"
	)
	def script_markElementFromMouse(self, gesture):
		obj = api.getMouseObject()
		if not obj:
			ui.message("No object found under the mouse.")
			return
		self._beginMarkingProcess(obj, "Mouse")

	@script(
		description="Captures the element at the navigator object or virtual caret to assign a custom name and shortcut.",
		gesture="kb:NVDA+windows+n"
	)
	def script_markElementFromNavigator(self, gesture):
		obj = api.getNavigatorObject()
		treeInterceptor = getattr(obj, "treeInterceptor", None)
		if treeInterceptor and treeInterceptor.isReady and not treeInterceptor.passThrough:
			try:
				caretInfo = treeInterceptor.makeTextInfo(textInfos.POSITION_CARET)
				caretObj = getattr(caretInfo, "focusableNVDAObjectAtStart", None) or getattr(
					caretInfo, "NVDAObjectAtStart", None
				)
				if caretObj:
					obj = caretObj
			except NotImplementedError:
				pass
		if not obj:
			ui.message("No navigator object found.")
			return
		self._beginMarkingProcess(obj, "Navigator")

	@script(
		description="Opens the Remote Element Marker Manager for the current application.",
		gesture="kb:NVDA+windows+shift+m"
	)
	def script_openMarkerManager(self, gesture):
		candidates = self._get_app_key_candidates()
		app_key = None
		markers_dict = {}
		for candidate in candidates:
			md = self._store.get_markers(candidate)
			if md:
				app_key = candidate
				markers_dict = md
				break
		if not markers_dict:
			display = self._format_app_name(candidates[0]) if candidates else "this application"
			ui.message(f"No markers saved for {display}.")
			return

		def run_manager_dialog():
			nvda_gui.mainFrame.prePopup()
			from .gui import MarkerManagerDialog
			d = MarkerManagerDialog(nvda_gui.mainFrame, app_key, markers_dict, self._delete_marker_callback)
			d.ShowModal()
			nvda_gui.mainFrame.postPopup()

		wx.CallAfter(run_manager_dialog)

	@script(
		description="Opens the Remote Element Marker list for the current application.",
		gesture="kb:NVDA+alt+l"
	)
	def script_openMarkerList(self, gesture):
		# Capture everything needed BEFORE the dialog opens and steals focus from the browser.
		pre_candidates = self._get_app_key_candidates()
		pre_root = self._get_browse_root()
		log.debugWarning(f"REM openMarkerList: candidates={pre_candidates}, root={getattr(pre_root, 'name', None) or '?'}")

		items = self._get_markers_for_current_app()
		if not items:
			ui.message("No markers saved for current application.")
			return

		def run_picker_dialog():
			nvda_gui.mainFrame.prePopup()
			from .gui import MarkerPickerDialog
			d = MarkerPickerDialog(nvda_gui.mainFrame, items)
			if d.ShowModal() == wx.ID_OK:
				sig_hash = getattr(d, "selected_hash", None)
				app_key = getattr(d, "selected_app_key", None)
				if sig_hash and app_key:
					# Pass pre_root so _invoke_marker uses the browser root
					# captured before the dialog opened, not the NVDA dialog root.
					self._invoke_marker(
						app_key, sig_hash,
						pre_candidates=pre_candidates,
						pre_root=pre_root,
					)
			nvda_gui.mainFrame.postPopup()

		wx.CallAfter(run_picker_dialog)

	@script(
		description="Arms capture for the next mouse click so a sighted user can click an element to mark.",
		gesture="kb:NVDA+windows+c"
	)
	def script_armClickCapture(self, gesture):
		if self._capture_next_click:
			self._capture_next_click = False
			ui.message("Remote click capture canceled.")
		else:
			self._capture_next_click = True
			ui.message("Remote click capture armed. Click an element now.")

	def _delete_marker_callback(self, app_key: str, sig_hash: str):
		if self._store.delete_marker(app_key, sig_hash):
			self._save_store()
			self._bind_saved_shortcuts()
			log.debugWarning(f"REM deleted marker {sig_hash} for {app_key}")

	def _get_browse_root(self):
		"""
		Get the treeInterceptor rootNVDAObject for BrowseMode resolution.
		Must be called while the target browser window is active.
		"""
		for getter in [api.getNavigatorObject, api.getFocusObject]:
			try:
				obj = getter()
				if obj:
					ti = getattr(obj, "treeInterceptor", None)
					if ti and getattr(ti, "isReady", False):
						root = getattr(ti, "rootNVDAObject", None)
						if root:
							log.debugWarning(f"REM _get_browse_root: found root={getattr(root, 'name', '?')!r} via {getter.__name__}")
							return root
			except Exception:
				pass
		fg = api.getForegroundObject()
		log.debugWarning(f"REM _get_browse_root: falling back to foreground={getattr(fg, 'appName', '?')}")
		return fg

	def _beginMarkingProcess(self, obj, source):
		app_key = self._get_app_key(obj)
		signature = generate_signature(obj)
		log.debugWarning(f"REM generated signature for {source} object: {signature}")

		def run_dialog():
			nvda_gui.mainFrame.prePopup()
			default_name = getattr(obj, "name", "") or getattr(obj, "roleText", "") or "Element"
			d = MarkerDialog(nvda_gui.mainFrame, default_name=default_name)
			if d.ShowModal() == wx.ID_OK:
				name = d.friendly_name
				shortcut = d.shortcut
				normalized = normalize_shortcut(shortcut) if shortcut else ""
				if shortcut and not normalized:
					ui.message("Invalid gesture. Use an NVDA gesture identifier like kb:NVDA+shift+v.")
					return
				if normalized:
					conflicts = self._find_conflicts(normalized)
					if conflicts:
						conflict_text = "; ".join([f"{n} ({cat})" for cat, n in conflicts])
						ui.message(f"Gesture already assigned: {conflict_text}")
						return
					if self._is_shortcut_taken(normalized, app_key, signature["hash"]):
						ui.message("That shortcut is already assigned to another marker.")
						return
				self._save_new_marker(app_key, signature, name, normalized)
				if normalized:
					ui.message(f"Marker '{name}' saved with shortcut {normalized}.")
				else:
					ui.message(f"Marker '{name}' saved without a shortcut.")
			nvda_gui.mainFrame.postPopup()

		wx.CallAfter(run_dialog)

	def event_mouseDown(self, obj, nextHandler):
		if self._capture_next_click:
			self._capture_next_click = False
			if obj:
				queueHandler.queueFunction(
					queueHandler.eventQueue,
					lambda: self._beginMarkingProcess(obj, "MouseClick")
				)
			else:
				ui.message("No object found at click.")
		if nextHandler:
			nextHandler()

	def _is_shortcut_taken(self, shortcut: str, app_key: str, sig_hash: str) -> bool:
		for existing_app_key, app_data in self._store.all_markers().items():
			for existing_hash, marker_data in app_data.get("markers", {}).items():
				if existing_app_key == app_key and existing_hash == sig_hash:
					continue
				existing_shortcut = normalize_shortcut(marker_data.get("shortcut", ""))
				if existing_shortcut == shortcut:
					return True
		return False

	def _save_new_marker(self, app_key: str, signature: Dict[str, Any], name: str, shortcut: str):
		sig_hash = signature["hash"]
		signature["friendlyName"] = name
		signature["shortcut"] = shortcut
		self._store.set_marker(app_key, sig_hash, signature)
		self._save_store()
		self._bind_saved_shortcuts()

	def _invoke_marker(
		self,
		app_key: str,
		sig_hash: str,
		pre_candidates: Optional[List[str]] = None,
		pre_root=None,
	):
		"""
		Validate app context, resolve the element, and activate it.
		pre_candidates / pre_root: captured before any dialog opened (picker list path).
		When None, captures live (shortcut path — browser is still foreground).
		"""
		marker_data = self._store.get_marker(app_key, sig_hash)
		if not marker_data:
			ui.message("Marker data corrupted or missing.")
			return

		candidates = pre_candidates if pre_candidates else self._get_app_key_candidates()
		base_target = app_key.split("|doc:", 1)[0]
		base_candidates = {c.split("|doc:", 1)[0] for c in candidates}

		log.debugWarning(f"REM invoking marker. Candidates={candidates}, Target={app_key}")

		if not ((app_key in candidates) or (base_target in base_candidates)):
			log.warning(f"App key mismatch. Target base={base_target}, Candidates={base_candidates}")
			ui.message("Element not found. Application context mismatch.")
			return

		ui.message(f"Resolving {marker_data.get('friendlyName')}...")

		# Determine the root object for tree traversal.
		# For the shortcut path (pre_root=None): capture live now — browser is still active.
		# For the picker path (pre_root set): use what was captured before dialog opened.
		if pre_root is not None:
			resolve_root = pre_root
			log.debugWarning(f"REM using pre_root: {getattr(resolve_root, 'name', '?')!r}")
		else:
			resolve_root = self._get_browse_root() if marker_data.get("backend") == "BrowseMode" else api.getForegroundObject()
			log.debugWarning(f"REM using live root: {getattr(resolve_root, 'name', None) or getattr(resolve_root, 'appName', '?')!r}")

		def on_resolve_done(target_obj):
			self._activate_resolved_element(target_obj, marker_data)

		resolve_element(marker_data, resolve_root, on_resolve_done)

	def _activate_resolved_element(self, obj: Optional[Any], marker_data: Dict[str, Any]):
		if not obj:
			ui.message("Element not found. Please re-mark the element.")
			log.warning("Element resolution failed.")
			return

		try:
			states = obj.states
			if controlTypes.State.UNAVAILABLE in states or controlTypes.State.INVISIBLE in states:
				ui.message("Element found but currently unavailable or invisible.")
				return
		except Exception:
			pass

		treeInterceptor = getattr(obj, "treeInterceptor", None)
		if treeInterceptor and treeInterceptor.isReady and not treeInterceptor.passThrough:
			try:
				info = obj.makeTextInfo(textInfos.POSITION_FIRST)
				treeInterceptor.selection = info
				obj.scrollIntoView()
				ui.message(f"Moved to {marker_data.get('friendlyName')}")
			except Exception as e:
				log.error(f"Failed to move virtual caret: {e}")
				try:
					obj.setFocus()
				except Exception:
					pass
		else:
			try:
				obj.setFocus()
			except Exception as e:
				log.error(f"Failed to set focus: {e}")

		try:
			obj.doAction()
		except Exception as e:
			log.debugWarning(f"REM doAction not supported or failed: {e}")

# -*- coding: UTF-8 -*-
# Remote Element Marker

from typing import Dict, Any, Optional, List
import time


import globalPluginHandler  # type: ignore
import addonHandler  # type: ignore
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
from .storage import MarkerStore, is_stable_document_identifier
from .signature import generate_signature_for_lookup, generate_signature_async
from .resolver import resolve_element
from .bindings import normalize_shortcut
from .settings import RemoteElementMarkerSettingsPanel
from .beep import beep_success, beep_failure, ProgressBeeper

addonHandler.initTranslation()

def _shortcut_to_script_suffix(shortcut: str) -> str:
	"""
	 Convert a normalized shortcut string like 'kb:NVDA+alt+1' into a safe
	Python identifier suffix like 'kb_NVDA_alt_1' for use as a script name.
	"""
	import re
	return re.sub(r"[^a-zA-Z0-9]", "_", shortcut)


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
		# Cache beep enabled state — read once at startup, updated live from settings.
		self._beep_enabled = self._load_beep_enabled()
		# Cache whether resolve should trigger the target after navigation.
		self._activate_after_resolve = self._load_activate_after_resolve()
		# Active progress beeper for the current resolve operation (if any).
		self._progress_beeper: Optional[ProgressBeeper] = None
		self._register_settings_panel()
		self._bind_saved_shortcuts()
		if self._announce_enabled:
			self._schedule_nav_monitor_tick()

	def _bind_saved_shortcuts(self):
		"""
		Bind marker shortcuts as document-scoped dispatchers.

		Each unique shortcut string gets exactly ONE bound script — a dispatcher
		that, at invocation time, looks up which marker in the *current document*
		uses that shortcut.  This allows the same gesture (e.g. NVDA+Alt+1) to be
		assigned to different markers on different pages / applications without
		conflict, and prevents the gesture from firing when the target document is
		not open.
		"""
		self.clearGestureBindings()
		self.bindGestures(
			{
				"kb:NVDA+alt+n": "markElementFromMouse",
				"kb:NVDA+alt+b": "markElementFromNavigator",
				"kb:NVDA+alt+shift+m": "openMarkerManager",
				"kb:NVDA+alt+l": "openMarkerList",
				"kb:NVDA+alt+a": "toggleAnnounceLabels",
			}
		)
		self._remove_dynamic_scripts()

		# Collect every unique shortcut string across ALL documents.
		# We register one dispatcher script per shortcut, not one per marker.
		unique_shortcuts = set()
		for app_key, app_data in self._store.all_markers().items():
			for marker_data in app_data.get("markers", {}).values():
				shortcut = normalize_shortcut(marker_data.get("shortcut", ""))
				if shortcut:
					unique_shortcuts.add(shortcut)

		for shortcut in unique_shortcuts:
			script_name = f"invokeMarkerByShortcut_{_shortcut_to_script_suffix(shortcut)}"
			self._register_shortcut_dispatcher(script_name, shortcut)
			self.bindGesture(shortcut, script_name)

	def _get_app_key(self, obj) -> str:
		return self._store.get_app_key(obj)

	def _get_storage_app_key(self, obj, signature: Optional[Dict[str, Any]] = None) -> str:
		"""
		Choose the storage bucket that best matches the captured signature.

		Hybrid Chromium BrowseMode captures may come from a ChromiumUIA object whose
		own treeInterceptor/app context does not match the active document-scoped key.
		In that case prefer a live candidate whose doc id matches the signature URL.
		"""
		default_key = self._get_app_key(obj)
		if not signature:
			return default_key
		if signature.get("backend") != "BrowseMode":
			return default_key
		target_url = (signature.get("primarySignature", {}) or {}).get("url_if_web", "") or ""
		if not target_url:
			return default_key
		if not is_stable_document_identifier(target_url):
			base_key = self._get_base_app_key(obj)
			log.debugWarning(
				f"REM storage app key: unstable target_url={target_url!r}, "
				f"using base app key={base_key!r}"
			)
			return base_key
		for candidate in self._get_app_key_candidates():
			if "|doc:" not in candidate:
				continue
			doc_part = candidate.split("|doc:", 1)[1]
			if doc_part == target_url:
				log.debugWarning(
					f"REM storage app key: using live doc candidate={candidate!r} "
					f"for target_url={target_url!r} instead of default={default_key!r}"
				)
				return candidate
		log.debugWarning(
			f"REM storage app key: no doc candidate matched target_url={target_url!r}, "
			f"falling back to default={default_key!r}"
		)
		return default_key

	def _is_legacy_unstable_doc_key(self, app_key: str) -> bool:
		if "|doc:" not in app_key:
			return False
		doc_part = app_key.split("|doc:", 1)[1].strip()
		return not is_stable_document_identifier(doc_part)

	def _app_key_matches_current_context(
		self,
		app_key: str,
		candidate_set: set,
		base_keys: set,
		doc_keys: set,
	) -> bool:
		base = app_key.split("|doc:", 1)[0]
		is_doc_scoped = "|doc:" in app_key
		if not is_doc_scoped:
			return app_key in candidate_set or base in base_keys
		if app_key in doc_keys:
			return True
		if self._is_legacy_unstable_doc_key(app_key):
			return base in base_keys
		return False

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
			if not self._app_key_matches_current_context(app_key, candidate_set, base_keys, doc_keys):
				continue

			for sig_hash, marker_data in app_data.get("markers", {}).items():
				label = marker_data.get("friendlyName", "Unknown")
				if "|doc:" in app_key and not self._is_legacy_unstable_doc_key(app_key):
					label = f"{label} [{app_key.split('doc:', 1)[1]}]"
				items.append(
					{
						"app_key": app_key,
						"sig_hash": sig_hash,
						"label": label,
					}
				)
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
			if "beepEnabled" not in config.conf.spec["remoteElementMarker"]:
				config.conf.spec["remoteElementMarker"]["beepEnabled"] = "boolean(default=True)"
			_ = config.conf["remoteElementMarker"]["beepEnabled"]
			if "activateAfterResolve" not in config.conf.spec["remoteElementMarker"]:
				config.conf.spec["remoteElementMarker"]["activateAfterResolve"] = "boolean(default=True)"
			_ = config.conf["remoteElementMarker"]["activateAfterResolve"]
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
		self._stop_progress_beeper()
		self._stop_nav_monitor()
		self._unregister_settings_panel()

	def _load_announce_enabled(self) -> bool:
		"""Read the persisted enabled state from config. Called once at startup
		and after toggling, not on every event."""
		try:
			return bool(config.conf["remoteElementMarker"]["announceLabels"])
		except Exception:
			return False

	def _load_beep_enabled(self) -> bool:
		"""Read the beep-enabled state from config. Default is True."""
		try:
			return bool(config.conf["remoteElementMarker"]["beepEnabled"])
		except Exception:
			return True

	def _load_activate_after_resolve(self) -> bool:
		"""Read whether resolving should activate the target. Default is True."""
		try:
			return bool(config.conf["remoteElementMarker"]["activateAfterResolve"])
		except Exception:
			return True

	def _move_to_browse_mode_target(self, obj) -> bool:
		treeInterceptor = getattr(obj, "treeInterceptor", None)
		if not (treeInterceptor and treeInterceptor.isReady and not treeInterceptor.passThrough):
			return False
		info = obj.makeTextInfo(textInfos.POSITION_FIRST)
		info.collapse()
		try:
			set_selection = getattr(treeInterceptor, "_set_selection", None)
			if callable(set_selection):
				set_selection(info)
				log.debugWarning("REM browse move: used treeInterceptor._set_selection().")
			else:
				treeInterceptor.selection = info
				log.debugWarning("REM browse move: used treeInterceptor.selection.")
		except Exception:
			info.updateCaret()
			log.debugWarning("REM browse move: used info.updateCaret().")
		api.setReviewPosition(info, clearNavigatorObject=False, isCaret=True)
		api.setNavigatorObject(obj)
		try:
			obj.scrollIntoView()
		except Exception as e:
			log.debugWarning(f"REM browse move: scrollIntoView failed: {e}")
		return True

	def _move_focus_to_target(self, obj, from_browse_mode: bool = False) -> bool:
		try:
			obj.setFocus()
			api.setNavigatorObject(obj, isFocus=True)
			log.debugWarning(
				f"REM focus move: setFocus succeeded (from_browse_mode={from_browse_mode})."
			)
			return True
		except Exception as e:
			log.debugWarning(
				f"REM focus move: setFocus failed (from_browse_mode={from_browse_mode}): {e}"
			)
			return False

	# ------------------------------------------------------------------ #
	# Progress beeper helpers                                             #
	# ------------------------------------------------------------------ #

	def _start_progress_beeper(self) -> None:
		"""Start the progress beeper if beeps are enabled. Stops any running one first."""
		self._stop_progress_beeper()
		if not self._beep_enabled:
			return
		try:
			self._progress_beeper = ProgressBeeper()
			self._progress_beeper.start()
		except Exception as e:
			log.debugWarning(f"REM _start_progress_beeper error: {e}")
			self._progress_beeper = None

	def _stop_progress_beeper(self) -> None:
		"""Stop and discard the active progress beeper."""
		pb = self._progress_beeper
		self._progress_beeper = None
		if pb is not None:
			try:
				pb.stop()
			except Exception:
				pass

	@script(
		description="Toggle Remote Element Marker label announcements on or off.",
		gesture="kb:NVDA+alt+a",
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
			# Use the lightweight lookup variant — no getTextWithFields() call.
			# Position hints are only needed at mark time, not on every nav event.
			signature = generate_signature_for_lookup(obj)
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
				# Hash miss — fall back to position-aware BrowseMode matching.
				# This handles old markers saved before role_index/context were
				# added, or edge cases where NVDA rebuilds the object with a
				# slightly different wrapper. The fallback MUST enforce name
				# equality (including empty names) and position hints so that
				# unlabeled buttons are not confused with each other.
				if backend != "BrowseMode":
					continue
				s_primary = signature.get("primarySignature", {})
				s_name = (s_primary.get("name", "") or "").strip()
				s_url = s_primary.get("url_if_web", "") or ""
				s_role = s_primary.get("role")
				# generate_signature_for_lookup produces no position hints.
				# Compute them lazily once, only if any stored marker needs them.
				_live_pos = None  # (role_index, context_before, context_after)

				def _get_live_pos():
					nonlocal _live_pos
					if _live_pos is None:
						from .signature import _compute_position_hints as _cph
						ti = getattr(obj, "treeInterceptor", None)
						pos = _cph(obj, ti)
						_live_pos = (
							pos["role_index"],
							pos["context_before"],
							pos["context_after"],
						)
					return _live_pos

				for m in markers.values():
					if m.get("backend") != "BrowseMode":
						continue
					m_primary = m.get("primarySignature", {})
					if m_primary.get("role") != s_role:
						continue
					# Always enforce name equality, even when both are empty.
					m_name = (m_primary.get("name", "") or "").strip()
					if m_name != s_name:
						continue
					# URL must match when present.
					m_url = (m_primary.get("url_if_web", "") or "").strip()
					if m_url and s_url and m_url != s_url:
						continue
					# Position hints from the stored marker.
					m_role_index = m_primary.get("role_index", -1)
					m_context_before = m_primary.get("context_before", "")
					m_context_after = m_primary.get("context_after", "")
					has_context = bool(m_context_before or m_context_after)
					has_index = m_role_index >= 0
					if has_index:
						# Compute live position once (lazy, shared across marker loop).
						live_idx, live_before, live_after = _get_live_pos()
						if live_idx >= 0 and live_idx != m_role_index:
							# Index mismatch — check context as fallback for dynamic pages.
							if has_context:
								ctx_ok = True
								if m_context_before and m_context_before not in live_before and live_before not in m_context_before:
									ctx_ok = False
								if m_context_after and m_context_after not in live_after and live_after not in m_context_after:
									ctx_ok = False
								if not ctx_ok:
									continue
							else:
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
			for position in (textInfos.POSITION_CARET, textInfos.POSITION_SELECTION):
				try:
					info = ti_obj.makeTextInfo(position)
				except Exception:
					continue
				for candidate in (
					getattr(info, "NVDAObjectAtStart", None),
					getattr(info, "focusableNVDAObjectAtStart", None),
				):
					if candidate:
						return candidate
			return None

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

	def _register_shortcut_dispatcher(self, script_name: str, shortcut: str):
		"""
		Register a dispatcher script for a shortcut string.

		At invocation time the dispatcher:
		  1. Determines the active document key(s).
		  2. Searches for a marker in those documents that uses this shortcut.
		  3. If found, invokes it.  If not found (wrong document / app), speaks
		     a friendly "not available here" message instead of silently resolving.
		"""
		def script_func(self_plugin, gesture):
			self_plugin._dispatch_shortcut(shortcut)

		script_func.__doc__ = f"Remote Element Marker shortcut dispatcher for {shortcut}"
		setattr(self.__class__, f"script_{script_name}", script_func)
		self._dynamic_script_names.add(script_name)

	def _dispatch_shortcut(self, shortcut: str):
		"""
		Find the marker for *shortcut* that belongs to the current document and
		invoke it.  If no marker matches the current document, tell the user.
		"""
		candidates = self._get_app_key_candidates()
		candidate_set = set(candidates)
		base_candidates = {c.split("|doc:", 1)[0] for c in candidates}
		doc_candidates = {c for c in candidates if "|doc:" in c}

		for app_key, app_data in self._store.all_markers().items():
			if not self._app_key_matches_current_context(app_key, candidate_set, base_candidates, doc_candidates):
				continue

			# --- shortcut match ---
			for sig_hash, marker_data in app_data.get("markers", {}).items():
				stored = normalize_shortcut(marker_data.get("shortcut", ""))
				if stored == shortcut:
					log.debugWarning(
						f"REM dispatcher matched shortcut={shortcut} -> "
						f"app_key={app_key}, hash={sig_hash}"
					)
					self._invoke_marker(app_key, sig_hash)
					return

		# No match for the current document.
		ui.message("This shortcut has no marker for the current document.")
		log.debugWarning(
			f"REM dispatcher: no match for shortcut={shortcut} in candidates={candidates}"
		)

	def _register_dynamic_script(self, script_name: str, app_key: str, sig_hash: str, friendly_name: str):
		"""Legacy helper kept for external callers; internally unused."""
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

	@staticmethod
	def _gesture_variants(shortcut: str):
		"""
		Return the set of normalised gesture identifiers that are effectively
		equivalent to *shortcut* across keyboard layouts.

		NVDA stores gestures in three layout namespaces:
		  kb:          — all layouts
		  kb(laptop):  — laptop layout only
		  kb(desktop): — desktop layout only

		A gesture assigned to "all layouts" (kb:) conflicts with the same
		key in any specific layout and vice-versa.  We expand the shortcut
		into all three variants so the caller can check them all at once.
		"""
		variants = {shortcut}
		if ":" not in shortcut:
			return variants
		source, rest = shortcut.split(":", 1)
		sl = source.lower()
		if sl == "kb":
			# all-layouts gesture also conflicts with laptop/desktop specifics
			variants.add(f"kb(laptop):{rest}")
			variants.add(f"kb(desktop):{rest}")
		elif sl in ("kb(laptop)", "kb(desktop)"):
			# specific-layout gesture also conflicts with the all-layouts one
			variants.add(f"kb:{rest}")
			# and with the other specific layout (they share the same physical key)
			other = "kb(desktop)" if sl == "kb(laptop)" else "kb(laptop)"
			variants.add(f"{other}:{rest}")
		return variants

	def _find_conflicts(self, shortcut: str):
		"""
		Return a list of (category, displayName) tuples for every NVDA script
		that uses a gesture effectively equivalent to *shortcut*, across all
		keyboard-layout variants (kb:, kb(laptop):, kb(desktop):).
		"""
		if not inputCore.manager:
			return None
		try:
			mappings = inputCore.manager.getAllGestureMappings()
		except Exception:
			return None
		variants = self._gesture_variants(shortcut)
		conflicts = []
		for category, scripts in mappings.items():
			for script_info in scripts.values():
				# script_info.gestures is a set/list of normalised gesture strings
				for g in script_info.gestures:
					if g in variants:
						conflicts.append((category, script_info.displayName))
						break  # don't double-count the same script
		return conflicts

	@script(
		description="Captures the element under the mouse pointer to assign a custom name and shortcut.",
		gesture="kb:NVDA+alt+n",
	)
	def script_markElementFromMouse(self, gesture):
		obj = api.getMouseObject()
		if not obj:
			ui.message("No object found under the mouse.")
			return
		self._beginMarkingProcess(obj, "Mouse")

	@script(
		description="Captures the element at the navigator object or virtual caret to assign a custom name and shortcut.",
		gesture="kb:NVDA+alt+b",
	)
	def script_markElementFromNavigator(self, gesture):
		obj = api.getNavigatorObject()
		treeInterceptor = getattr(obj, "treeInterceptor", None)
		if treeInterceptor and treeInterceptor.isReady and not treeInterceptor.passThrough:
			try:
				caretObj = self._extract_caret_object(obj)
				if caretObj:
					obj = caretObj
			except NotImplementedError:
				pass
		if not obj:
			ui.message("No navigator object found.")
			return
		self._beginMarkingProcess(obj, "Navigator")

	@script(
		description="Opens the Remote Element Marker Manager for all saved markers.",
		gesture="kb:NVDA+alt+shift+m",
	)
	def script_openMarkerManager(self, gesture):
		all_markers = {
			app_key: app_data
			for app_key, app_data in self._store.all_markers().items()
			if app_data.get("markers")
		}
		if not all_markers:
			ui.message("No markers saved.")
			return

		def run_manager_dialog():
			nvda_gui.mainFrame.prePopup()
			from .gui import MarkerManagerDialog

			d = MarkerManagerDialog(
				nvda_gui.mainFrame,
				all_markers,
				marker_instance=self,
				delete_callback=self._delete_marker_callback,
				edit_callback=self._edit_marker_callback,
			)
			d.ShowModal()
			nvda_gui.mainFrame.postPopup()

		wx.CallAfter(run_manager_dialog)

	@script(
		description="Opens the Remote Element Marker list for the current application.",
		gesture="kb:NVDA+alt+l",
	)
	def script_openMarkerList(self, gesture):
		# Capture everything needed BEFORE the dialog opens and steals focus from the browser.
		pre_candidates = self._get_app_key_candidates()
		pre_root = self._get_browse_root()
		log.debugWarning(
			f"REM openMarkerList: candidates={pre_candidates}, root={getattr(pre_root, 'name', None) or '?'}"
		)

		items = self._get_markers_for_current_app()
		if not items:
			ui.message("No markers saved for current application.")
			return

		def run_picker_dialog():
			nvda_gui.mainFrame.prePopup()
			from .gui import MarkerPickerDialog

			d = MarkerPickerDialog(
				nvda_gui.mainFrame,
				items,
				marker_instance=self,
				delete_callback=self._delete_marker_callback,
				edit_callback=self._edit_marker_callback,
			)
			if d.ShowModal() == wx.ID_OK:
				sig_hash = getattr(d, "selected_hash", None)
				app_key = getattr(d, "selected_app_key", None)
				if sig_hash and app_key:
					# Pass pre_root so _invoke_marker uses the browser root
					# captured before the dialog opened, not the NVDA dialog root.
					self._invoke_marker(
						app_key,
						sig_hash,
						pre_candidates=pre_candidates,
						pre_root=pre_root,
					)
			nvda_gui.mainFrame.postPopup()

		wx.CallAfter(run_picker_dialog)

	def _delete_marker_callback(self, app_key: str, sig_hash: str):
		if self._store.delete_marker(app_key, sig_hash):
			self._save_store()
			self._bind_saved_shortcuts()
			log.debugWarning(f"REM deleted marker {sig_hash} for {app_key}")

	def _edit_marker_callback(self, app_key: str, sig_hash: str, new_name: str, new_shortcut: str):
		"""
		Update an existing marker's friendly name and shortcut in place.
		The element signature (hash, backend, primarySignature, etc.) is preserved —
		only the user-facing fields are overwritten.
		"""
		marker = self._store.get_marker(app_key, sig_hash)
		if not marker:
			log.error(f"REM edit: marker not found app_key={app_key}, hash={sig_hash}")
			return
		normalized = normalize_shortcut(new_shortcut) if new_shortcut else ""
		same_name_conflict = self._find_same_doc_label_conflict(new_name, app_key, sig_hash)
		if same_name_conflict:
			self._store.delete_marker(same_name_conflict["app_key"], same_name_conflict["sig_hash"])
		marker["friendlyName"] = new_name
		marker["shortcut"] = normalized
		self._store.set_marker(app_key, sig_hash, marker)
		self._save_store()
		self._bind_saved_shortcuts()
		log.debugWarning(f"REM edited marker {sig_hash}: name={new_name!r}, shortcut={normalized!r}")

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
							log.debugWarning(
								f"REM _get_browse_root: found root={getattr(root, 'name', '?')!r} via {getter.__name__}"
							)
							return root
			except Exception:
				pass
		fg = api.getForegroundObject()
		log.debugWarning(f"REM _get_browse_root: falling back to foreground={getattr(fg, 'appName', '?')}")
		return fg

	def _log_mark_capture_timing(self, start_time: float, source: str, signature: Optional[Dict[str, Any]] = None, **kwargs) -> None:
		elapsed_ms = (time.perf_counter() - start_time) * 1000
		backend = (signature or {}).get("backend", "Unknown")
		extras = ", ".join(f"{k}={v}" for k, v in kwargs.items())
		log.debugWarning(
			f"REM Timing: mark_capture source={source} backend={backend} took {elapsed_ms:.2f}ms"
			f"{extras and ', ' + extras}"
		)

	def _beginMarkingProcess(self, obj, source):
		capture_start_time = time.perf_counter()
		ui.message("Capturing element: please wait...")
		self._start_progress_beeper()

		def on_signature_ready(signature):
			self._stop_progress_beeper()
			if not signature:
				self._log_mark_capture_timing(capture_start_time, source, success=False, emptySignature=True)
				log.error(f"REM failed to capture {source} object: empty signature")
				ui.message("Failed to capture element.")
				if self._beep_enabled:
					beep_failure()
				return
			primary = signature.get("primarySignature", {})
			fast_path = signature.get("fastPathHints", {})
			has_dom_hints = bool(fast_path.get("domHints"))
			has_runtime_id = bool(fast_path.get("runtimeId"))
			has_uia_identity = bool(
				fast_path.get("automationId")
				or fast_path.get("controlType")
				or fast_path.get("className")
			)
			if (
				signature.get("backend") == "BrowseMode"
				and primary.get("role_index", -1) < 0
				and primary.get("role_ordinal", -1) < 0
				and not has_runtime_id
				and not has_dom_hints
				and not has_uia_identity
			):
				self._log_mark_capture_timing(
					capture_start_time,
					source,
					signature,
					success=False,
					unresolvedBrowseModeIdentity=True,
				)
				log.warning(
					f"REM failed to capture {source} object: BrowseMode identity unresolved, "
					f"signature={signature}"
				)
				ui.message("Can not capture element.")
				if self._beep_enabled:
					beep_failure()
				return
			app_key = self._get_storage_app_key(obj, signature)
			self._log_mark_capture_timing(
				capture_start_time,
				source,
				signature,
				success=True,
				signatureHash=signature.get("hash", ""),
			)
			log.debugWarning(f"REM generated signature for {source} object: {signature}")

			def run_dialog():
				nvda_gui.mainFrame.prePopup()
				default_name = getattr(obj, "name", "") or getattr(obj, "roleText", "") or "Element"
				d = MarkerDialog(
					nvda_gui.mainFrame,
					default_name=default_name,
					marker_instance=self,
					app_key=app_key,
					signature_hash=signature["hash"],
				)
				if d.ShowModal() == wx.ID_OK:
					name = d.friendly_name
					shortcut = d.shortcut
					normalized = normalize_shortcut(shortcut) if shortcut else ""
					replacement = getattr(d, "replace_existing_marker", None)
					saved_ok = True
					try:
						if replacement:
							self._replace_marker(
								replacement["app_key"],
								replacement["sig_hash"],
								app_key,
								signature,
								name,
								normalized,
							)
						else:
							self._save_new_marker(app_key, signature, name, normalized)
					except Exception:
						saved_ok = False
					if normalized:
						ui.message(f"Marker '{name}' saved with shortcut {normalized}.")
					else:
						ui.message(f"Marker '{name}' saved without a shortcut.")
					# Audio feedback: delayed so speech message plays first.
					if self._beep_enabled:
						if saved_ok:
							wx.CallLater(200, beep_success)
						else:
							wx.CallLater(200, beep_failure)
				nvda_gui.mainFrame.postPopup()

			wx.CallAfter(run_dialog)
		try:
			generate_signature_async(obj, on_signature_ready)
		except Exception as e:
			self._stop_progress_beeper()
			self._log_mark_capture_timing(capture_start_time, source, success=False, exception=type(e).__name__)
			log.error(f"REM failed to capture {source} object: {e}")
			ui.message("Failed to capture element.")
			if self._beep_enabled:
				beep_failure()

	def _find_same_doc_shortcut_conflict(self, shortcut: str, app_key: str, sig_hash: str):
		"""
		Look for another marker *within the exact same document / app key* that
		already uses *shortcut* (cross-layout aware).

		Only markers stored under the identical app_key are checked.
		Markers on other documents (even from the same browser/app) are
		entirely separate scopes and must never trigger a conflict here.

		Returns a dict with keys 'friendly_name', 'app_key', 'sig_hash' if a
		conflict exists, or None if the shortcut is free in this scope.
		"""
		variants = self._gesture_variants(shortcut)
		# Only examine the single bucket that matches this exact document key.
		app_data = self._store.all_markers().get(app_key, {})
		for existing_hash, marker_data in app_data.get("markers", {}).items():
			# Skip the marker we are currently editing/creating.
			if existing_hash == sig_hash:
				continue
			existing_shortcut = normalize_shortcut(marker_data.get("shortcut", ""))
			if existing_shortcut in variants:
				return {
					"friendly_name": marker_data.get("friendlyName", "Unknown"),
					"app_key": app_key,
					"sig_hash": existing_hash,
				}
		return None

	def _is_shortcut_taken(self, shortcut: str, app_key: str, sig_hash: str) -> bool:
		"""Backward-compat wrapper — returns bool."""
		return self._find_same_doc_shortcut_conflict(shortcut, app_key, sig_hash) is not None

	def _find_same_doc_label_conflict(self, friendly_name: str, app_key: str, sig_hash: str):
		"""
		Look for another marker within the exact same document/app scope that
		already uses the same friendly label.
		"""
		name_key = (friendly_name or "").strip().casefold()
		if not name_key:
			return None
		app_data = self._store.all_markers().get(app_key, {})
		for existing_hash, marker_data in app_data.get("markers", {}).items():
			if existing_hash == sig_hash:
				continue
			existing_name = (marker_data.get("friendlyName", "") or "").strip()
			if existing_name.casefold() != name_key:
				continue
			return {
				"friendly_name": existing_name or "Unknown",
				"app_key": app_key,
				"sig_hash": existing_hash,
			}
		return None

	def _clear_shortcut_from_marker(self, app_key: str, sig_hash: str) -> None:
		"""Remove the shortcut from an existing marker without deleting it."""
		marker = self._store.get_marker(app_key, sig_hash)
		if marker:
			marker["shortcut"] = ""
			self._store.set_marker(app_key, sig_hash, marker)
			self._save_store()
			self._bind_saved_shortcuts()

	def _save_new_marker(self, app_key: str, signature: Dict[str, Any], name: str, shortcut: str):
		sig_hash = signature["hash"]
		signature["friendlyName"] = name
		signature["shortcut"] = shortcut
		self._store.set_marker(app_key, sig_hash, signature)
		self._save_store()
		self._bind_saved_shortcuts()

	def _replace_marker(
		self,
		old_app_key: str,
		old_sig_hash: str,
		new_app_key: str,
		signature: Dict[str, Any],
		name: str,
		shortcut: str,
	) -> None:
		"""
		Replace an existing marker entirely with a new marker definition.
		Used when the user reuses a friendly label and chooses Replace.
		"""
		self._store.delete_marker(old_app_key, old_sig_hash)
		self._save_new_marker(new_app_key, signature, name, shortcut)

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
			if not self._is_legacy_unstable_doc_key(app_key):
				log.warning(f"App key mismatch. Target base={base_target}, Candidates={base_candidates}")
				ui.message("Element not found. Application context mismatch.")
				return
		if self._is_legacy_unstable_doc_key(app_key) and base_target not in base_candidates:
			log.warning(f"App key mismatch. Target base={base_target}, Candidates={base_candidates}")
			ui.message("Element not found. Application context mismatch.")
			return

		ui.message(f"Resolving {marker_data.get('friendlyName')}...")

		# Start progress beeper — stopped in _activate_resolved_element.
		self._start_progress_beeper()

		# Determine the root object for tree traversal.
		# For the shortcut path (pre_root=None): capture live now — browser is still active.
		# For the picker path (pre_root set): use what was captured before dialog opened.
		if pre_root is not None:
			resolve_root = pre_root
			log.debugWarning(f"REM using pre_root: {getattr(resolve_root, 'name', '?')!r}")
		else:
			resolve_root = (
				self._get_browse_root()
				if marker_data.get("backend") == "BrowseMode"
				else api.getForegroundObject()
			)
			log.debugWarning(
				f"REM using live root: {getattr(resolve_root, 'name', None) or getattr(resolve_root, 'appName', '?')!r}"
			)

		def on_resolve_done(target_obj):
			self._activate_resolved_element(target_obj, marker_data)

		resolve_element(marker_data, resolve_root, on_resolve_done)

	def _activate_resolved_element(self, obj: Optional[Any], marker_data: Dict[str, Any]):
		# Always stop the progress beeper first, before any early return.
		self._stop_progress_beeper()

		if not obj:
			ui.message("Element not found. Please re-mark the element.")
			log.warning("Element resolution failed.")
			if self._beep_enabled:
				beep_failure()
			return

		if isinstance(obj, bool) or not hasattr(obj, "role"):
			log.warning(
				f"REM resolved invalid target object: type={type(obj).__name__!r}, value={obj!r}"
			)
			ui.message("Element found, but the resolved target is invalid. Please re-mark the element.")
			if self._beep_enabled:
				beep_failure()
			return

		try:
			states = obj.states
			if controlTypes.State.UNAVAILABLE in states or controlTypes.State.INVISIBLE in states:
				ui.message("Element found but currently unavailable or invisible.")
				if self._beep_enabled:
					beep_failure()
				return
		except Exception:
			pass

		navigated = False
		focused = False
		action_performed = False
		treeInterceptor = getattr(obj, "treeInterceptor", None)
		if treeInterceptor and treeInterceptor.isReady and not treeInterceptor.passThrough:
			try:
				navigated = self._move_to_browse_mode_target(obj)
				ui.message(f"Moved to {marker_data.get('friendlyName')}")
			except Exception as e:
				log.error(f"Failed to move virtual caret: {e}")
			if not self._activate_after_resolve:
				focused = self._move_focus_to_target(obj, from_browse_mode=True)
			elif not navigated:
				focused = self._move_focus_to_target(obj, from_browse_mode=True)
		else:
			focused = self._move_focus_to_target(obj)

		if self._activate_after_resolve and (navigated or focused):
			try:
				obj.doAction()
				action_performed = True
			except Exception as e:
				log.debugWarning(f"REM doAction not supported or failed: {e}")

		resolved_ok = navigated or focused or action_performed
		if not resolved_ok:
			ui.message("Element found but could not be reached.")
			if self._beep_enabled:
				beep_failure()
			return

		if not self._activate_after_resolve and (navigated or focused):
			log.debugWarning("REM activation skipped because activateAfterResolve is disabled.")

		if self._beep_enabled:
			beep_success()

from typing import Any, Dict, Optional, Callable

from logHandler import log  # type: ignore


def resolve_element(marker_data: Dict[str, Any], root_obj, on_done: Callable) -> None:
	"""
	Searches for the element using primary signature.
	Must be called from NVDA's main thread.

	Because COM accessibility objects (IAccessible, UIA, Chrome virtual buffer)
	are apartment-threaded they can only be accessed from the main thread.
	Running the walk on a background thread silently returns None for every
	child/property access, which is why previous threading attempts failed.

	To avoid freezing NVDA we walk the tree in small incremental chunks,
	yielding back to the main thread's wx event loop between each chunk via
	wx.CallLater(0, ...).  This keeps NVDA responsive while still doing a
	full unlimited-depth search.

	on_done(result) is called on the main thread when the walk finishes.
	result is the matched NVDAObject or None.
	"""
	import wx  # type: ignore

	backend = marker_data.get("backend")
	primary = marker_data.get("primarySignature", {})
	fast_path = marker_data.get("fastPathHints", {})

	log.debugWarning(
		f"REM resolve_element: backend={backend}, primary={primary}, "
		f"root_type={type(root_obj).__name__!r}, "
		f"root_name={getattr(root_obj, 'name', None)!r}"
	)

	# UIA: try runtimeId fast-path first — completely synchronous and fast.
	if backend == "UIA" and fast_path.get("runtimeId"):
		result = _uia_fast_path(fast_path["runtimeId"])
		if result:
			log.debugWarning("REM UIA runtimeId fast-path succeeded.")
			on_done(result)
			return

	# BrowseMode fast path: fetch all virtual-buffer objects in one batch call
	# via getTextWithFields(). This avoids per-node COM round-trips to Chrome/Firefox
	# and is typically 10-50x faster than tree-walking for browser content.
	if backend == "BrowseMode":
		result = _browsemode_batch_resolve(primary, root_obj)
		if result is not None:
			log.debugWarning("REM BrowseMode batch resolve succeeded.")
			on_done(result)
			return
		log.warning("REM BrowseMode batch resolve found no match; falling back to chunked tree walk.")

	# UIA/IAccessible (and BrowseMode fallback): chunked tree walk on main thread.
	walker = _tree_walk_iter(backend, primary, root_obj)
	_drive_walk(walker, on_done)


# ------------------------------------------------------------------ #
# BrowseMode batch resolve via getTextWithFields                      #
# ------------------------------------------------------------------ #

def _browsemode_batch_resolve(primary: Dict[str, Any], root_obj) -> Optional[Any]:
	"""
	Fetches all embedded objects from the virtual buffer in a single
	getTextWithFields() call, then matches in pure Python with no further
	COM round-trips.  Typically 10-50x faster than node-by-node tree walk
	for browser content because Chrome/Firefox batch the entire document
	into one response.
	"""
	try:
		import textInfos  # type: ignore
		from NVDAObjects import NVDAObject  # type: ignore

		ti = getattr(root_obj, "treeInterceptor", None) or (
			root_obj if hasattr(root_obj, "makeTextInfo") else None
		)
		if ti is None or not getattr(ti, "isReady", False):
			log.warning("REM batch resolve: no ready treeInterceptor.")
			return None

		# Verify URL before fetching the whole document.
		target_url = primary.get("url_if_web", "") or ""
		if target_url:
			doc_id = str(getattr(ti, "documentConstantIdentifier", "") or "")
			if doc_id and doc_id != target_url:
				log.warning(f"REM batch resolve: URL mismatch (stored={target_url!r}, current={doc_id!r}).")
				return None

		info = ti.makeTextInfo(textInfos.POSITION_ALL)
		fields = info.getTextWithFields()

		seen_ids = set()
		matched = 0
		for field in fields:
			# Fields are a mix of strings and FieldCommand objects.
			# We only care about FieldCommand("controlStart", ...) which carry NVDAObjects.
			if not isinstance(field, textInfos.FieldCommand):
				continue
			if field.command != "controlStart":
				continue
			obj = field.field.get("_startOfNode") or None
			if obj is None:
				# Fall back: some browse-mode implementations store the object differently.
				obj = field.field.get("obj") or None
			if not isinstance(obj, NVDAObject):
				continue
			oid = id(obj)
			if oid in seen_ids:
				continue
			seen_ids.add(oid)
			matched += 1
			if _match_browsemode(obj, primary):
				log.debugWarning(f"REM batch resolve: matched after checking {matched} objects.")
				return obj

		log.debugWarning(f"REM batch resolve: no match after {matched} objects from getTextWithFields.")
		return None
	except Exception as e:
		log.warning(f"REM batch resolve exception: {e}")
		return None


# ------------------------------------------------------------------ #
# Chunked walker driver                                               #
# ------------------------------------------------------------------ #

# How many nodes to visit per main-thread timeslice.
# ~50 nodes takes < 1ms on native apps and < 50ms on Chrome, keeping
# NVDA's speech/input latency imperceptible.
_CHUNK_SIZE = 50


def _drive_walk(walker, on_done: Callable) -> None:
	"""
	Pulls up to _CHUNK_SIZE nodes from the walker on the main thread,
	then schedules itself again via wx.CallLater(0) so the wx event loop
	gets a turn between chunks.  Calls on_done when finished.
	"""
	import wx  # type: ignore

	try:
		for _ in range(_CHUNK_SIZE):
			result = next(walker)
			if result is not None:
				# Found it.
				log.debugWarning(f"REM walk found match: {result!r}")
				on_done(result)
				return
		# Chunk exhausted, no match yet — yield to event loop and continue.
		wx.CallLater(0, _drive_walk, walker, on_done)
	except StopIteration:
		# Walk finished with no match.
		log.warning("REM tree walk: exhausted all nodes, no match found.")
		on_done(None)


# ------------------------------------------------------------------ #
# Tree walk generator                                                 #
# ------------------------------------------------------------------ #

def _tree_walk_iter(backend: str, primary: Dict[str, Any], root_obj):
	"""
	Generator that yields None for each non-matching node visited,
	and yields the matching object when found, then returns.
	Iterative DFS so there is no Python recursion limit.
	"""
	log.debugWarning(f"REM tree walk iter start: backend={backend}, primary={primary}")

	visited = 0
	stack = [root_obj]

	while stack:
		obj = stack.pop()
		if obj is None:
			continue

		visited += 1

		if _matches(backend, primary, obj):
			log.debugWarning(f"REM tree walk matched after {visited} nodes.")
			yield obj
			return

		# Collect children and push in reverse order (first child processed first).
		children = []
		try:
			child = obj.firstChild
			while child:
				children.append(child)
				try:
					child = child.next
				except Exception:
					break
		except Exception:
			pass

		for child in reversed(children):
			stack.append(child)

		yield None  # Yield control back after each node.

	log.warning(f"REM tree walk: no match after {visited} nodes.")


# ------------------------------------------------------------------ #
# UIA runtimeId fast-path                                             #
# ------------------------------------------------------------------ #

def _uia_fast_path(runtime_id) -> Optional[Any]:
	try:
		import UIAHandler  # type: ignore
		if not UIAHandler.handler:
			return None
		condition = UIAHandler.handler.clientObject.CreatePropertyCondition(
			UIAHandler.UIA_RuntimeIdPropertyId, runtime_id,
		)
		found = UIAHandler.handler.rootElement.FindFirst(
			UIAHandler.TreeScope_Subtree, condition,
		)
		if found:
			import NVDAObjects.UIA as UIA_module  # type: ignore
			return UIA_module.UIA(UIAElement=found)
	except Exception as e:
		log.debugWarning(f"REM UIA fast-path exception: {e}")
	return None


# ------------------------------------------------------------------ #
# Match predicates                                                    #
# ------------------------------------------------------------------ #

def _matches(backend: str, primary: Dict[str, Any], obj) -> bool:
	try:
		if backend == "UIA":
			return _match_uia(obj, primary)
		elif backend == "IAccessible":
			return _match_iaccessible(obj, primary)
		elif backend == "BrowseMode":
			return _match_browsemode(obj, primary)
	except Exception:
		pass
	return False


def _match_uia(obj, primary: Dict[str, Any]) -> bool:
	stored_automation_id = primary.get("automationId", "")
	stored_control_type = primary.get("controlType", "")
	stored_class_name = primary.get("className", "")
	if not any([stored_automation_id, stored_control_type, stored_class_name]):
		return False
	if stored_automation_id and getattr(obj, "UIAAutomationId", "") != stored_automation_id:
		return False
	if stored_control_type and getattr(obj, "UIAControlType", "") != stored_control_type:
		return False
	if stored_class_name and getattr(obj, "UIAClassName", "") != stored_class_name:
		return False
	return True


def _match_iaccessible(obj, primary: Dict[str, Any]) -> bool:
	if obj.role != primary.get("accRole"):
		return False
	stored_class = primary.get("windowClassName", "")
	if stored_class and getattr(obj, "windowClassName", "") != stored_class:
		return False
	return True


def _match_browsemode(obj, primary: Dict[str, Any]) -> bool:
	if obj.role != primary.get("role"):
		return False
	if "states" in primary:
		try:
			required = set(primary["states"])
			if not required.issubset(set(obj.states)):
				return False
		except Exception:
			pass
	name_hint = primary.get("name", "")
	if name_hint:
		if (getattr(obj, "name", "") or "").strip() != name_hint.strip():
			return False
	url_hint = primary.get("url_if_web", "")
	if url_hint:
		ti = getattr(obj, "treeInterceptor", None)
		doc_id = getattr(ti, "documentConstantIdentifier", None) if ti else None
		if doc_id and str(doc_id) != str(url_hint):
			return False
	return True

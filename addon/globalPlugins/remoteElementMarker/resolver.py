import time
from typing import Any, Dict, Optional, Callable

from logHandler import log  # type: ignore

_TIMING_ENABLED = True


def _log_timing(method: str, elapsed_ms: float, **kwargs) -> None:
	if not _TIMING_ENABLED:
		return
	extras = ", ".join(f"{k}={v}" for k, v in kwargs.items())
	log.debugWarning(f"REM Timing: {method} took {elapsed_ms:.2f}ms{extras and ', ' + extras}")


def resolve_element(marker_data: Dict[str, Any], root_obj, on_done: Callable) -> None:
	"""
	Searches for the element using primary signature.
	Must be called from NVDA's main thread.
	"""

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
		t0 = time.perf_counter()
		result = _uia_fast_path(fast_path["runtimeId"])
		elapsed = (time.perf_counter() - t0) * 1000
		_log_timing("UIA_fast_path", elapsed, result=result is not None)
		if result:
			log.debugWarning("REM UIA runtimeId fast-path succeeded.")
			on_done(result)
			return

	# BrowseMode: walk the virtual buffer tree to find by role_index + name.
	if backend == "BrowseMode":
		t0 = time.perf_counter()
		result = _browsemode_resolve(primary, root_obj)
		elapsed = (time.perf_counter() - t0) * 1000
		_log_timing("BrowseMode", elapsed, result=result is not None)
		if result is not None:
			log.debugWarning("REM BrowseMode resolve succeeded.")
			on_done(result)
			return
		log.warning("REM BrowseMode resolve found no match; falling back to chunked tree walk.")

	# UIA/IAccessible (and BrowseMode fallback): chunked tree walk on main thread.
	t0 = time.perf_counter()
	walker = _tree_walk_iter(backend, primary, root_obj)
	_drive_walk(walker, on_done, start_time=t0)


# ------------------------------------------------------------------ #
# BrowseMode resolve via tree walk                                    #
# ------------------------------------------------------------------ #


def _browsemode_resolve(primary: Dict[str, Any], root_obj) -> Optional[Any]:
	"""
	Resolve a BrowseMode element by walking the virtual buffer tree.

	Matching priority:
	  1. role_index — 0-based count of same-role+name elements in tree order,
	                  computed identically at mark time and resolve time.
	  2. context    — surrounding document text, fallback for dynamic pages
	                  where insertions above the element shifted role_index.
	  3. single candidate — if only one element matches role+name, return it.
	"""
	try:
		ti = getattr(root_obj, "treeInterceptor", None) or (
			root_obj if hasattr(root_obj, "rootNVDAObject") else None
		)

		# Verify URL.
		target_url = primary.get("url_if_web", "") or ""
		if target_url:
			doc_id = str(getattr(ti, "documentConstantIdentifier", "") or "") if ti else ""
			if doc_id and doc_id != target_url:
				log.warning("REM BrowseMode resolve: URL mismatch.")
				return None

		target_role = primary.get("role")
		target_name = (primary.get("name", "") or "").strip()
		stored_index = primary.get("role_index", -1)
		stored_before = primary.get("context_before", "")
		stored_after = primary.get("context_after", "")

		# Get the document root.
		root = getattr(ti, "rootNVDAObject", None) if ti else None
		if root is None:
			root = root_obj

		# Walk tree collecting all same-role+name candidates with their
		# role_index (count of same-role elements seen before each one).
		role_counter = 0  # counts ALL same-role elements (including different names)
		name_counter = 0  # counts same-role+name elements only
		stack = [root]
		visited = set()
		candidates = []  # list of (name_index, role_index_overall, node)

		while stack:
			node = stack.pop()
			if node is None:
				continue
			nid = id(node)
			if nid in visited:
				continue
			visited.add(nid)

			if node.role == target_role:
				node_name = (getattr(node, "name", "") or "").strip()
				if node_name == target_name:
					candidates.append((name_counter, role_counter, node))
					name_counter += 1
				role_counter += 1

			children = []
			try:
				child = node.firstChild
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

		log.debugWarning(
			f"REM BrowseMode resolve: {len(candidates)} name-matching candidates, "
			f"stored_index={stored_index}, role_counter_total={role_counter}"
		)

		if not candidates:
			return None

		# 1. Match by role_index (= name_counter value at mark time).
		if stored_index >= 0:
			for name_idx, role_idx, node in candidates:
				if name_idx == stored_index:
					log.debugWarning(f"REM resolved by name_index={name_idx}")
					return node


		# 2. Single candidate.
		if len(candidates) == 1:
			log.debugWarning("REM resolved: only one name-matching candidate.")
			return candidates[0][2]

		log.warning(f"REM BrowseMode resolve: no match among {len(candidates)} candidates.")
		return None

	except Exception as e:
		log.warning(f"REM BrowseMode resolve exception: {e}")
		return None


# ------------------------------------------------------------------ #
# Chunked walker driver                                               #
# ------------------------------------------------------------------ #

_CHUNK_SIZE = 50


def _drive_walk(walker, on_done: Callable, nodes_visited: int = 0, start_time: float = 0) -> None:
	import wx  # type: ignore

	try:
		for _ in range(_CHUNK_SIZE):
			result = next(walker)
			nodes_visited += 1
			if result is not None:
				elapsed = (time.perf_counter() - start_time) * 1000
				_log_timing("chunked_tree_walk", elapsed, nodes=nodes_visited, result=True)
				log.debugWarning(f"REM walk resolved found match: {result!r}")
				on_done(result)
				return
		wx.CallLater(0, _drive_walk, walker, on_done, nodes_visited, start_time)
	except StopIteration:
		elapsed = (time.perf_counter() - start_time) * 1000
		_log_timing("chunked_tree_walk", elapsed, nodes=nodes_visited, result=False)
		log.warning("REM tree walk: exhausted all nodes, no match found.")
		on_done(None)


# ------------------------------------------------------------------ #
# Tree walk generator                                                 #
# ------------------------------------------------------------------ #


def _tree_walk_iter(backend: str, primary: Dict[str, Any], root_obj):
	log.debugWarning(f"REM tree walk iter start: backend={backend}")

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

		yield None

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
			UIAHandler.UIA_RuntimeIdPropertyId,
			runtime_id,
		)
		found = UIAHandler.handler.rootElement.FindFirst(
			UIAHandler.TreeScope_Subtree,
			condition,
		)
		if found:
			import NVDAObjects.UIA as UIA_module  # type: ignore

			return UIA_module.UIA(UIAElement=found)
	except Exception as e:
		log.debugWarning(f"REM UIA fast-path exception: {e}")
	return None


# ------------------------------------------------------------------ #
# Match predicates (tree-walk fallback path)                         #
# ------------------------------------------------------------------ #


def _matches(backend: str, primary: Dict[str, Any], obj) -> bool:
	try:
		if backend == "UIA":
			return _match_uia(obj, primary)
		elif backend == "IAccessible":
			return _match_iaccessible(obj, primary)
		elif backend == "BrowseMode":
			return _match_browsemode_simple(obj, primary)
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


def _match_browsemode_simple(obj, primary: Dict[str, Any]) -> bool:
	"""
	Tree-walk fallback: role + name only. Only runs if _browsemode_resolve
	fails (e.g. no treeInterceptor). Approximate but better than nothing.
	"""
	if obj.role != primary.get("role"):
		return False
	name_hint = (primary.get("name", "") or "").strip()
	obj_name = (getattr(obj, "name", "") or "").strip()
	if obj_name != name_hint:
		return False
	url_hint = primary.get("url_if_web", "")
	if url_hint:
		ti = getattr(obj, "treeInterceptor", None)
		doc_id = getattr(ti, "documentConstantIdentifier", None) if ti else None
		if doc_id and str(doc_id) != str(url_hint):
			return False
	return True

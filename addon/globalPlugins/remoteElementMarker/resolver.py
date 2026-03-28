import time
from typing import Any, Dict, Optional, Callable

from logHandler import log  # type: ignore
from .storage import is_stable_document_identifier

_TIMING_ENABLED = True

# Time budget per chunk in seconds. The walker processes nodes until this
# wall-clock budget is spent, then yields to the event loop. This is
# self-calibrating: on a fast machine with cheap COM calls it processes more
# nodes per tick; on a slow machine or a busy browser it yields sooner.
_CHUNK_BUDGET_S = 0.008  # 8 ms per chunk — leaves ~8 ms headroom in a 16 ms frame

# Hard cap: never process more than this many nodes in one chunk regardless of
# timing, as a safety net against runaway loops on pathological trees.
_CHUNK_MAX = 200

# Roles that are pure structural containers in BrowseMode and can never be
# the resolved target themselves. Their children still need visiting, but we
# skip the match check on the node itself. These are NVDA controlTypes Role
# integer values for the most common container roles.
# We resolve them lazily the first time they are needed.
_BROWSE_SKIP_ROLES: Optional[frozenset] = None


def _get_browse_skip_roles() -> frozenset:
	global _BROWSE_SKIP_ROLES
	if _BROWSE_SKIP_ROLES is not None:
		return _BROWSE_SKIP_ROLES
	try:
		import controlTypes  # type: ignore
		R = controlTypes.Role
		_BROWSE_SKIP_ROLES = frozenset({
			R.DOCUMENT,
			R.FRAME,
			R.INTERNALFRAME,
			R.SECTION,
			R.DIVISION,
			R.GROUPING,
			R.FORM,
			R.PARAGRAPH,
			R.BLOCKQUOTE,
			R.SEPARATOR,
			R.WHITESPACE,
			R.STATICTEXT,
		})
	except Exception:
		_BROWSE_SKIP_ROLES = frozenset()
	return _BROWSE_SKIP_ROLES


def _log_timing(method: str, elapsed_ms: float, **kwargs) -> None:
	if not _TIMING_ENABLED:
		return
	extras = ", ".join(f"{k}={v}" for k, v in kwargs.items())
	log.debugWarning(f"REM Timing: {method} took {elapsed_ms:.2f}ms{extras and ', ' + extras}")


def _normalized_name(obj) -> str:
	try:
		return (getattr(obj, "name", "") or "").strip()
	except Exception:
		return ""


def _browse_doc_matches_target(ti, target_url: str) -> bool:
	target_url = str(target_url or "").strip()
	if not target_url or not is_stable_document_identifier(target_url):
		return True
	doc_id = str(getattr(ti, "documentConstantIdentifier", "") or "") if ti else ""
	if not doc_id or not is_stable_document_identifier(doc_id):
		return True
	return doc_id == target_url


def _iter_children(parent):
	try:
		child = parent.firstChild
	except Exception:
		return
	while child:
		yield child
		try:
			child = child.next
		except Exception:
			break


def _normalize_hint_value(value) -> str:
	if value is None:
		return ""
	try:
		return str(value).strip()
	except Exception:
		return ""


def _parse_attr_blob(raw) -> Dict[str, str]:
	if isinstance(raw, dict):
		return {str(k).strip(): _normalize_hint_value(v) for k, v in raw.items() if _normalize_hint_value(v)}
	text = _normalize_hint_value(raw)
	if not text:
		return {}
	result: Dict[str, str] = {}
	for part in text.split(";"):
		part = part.strip()
		if not part or ":" not in part:
			continue
		key, value = part.split(":", 1)
		key = key.strip()
		value = value.strip()
		if key and value:
			result[key] = value
	return result


def _get_browse_dom_hints(obj) -> Dict[str, str]:
	hints: Dict[str, str] = {}
	try:
		ia_obj = getattr(obj, "IAccessibleObject", None)
		if ia_obj is not None:
			try:
				tag_name = _normalize_hint_value(ia_obj.accValue(0))
				if tag_name:
					hints["tag"] = tag_name
			except Exception:
				pass
	except Exception:
		pass

	raw_attrs = None
	for attr_name in ("IA2Attributes", "IA2Attribs", "attributes"):
		try:
			raw_attrs = getattr(obj, attr_name, None)
		except Exception:
			raw_attrs = None
		if raw_attrs:
			break
	if not raw_attrs:
		try:
			ia_obj = getattr(obj, "IAccessibleObject", None)
			raw_attrs = getattr(ia_obj, "attributes", None) if ia_obj is not None else None
		except Exception:
			raw_attrs = None

	attrs = _parse_attr_blob(raw_attrs)
	for src_key, dst_key in (
		("id", "id"),
		("class", "class"),
		("className", "class"),
		("aria-label", "ariaLabel"),
		("ariaLabel", "ariaLabel"),
		("display", "display"),
	):
		value = attrs.get(src_key)
		if value:
			hints[dst_key] = value
	return hints


def _matches_dom_hints(obj, dom_hints: Dict[str, str]) -> bool:
	if not dom_hints:
		return False
	obj_hints = _get_browse_dom_hints(obj)
	if not obj_hints:
		return False
	for key, value in dom_hints.items():
		if obj_hints.get(key, "") != value:
			return False
	return True


def _get_browse_root(root_obj):
	ti = getattr(root_obj, "treeInterceptor", None) or (
		root_obj if hasattr(root_obj, "rootNVDAObject") else None
	)
	root = getattr(ti, "rootNVDAObject", None) if ti else None
	if root is None:
		root = root_obj
	return ti, root


def _path_step_matches(node, step: Dict[str, Any]) -> bool:
	if getattr(node, "role", None) != step.get("role"):
		return False
	return _normalized_name(node) == (step.get("name", "") or "").strip()


def _rank_path_children(children, step: Dict[str, Any]):
	expected_index = step.get("childIndex", -1)
	exact_matches = []
	role_only_matches = []
	for index, child in enumerate(children):
		if _path_step_matches(child, step):
			exact_matches.append((abs(index - expected_index) if expected_index >= 0 else index, index, child))
			continue
		if getattr(child, "role", None) == step.get("role"):
			role_only_matches.append((abs(index - expected_index) if expected_index >= 0 else index, index, child))
	exact_matches.sort(key=lambda item: (item[0], item[1]))
	role_only_matches.sort(key=lambda item: (item[0], item[1]))
	if exact_matches:
		return [child for _, _, child in exact_matches]
	return [child for _, _, child in role_only_matches]


def _browse_candidate_matches_primary(obj, primary: Dict[str, Any]) -> bool:
	if obj is None:
		return False
	if getattr(obj, "role", None) != primary.get("role"):
		return False
	return _normalized_name(obj) == (primary.get("name", "") or "").strip()


def _follow_browse_path(node, path, path_index: int, primary: Dict[str, Any]):
	if path_index >= len(path):
		return node if _browse_candidate_matches_primary(node, primary) else None
	children = list(_iter_children(node))
	if not children:
		return None
	for child in _rank_path_children(children, path[path_index]):
		result = _follow_browse_path(child, path, path_index + 1, primary)
		if result is not None:
			return result
	return None


def _browsemode_path_resolve(primary: Dict[str, Any], fast_path: Dict[str, Any], root_obj) -> Optional[Any]:
	path = fast_path.get("browsePath")
	if not path and path != []:
		return None
	try:
		ti, root = _get_browse_root(root_obj)
		target_url = (primary.get("url_if_web", "") or "").strip()
		if not _browse_doc_matches_target(ti, target_url):
			log.debugWarning("REM browse path fast-path: URL mismatch.")
			return None
		result = _follow_browse_path(root, path, 0, primary)
		dom_hints = fast_path.get("domHints", {})
		if result is not None and dom_hints and not _matches_dom_hints(result, dom_hints):
			return None
		if result is not None:
			log.debugWarning("REM BrowseMode path fast-path succeeded.")
		return result
	except Exception as e:
		log.debugWarning(f"REM browse path fast-path exception: {e}")
		return None


def _browsemode_dom_resolve(primary: Dict[str, Any], fast_path: Dict[str, Any], root_obj) -> Optional[Any]:
	dom_hints = fast_path.get("domHints", {})
	if not dom_hints:
		return None
	try:
		ti, root = _get_browse_root(root_obj)
		target_url = (primary.get("url_if_web", "") or "").strip()
		if not _browse_doc_matches_target(ti, target_url):
			return None
		target_role = primary.get("role")
		target_name = (primary.get("name", "") or "").strip()
		stored_index = primary.get("role_index", -1)
		stored_role_ordinal = primary.get("role_ordinal", -1)
		stack = [root]
		visited = set()
		name_counter = 0
		role_counter = 0
		candidates = []
		while stack:
			node = stack.pop()
			if node is None:
				continue
			nid = id(node)
			if nid in visited:
				continue
			visited.add(nid)
			if getattr(node, "role", None) == target_role:
				current_role_ordinal = role_counter
				role_counter += 1
				node_name = _normalized_name(node)
				current_name_index = -1
				if node_name == target_name:
					current_name_index = name_counter
					name_counter += 1
				if _matches_dom_hints(node, dom_hints):
					candidates.append((current_name_index, current_role_ordinal, node))
					if stored_index >= 0 and current_name_index == stored_index:
						return node
					if stored_index < 0 and stored_role_ordinal >= 0 and current_role_ordinal == stored_role_ordinal:
						return node
			children = list(_iter_children(node))
			for child in reversed(children):
				stack.append(child)
		if len(candidates) == 1:
			return candidates[0][2]
		if stored_index >= 0:
			for name_idx, _, node in candidates:
				if name_idx == stored_index:
					return node
		if stored_index < 0 and stored_role_ordinal >= 0:
			for _, role_ordinal, node in candidates:
				if role_ordinal == stored_role_ordinal:
					return node
		return None
	except Exception as e:
		log.debugWarning(f"REM browse DOM fast-path exception: {e}")
		return None


def resolve_element(marker_data: Dict[str, Any], root_obj, on_done: Callable) -> None:
	"""
	Search for the element using its saved primary signature.
	Must be called from NVDA's main thread.
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

	# UIA runtimeId fast-path — synchronous and near-instantaneous.
	if fast_path.get("runtimeId"):
		t0 = time.perf_counter()
		result = _uia_fast_path(fast_path["runtimeId"])
		elapsed = (time.perf_counter() - t0) * 1000
		_log_timing(f"{backend or 'Unknown'}_UIA_fast_path", elapsed, result=result is not None)
		if result:
			log.debugWarning("REM runtimeId fast-path succeeded.")
			on_done(result)
			return

	if backend == "BrowseMode":
		t0 = time.perf_counter()
		result = _browsemode_path_resolve(primary, fast_path, root_obj)
		elapsed = (time.perf_counter() - t0) * 1000
		_log_timing("BrowseMode_path", elapsed, result=result is not None)
		if result is not None:
			on_done(result)
			return
		t0 = time.perf_counter()
		result = _browsemode_dom_resolve(primary, fast_path, root_obj)
		elapsed = (time.perf_counter() - t0) * 1000
		_log_timing("BrowseMode_dom", elapsed, result=result is not None)
		if result is not None:
			on_done(result)
			return
		# Try the virtual-buffer fast path first (no COM, uses NVDA's own cache).
		t0 = time.perf_counter()
		result = _browsemode_vbuf_resolve(primary, root_obj)
		elapsed = (time.perf_counter() - t0) * 1000
		if result is not None:
			_log_timing("BrowseMode_vbuf", elapsed, result=True)
			log.debugWarning("REM BrowseMode vbuf fast-path succeeded.")
			on_done(result)
			return
		_log_timing("BrowseMode_vbuf", elapsed, result=False)
		log.debugWarning("REM BrowseMode vbuf fast-path found nothing; falling back to chunked walk.")
		wx.CallAfter(_begin_browsemode_resolve, primary, root_obj, on_done)
		return

	# UIA/IAccessible fallback: defer so the progress beeper can fire.
	wx.CallAfter(_begin_chunked_tree_walk, backend, primary, root_obj, on_done)


# ------------------------------------------------------------------ #
# BrowseMode virtual-buffer fast path (no COM)                       #
# ------------------------------------------------------------------ #

def _browsemode_vbuf_resolve(primary: Dict[str, Any], root_obj) -> Optional[Any]:
	"""
	Resolve a BrowseMode element using NVDA's virtual buffer (textInfo) API.

	Matching priority:
	  1. role_index (name-based ordinal) — primary key, used when >= 0.
	  2. role_ordinal — tiebreaker used ONLY when role_index == -1, i.e. when
	     the element could not be positively identified at mark time (position:fixed
	     location mismatch or id() invalidation). Using role_ordinal as a secondary
	     key for named elements would risk matching the wrong element when the same
	     name appears at different ordinal positions after DOM changes.
	  3. Single-candidate shortcut — only when exactly one candidate exists and
	     both stored indices are -1, meaning we have no positional information at
	     all. This is safe only for truly unique elements.

	Returns the matching NVDAObject, or None.
	"""
	try:
		import textInfos  # type: ignore
		import controlTypes  # type: ignore

		ti = getattr(root_obj, "treeInterceptor", None) or (
			root_obj if hasattr(root_obj, "rootNVDAObject") else None
		)
		if ti is None or not getattr(ti, "isReady", False):
			return None

		# URL check.
		target_url = (primary.get("url_if_web", "") or "").strip()
		if not _browse_doc_matches_target(ti, target_url):
			log.debugWarning("REM vbuf fast-path: URL mismatch.")
			return None

		target_role = primary.get("role")
		target_name = (primary.get("name", "") or "").strip()
		stored_index = primary.get("role_index", -1)
		stored_role_ordinal = primary.get("role_ordinal", -1)

		doc_info = ti.makeTextInfo(textInfos.POSITION_ALL)
		fields = doc_info.getTextWithFields({})

		# name_counter counts ALL role+name matches in document order, exactly
		# mirroring what the tree walk did at mark time. We must increment it
		# even when obj is None so that the stored role_index stays valid.
		name_counter = 0
		role_counter = 0
		candidates = []       # (name_index, role_ordinal, obj)  — role+name matches with valid obj
		role_candidates = []  # (role_ordinal, obj)              — role-only matches with valid obj

		for field in fields:
			if not isinstance(field, textInfos.FieldCommand):
				continue
			if field.command != "controlStart":
				continue
			attrs = field.field
			if attrs is None:
				continue

			field_role = attrs.get("role")
			if field_role != target_role:
				continue

			current_role_ordinal = role_counter
			role_counter += 1

			field_name = (attrs.get("name", "") or "").strip()
			current_index = -1
			if field_name == target_name:
				current_index = name_counter
				name_counter += 1

			obj = attrs.get("obj")
			if obj is None:
				obj = attrs.get("_startOfNode") or attrs.get("focusableNVDAObjectAtStart")

			# Guard: reject booleans stored under "obj" in some NVDA versions.
			if not hasattr(obj, "role"):
				continue

			role_candidates.append((current_role_ordinal, obj))
			if current_index >= 0:
				candidates.append((current_index, current_role_ordinal, obj))

			# Early exit: role_index match (primary criterion).
			if stored_index >= 0 and current_index == stored_index:
				log.debugWarning(f"REM vbuf fast-path: early exit at name_index={current_index}")
				return obj

			# Early exit: role_ordinal match — used ONLY when role_index is
			# unavailable (stored_index == -1).  Avoids wrongly returning a
			# different same-name element that happens to share the ordinal.
			if stored_index < 0 and stored_role_ordinal >= 0 and current_role_ordinal == stored_role_ordinal:
				log.debugWarning(f"REM vbuf fast-path: early exit at role_ordinal={current_role_ordinal} (no role_index)")
				return obj

		log.debugWarning(
			f"REM vbuf fast-path: {len(candidates)} name candidates, "
			f"{len(role_candidates)} role candidates, stored_index={stored_index}, "
			f"stored_role_ordinal={stored_role_ordinal}"
		)

		# Post-scan fallback: role_index.
		if stored_index >= 0:
			for idx, role_ordinal, obj in candidates:
				if idx == stored_index:
					return obj

		# Post-scan fallback: role_ordinal — only when role_index unavailable.
		if stored_index < 0 and stored_role_ordinal >= 0:
			for role_ordinal, obj in role_candidates:
				if role_ordinal == stored_role_ordinal:
					return obj

		# No positional info at all — only resolve if there is exactly one
		# candidate, meaning the element is unique on the page.
		if stored_index < 0 and stored_role_ordinal < 0:
			if len(candidates) == 1:
				log.debugWarning("REM vbuf: unique name candidate, no stored index.")
				return candidates[0][2]
			if len(role_candidates) == 1:
				log.debugWarning("REM vbuf: unique role candidate, no stored index.")
				return role_candidates[0][1]

		return None

	except Exception as e:
		log.debugWarning(f"REM vbuf fast-path exception: {e}")
		return None


# ------------------------------------------------------------------ #
# BrowseMode resolve via chunked tree walk (fallback)                #
# ------------------------------------------------------------------ #

def _begin_browsemode_resolve(primary: Dict[str, Any], root_obj, on_done: Callable) -> None:
	state = _create_browsemode_state(primary, root_obj)
	if state is None:
		on_done(None)
		return
	_drive_browsemode_resolve(state, on_done, start_time=time.perf_counter())


def _create_browsemode_state(primary: Dict[str, Any], root_obj) -> Optional[Dict[str, Any]]:
	try:
		ti = getattr(root_obj, "treeInterceptor", None) or (
			root_obj if hasattr(root_obj, "rootNVDAObject") else None
		)

		target_url = primary.get("url_if_web", "") or ""
		if not _browse_doc_matches_target(ti, target_url):
			log.warning("REM BrowseMode resolve: URL mismatch.")
			return None

		root = getattr(ti, "rootNVDAObject", None) if ti else None
		if root is None:
			root = root_obj

		return {
			"primary": primary,
			"root_obj": root_obj,
			"stack": [root],
			"visited": set(),
			"candidates": [],
			"role_candidates": [],
			"role_counter": 0,
			"name_counter": 0,
		}
	except Exception as e:
		log.warning(f"REM BrowseMode resolve setup exception: {e}")
		return None


def _drive_browsemode_resolve(
	state: Dict[str, Any],
	on_done: Callable,
	nodes_visited: int = 0,
	start_time: float = 0,
) -> None:
	import wx  # type: ignore

	try:
		stack = state["stack"]
		visited = state["visited"]
		primary = state["primary"]
		target_role = primary.get("role")
		target_name = (primary.get("name", "") or "").strip()
		stored_index = primary.get("role_index", -1)
		stored_role_ordinal = primary.get("role_ordinal", -1)

		chunk_start = time.perf_counter()
		nodes_this_chunk = 0

		while stack:
			node = stack.pop()
			if node is None:
				continue
			nid = id(node)
			if nid in visited:
				continue
			visited.add(nid)
			nodes_visited += 1
			nodes_this_chunk += 1

			node_role = node.role

			if node_role == target_role:
				current_role_ordinal = state["role_counter"]
				# Increment role_counter BEFORE any early-exit so ordinals stay
				# correct for all subsequent nodes regardless of exit path.
				state["role_counter"] += 1

				node_name = (getattr(node, "name", "") or "").strip()
				state["role_candidates"].append((current_role_ordinal, node))

				if node_name == target_name:
					idx = state["name_counter"]
					state["name_counter"] += 1
					state["candidates"].append((idx, current_role_ordinal, node))

					# Early exit: role_index match (primary criterion).
					if stored_index >= 0 and idx == stored_index:
						elapsed = (time.perf_counter() - start_time) * 1000
						_log_timing("BrowseMode_walk_early_exit", elapsed, nodes=nodes_visited)
						log.debugWarning(f"REM BrowseMode walk: early exit at name_index={idx}")
						on_done(node)
						return

				# Early exit: role_ordinal match — only when role_index unavailable.
				if stored_index < 0 and stored_role_ordinal >= 0 and current_role_ordinal == stored_role_ordinal:
					elapsed = (time.perf_counter() - start_time) * 1000
					_log_timing("BrowseMode_walk_early_exit", elapsed, nodes=nodes_visited)
					log.debugWarning(f"REM BrowseMode walk: early exit at role_ordinal={current_role_ordinal} (no role_index)")
					on_done(node)
					return

			# Enqueue children for all nodes (containers may hold the target).
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

			# Yield to the event loop when the time budget is spent.
			elapsed_chunk = time.perf_counter() - chunk_start
			if elapsed_chunk >= _CHUNK_BUDGET_S or nodes_this_chunk >= _CHUNK_MAX:
				wx.CallLater(0, _drive_browsemode_resolve, state, on_done, nodes_visited, start_time)
				return

		# Stack exhausted — finish up.
		result = _finish_browsemode_resolve(state)
		elapsed = (time.perf_counter() - start_time) * 1000
		_log_timing("BrowseMode_walk", elapsed, nodes=nodes_visited, result=result is not None)
		if result is not None:
			log.debugWarning("REM BrowseMode walk succeeded.")
			on_done(result)
			return
		log.warning("REM BrowseMode walk found no match; falling back to chunked tree walk.")
		_begin_chunked_tree_walk("BrowseMode", primary, state["root_obj"], on_done)

	except Exception as e:
		log.warning(f"REM BrowseMode resolve exception: {e}")
		on_done(None)


def _finish_browsemode_resolve(state: Dict[str, Any]) -> Optional[Any]:
	primary = state["primary"]
	candidates = state["candidates"]
	stored_index = primary.get("role_index", -1)
	stored_role_ordinal = primary.get("role_ordinal", -1)
	role_candidates = state["role_candidates"]

	log.debugWarning(
		f"REM BrowseMode resolve: {len(candidates)} name-matching candidates, "
		f"{len(role_candidates)} role candidates, stored_index={stored_index}, "
		f"stored_role_ordinal={stored_role_ordinal}, role_counter_total={state['role_counter']}"
	)

	# Primary: role_index match.
	if stored_index >= 0:
		for name_idx, role_idx, node in candidates:
			if name_idx == stored_index:
				log.debugWarning(f"REM resolved by name_index={name_idx}")
				return node

	# Secondary: role_ordinal — only when role_index is unavailable.
	if stored_index < 0 and stored_role_ordinal >= 0:
		for role_idx, node in role_candidates:
			if role_idx == stored_role_ordinal:
				log.debugWarning(f"REM resolved by role_ordinal={role_idx}")
				return node

	# No positional info at all — only resolve if truly unique.
	if stored_index < 0 and stored_role_ordinal < 0:
		if len(candidates) == 1:
			log.debugWarning("REM resolved: only one name-matching candidate.")
			return candidates[0][2]
		if len(role_candidates) == 1:
			log.debugWarning("REM resolved: only one role-matching candidate.")
			return role_candidates[0][1]

	log.warning(f"REM BrowseMode resolve: no match among {len(candidates)} candidates.")
	return None


# ------------------------------------------------------------------ #
# Chunked walker driver (UIA / IAccessible fallback)                 #
# ------------------------------------------------------------------ #

def _begin_chunked_tree_walk(backend: str, primary: Dict[str, Any], root_obj, on_done: Callable) -> None:
	t0 = time.perf_counter()
	walker = _tree_walk_iter(backend, primary, root_obj)
	_drive_walk(walker, on_done, start_time=t0)


def _drive_walk(walker, on_done: Callable, nodes_visited: int = 0, start_time: float = 0) -> None:
	import wx  # type: ignore

	try:
		chunk_start = time.perf_counter()
		nodes_this_chunk = 0

		while True:
			result = next(walker)
			nodes_visited += 1
			nodes_this_chunk += 1

			if result is not None:
				elapsed = (time.perf_counter() - start_time) * 1000
				_log_timing("chunked_tree_walk", elapsed, nodes=nodes_visited, result=True)
				log.debugWarning(f"REM walk resolved found match: {result!r}")
				on_done(result)
				return

			elapsed_chunk = time.perf_counter() - chunk_start
			if elapsed_chunk >= _CHUNK_BUDGET_S or nodes_this_chunk >= _CHUNK_MAX:
				wx.CallLater(0, _drive_walk, walker, on_done, nodes_visited, start_time)
				return

	except StopIteration:
		elapsed = (time.perf_counter() - start_time) * 1000
		_log_timing("chunked_tree_walk", elapsed, nodes=nodes_visited, result=False)
		log.warning("REM tree walk: exhausted all nodes, no match found.")
		on_done(None)


# ------------------------------------------------------------------ #
# Tree walk generator (UIA / IAccessible)                            #
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
# UIA runtimeId fast-path                                            #
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
	Tree-walk fallback: role + name only. Only runs if BrowseMode candidate
	collection fails to produce a unique result. Approximate but better than
	nothing.
	"""
	if obj.role != primary.get("role"):
		return False
	name_hint = (primary.get("name", "") or "").strip()
	obj_name = (getattr(obj, "name", "") or "").strip()
	if obj_name != name_hint:
		return False
	url_hint = primary.get("url_if_web", "")
	if url_hint and is_stable_document_identifier(url_hint):
		ti = getattr(obj, "treeInterceptor", None)
		doc_id = getattr(ti, "documentConstantIdentifier", None) if ti else None
		if doc_id and is_stable_document_identifier(doc_id) and str(doc_id) != str(url_hint):
			return False
	return True

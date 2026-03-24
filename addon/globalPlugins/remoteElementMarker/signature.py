import hashlib
import json
import time
from typing import Any, Dict

from logHandler import log  # type: ignore

def _compute_position_hints(obj, ti) -> Dict[str, Any]:
	"""
	Compute role_index and surrounding text context for obj.

	Uses obj.location (screen coordinates) to identify the element among
	same-role/same-name siblings. Screen coordinates are stable within a
	page load and unique per element, unlike object identity (id()) which
	changes when NVDA rebuilds wrappers.

	Falls back to tree-walk counting if location is unavailable.
	"""
	_empty = {"role_index": -1, "context_before": "", "context_after": ""}
	try:
		if ti is None or not getattr(ti, "isReady", False):
			return _empty

		target_role = obj.role
		target_name = (getattr(obj, "name", "") or "").strip()

		# Get the screen location of the target object — this is our identity anchor.
		target_location = None
		try:
			loc = obj.location
			if loc and len(loc) >= 2:
				target_location = (loc[0], loc[1])  # (x, y)
		except Exception:
			pass

		# Get document root for tree walking.
		root = getattr(ti, "rootNVDAObject", None) or root_obj_fallback(ti)
		if root is None:
			return _empty

		# Walk the tree in document order, counting same-role+name elements.
		# Match by screen location (most reliable) or name equality.
		counter = 0
		found_index = -1
		found_offset_estimate = -1
		stack = [root]
		visited = set()
		doc_order_pos = 0  # approximate char offset via element count
		timeout_seconds = float("inf")
		start_time = time.monotonic()
		timed_out = False

		while stack:
			node = stack.pop()
			if node is None:
				continue
			nid = id(node)
			if nid in visited:
				continue
			visited.add(nid)

			if time.monotonic() - start_time > timeout_seconds:
				log.debugWarning("REM _compute_position_hints: timeout, returning fallback")
				timed_out = True
				break

			if node.role == target_role:
				node_name = (getattr(node, "name", "") or "").strip()
				if node_name == target_name:
					# Try location match first.
					matched = False
					if target_location is not None:
						try:
							nloc = node.location
							if nloc and len(nloc) >= 2 and (nloc[0], nloc[1]) == target_location:
								matched = True
						except Exception:
							pass
					if matched:
						found_index = counter
						found_offset_estimate = doc_order_pos
						break
					counter += 1
				doc_order_pos += 1

			children = []
			try:
				child = node.firstChild
				while child:
					if time.monotonic() - start_time > timeout_seconds:
						timed_out = True
						break
					children.append(child)
					try:
						child = child.next
					except Exception:
						break
			except Exception:
				pass
			for child in reversed(children):
				stack.append(child)

		# If location match failed, fall back to positional index by tree order.
		# Skip fallback if we timed out - another tree walk would also be slow.
		if found_index < 0 and not timed_out:
			found_index = _count_by_tree_order(obj, ti, target_role, target_name)

		# Resolver will handle fallback via role_index or tree walk when needed.
		# Context based approach for future solution
		context_before = ""
		context_after = ""
		
		return {
			"role_index": found_index,
			"context_before": context_before,
			"context_after": context_after,
		}

	except Exception:
		return {"role_index": -1, "context_before": "", "context_after": ""}

# Context based approach for future solution
def _get_obj_offset(obj, ti) -> int:
	"""Return char offset of obj within the document text, or -1."""
	try:
		import textInfos  # type: ignore

		obj_info = obj.makeTextInfo(textInfos.POSITION_FIRST)
		start_info = ti.makeTextInfo(textInfos.POSITION_FIRST)
		range_info = start_info.copy()
		range_info.setEndPoint(obj_info, "endToStart")
		return len(range_info.getText())
	except Exception:
		return -1


def _count_by_tree_order(obj, ti, target_role: int, target_name: str) -> int:
	"""
	Fallback: count same-role+name elements before obj using tree walk.
	Matches by name only (no identity or location available).
	Returns the index of the FIRST element with matching name, which is
	a best-effort fallback when location is unavailable.
	"""
	try:
		root = getattr(ti, "rootNVDAObject", None)
		if root is None:
			return -1

		counter = 0
		stack = [root]
		visited = set()
		timeout_seconds = float("inf")
		start_time = time.monotonic()

		while stack:
			node = stack.pop()
			if node is None:
				continue
			nid = id(node)
			if nid in visited:
				continue
			visited.add(nid)

			if time.monotonic() - start_time > timeout_seconds:
				log.debugWarning("REM _count_by_tree_order: timeout, returning -1")
				break

			if node.role == target_role:
				node_name = (getattr(node, "name", "") or "").strip()
				if node_name == target_name:
					# Can't distinguish further without location — return first match.
					return counter
				counter += 1

			children = []
			try:
				child = node.firstChild
				while child:
					if time.monotonic() - start_time > timeout_seconds:
						log.debugWarning("REM _count_by_tree_order: inner loop timeout")
						break
					children.append(child)
					try:
						child = child.next
					except Exception:
						break
			except Exception:
				pass
			for child in reversed(children):
				stack.append(child)

	except Exception:
		pass
	return -1


def root_obj_fallback(ti):
	"""Get document root from treeInterceptor."""
	try:
		return getattr(ti, "rootNVDAObject", None)
	except Exception:
		return None


def generate_signature_for_lookup(obj) -> Dict[str, Any]:
	"""
	Lightweight variant used during navigation event handling (announce path).
	No getTextWithFields or tree walk — just role+name+url for a cheap hash.
	Always misses for BrowseMode; caller uses fuzzy fallback with stored hints.
	"""
	backend = "Unknown"
	primary: Dict[str, Any] = {}
	fast_path: Dict[str, Any] = {}

	ti = getattr(obj, "treeInterceptor", None)
	in_browse_mode = ti is not None and getattr(ti, "isReady", False)

	if in_browse_mode:
		backend = "BrowseMode"
		url = ""
		if hasattr(ti, "documentConstantIdentifier"):
			url = ti.documentConstantIdentifier or ""
		primary = {
			"role": obj.role,
			"name": getattr(obj, "name", "") or "",
			"url_if_web": url,
		}

	elif hasattr(obj, "UIAElement"):
		backend = "UIA"
		primary = {
			"automationId": getattr(obj, "UIAAutomationId", "") or "",
			"controlType": getattr(obj, "UIAControlType", "") or "",
			"className": getattr(obj, "UIAClassName", "") or "",
		}
		try:
			fast_path["runtimeId"] = obj.UIAElement.getRuntimeId()
		except Exception:
			pass

	elif hasattr(obj, "IAccessibleObject"):
		backend = "IAccessible"
		primary = {
			"accRole": obj.role,
			"windowClassName": getattr(obj, "windowClassName", "") or "",
		}
		if hasattr(obj, "IAccessibleChildID"):
			fast_path["childId"] = obj.IAccessibleChildID

	hash_str = json.dumps(primary, sort_keys=True)
	signature_hash = hashlib.md5(hash_str.encode("utf-8")).hexdigest()

	return {
		"backend": backend,
		"hash": signature_hash,
		"primarySignature": primary,
		"fastPathHints": fast_path,
		"fuzzyHints": {},
	}


def generate_signature(obj) -> Dict[str, Any]:
	"""
	Full signature including position hints. Called once at mark time.

	Backend detection order:
	  1. BrowseMode — checked first (browse element also has IAccessibleObject)
	  2. UIA
	  3. IAccessible
	"""
	backend = "Unknown"
	primary: Dict[str, Any] = {}
	fast_path: Dict[str, Any] = {}
	fuzzy: Dict[str, Any] = {
		"name": getattr(obj, "name", "") or "",
		"accDescription": getattr(obj, "description", "") or "",
	}

	ti = getattr(obj, "treeInterceptor", None)
	in_browse_mode = ti is not None and getattr(ti, "isReady", False)

	if in_browse_mode:
		backend = "BrowseMode"
		url = ""
		if hasattr(ti, "documentConstantIdentifier"):
			url = ti.documentConstantIdentifier or ""
		fuzzy["url_if_web"] = url
		try:
			if hasattr(obj, "IAccessibleObject"):
				fuzzy["tagName"] = obj.IAccessibleObject.accValue(0) or ""
		except Exception:
			fuzzy["tagName"] = ""

		pos = _compute_position_hints(obj, ti)

		primary = {
			"role": obj.role,
			"name": getattr(obj, "name", "") or "",
			"url_if_web": url,
			"role_index": pos["role_index"],
			"context_before": pos["context_before"],
			"context_after": pos["context_after"],
		}

	elif hasattr(obj, "UIAElement"):
		backend = "UIA"
		primary = {
			"automationId": getattr(obj, "UIAAutomationId", "") or "",
			"controlType": getattr(obj, "UIAControlType", "") or "",
			"className": getattr(obj, "UIAClassName", "") or "",
		}
		try:
			fast_path["runtimeId"] = obj.UIAElement.getRuntimeId()
		except Exception:
			pass

	elif hasattr(obj, "IAccessibleObject"):
		backend = "IAccessible"
		primary = {
			"accRole": obj.role,
			"windowClassName": getattr(obj, "windowClassName", "") or "",
		}
		if hasattr(obj, "IAccessibleChildID"):
			fast_path["childId"] = obj.IAccessibleChildID

	hash_str = json.dumps(primary, sort_keys=True)
	signature_hash = hashlib.md5(hash_str.encode("utf-8")).hexdigest()

	return {
		"backend": backend,
		"hash": signature_hash,
		"primarySignature": primary,
		"fastPathHints": fast_path,
		"fuzzyHints": fuzzy,
	}

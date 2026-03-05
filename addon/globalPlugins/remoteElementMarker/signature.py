import hashlib
import json
from typing import Any, Dict


def generate_signature(obj) -> Dict[str, Any]:
	"""
	Generates the deterministic signature for the object depending on its backend.
	Returns a dict with 'primarySignature', 'fastPathHints', 'fuzzyHints', 'hash' and 'backend'.

	Backend detection order:
	  1. BrowseMode — checked FIRST because a browse mode element also has IAccessibleObject.
	     If we checked IAccessible first, browse mode elements would be mis-classified,
	     producing a different hash than the one saved when marking.
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

	# ------------------------------------------------------------------ #
	# 1. BrowseMode — must be checked before IAccessible                  #
	#    An object is BrowseMode if it has a live, non-passthrough        #
	#    treeInterceptor. Just having treeInterceptor != None is not      #
	#    enough — it could be a passthrough (forms mode) element.         #
	# ------------------------------------------------------------------ #
	ti = getattr(obj, "treeInterceptor", None)
	in_browse_mode = (
		ti is not None
		and getattr(ti, "isReady", False)
		# Don't require passThrough==False: even focused form fields still
		# belong to the browse mode document and should use BrowseMode backend
		# so that their hash is consistent with how they were marked.
	)

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
		primary = {
			"role": obj.role,
			"name": getattr(obj, "name", "") or "",
			"url_if_web": url,
		}

	# ------------------------------------------------------------------ #
	# 2. UIA                                                               #
	# ------------------------------------------------------------------ #
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

	# ------------------------------------------------------------------ #
	# 3. IAccessible                                                       #
	# ------------------------------------------------------------------ #
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

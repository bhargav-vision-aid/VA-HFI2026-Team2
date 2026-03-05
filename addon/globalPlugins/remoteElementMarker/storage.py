import json
import os
from typing import Any, Dict, Optional

import config  # type: ignore
from logHandler import log  # type: ignore


def get_document_identifier(obj) -> Optional[str]:
	try:
		ti = getattr(obj, "treeInterceptor", None)
		doc_id = getattr(ti, "documentConstantIdentifier", None) if ti else None
		if doc_id:
			return str(doc_id)
	except Exception:
		return None
	return None


class MarkerStore:
	def __init__(self, config_path: Optional[str] = None):
		self._config_path = config_path or os.path.join(
			config.getUserDefaultConfigPath(), "remoteElementMarkers.json"
		)
		self._cache: Dict[str, Any] = {}
		self.load()

	def load(self) -> None:
		if os.path.exists(self._config_path):
			try:
				with open(self._config_path, "r", encoding="utf-8") as f:
					self._cache = json.load(f)
			except Exception as e:
				log.error(f"Failed to load Remote Element Markers from {self._config_path}: {e}")
				self._cache = {}
		else:
			self._cache = {}

	def save(self) -> None:
		try:
			with open(self._config_path, "w", encoding="utf-8") as f:
				json.dump(self._cache, f, indent=4)
		except Exception as e:
			log.error(f"Failed to save Remote Element Markers to {self._config_path}: {e}")
			raise

	def get_app_key(self, obj) -> str:
		process_name = getattr(obj, "processName", "unknown")
		app_module = getattr(obj.appModule, "appModuleName", "unknown") if obj.appModule else "unknown"
		parts = [process_name, app_module]
		doc_id = get_document_identifier(obj)
		if doc_id:
			parts.append(f"doc:{doc_id}")
		return "|".join(parts)

	def get_markers(self, app_key: str) -> Dict[str, Any]:
		return self._cache.get(app_key, {}).get("markers", {})

	def get_marker(self, app_key: str, sig_hash: str) -> Optional[Dict[str, Any]]:
		return self._cache.get(app_key, {}).get("markers", {}).get(sig_hash)

	def set_marker(self, app_key: str, sig_hash: str, marker_data: Dict[str, Any]) -> None:
		if app_key not in self._cache:
			self._cache[app_key] = {"markers": {}}
		self._cache[app_key]["markers"][sig_hash] = marker_data

	def delete_marker(self, app_key: str, sig_hash: str) -> bool:
		markers = self._cache.get(app_key, {}).get("markers", {})
		if sig_hash in markers:
			del markers[sig_hash]
			return True
		return False

	def all_markers(self) -> Dict[str, Any]:
		return self._cache

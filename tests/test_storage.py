import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "globalPlugins" / "remoteElementMarker"))

from storage import MarkerStore, get_document_identifier


class TestGetDocumentIdentifier:
	def test_with_valid_tree_interceptor(self):
		mock_ti = MagicMock()
		mock_ti.documentConstantIdentifier = "doc123"
		mock_obj = MagicMock()
		mock_obj.treeInterceptor = mock_ti

		result = get_document_identifier(mock_obj)
		assert result == "doc123"

	def test_with_none_tree_interceptor(self):
		mock_obj = MagicMock()
		mock_obj.treeInterceptor = None

		result = get_document_identifier(mock_obj)
		assert result is None

	def test_with_no_document_identifier(self):
		mock_ti = MagicMock()
		mock_ti.documentConstantIdentifier = None
		mock_obj = MagicMock()
		mock_obj.treeInterceptor = mock_ti

		result = get_document_identifier(mock_obj)
		assert result is None

	def test_with_exception(self):
		class FailingAttr:
			def __str__(self):
				raise Exception("test")

		mock_ti = MagicMock()
		mock_ti.documentConstantIdentifier = FailingAttr()
		mock_obj = MagicMock()
		mock_obj.treeInterceptor = mock_ti

		result = get_document_identifier(mock_obj)
		assert result is None


class TestMarkerStore:
	def test_init_with_default_path(self):
		with patch("storage.config") as mock_config, patch("storage.os.path.exists", return_value=False):
			mock_config.getUserDefaultConfigPath.return_value = "/tmp/nvda_config"
			store = MarkerStore()
			assert store._config_path == "/tmp/nvda_config/remoteElementMarkers.json"

	def test_init_with_custom_path(self, temp_config_file):
		store = MarkerStore(config_path=temp_config_file)
		assert store._config_path == temp_config_file

	def test_load_from_existing_file(self, temp_config_file):
		test_data = {"app1": {"markers": {"hash1": {"name": "Test"}}}}
		with open(temp_config_file, "w") as f:
			json.dump(test_data, f)

		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			assert store._cache == test_data

	def test_load_nonexistent_file(self, temp_config_file):
		os.unlink(temp_config_file)

		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			assert store._cache == {}

	def test_load_corrupted_file(self, temp_config_file):
		with open(temp_config_file, "w") as f:
			f.write("invalid json{")

		with patch("storage.log") as mock_log:
			store = MarkerStore(config_path=temp_config_file)
			assert store._cache == {}
			mock_log.error.assert_called()

	def test_save_to_file(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {"hash1": {"name": "Test"}}}}
			store.save()

			with open(temp_config_file) as f:
				loaded = json.load(f)
			assert loaded == {"app1": {"markers": {"hash1": {"name": "Test"}}}}

	def test_save_failure_logs_error(self, temp_config_file):
		with patch("storage.log") as mock_log:
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {}}}

			with patch("builtins.open", side_effect=Exception("write error")):
				with pytest.raises(Exception):
					store.save()
				mock_log.error.assert_called()

	def test_get_app_key(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)

			mock_obj = MagicMock()
			mock_obj.appModule.appName = "testapp"
			mock_obj.appModule.appModuleName = "testmodule"
			mock_obj.treeInterceptor = None

			key = store.get_app_key(mock_obj)
			assert key == "testapp|testmodule"

	def test_get_app_key_with_document_id(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)

			mock_ti = MagicMock()
			mock_ti.documentConstantIdentifier = "doc123"
			mock_obj = MagicMock()
			mock_obj.appModule.appName = "testapp"
			mock_obj.appModule.appModuleName = "testmodule"
			mock_obj.treeInterceptor = mock_ti

			key = store.get_app_key(mock_obj)
			assert key == "testapp|testmodule|doc:doc123"

	def test_get_markers(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {"h1": {"name": "Test"}}}}

			markers = store.get_markers("app1")
			assert markers == {"h1": {"name": "Test"}}

	def test_get_markers_nonexistent_app(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {}

			markers = store.get_markers("nonexistent")
			assert markers == {}

	def test_get_marker(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {"h1": {"name": "Test"}}}}

			marker = store.get_marker("app1", "h1")
			assert marker == {"name": "Test"}

	def test_get_marker_not_found(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {}}}

			marker = store.get_marker("app1", "nonexistent")
			assert marker is None

	def test_set_marker(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store.set_marker("app1", "h1", {"name": "Test"})

			assert store._cache["app1"]["markers"]["h1"] == {"name": "Test"}

	def test_set_marker_creates_new_app_key(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store.set_marker("newapp", "h1", {"name": "Test"})

			assert "newapp" in store._cache
			assert store._cache["newapp"]["markers"]["h1"] == {"name": "Test"}

	def test_delete_marker_existing(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {"h1": {"name": "Test"}}}}

			result = store.delete_marker("app1", "h1")
			assert result is True
			assert "h1" not in store._cache["app1"]["markers"]

	def test_delete_marker_nonexistent(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {}}}

			result = store.delete_marker("app1", "nonexistent")
			assert result is False

	def test_all_markers(self, temp_config_file):
		with patch("storage.log"):
			store = MarkerStore(config_path=temp_config_file)
			store._cache = {"app1": {"markers": {}}, "app2": {"markers": {}}}

			all_m = store.all_markers()
			assert all_m == {"app1": {"markers": {}}, "app2": {"markers": {}}}

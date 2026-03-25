import os
import sys
import tempfile
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest


class MockConfig:
	class conf:
		spec = {}

	@staticmethod
	def getUserDefaultConfigPath():
		return "/tmp/nvda_config"


class MockLog:
	@staticmethod
	def debugWarning(*args, **kwargs):
		pass

	@staticmethod
	def error(*args, **kwargs):
		pass

	@staticmethod
	def warning(*args, **kwargs):
		pass


class MockTextInfos:
	POSITION_ALL = "all"
	POSITION_CARET = "caret"
	POSITION_FIRST = "first"


sys.modules["config"] = MockConfig()
sys.modules["logHandler"] = MagicMock()
sys.modules["logHandler"].log = MockLog()
sys.modules["textInfos"] = MockTextInfos()


class MockAppModule:
	def __init__(self, app_name: str = "testapp", app_module_name: str = "testmodule"):
		self.appName = app_name
		self.appModuleName = app_module_name


class MockTreeInterceptor:
	def __init__(
		self,
		is_ready: bool = True,
		document_constant_identifier: Optional[str] = None,
		root_nvda_object: Optional[Any] = None,
	):
		self.isReady = is_ready
		self.documentConstantIdentifier = document_constant_identifier
		self._root_nvda_object = root_nvda_object

	@property
	def rootNVDAObject(self):
		return self._root_nvda_object


class MockNVDAObject:
	def __init__(
		self,
		role: int = 0,
		name: str = "",
		tree_interceptor: Optional[MockTreeInterceptor] = None,
		app_module: Optional[MockAppModule] = None,
		location: Optional[tuple] = None,
		**attrs,
	):
		self.role = role
		self.name = name
		self.treeInterceptor = tree_interceptor
		self.appModule = app_module
		self.location = location
		for k, v in attrs.items():
			setattr(self, k, v)


class MockUIAObject(MockNVDAObject):
	def __init__(
		self,
		uia_element: Optional[Any] = None,
		uia_automation_id: str = "",
		uia_control_type: str = "",
		uia_class_name: str = "",
		**kwargs,
	):
		super().__init__(**kwargs)
		self.UIAElement = uia_element
		self.UIAAutomationId = uia_automation_id
		self.UIAControlType = uia_control_type
		self.UIAClassName = uia_class_name


class MockIAccessibleObject(MockNVDAObject):
	def __init__(
		self,
		iaccessible_object: Optional[Any] = None,
		iaccessible_child_id: Optional[int] = None,
		window_class_name: str = "",
		acc_role: int = 0,
		**kwargs,
	):
		super().__init__(**kwargs)
		self.IAccessibleObject = iaccessible_object
		self.IAccessibleChildID = iaccessible_child_id
		self.windowClassName = window_class_name
		self.role = acc_role


class MockTextInfo:
	def __init__(self, text: str = "", offset: int = 0):
		self._text = text
		self._offset = offset

	def getText(self) -> str:
		return self._text

	def makeTextInfo(self, position):
		return MockTextInfo(self._text, self._offset)

	def copy(self):
		return MockTextInfo(self._text, self._offset)

	def setEndPoint(self, other, point):
		pass


class MockRootNode:
	def __init__(self, role: int = 0, name: str = "", children: Optional[list] = None):
		self.role = role
		self.name = name
		self.firstChild = children[0] if children else None
		self.next = None
		self._children = children or []

	def makeTextInfo(self, position):
		return MockTextInfo(text="")


def create_mock_tree(root_children: list) -> Optional[MockRootNode]:
	if not root_children:
		return None
	return MockRootNode(children=root_children)


@pytest.fixture
def temp_config_file():
	fd, path = tempfile.mkstemp(suffix=".json")
	os.close(fd)
	yield path
	if os.path.exists(path):
		os.unlink(path)


@pytest.fixture
def sample_marker_data() -> Dict[str, Any]:
	return {
		"backend": "BrowseMode",
		"hash": "abc123def456",
		"friendlyName": "Test Button",
		"shortcut": "kb:NVDA+alt+1",
		"primarySignature": {
			"role": 0,
			"name": "Test Button",
			"url_if_web": "https://example.com",
			"role_index": 0,
			"context_before": "Some text before",
			"context_after": "Some text after",
		},
		"fastPathHints": {},
		"fuzzyHints": {"name": "Test Button"},
	}


@pytest.fixture
def sample_storage_data() -> Dict[str, Any]:
	return {
		"testapp|testmodule": {
			"markers": {
				"abc123def456": {
					"backend": "BrowseMode",
					"hash": "abc123def456",
					"friendlyName": "Test Button",
					"shortcut": "kb:NVDA+alt+1",
					"primarySignature": {"role": 0, "name": "Test Button"},
				}
			}
		}
	}

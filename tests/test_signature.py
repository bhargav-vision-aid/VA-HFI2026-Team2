import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "globalPlugins" / "remoteElementMarker"))

from signature import (
	generate_signature,
	generate_signature_for_lookup,
	root_obj_fallback,
	_compute_position_hints,
	_count_by_tree_order,
)


class MockTreeInterceptor:
	def __init__(self, is_ready=True, doc_id=None, root_obj=None):
		self.isReady = is_ready
		self.documentConstantIdentifier = doc_id
		self._root_obj = root_obj

	@property
	def rootNVDAObject(self):
		return self._root_obj


class MockObj:
	def __init__(
		self,
		role=0,
		name="",
		tree_interceptor=None,
		location=None,
		uia_element=None,
		iaccessible_object=None,
		**attrs,
	):
		self.role = role
		self.name = name
		self.treeInterceptor = tree_interceptor
		self.location = location
		self.UIAElement = uia_element
		self.IAccessibleObject = iaccessible_object
		for k, v in attrs.items():
			setattr(self, k, v)


class TestRootObjFallback:
	def test_returns_root_nvda_object(self):
		mock_ti = MagicMock()
		mock_ti.rootNVDAObject = "root_object"

		result = root_obj_fallback(mock_ti)
		assert result == "root_object"

	def test_returns_none_on_exception(self):
		class FailingAttr:
			@property
			def rootNVDAObject(self):
				raise Exception("test")

		mock_ti = FailingAttr()

		result = root_obj_fallback(mock_ti)
		assert result is None


class TestGenerateSignatureForLookup:
	def test_browse_mode_backend(self):
		mock_ti = MockTreeInterceptor(is_ready=True, doc_id="https://example.com")
		mock_obj = MockObj(role=0, name="Test Button", tree_interceptor=mock_ti)

		result = generate_signature_for_lookup(mock_obj)

		assert result["backend"] == "BrowseMode"
		assert "hash" in result
		assert "primarySignature" in result
		assert result["primarySignature"]["role"] == 0
		assert result["primarySignature"]["name"] == "Test Button"
		assert result["primarySignature"]["url_if_web"] == "https://example.com"

	def test_uia_backend(self):
		mock_uia_element = MagicMock()
		mock_obj = MockObj(
			role=0,
			name="",
			uia_element=mock_uia_element,
			UIAAutomationId="btnSubmit",
			UIAControlType="Button",
			UIAClassName="SubmitButton",
		)

		result = generate_signature_for_lookup(mock_obj)

		assert result["backend"] == "UIA"
		assert "hash" in result
		assert result["primarySignature"]["automationId"] == "btnSubmit"
		assert result["primarySignature"]["controlType"] == "Button"
		assert result["primarySignature"]["className"] == "SubmitButton"
		assert "runtimeId" in result["fastPathHints"]

	def test_iaccessible_backend(self):
		from unittest.mock import MagicMock

		class TestObj:
			def __init__(self):
				self.role = 0
				self.name = ""
				self.treeInterceptor = None
				self.IAccessibleObject = MagicMock()
				self.IAccessibleChildID = 5
				self.windowClassName = "Edit"

		mock_obj = TestObj()

		result = generate_signature_for_lookup(mock_obj)

		assert result["backend"] == "IAccessible"
		assert "hash" in result
		assert result["primarySignature"]["accRole"] == 0
		assert result["primarySignature"]["windowClassName"] == "Edit"
		assert result["fastPathHints"]["childId"] == 5

	def test_unknown_backend(self):

		class TestObj:
			def __init__(self):
				self.role = 0
				self.name = ""
				self.treeInterceptor = None

		mock_obj = TestObj()

		result = generate_signature_for_lookup(mock_obj)

		assert result["backend"] == "Unknown"
		assert "hash" in result

	def test_hash_is_md5_of_primary(self):
		mock_obj = MockObj(role=0, name="Test", tree_interceptor=None)

		result = generate_signature_for_lookup(mock_obj)

		primary_json = json.dumps(result["primarySignature"], sort_keys=True)
		expected_hash = hashlib.md5(primary_json.encode("utf-8")).hexdigest()
		assert result["hash"] == expected_hash


class TestGenerateSignature:
	def test_browse_mode_with_position_hints(self):
		mock_root = MagicMock()
		mock_root.role = 0
		mock_root.name = "root"
		mock_root.firstChild = None
		mock_root.location = (0, 0)

		mock_ti = MockTreeInterceptor(is_ready=True, doc_id="https://example.com", root_obj=mock_root)
		mock_obj = MockObj(role=0, name="Test Button", tree_interceptor=mock_ti, location=(100, 100))

		with patch("signature._compute_position_hints") as mock_compute:
			mock_compute.return_value = {
				"role_index": 2,
				"context_before": "before text",
				"context_after": "after text",
			}

			result = generate_signature(mock_obj)

		assert result["backend"] == "BrowseMode"
		assert result["primarySignature"]["role_index"] == 2
		assert result["primarySignature"]["context_before"] == "before text"
		assert result["primarySignature"]["context_after"] == "after text"
		assert "fuzzyHints" in result
		assert result["fuzzyHints"]["name"] == "Test Button"
		assert result["fuzzyHints"]["url_if_web"] == "https://example.com"

	def test_uia_backend_full_signature(self):
		mock_uia_element = MagicMock()
		mock_obj = MockObj(
			role=0,
			name="",
			tree_interceptor=None,
			uia_element=mock_uia_element,
			UIAAutomationId="btnSubmit",
			UIAControlType="Button",
			UIAClassName="SubmitButton",
		)

		result = generate_signature(mock_obj)

		assert result["backend"] == "UIA"
		assert result["primarySignature"]["automationId"] == "btnSubmit"
		assert result["primarySignature"]["controlType"] == "Button"
		assert result["primarySignature"]["className"] == "SubmitButton"
		assert "runtimeId" in result["fastPathHints"]

	def test_iaccessible_backend_full_signature(self):
		from unittest.mock import MagicMock

		class TestObj:
			def __init__(self):
				self.role = 32
				self.name = ""
				self.treeInterceptor = None
				self.IAccessibleObject = MagicMock()
				self.IAccessibleChildID = 5
				self.windowClassName = "Edit"

		mock_obj = TestObj()

		result = generate_signature(mock_obj)

		assert result["backend"] == "IAccessible"
		assert result["primarySignature"]["accRole"] == 32
		assert result["primarySignature"]["windowClassName"] == "Edit"
		assert result["fastPathHints"]["childId"] == 5

	def test_unknown_backend(self):

		class TestObj:
			def __init__(self):
				self.role = 0
				self.name = "Test"
				self.treeInterceptor = None

		mock_obj = TestObj()

		result = generate_signature(mock_obj)

		assert result["backend"] == "Unknown"

	def test_empty_name_handled(self):
		mock_obj = MockObj(role=0, name="", tree_interceptor=None)

		result = generate_signature(mock_obj)

		assert result["fuzzyHints"]["name"] == ""


class TestComputePositionHints:
	def test_none_tree_interceptor(self):
		mock_obj = MagicMock()

		result = _compute_position_hints(mock_obj, None)

		assert result["role_index"] == -1
		assert result["context_before"] == ""
		assert result["context_after"] == ""

	def test_tree_interceptor_not_ready(self):
		mock_ti = MockTreeInterceptor(is_ready=False)
		mock_obj = MagicMock()

		result = _compute_position_hints(mock_obj, mock_ti)

		assert result["role_index"] == -1

	def test_uses_location_for_matching(self):
		mock_root = MagicMock()
		mock_root.role = 0
		mock_root.name = ""
		mock_root.firstChild = None
		mock_root.location = None

		mock_target = MagicMock()
		mock_target.role = 0
		mock_target.name = "target"
		mock_target.location = (100, 100)

		mock_ti = MockTreeInterceptor(is_ready=True, root_obj=mock_root)

		result = _compute_position_hints(mock_target, mock_ti)

		assert "role_index" in result


class TestCountByTreeOrder:
	def test_fallback_counting(self):
		mock_root = MagicMock()
		mock_root.role = 0
		mock_root.name = ""
		mock_root.firstChild = None

		mock_ti = MockTreeInterceptor(is_ready=True, root_obj=mock_root)

		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = "target"

		result = _count_by_tree_order(mock_obj, mock_ti, 0, "target")

		assert isinstance(result, int)

	def test_exception_returns_negative_one(self):
		from unittest.mock import PropertyMock

		mock_root = MagicMock()
		mock_root.role = PropertyMock(side_effect=Exception("test"))
		mock_root.firstChild = None
		mock_root.name = ""

		mock_ti = MagicMock()
		mock_ti.rootNVDAObject = mock_root

		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = "target"

		result = _count_by_tree_order(mock_obj, mock_ti, 0, "target")

		assert result == -1

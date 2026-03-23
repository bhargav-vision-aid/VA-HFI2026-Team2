import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "globalPlugins" / "remoteElementMarker"))

from resolver import (
	_match_uia,
	_match_iaccessible,
	_match_browsemode_simple,
)


class TestMatchUIA:
	def test_all_fields_match(self):
		mock_obj = MagicMock()
		mock_obj.UIAAutomationId = "btnSubmit"
		mock_obj.UIAControlType = "Button"
		mock_obj.UIAClassName = "SubmitButton"

		primary = {
			"automationId": "btnSubmit",
			"controlType": "Button",
			"className": "SubmitButton",
		}

		assert _match_uia(mock_obj, primary) is True

	def test_partial_match_automation_id(self):
		mock_obj = MagicMock()
		mock_obj.UIAAutomationId = "btnSubmit"
		mock_obj.UIAControlType = "Button"
		mock_obj.UIAClassName = "SubmitButton"

		primary = {"automationId": "btnSubmit"}

		assert _match_uia(mock_obj, primary) is True

	def test_mismatch_automation_id(self):
		mock_obj = MagicMock()
		mock_obj.UIAAutomationId = "btnCancel"
		mock_obj.UIAControlType = "Button"
		mock_obj.UIAClassName = "SubmitButton"

		primary = {"automationId": "btnSubmit"}

		assert _match_uia(mock_obj, primary) is False

	def test_mismatch_control_type(self):
		mock_obj = MagicMock()
		mock_obj.UIAAutomationId = "btnSubmit"
		mock_obj.UIAControlType = "Text"
		mock_obj.UIAClassName = "SubmitButton"

		primary = {"controlType": "Button"}

		assert _match_uia(mock_obj, primary) is False

	def test_mismatch_class_name(self):
		mock_obj = MagicMock()
		mock_obj.UIAAutomationId = "btnSubmit"
		mock_obj.UIAControlType = "Button"
		mock_obj.UIAClassName = "CancelButton"

		primary = {"className": "SubmitButton"}

		assert _match_uia(mock_obj, primary) is False

	def test_empty_primary_returns_false(self):
		mock_obj = MagicMock()

		primary = {}

		assert _match_uia(mock_obj, primary) is False


class TestMatchIAccessible:
	def test_role_and_class_match(self):
		mock_obj = MagicMock()
		mock_obj.role = 32
		mock_obj.windowClassName = "Edit"

		primary = {"accRole": 32, "windowClassName": "Edit"}

		assert _match_iaccessible(mock_obj, primary) is True

	def test_role_match_only(self):
		mock_obj = MagicMock()
		mock_obj.role = 32
		mock_obj.windowClassName = "Edit"

		primary = {"accRole": 32}

		assert _match_iaccessible(mock_obj, primary) is True

	def test_role_mismatch(self):
		mock_obj = MagicMock()
		mock_obj.role = 32

		primary = {"accRole": 64}

		assert _match_iaccessible(mock_obj, primary) is False

	def test_class_mismatch(self):
		mock_obj = MagicMock()
		mock_obj.role = 32
		mock_obj.windowClassName = "Button"

		primary = {"accRole": 32, "windowClassName": "Edit"}

		assert _match_iaccessible(mock_obj, primary) is False


class TestMatchBrowsemodeSimple:
	def test_role_and_name_match(self):
		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = "Test Button"

		primary = {"role": 0, "name": "Test Button"}

		assert _match_browsemode_simple(mock_obj, primary) is True

	def test_role_mismatch(self):
		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = "Test"

		primary = {"role": 1, "name": "Test"}

		assert _match_browsemode_simple(mock_obj, primary) is False

	def test_name_mismatch(self):
		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = "Test"

		primary = {"role": 0, "name": "Other"}

		assert _match_browsemode_simple(mock_obj, primary) is False

	def test_empty_name_handled(self):
		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = ""

		primary = {"role": 0, "name": ""}

		assert _match_browsemode_simple(mock_obj, primary) is True

	def test_url_mismatch_returns_false(self):
		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = "Test"
		mock_obj.treeInterceptor = MagicMock()
		mock_obj.treeInterceptor.documentConstantIdentifier = "http://other.com"

		primary = {"role": 0, "name": "Test", "url_if_web": "http://example.com"}

		assert _match_browsemode_simple(mock_obj, primary) is False

	def test_url_match_returns_true(self):
		mock_obj = MagicMock()
		mock_obj.role = 0
		mock_obj.name = "Test"
		mock_obj.treeInterceptor = MagicMock()
		mock_obj.treeInterceptor.documentConstantIdentifier = "http://example.com"

		primary = {"role": 0, "name": "Test", "url_if_web": "http://example.com"}

		assert _match_browsemode_simple(mock_obj, primary) is True


class TestGetObjTextOffset:
	pass


class TestUiaFastPath:
	pass


class TestTreeWalkIter:
	def test_finds_matching_object(self):
		from resolver import _tree_walk_iter

		mock_matching = MagicMock()
		mock_matching.role = 0
		mock_matching.name = "target"
		mock_matching.firstChild = None
		mock_matching.next = None

		mock_root = MagicMock()
		mock_root.role = 1
		mock_root.name = "root"
		mock_root.firstChild = mock_matching
		mock_root.next = None

		backend = "BrowseMode"
		primary = {"role": 0, "name": "target"}

		walker = _tree_walk_iter(backend, primary, mock_root)

		result = next(walker)
		assert result is None
		result = next(walker)
		assert result is mock_matching

	def test_yields_none_for_nonmatching(self):
		from resolver import _tree_walk_iter

		mock_nonmatching = MagicMock()
		mock_nonmatching.role = 1
		mock_nonmatching.name = "other"
		mock_nonmatching.firstChild = None
		mock_nonmatching.next = None

		mock_root = MagicMock()
		mock_root.role = 0
		mock_root.name = "root"
		mock_root.firstChild = mock_nonmatching
		mock_root.next = None

		backend = "BrowseMode"
		primary = {"role": 0, "name": "target"}

		walker = _tree_walk_iter(backend, primary, mock_root)

		result = next(walker)
		assert result is None
		result = next(walker)
		assert result is None


class TestBrowsemodeResolve:
	pass


class TestUiaFastPathFailed:
	pass

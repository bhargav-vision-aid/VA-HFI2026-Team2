import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "addon" / "globalPlugins" / "remoteElementMarker"))

from bindings import normalize_shortcut


class TestNormalizeShortcut:
	def test_none_input(self):
		result = normalize_shortcut(None)
		assert result is None

	def test_empty_string(self):
		result = normalize_shortcut("")
		assert result is None

	def test_whitespace_only(self):
		result = normalize_shortcut("   ")
		assert result is None

	def test_adds_kb_prefix(self):
		result = normalize_shortcut("NVDA+alt+1")
		assert result == "kb:NVDA+alt+1"

	def test_preserves_kb_prefix(self):
		result = normalize_shortcut("kb:NVDA+alt+1")
		assert result == "kb:NVDA+alt+1"

	def test_normalizes_ctrl_token(self):
		result = normalize_shortcut("Ctrl+Alt+1")
		assert result == "kb:control+alt+1"

	def test_normalizes_control_token(self):
		result = normalize_shortcut("Control+Shift+A")
		assert result == "kb:control+shift+a"

	def test_normalizes_alt_token(self):
		result = normalize_shortcut("ALT+X")
		assert result == "kb:alt+x"

	def test_normalizes_shift_token(self):
		result = normalize_shortcut("SHIFT+Enter")
		assert result == "kb:shift+enter"

	def test_normalizes_win_token(self):
		result = normalize_shortcut("WIN+D")
		assert result == "kb:windows+d"

	def test_normalizes_windows_token(self):
		result = normalize_shortcut("WINDOWS+B")
		assert result == "kb:windows+b"

	def test_normalizes_nvda_token(self):
		result = normalize_shortcut("nvda+t")
		assert result == "kb:NVDA+t"

	def test_removes_spaces(self):
		result = normalize_shortcut("NVDA + alt + 1")
		assert result == "kb:NVDA+alt+1"

	def test_no_colon_no_parts(self):
		result = normalize_shortcut("   ")
		assert result is None

	def test_colon_with_empty_after(self):
		result = normalize_shortcut("kb:")
		assert result is None

	def test_colon_with_empty_parts(self):
		result = normalize_shortcut("kb:+")
		assert result is None

	def test_mixed_case_normalization(self):
		result = normalize_shortcut("NvDa+AlT+ShIfT+1")
		assert result == "kb:NVDA+alt+shift+1"

	def test_special_keys(self):
		result = normalize_shortcut("kb:enter")
		assert result == "kb:enter"

	def test_function_keys(self):
		result = normalize_shortcut("kb:f1")
		assert result == "kb:f1"

	def test_arrow_keys(self):
		result = normalize_shortcut("kb:up")
		assert result == "kb:up"

	def test_laptop_layout(self):
		result = normalize_shortcut("kb(laptop):NVDA+alt+1")
		assert result == "kb(laptop):NVDA+alt+1"

	def test_desktop_layout(self):
		result = normalize_shortcut("kb(desktop):NVDA+alt+1")
		assert result == "kb(desktop):NVDA+alt+1"

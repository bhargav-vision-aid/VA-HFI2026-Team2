from __future__ import annotations

try:
	import ui
except Exception:
	ui = None

try:
	import tones
except Exception:
	tones = None

from .elementCapture import ElementMetadata


CAPTURE_SUCCESS_SOUND = (440, 50)
CAPTURE_ERROR_SOUND = (220, 100)


def _speak(message: str) -> None:
	if ui:
		ui.message(message)


def _beep(frequency: int, duration: int) -> None:
	if tones:
		tones.beep(frequency, duration)


def announce_element_captured(metadata: ElementMetadata) -> None:
	if not metadata:
		_announce_failure()
		return

	if metadata.name:
		if metadata.role_text:
			message = f"{metadata.name} {metadata.role_text} captured"
		else:
			message = f"{metadata.name} captured"
	else:
		if metadata.role_text:
			message = f"{metadata.role_text} captured"
		else:
			message = "Element captured"

	_speak(message)
	_beep(*CAPTURE_SUCCESS_SOUND)


def announce_element_captured_at_point(x: int, y: int, metadata: ElementMetadata) -> None:
	if not metadata:
		_announce_failure()
		return

	if metadata.name:
		if metadata.role_text:
			message = f"{metadata.name} {metadata.role_text} at position {x}, {y} captured"
		else:
			message = f"{metadata.name} at position {x}, {y} captured"
	else:
		if metadata.role_text:
			message = f"{metadata.role_text} at position {x}, {y} captured"
		else:
			message = f"Element at position {x}, {y} captured"

	_speak(message)
	_beep(*CAPTURE_SUCCESS_SOUND)


def announce_no_element() -> None:
	_speak("No element to capture")
	_beep(*CAPTURE_ERROR_SOUND)


def announce_not_actionable() -> None:
	_speak("No actionable element")
	_beep(*CAPTURE_ERROR_SOUND)


def _announce_failure() -> None:
	_speak("Could not capture element")
	_beep(*CAPTURE_ERROR_SOUND)


def announce_capture_mode(mode: str) -> None:
	if mode == "focused":
		_speak("Capture focused element")
	elif mode == "mouse":
		_speak("Click on element to capture")
	else:
		_speak(f"Capture mode: {mode}")


def announce_remote_session(enabled: bool) -> None:
	if enabled:
		_speak("Remote session detected")
	else:
		_speak("Local session")

import globalPluginHandler
from scriptHandler import script
import ui
from logHandler import log

from .elementCapture import (capture_element_at_mouse,
                             capture_focused_element, is_remote_session)
from .speechFeedback import (announce_element_captured, announce_no_element,
                             announce_not_actionable)


class GlobalPlugin(globalPluginHandler.GlobalPlugin):

    def __init__(self):
        super().__init__()
        log.info("CustomRemoteGesture add-on loaded")
        self._last_captured_metadata = None

    @property
    def last_captured_metadata(self):
        return self._last_captured_metadata

    @last_captured_metadata.setter
    def last_captured_metadata(self, value):
        self._last_captured_metadata = value

    @script(
            description=_("Test capture"),
            gesture="kb:NVDA+shift+c"
    )
    def script_captureFocusedElement(self, gesture):
        log.debug("Capturing focused element")
        metadata = capture_focused_element()

        if metadata is None:
            import api
            obj = api.getFocusObject()
            if obj is None:
                announce_no_element()
            else:
                announce_not_actionable()
            return

        self.last_captured_metadata = metadata
        announce_element_captured(metadata)
        log.debug(f"Captured: {metadata.name} ({metadata.role_text})")

    @script(
            description=_("Test capture"),
            gesture="kb:NVDA+shift+m"
    )
    def script_captureAtMouse(self, gesture):
        log.debug("Capturing element at mouse position")
        metadata = capture_element_at_mouse()

        if metadata is None:
            announce_no_element()
            return

        self.last_captured_metadata = metadata
        announce_element_captured(metadata)
        log.debug(f"Captured at mouse: {metadata.name} ({metadata.role_text})")

    @script(
            description=_("Test capture"),
            gesture="kb:NVDA+shift+s"
    )
    def script_checkSession(self, gesture):
        is_remote = is_remote_session()
        if is_remote:
            ui.message("Remote session active")
        else:
            ui.message("Local session")
        log.debug(f"Remote session: {is_remote}")

    def terminate(self):
        log.info("CustomRemoteGesture add-on terminating")
        super().terminate()


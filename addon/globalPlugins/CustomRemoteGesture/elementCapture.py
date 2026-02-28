from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set
from logHandler import log

try:
	import api
	import controlTypes
	from NVDAObjects import NVDAObject
except Exception:
	api = None
	controlTypes = None
	NVDAObject = None


@dataclass
class ElementMetadata:
    name: str
    role: str
    role_text: str
    states: Set[str]
    processID: int
    windowHandle: int
    windowClassName: str
    windowControlID: int
    value: str
    location: Optional[tuple[int, int, int, int]]
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "role_text": self.role_text,
            "states": list(self.states),
            "processID": self.processID,
            "windowHandle": self.windowHandle,
            "windowClassName": self.windowClassName,
            "windowControlID": self.windowControlID,
            "value": self.value,
            "location": self.location,
            "timestamp": self.timestamp.isoformat(),
        }

    def has_meaningful_content(self) -> bool:
        return bool(self.name or self.value)


def get_focused_element() -> Optional[NVDAObject]:
	if api is None:
		return None
	try:
		obj = api.getFocusObject()
		if obj:
			log.debug(f"Focused element: {obj.name} role={obj.role}")
		return obj
	except Exception as e:
		log.error(f"Error getting focused element: {e}")
		return None


def get_element_at_point(x: int, y: int) -> Optional[NVDAObject]:
	if NVDAObject is None:
		return None
	try:
		obj = NVDAObject.objectFromPoint(x, y)
		if obj:
			log.debug(f"Element at point ({x}, {y}): {obj.name} role={obj.role}")
		return obj
	except Exception as e:
		log.error(f"Error getting element at point ({x}, {y}): {e}")
		return None


def get_element_at_mouse_position() -> Optional[NVDAObject]:
	try:
		import winUser
		x, y = winUser.getCursorPos()
		return get_element_at_point(x, y)
	except Exception as e:
		log.error(f"Error getting mouse position: {e}")
		return None


def extract_metadata(obj: NVDAObject) -> Optional[ElementMetadata]:
	if controlTypes is None:
		return None
	if not obj:
		return None

	try:
		name = getattr(obj, "name", "") or ""
		if callable(name):
			name = name() or ""

		role = getattr(obj, "role", None)
		role_text = ""
		if role is not None:
			try:
				role_text = controlTypes.role.Roles.get(role, "").displayName if hasattr(controlTypes.role.Roles.get(role, 0), 'displayName') else str(role)
			except Exception:
				role_text = str(role)
			if not role_text:
				role_text = _get_role_display_name(role)

		states: Set[str] = set()
		try:
			obj_states = getattr(obj, "states", None)
			if obj_states:
				for state in obj_states:
					try:
						state_name = controlTypes.state.STATES.get(state, "").displayName if hasattr(controlTypes.state.STATES.get(state, 0), 'displayName') else str(state)
					except Exception:
						state_name = str(state)
					if state_name:
						states.add(state_name)
					else:
						states.add(_get_state_display_name(state))
		except Exception:
			pass

		processID = getattr(obj, "processID", None) or 0

		windowHandle = 0
		try:
			windowHandle = getattr(obj, "windowHandle", None) or 0
			if not windowHandle and hasattr(obj, '_windowHandle'):
				windowHandle = obj._windowHandle
		except Exception:
			pass

		windowClassName = ""
		try:
			windowClassName = getattr(obj, "windowClassName", "") or ""
			if callable(windowClassName):
				windowClassName = windowClassName() or ""
		except Exception:
			pass

		windowControlID = 0
		try:
			windowControlID = getattr(obj, "windowControlID", None) or 0
		except Exception:
			pass

		value = ""
		try:
			value = getattr(obj, "value", "") or ""
			if callable(value):
				value = value() or ""
		except Exception:
			pass

		location = None
		try:
			location = getattr(obj, "location", None)
			if location:
				location = (location.left, location.top, location.width, location.height)
		except Exception:
			pass

		return ElementMetadata(
			name=name,
			role=str(role) if role is not None else "",
			role_text=role_text,
			states=states,
			processID=processID,
			windowHandle=windowHandle,
			windowClassName=windowClassName,
			windowControlID=windowControlID,
			value=value,
			location=location,
		)

	except Exception as e:
		log.error(f"Error extracting metadata: {e}")
		return None


ROLE_MAP = {
	"ROLE_PUSHBUTTON": "button",
	"ROLE_CHECKBOX": "check box",
	"ROLE_RADIOBUTTON": "radio button",
	"ROLE_COMBOBOX": "combo box",
	"ROLE_EDIT": "edit",
	"ROLE_EDITABLETEXT": "edit",
	"ROLE_LINK": "link",
	"ROLE_LIST": "list",
	"ROLE_LISTITEM": "list item",
	"ROLE_TREEVIEW": "tree view",
	"ROLE_TREEVIEWITEM": "tree view item",
	"ROLE_MENU": "menu",
	"ROLE_MENUITEM": "menu item",
	"ROLE_TAB": "tab",
	"ROLE_TABCONTROL": "tab control",
	"ROLE_SLIDER": "slider",
	"ROLE_PROGRESSBAR": "progress bar",
	"ROLE_STATUSBAR": "status bar",
	"ROLE_TOOLTIP": "tooltip",
	"ROLE_PANE": "pane",
	"ROLE_DIALOG": "dialog",
	"ROLE_WINDOW": "window",
	"ROLE_DOCUMENT": "document",
	"ROLE_GRAPHIC": "graphic",
	"ROLE_HELP": "help",
	"ROLE_UNKNOWN": "unknown",
}


def _get_role_display_name(role: int) -> str:
	if controlTypes is None:
		return str(role)
	role_name = ""
	for attr in dir(controlTypes):
		if attr.startswith("ROLE_") and getattr(controlTypes, attr, None) == role:
			role_name = attr.replace("ROLE_", "").lower()
			break
	return ROLE_MAP.get(role_name, str(role))


STATE_MAP = {
	"STATE_FOCUSED": "focused",
	"STATE_SELECTED": "selected",
	"STATE_CHECKED": "checked",
	"STATE_PRESSED": "pressed",
	"STATE_EXPANDED": "expanded",
	"STATE_COLLAPSED": "collapsed",
	"STATE_READONLY": "read only",
	"STATE_HASPOPUP": "has popup",
	"STATE_REQUIRED": "required",
	"STATE_VISITED": "visited",
	"STATE_DISABLED": "disabled",
	"STATE_INVISIBLE": "invisible",
	"STATE_OFFSCREEN": "off screen",
}


def _get_state_display_name(state: int) -> str:
	if controlTypes is None:
		return str(state)
	state_name = ""
	for attr in dir(controlTypes):
		if attr.startswith("STATE_") and getattr(controlTypes, attr, None) == state:
			state_name = attr.replace("STATE_", "").lower()
			break
	return STATE_MAP.get(state_name, str(state))


def is_actionable(obj: Optional[NVDAObject]) -> bool:
	if not obj:
		return False

	try:
		if not hasattr(obj, "processID") or not obj.processID:
			log.debug("Element not actionable: no processID")
			return False

		name = getattr(obj, "name", "") or ""
		if callable(name):
			name = name() or ""
		value = getattr(obj, "value", "") or ""
		if callable(value):
			value = value() or ""
		if not name and not value:
			log.debug("Element not actionable: no name or value")
			return False

		try:
			if controlTypes is not None:
				role = getattr(obj, "role", None)
				if role == controlTypes.ROLE_PANE:
					if not (obj.firstChild or obj.next):
						log.debug("Element not actionable: empty pane")
						return False
		except Exception:
			pass

		return True

	except Exception as e:
		log.error(f"Error checking if actionable: {e}")
		return False


def capture_focused_element() -> Optional[ElementMetadata]:
    obj = get_focused_element()
    if not obj:
        log.debug("No focused element to capture")
        return None

    if not is_actionable(obj):
        log.debug("Focused element is not actionable")
        return None

    return extract_metadata(obj)


def capture_element_at_point(x: int, y: int) -> Optional[ElementMetadata]:
    obj = get_element_at_point(x, y)
    if not obj:
        log.debug(f"No element at point ({x}, {y}) to capture")
        return None

    if not is_actionable(obj):
        log.debug(f"Element at point ({x}, {y}) is not actionable")
        return None

    return extract_metadata(obj)


def capture_element_at_mouse() -> Optional[ElementMetadata]:
    obj = get_element_at_mouse_position()
    if not obj:
        log.debug("No element at mouse position to capture")
        return None

    if not is_actionable(obj):
        log.debug("Element at mouse position is not actionable")
        return None

    return extract_metadata(obj)


REMOTE_WINDOW_CLASSES = {
    "TstNotepad",
    "Teams",
    "Microsoft Teams",
    "Microsoft Teams - Preview",
    "Chrome Legacy Window",
    "MozillaWindowClass",
    "Windows.UI.Core.CoreWindow",
    "ApplicationFrameWindow",
    "RDP",
    "mstsc",
}


def is_remote_session() -> bool:
    try:
        foreground = api.getForegroundObject()
        if not foreground:
            return False

        windowClass = getattr(foreground, "windowClassName", "") or ""
        if callable(windowClass):
            windowClass = windowClass() or ""

        if windowClass in REMOTE_WINDOW_CLASSES:
            return True

        for remote_class in REMOTE_WINDOW_CLASSES:
            if remote_class.lower() in windowClass.lower():
                return True

        return False

    except Exception as e:
        log.error(f"Error checking remote session: {e}")
        return False

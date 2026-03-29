# -*- coding: UTF-8 -*-
import hashlib
import json
import time
from typing import Any, Dict, Callable, Tuple, List

from logHandler import log  # type: ignore
from .storage import is_stable_document_identifier

_CHUNK_SIZE = 50

# Keep mark-time BrowseMode hint capture on the same budget as resolve-time
# hint capture so a busy browser renderer can't stall signature generation.
_IA2_ATTR_TIMEOUT_MS = 50


def _log_browse_capture(stage: str, **kwargs) -> None:
    extras = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
    log.debugWarning(f"REM BrowseCapture[{stage}]{extras and ': ' + extras}")


def _normalized_name(obj) -> str:
    try:
        return (getattr(obj, "name", "") or "").strip()
    except Exception:
        return ""


def _iter_children(parent):
    try:
        child = parent.firstChild
    except Exception:
        return
    while child:
        yield child
        try:
            child = child.next
        except Exception:
            break


def _normalize_hint_value(value) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _parse_attr_blob(raw) -> Dict[str, str]:
    if isinstance(raw, dict):
        return {
            str(k).strip(): _normalize_hint_value(v)
            for k, v in raw.items()
            if _normalize_hint_value(v)
        }
    text = _normalize_hint_value(raw)
    if not text:
        return {}
    result: Dict[str, str] = {}
    for part in text.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            result[key] = value
    return result


def _extract_dom_hints_from_attrs(attrs) -> Dict[str, str]:
    if not attrs:
        return {}
    hints: Dict[str, str] = {}
    attr_map: Dict[str, str] = {}
    try:
        if hasattr(attrs, "items"):
            attr_map = {
                str(k).strip(): _normalize_hint_value(v)
                for k, v in attrs.items()
                if _normalize_hint_value(v)
            }
        else:
            attr_map = _parse_attr_blob(attrs)
    except Exception:
        attr_map = {}
    for src_key, dst_key in (
        ("id", "id"),
        ("identifier", "id"),
        ("HTMLAttrib::id", "id"),
        ("class", "class"),
        ("className", "class"),
        ("HTMLAttrib::class", "class"),
        ("aria-label", "ariaLabel"),
        ("ariaLabel", "ariaLabel"),
        ("HTMLAttrib::aria-label", "ariaLabel"),
        ("display", "display"),
        ("tag", "tag"),
        ("tagName", "tag"),
    ):
        value = attr_map.get(src_key)
        if value:
            hints[dst_key] = value
    return hints


def _dom_hints_match(actual: Dict[str, str], expected: Dict[str, str]) -> bool:
    if not expected:
        return False
    for key, value in expected.items():
        if actual.get(key, "") != value:
            return False
    return True


def _text_info_length(info) -> int:
    try:
        return len(info.getText())
    except Exception:
        pass
    try:
        text = getattr(info, "text")
        if text is not None:
            return len(text)
    except Exception:
        pass
    try:
        text = info._getText()  # type: ignore[attr-defined]
        if text is not None:
            return len(text)
    except Exception:
        pass
    return -1


def _get_browse_dom_hints(
    obj,
    cache: Dict[int, Dict[str, str]] | None = None,
) -> Dict[str, str]:
    """
    Extract stable DOM-like hints for BrowseMode controls when the backend
    exposes them through IA2 / Gecko accessibility attributes.
    """
    nid = id(obj)
    if cache is not None:
        cached = cache.get(nid)
        if cached is not None:
            return cached

    hints: Dict[str, str] = {}
    t0 = time.perf_counter()
    try:
        ia_obj = getattr(obj, "IAccessibleObject", None)
        if ia_obj is not None:
            try:
                tag_name = _normalize_hint_value(ia_obj.accValue(0))
                if tag_name:
                    hints["tag"] = tag_name
            except Exception:
                pass
    except Exception:
        pass

    if (time.perf_counter() - t0) * 1000 > _IA2_ATTR_TIMEOUT_MS:
        log.debugWarning(
            "REM signature _get_browse_dom_hints: tag lookup exceeded budget, skipping attrs"
        )
        if cache is not None:
            cache[nid] = hints
        return hints

    raw_attrs = None
    for attr_name in ("IA2Attributes", "IA2Attribs", "attributes"):
        if (time.perf_counter() - t0) * 1000 > _IA2_ATTR_TIMEOUT_MS:
            log.debugWarning(
                f"REM signature _get_browse_dom_hints: attr loop timed out at {attr_name!r}"
            )
            break
        try:
            raw_attrs = getattr(obj, attr_name, None)
        except Exception:
            raw_attrs = None
        if raw_attrs:
            break
    if not raw_attrs:
        try:
            ia_obj = getattr(obj, "IAccessibleObject", None)
            raw_attrs = (
                getattr(ia_obj, "attributes", None) if ia_obj is not None else None
            )
        except Exception:
            raw_attrs = None

    attrs = _parse_attr_blob(raw_attrs)
    for src_key, dst_key in (
        ("id", "id"),
        ("class", "class"),
        ("className", "class"),
        ("aria-label", "ariaLabel"),
        ("ariaLabel", "ariaLabel"),
        ("display", "display"),
    ):
        value = attrs.get(src_key)
        if value:
            hints[dst_key] = value
    if cache is not None:
        cache[nid] = hints
    return hints


def _get_uia_fast_hints(obj) -> Dict[str, Any]:
    hints: Dict[str, Any] = {}
    try:
        if hasattr(obj, "UIAElement"):
            runtime_id = obj.UIAElement.getRuntimeId()
            if runtime_id:
                hints["runtimeId"] = runtime_id
    except Exception:
        pass
    for attr_name, key in (
        ("UIAAutomationId", "automationId"),
        ("UIAControlType", "controlType"),
        ("UIAClassName", "className"),
    ):
        try:
            value = getattr(obj, attr_name, "") or ""
        except Exception:
            value = ""
        if value:
            hints[key] = value
    return hints


def _get_stable_browse_document_id(ti) -> str:
    try:
        doc_id = getattr(ti, "documentConstantIdentifier", None)
    except Exception:
        doc_id = None
    if not is_stable_document_identifier(doc_id):
        return ""
    return str(doc_id).strip()


def _node_matches_dom_hints(
    node,
    dom_hints: Dict[str, str],
    cache: Dict[int, Dict[str, str]] | None = None,
) -> bool:
    if not dom_hints:
        return False
    node_hints = _get_browse_dom_hints(node, cache=cache)
    if not node_hints:
        return False
    return _dom_hints_match(node_hints, dom_hints)


def _compute_browse_fast_path(obj, ti) -> Dict[str, Any]:
    """
    Build a compact ancestry path from the browse root to obj.

    Each step records the child index under its parent plus role/name hints.
    This lets the resolver jump directly into the likely branch instead of
    blindly scanning the full tree.
    """
    try:
        root = getattr(ti, "rootNVDAObject", None) or root_obj_fallback(ti)
        if root is None:
            _log_browse_capture("fast_path_no_root", obj_type=type(obj).__name__)
            return {}
        if id(root) == id(obj):
            _log_browse_capture("fast_path_root_match", obj_type=type(obj).__name__)
            return {"browsePath": []}

        path_steps: List[Dict[str, Any]] = []
        seen = set()
        node = obj
        while node is not None:
            node_id = id(node)
            if node_id in seen:
                _log_browse_capture(
                    "fast_path_cycle",
                    obj_type=type(obj).__name__,
                    depth=len(path_steps),
                )
                return {}
            seen.add(node_id)

            if node_id == id(root):
                path_steps.reverse()
                return {"browsePath": path_steps}

            try:
                parent = node.parent
            except Exception:
                _log_browse_capture(
                    "fast_path_parent_error",
                    obj_type=type(obj).__name__,
                    depth=len(path_steps),
                )
                return {}
            if parent is None:
                _log_browse_capture(
                    "fast_path_parent_none",
                    obj_type=type(obj).__name__,
                    depth=len(path_steps),
                )
                return {}

            child_index = -1
            for index, child in enumerate(_iter_children(parent)):
                if id(child) == node_id:
                    child_index = index
                    break
            if child_index < 0:
                _log_browse_capture(
                    "fast_path_child_not_found",
                    obj_type=type(obj).__name__,
                    depth=len(path_steps),
                )
                return {}

            path_steps.append(
                {
                    "childIndex": child_index,
                    "role": getattr(node, "role", None),
                    "name": _normalized_name(node),
                }
            )
            node = parent
        _log_browse_capture(
            "fast_path_exhausted", obj_type=type(obj).__name__, depth=len(path_steps)
        )
    except Exception:
        _log_browse_capture("fast_path_exception", obj_type=type(obj).__name__)
    return {}


def _node_matches_browse_path(node, browse_path) -> bool:
    """
    Confirm whether node sits at the same ancestry path recorded at mark time.

    This is more reliable than screen coordinates for fixed-position or unlabeled
    controls where multiple nodes can report the same location.
    """
    if browse_path is None:
        return False
    if browse_path == []:
        return True
    try:
        current = node
        collected = []
        for _ in range(len(browse_path)):
            if current is None:
                return False
            try:
                parent = current.parent
            except Exception:
                return False
            if parent is None:
                return False

            current_id = id(current)
            child_index = -1
            for index, child in enumerate(_iter_children(parent)):
                if id(child) == current_id:
                    child_index = index
                    break
            if child_index < 0:
                return False

            collected.append(
                {
                    "childIndex": child_index,
                    "role": getattr(current, "role", None),
                    "name": _normalized_name(current),
                }
            )
            current = parent
        collected.reverse()
        return collected == browse_path
    except Exception:
        return False


def _compute_position_hints_from_caret(
    obj,
    ti,
    target_role: int,
    target_name: str,
    target_dom_hints: Dict[str, str] | None = None,
) -> Tuple[int, int]:
    """
    Use the virtual-buffer caret position to identify the control containing the
    caret, then derive role_index / role_ordinal from document-order fields.

    This avoids depending on NVDA object identity for BrowseMode elements whose
    live wrapper cannot be rediscovered in the walked tree.
    """
    try:
        import textInfos  # type: ignore

        caret_info = None
        caret_position = None
        for position in (textInfos.POSITION_CARET, textInfos.POSITION_SELECTION):
            try:
                caret_info = ti.makeTextInfo(position)
                if caret_info is not None:
                    caret_position = position
                    break
            except Exception:
                continue
        if caret_info is None:
            _log_browse_capture(
                "caret_no_textinfo",
                obj_type=type(obj).__name__,
                role=target_role,
                name=target_name,
            )
            return -1, -1

        start_info = ti.makeTextInfo(textInfos.POSITION_FIRST)
        range_info = start_info.copy()
        range_info.setEndPoint(caret_info, "endToStart")
        caret_offset = _text_info_length(range_info)
        if caret_offset < 0:
            _log_browse_capture(
                "caret_offset_unavailable",
                position=caret_position,
                obj_type=type(obj).__name__,
            )
            return -1, -1

        doc_info = ti.makeTextInfo(textInfos.POSITION_ALL)
        fields = doc_info.getTextWithFields({})

        text_offset = 0
        name_counter = 0
        role_counter = 0
        stack = []
        control_start_count = 0
        role_match_count = 0
        name_match_count = 0

        target_dom_hints = target_dom_hints or {}
        for field in fields:
            if isinstance(field, textInfos.FieldCommand):
                if field.command == "controlStart":
                    control_start_count += 1
                    attrs = field.field or {}
                    field_role = attrs.get("role")
                    field_name = (attrs.get("name", "") or "").strip()
                    field_dom_hints = _extract_dom_hints_from_attrs(attrs)
                    current_role_ordinal = -1
                    current_name_index = -1
                    if field_role == target_role:
                        role_match_count += 1
                        current_role_ordinal = role_counter
                        role_counter += 1
                        if field_name == target_name:
                            name_match_count += 1
                            current_name_index = name_counter
                            name_counter += 1
                    frame = {
                        "role": field_role,
                        "name": field_name,
                        "dom_hints": field_dom_hints,
                        "role_ordinal": current_role_ordinal,
                        "name_index": current_name_index,
                        "start_offset": text_offset,
                    }
                    stack.append(frame)
                    if (
                        field_role == target_role
                        and _dom_hints_match(field_dom_hints, target_dom_hints)
                        and current_role_ordinal >= 0
                    ):
                        _log_browse_capture(
                            "caret_match_dom_hints_start",
                            position=caret_position,
                            caret_offset=caret_offset,
                            control_starts=control_start_count,
                            role_matches=role_match_count,
                            name_matches=name_match_count,
                            role_index=current_name_index,
                            role_ordinal=current_role_ordinal,
                            field_dom_hints=field_dom_hints,
                        )
                        return current_name_index, current_role_ordinal
                    if (
                        field_role == target_role
                        and field_name == target_name
                        and text_offset >= caret_offset
                        and current_name_index >= 0
                    ):
                        _log_browse_capture(
                            "caret_match_at_start",
                            position=caret_position,
                            caret_offset=caret_offset,
                            control_starts=control_start_count,
                            role_matches=role_match_count,
                            name_matches=name_match_count,
                            role_index=current_name_index,
                            role_ordinal=current_role_ordinal,
                        )
                        return current_name_index, current_role_ordinal
                    continue
                if field.command == "controlEnd":
                    if stack:
                        frame = stack.pop()
                        if (
                            frame["role"] == target_role
                            and _dom_hints_match(
                                frame.get("dom_hints", {}), target_dom_hints
                            )
                            and frame["role_ordinal"] >= 0
                            and frame["start_offset"] <= caret_offset <= text_offset
                        ):
                            _log_browse_capture(
                                "caret_match_dom_hints_frame",
                                position=caret_position,
                                caret_offset=caret_offset,
                                control_starts=control_start_count,
                                role_matches=role_match_count,
                                name_matches=name_match_count,
                                role_index=frame["name_index"],
                                role_ordinal=frame["role_ordinal"],
                                field_dom_hints=frame.get("dom_hints", {}),
                                frame_start=frame["start_offset"],
                                frame_end=text_offset,
                            )
                            return frame["name_index"], frame["role_ordinal"]
                        if (
                            frame["role"] == target_role
                            and frame["name"] == target_name
                            and frame["name_index"] >= 0
                            and frame["start_offset"] <= caret_offset <= text_offset
                        ):
                            _log_browse_capture(
                                "caret_match_in_frame",
                                position=caret_position,
                                caret_offset=caret_offset,
                                control_starts=control_start_count,
                                role_matches=role_match_count,
                                name_matches=name_match_count,
                                role_index=frame["name_index"],
                                role_ordinal=frame["role_ordinal"],
                                frame_start=frame["start_offset"],
                                frame_end=text_offset,
                            )
                            return frame["name_index"], frame["role_ordinal"]
                    continue
            else:
                text_offset += len(str(field))
                if text_offset >= caret_offset:
                    for frame in reversed(stack):
                        if (
                            frame["role"] == target_role
                            and _dom_hints_match(
                                frame.get("dom_hints", {}), target_dom_hints
                            )
                            and frame["role_ordinal"] >= 0
                        ):
                            _log_browse_capture(
                                "caret_match_dom_hints_text",
                                position=caret_position,
                                caret_offset=caret_offset,
                                control_starts=control_start_count,
                                role_matches=role_match_count,
                                name_matches=name_match_count,
                                role_index=frame["name_index"],
                                role_ordinal=frame["role_ordinal"],
                                field_dom_hints=frame.get("dom_hints", {}),
                                text_offset=text_offset,
                            )
                            return frame["name_index"], frame["role_ordinal"]
                        if (
                            frame["role"] == target_role
                            and frame["name"] == target_name
                            and frame["name_index"] >= 0
                        ):
                            _log_browse_capture(
                                "caret_match_in_text",
                                position=caret_position,
                                caret_offset=caret_offset,
                                control_starts=control_start_count,
                                role_matches=role_match_count,
                                name_matches=name_match_count,
                                role_index=frame["name_index"],
                                role_ordinal=frame["role_ordinal"],
                                text_offset=text_offset,
                            )
                            return frame["name_index"], frame["role_ordinal"]
        for frame in reversed(stack):
            if (
                frame["role"] == target_role
                and _dom_hints_match(frame.get("dom_hints", {}), target_dom_hints)
                and frame["role_ordinal"] >= 0
                and frame["start_offset"] <= caret_offset
            ):
                _log_browse_capture(
                    "caret_match_dom_hints_after_scan",
                    position=caret_position,
                    caret_offset=caret_offset,
                    control_starts=control_start_count,
                    role_matches=role_match_count,
                    name_matches=name_match_count,
                    role_index=frame["name_index"],
                    role_ordinal=frame["role_ordinal"],
                    field_dom_hints=frame.get("dom_hints", {}),
                )
                return frame["name_index"], frame["role_ordinal"]
            if (
                frame["role"] == target_role
                and frame["name"] == target_name
                and frame["name_index"] >= 0
                and frame["start_offset"] <= caret_offset
            ):
                _log_browse_capture(
                    "caret_match_after_scan",
                    position=caret_position,
                    caret_offset=caret_offset,
                    control_starts=control_start_count,
                    role_matches=role_match_count,
                    name_matches=name_match_count,
                    role_index=frame["name_index"],
                    role_ordinal=frame["role_ordinal"],
                )
                return frame["name_index"], frame["role_ordinal"]
        _log_browse_capture(
            "caret_no_match",
            position=caret_position,
            caret_offset=caret_offset,
            fields=len(fields),
            control_starts=control_start_count,
            role_matches=role_match_count,
            name_matches=name_match_count,
            target_role=target_role,
            target_name=target_name,
        )
    except Exception as e:
        log.debugWarning(f"REM _compute_position_hints_from_caret exception: {e}")
    return -1, -1


def _compute_position_hints(obj, ti) -> Dict[str, Any]:
    """
    Compute role_index, role_ordinal, and surrounding text context for obj.

    Strategy (in order of preference):
      1. Screen-coordinate identity: walk the tree counting same-role+name
         elements; when a node's (x, y) matches obj.location, record the
         current name_counter as role_index and role_counter as role_ordinal.
      2. Object-identity fallback (_count_by_tree_order): if location is
         unavailable or non-matching (e.g. position:fixed elements whose
         viewport coordinates differ from document-flow coordinates), walk
         again matching by id(node) == id(obj).

    Both counters are incremented for EVERY qualifying node regardless of
    whether we can resolve its identity, so the indices stay aligned with
    what the resolver will count at resolve time.

    role_ordinal is intentionally counted across ALL same-role elements
    (regardless of name), making it useful as a tiebreaker for unlabeled
    elements (name == "") that share the same role_index == 0 — a situation
    that occurs frequently when hundreds of unlabeled buttons exist alongside
    a small number of named ones.
    """
    _empty = {
        "role_index": -1,
        "role_ordinal": -1,
        "context_before": "",
        "context_after": "",
    }
    try:
        if ti is None or not getattr(ti, "isReady", False):
            return _empty

        target_role = obj.role
        target_name = (getattr(obj, "name", "") or "").strip()
        target_fast_path = _compute_browse_fast_path(obj, ti).get("browsePath")
        hint_cache: Dict[int, Dict[str, str]] = {}
        target_dom_hints = _get_browse_dom_hints(obj, cache=hint_cache)
        _log_browse_capture(
            "position_hints_start",
            obj_type=type(obj).__name__,
            role=target_role,
            name=target_name,
            dom_hints=target_dom_hints,
            path_len=len(target_fast_path) if target_fast_path is not None else None,
            has_ti=ti is not None,
        )
        caret_index, caret_role_ordinal = _compute_position_hints_from_caret(
            obj,
            ti,
            target_role,
            target_name,
            target_dom_hints=target_dom_hints,
        )
        if caret_index >= 0:
            _log_browse_capture(
                "position_hints_caret_success",
                role_index=caret_index,
                role_ordinal=caret_role_ordinal,
            )
            return {
                "role_index": caret_index,
                "role_ordinal": caret_role_ordinal,
                "context_before": "",
                "context_after": "",
            }

        # Get the screen location of the target object — this is our identity anchor.
        target_location = None
        try:
            loc = obj.location
            if loc and len(loc) >= 2:
                target_location = (loc[0], loc[1])  # (x, y)
        except Exception:
            pass

        # Get document root for tree walking.
        root = getattr(ti, "rootNVDAObject", None) or root_obj_fallback(ti)
        if root is None:
            _log_browse_capture("position_hints_no_root")
            return _empty

        name_counter = (
            0  # counts elements with (role == target_role AND name == target_name)
        )
        role_ordinal = 0  # counts ALL elements with (role == target_role)
        found_index = -1
        found_role_ordinal = -1
        stack = [root]
        visited = set()
        timeout_s = 5.0
        start_time = time.monotonic()
        timed_out = False

        while stack:
            node = stack.pop()
            if node is None:
                continue
            nid = id(node)
            if nid in visited:
                continue
            visited.add(nid)

            if time.monotonic() - start_time > timeout_s:
                log.debugWarning(
                    "REM _compute_position_hints: timeout, returning fallback"
                )
                _log_browse_capture(
                    "position_hints_timeout",
                    visited=len(visited),
                    name_counter=name_counter,
                    role_counter=role_ordinal,
                )
                timed_out = True
                break

            if node.role == target_role:
                current_role_ordinal = role_ordinal
                role_ordinal += 1
                node_name = (getattr(node, "name", "") or "").strip()

                if node_name == target_name:
                    current_name_index = name_counter
                    # Always increment the name counter so subsequent elements
                    # get the correct index even if we can't match this one by location.
                    name_counter += 1

                    # Primary identity check: exact wrapper object.
                    if nid == id(obj):
                        _log_browse_capture(
                            "position_hints_match_object_id",
                            role_index=current_name_index,
                            role_ordinal=current_role_ordinal,
                        )
                        found_index = current_name_index
                        found_role_ordinal = current_role_ordinal
                        break

                    # Secondary identity check: stable DOM hints.
                    if _node_matches_dom_hints(
                        node, target_dom_hints, cache=hint_cache
                    ):
                        _log_browse_capture(
                            "position_hints_match_dom_hints",
                            role_index=current_name_index,
                            role_ordinal=current_role_ordinal,
                        )
                        found_index = current_name_index
                        found_role_ordinal = current_role_ordinal
                        break

                    # Tertiary identity check: structural ancestry path.
                    if _node_matches_browse_path(node, target_fast_path):
                        _log_browse_capture(
                            "position_hints_match_path",
                            role_index=current_name_index,
                            role_ordinal=current_role_ordinal,
                        )
                        found_index = current_name_index
                        found_role_ordinal = current_role_ordinal
                        break

                    # Last resort: screen coordinates.
                    if target_location is not None:
                        try:
                            nloc = node.location
                            if (
                                nloc
                                and len(nloc) >= 2
                                and (nloc[0], nloc[1]) == target_location
                            ):
                                _log_browse_capture(
                                    "position_hints_match_location",
                                    role_index=current_name_index,
                                    role_ordinal=current_role_ordinal,
                                    location=target_location,
                                )
                                found_index = current_name_index
                                found_role_ordinal = current_role_ordinal
                                break
                        except Exception:
                            pass

                # Role-only identity fallback for backends where the walked node's
                # accessible name differs from the original object name.
                if found_role_ordinal < 0 and (
                    nid == id(obj)
                    or _node_matches_dom_hints(node, target_dom_hints, cache=hint_cache)
                    or _node_matches_browse_path(node, target_fast_path)
                ):
                    found_index = -1
                    found_role_ordinal = current_role_ordinal
                    continue
                if found_role_ordinal < 0 and target_location is not None:
                    try:
                        nloc = node.location
                        if (
                            nloc
                            and len(nloc) >= 2
                            and (nloc[0], nloc[1]) == target_location
                        ):
                            found_index = -1
                            found_role_ordinal = current_role_ordinal
                            continue
                    except Exception:
                        pass

            children = []
            try:
                child = node.firstChild
                while child:
                    if time.monotonic() - start_time > timeout_s:
                        timed_out = True
                        break
                    children.append(child)
                    try:
                        child = child.next
                    except Exception:
                        break
            except Exception:
                pass
            for child in reversed(children):
                stack.append(child)

        # Location match succeeded — use the precise indices.
        if found_index >= 0:
            _log_browse_capture(
                "position_hints_tree_success",
                role_index=found_index,
                role_ordinal=found_role_ordinal,
            )
            return {
                "role_index": found_index,
                "role_ordinal": found_role_ordinal,
                "context_before": "",
                "context_after": "",
            }

        # Location unavailable or match failed — fall back to tree-order counting
        # by object identity. This handles position:fixed elements and any element
        # whose screen coordinates are inaccessible or non-unique.
        # Skip if we timed out; another full walk would also be slow.
        if not timed_out:
            found_index, found_role_ordinal = _count_by_tree_order(
                obj, ti, target_role, target_name
            )
            _log_browse_capture(
                "position_hints_tree_fallback_done",
                role_index=found_index,
                role_ordinal=found_role_ordinal,
                visited=len(visited),
                name_counter=name_counter,
                role_counter=role_ordinal,
            )

        return {
            "role_index": found_index,
            "role_ordinal": found_role_ordinal,
            "context_before": "",
            "context_after": "",
        }

    except Exception:
        return {
            "role_index": -1,
            "role_ordinal": -1,
            "context_before": "",
            "context_after": "",
        }


def _count_by_tree_order(
    obj, ti, target_role: int, target_name: str
) -> Tuple[int, int]:
    """
    Fallback: walk the full tree in document order and find the role_index and
    role_ordinal of *obj* (matched by object identity via id()).

    Returns (role_index, role_ordinal) — both -1 if obj is not found.

    IMPORTANT: We match by id(node) == id(obj) so we count exactly how many
    same-role+name elements precede *this specific object*, not just the first
    one with the same name.  For unlabeled elements (name == "") this is
    critical: there may be hundreds of them and we must find the right one.
    """
    try:
        root = getattr(ti, "rootNVDAObject", None)
        if root is None:
            _log_browse_capture("count_by_tree_no_root", obj_type=type(obj).__name__)
            return -1, -1

        target_id = id(obj)
        name_counter = 0  # counts (role+name) matches seen so far
        role_ordinal = 0  # counts (role) matches seen so far
        stack = [root]
        visited = set()
        timeout_s = 5.0
        start_time = time.monotonic()

        while stack:
            node = stack.pop()
            if node is None:
                continue
            nid = id(node)
            if nid in visited:
                continue
            visited.add(nid)

            if time.monotonic() - start_time > timeout_s:
                log.debugWarning("REM _count_by_tree_order: timeout, returning -1")
                _log_browse_capture(
                    "count_by_tree_timeout",
                    visited=len(visited),
                    name_counter=name_counter,
                    role_counter=role_ordinal,
                )
                break

            if node.role == target_role:
                current_role_ordinal = role_ordinal
                role_ordinal += 1
                node_name = (getattr(node, "name", "") or "").strip()
                current_name_index = -1

                if node_name == target_name:
                    current_name_index = name_counter
                    name_counter += 1

                    # Identity match — this is our target.
                    if nid == target_id:
                        _log_browse_capture(
                            "count_by_tree_match",
                            role_index=current_name_index,
                            role_ordinal=current_role_ordinal,
                            visited=len(visited),
                        )
                        return current_name_index, current_role_ordinal

                if nid == target_id:
                    _log_browse_capture(
                        "count_by_tree_match",
                        role_index=current_name_index,
                        role_ordinal=current_role_ordinal,
                        visited=len(visited),
                    )
                    return current_name_index, current_role_ordinal

            children = []
            try:
                child = node.firstChild
                while child:
                    if time.monotonic() - start_time > timeout_s:
                        log.debugWarning("REM _count_by_tree_order: inner loop timeout")
                        break
                    children.append(child)
                    try:
                        child = child.next
                    except Exception:
                        break
            except Exception:
                pass
            for child in reversed(children):
                stack.append(child)

    except Exception:
        _log_browse_capture("count_by_tree_exception", obj_type=type(obj).__name__)
    _log_browse_capture(
        "count_by_tree_no_match",
        visited=len(visited) if "visited" in locals() else None,
        name_counter=name_counter if "name_counter" in locals() else None,
        role_counter=role_ordinal if "role_ordinal" in locals() else None,
    )
    return -1, -1


def root_obj_fallback(ti):
    """Get document root from treeInterceptor."""
    try:
        return getattr(ti, "rootNVDAObject", None)
    except Exception:
        return None


def _build_signature_result(
    backend: str,
    primary: Dict[str, Any],
    fast_path: Dict[str, Any],
    fuzzy: Dict[str, Any],
) -> Dict[str, Any]:
    hash_str = json.dumps(primary, sort_keys=True)
    signature_hash = hashlib.md5(hash_str.encode("utf-8")).hexdigest()
    return {
        "backend": backend,
        "hash": signature_hash,
        "primarySignature": primary,
        "fastPathHints": fast_path,
        "fuzzyHints": fuzzy,
    }


def _log_signature_timing(start_time: float, backend: str, **kwargs) -> None:
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    extras = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    log.debugWarning(
        f"REM Timing: signature_capture backend={backend} took {elapsed_ms:.2f}ms"
        f"{extras and ', ' + extras}"
    )


def generate_signature_async(obj, on_done: Callable[[Dict[str, Any]], None]) -> None:
    """
    Asynchronous variant for mark-time capture. BrowseMode is chunked so wx timers
    can continue running; non-BrowseMode falls back to the synchronous path.
    """
    import wx  # type: ignore

    start_time = time.perf_counter()
    ti = getattr(obj, "treeInterceptor", None)
    in_browse_mode = ti is not None and getattr(ti, "isReady", False)
    if not in_browse_mode:

        def _done_sync():
            signature = generate_signature(obj)
            _log_signature_timing(start_time, signature.get("backend", "Unknown"))
            on_done(signature)

        wx.CallAfter(_done_sync)
        return

    try:
        url = _get_stable_browse_document_id(ti)
        fuzzy: Dict[str, Any] = {
            "name": getattr(obj, "name", "") or "",
            "accDescription": getattr(obj, "description", "") or "",
            "url_if_web": url,
        }
        uia_fast_hints = _get_uia_fast_hints(obj)
        hint_cache: Dict[int, Dict[str, str]] = {}
        target_dom_hints = _get_browse_dom_hints(obj, cache=hint_cache)
        try:
            if hasattr(obj, "IAccessibleObject"):
                fuzzy["tagName"] = obj.IAccessibleObject.accValue(0) or ""
        except Exception:
            fuzzy["tagName"] = ""

        root = getattr(ti, "rootNVDAObject", None) or root_obj_fallback(ti)
        if root is None:
            signature = generate_signature(obj)
            _log_signature_timing(
                start_time, signature.get("backend", "Unknown"), fallback=True
            )
            on_done(signature)
            return

        caret_index, caret_role_ordinal = _compute_position_hints_from_caret(
            obj,
            ti,
            obj.role,
            (getattr(obj, "name", "") or "").strip(),
            target_dom_hints=target_dom_hints,
        )
        if caret_index >= 0:
            _log_browse_capture(
                "async_caret_fast_success",
                role_index=caret_index,
                role_ordinal=caret_role_ordinal,
            )
            state = {
                "obj": obj,
                "target_role": obj.role,
                "url": url,
                "fuzzy": fuzzy,
                "found_index": caret_index,
                "found_role_ordinal": caret_role_ordinal,
                "fast_path": _compute_browse_fast_path(obj, ti),
                "target_dom_hints": target_dom_hints,
                "uia_fast_hints": uia_fast_hints,
                "start_time": start_time,
            }
            _finalise_browse_signature(state, on_done)
            return
        _log_browse_capture(
            "async_browse_start",
            obj_type=type(obj).__name__,
            role=obj.role,
            name=(getattr(obj, "name", "") or "").strip(),
            dom_hints=target_dom_hints,
            uia_hints=uia_fast_hints,
            path_len=len(_compute_browse_fast_path(obj, ti).get("browsePath", [])),
        )

        target_location = None
        try:
            loc = obj.location
            if loc and len(loc) >= 2:
                target_location = (loc[0], loc[1])
        except Exception:
            pass

        state = {
            "obj": obj,
            "obj_id": id(obj),
            "ti": ti,
            "root": root,
            "url": url,
            "fuzzy": fuzzy,
            "stack": [root],
            "visited": set(),
            "target_role": obj.role,
            "target_name": (getattr(obj, "name", "") or "").strip(),
            "target_location": target_location,
            "target_browse_path": _compute_browse_fast_path(obj, ti).get("browsePath"),
            "target_dom_hints": target_dom_hints,
            "hint_cache": hint_cache,
            "uia_fast_hints": uia_fast_hints,
            # name_counter: counts every (role+name) element seen, regardless of
            # whether it is obj. Incremented for EVERY matching name so the stored
            # index aligns with what the resolver will count at resolve time.
            "name_counter": 0,
            # role_counter: counts every same-role element seen.
            "role_counter": 0,
            # found_index / found_role_ordinal: set when we positively identify obj
            # via location or object-identity match.
            "found_index": -1,
            "found_role_ordinal": -1,
            "fast_path": _compute_browse_fast_path(obj, ti),
            "start_time": start_time,
        }
        wx.CallAfter(_drive_generate_signature_browse, state, on_done)
    except Exception:

        def _done_fallback():
            signature = generate_signature(obj)
            _log_signature_timing(
                start_time, signature.get("backend", "Unknown"), fallback=True
            )
            on_done(signature)

        wx.CallAfter(_done_fallback)


def _drive_generate_signature_browse(
    state: Dict[str, Any], on_done: Callable[[Dict[str, Any]], None]
) -> None:
    import wx  # type: ignore

    try:
        stack = state["stack"]
        visited = state["visited"]
        target_role = state["target_role"]
        target_name = state["target_name"]
        target_location = state["target_location"]
        target_obj_id = state["obj_id"]
        target_browse_path = state["target_browse_path"]
        target_dom_hints = state["target_dom_hints"]
        hint_cache = state.get("hint_cache")

        for _ in range(_CHUNK_SIZE):
            # Stack exhausted — location match either succeeded or we must fall back.
            if not stack:
                if state["found_role_ordinal"] >= 0:
                    # Location (or id) match confirmed — use it directly.
                    _finalise_browse_signature(state, on_done)
                else:
                    # Location match failed for every candidate (e.g. position:fixed
                    # elements outside normal document flow). Fall back to a second
                    # synchronous tree walk that matches by object identity (id()).
                    # This is the same strategy _compute_position_hints uses.
                    log.debugWarning(
                        "REM async sig: location match failed; falling back to "
                        "identity-based _count_by_tree_order"
                    )
                    _log_browse_capture(
                        "async_location_failed",
                        role=target_role,
                        name=target_name,
                        role_counter=state["role_counter"],
                        name_counter=state["name_counter"],
                        visited=len(state["visited"]),
                        dom_hints=state["target_dom_hints"],
                        path_len=len(state["target_browse_path"])
                        if state["target_browse_path"] is not None
                        else None,
                    )
                    found_index, found_role_ordinal = _count_by_tree_order(
                        state["obj"], state["ti"], target_role, target_name
                    )
                    state["found_index"] = found_index
                    state["found_role_ordinal"] = found_role_ordinal
                    _finalise_browse_signature(state, on_done)
                return

            # Confirmed match from a previous chunk — finalise immediately.
            if state["found_role_ordinal"] >= 0:
                _finalise_browse_signature(state, on_done)
                return

            node = stack.pop()
            if node is None:
                continue
            nid = id(node)
            if nid in visited:
                continue
            visited.add(nid)

            if node.role == target_role:
                current_role_ordinal = state["role_counter"]
                state["role_counter"] += 1
                node_name = (getattr(node, "name", "") or "").strip()

                if node_name == target_name:
                    current_name_index = state["name_counter"]
                    # Always increment so subsequent same-name elements get correct indices.
                    state["name_counter"] += 1

                    # Check if this is our target node.
                    is_target = False

                    # Primary identity check: screen location.
                    if nid == target_obj_id:
                        is_target = True

                    # Secondary identity check: stable DOM hints.
                    if not is_target and _node_matches_dom_hints(
                        node, target_dom_hints, cache=hint_cache
                    ):
                        is_target = True

                    # Tertiary identity check: structural ancestry path.
                    if not is_target and _node_matches_browse_path(
                        node, target_browse_path
                    ):
                        is_target = True

                    # Last resort: screen location.
                    if not is_target and target_location is not None:
                        try:
                            nloc = node.location
                            if (
                                nloc
                                and len(nloc) >= 2
                                and (nloc[0], nloc[1]) == target_location
                            ):
                                is_target = True
                        except Exception:
                            pass

                    if is_target:
                        state["found_index"] = current_name_index
                        state["found_role_ordinal"] = current_role_ordinal
                        # Don't return yet — let the outer loop hit the
                        # "found_index >= 0" guard at the top of the next iteration
                        # so we always go through _finalise_browse_signature.
                        continue

            children = []
            try:
                child = node.firstChild
                while child:
                    children.append(child)
                    try:
                        child = child.next
                    except Exception:
                        break
            except Exception:
                pass
            for child in reversed(children):
                stack.append(child)

        wx.CallLater(0, _drive_generate_signature_browse, state, on_done)
    except Exception:
        signature = generate_signature(state["obj"])
        _log_signature_timing(
            state["start_time"], signature.get("backend", "Unknown"), fallback=True
        )
        on_done(signature)


def _finalise_browse_signature(
    state: Dict[str, Any], on_done: Callable[[Dict[str, Any]], None]
) -> None:
    """Build and deliver the BrowseMode signature from the completed walk state."""
    target_role = state["target_role"]
    primary = {
        "role": target_role,
        "name": getattr(state["obj"], "name", "") or "",
        "url_if_web": state["url"],
        "role_index": state["found_index"],
        "role_ordinal": state["found_role_ordinal"],
        "context_before": "",
        "context_after": "",
    }
    signature = _build_signature_result("BrowseMode", primary, {}, state["fuzzy"])
    signature["fastPathHints"].update(state.get("fast_path", {}))
    signature["fastPathHints"]["domHints"] = state.get("target_dom_hints", {})
    signature["fastPathHints"].update(state.get("uia_fast_hints", {}))
    _log_signature_timing(
        state["start_time"],
        "BrowseMode",
        role_index=state["found_index"],
        role_ordinal=state["found_role_ordinal"],
    )
    on_done(signature)


def generate_signature_for_lookup(obj) -> Dict[str, Any]:
    """
    Lightweight variant used during navigation event handling (announce path).
    No getTextWithFields or tree walk — just role+name+url for a cheap hash.
    Always misses for BrowseMode; caller uses fuzzy fallback with stored hints.
    """
    backend = "Unknown"
    primary: Dict[str, Any] = {}
    fast_path: Dict[str, Any] = {}

    ti = getattr(obj, "treeInterceptor", None)
    in_browse_mode = ti is not None and getattr(ti, "isReady", False)

    if in_browse_mode:
        backend = "BrowseMode"
        url = _get_stable_browse_document_id(ti)
        primary = {
            "role": obj.role,
            "name": getattr(obj, "name", "") or "",
            "url_if_web": url,
        }

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

    elif hasattr(obj, "IAccessibleObject"):
        backend = "IAccessible"
        primary = {
            "accRole": obj.role,
            "windowClassName": getattr(obj, "windowClassName", "") or "",
        }
        if hasattr(obj, "IAccessibleChildID"):
            fast_path["childId"] = obj.IAccessibleChildID

    return _build_signature_result(backend, primary, fast_path, {})


def generate_signature(obj) -> Dict[str, Any]:
    """
    Full signature including position hints. Called once at mark time.

    Backend detection order:
      1. BrowseMode — checked first (browse element also has IAccessibleObject)
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

    ti = getattr(obj, "treeInterceptor", None)
    in_browse_mode = ti is not None and getattr(ti, "isReady", False)

    if in_browse_mode:
        backend = "BrowseMode"
        url = _get_stable_browse_document_id(ti)
        fuzzy["url_if_web"] = url
        try:
            if hasattr(obj, "IAccessibleObject"):
                fuzzy["tagName"] = obj.IAccessibleObject.accValue(0) or ""
        except Exception:
            fuzzy["tagName"] = ""

        pos = _compute_position_hints(obj, ti)
        fast_path.update(_compute_browse_fast_path(obj, ti))
        fast_path["domHints"] = _get_browse_dom_hints(obj)
        fast_path.update(_get_uia_fast_hints(obj))

        primary = {
            "role": obj.role,
            "name": getattr(obj, "name", "") or "",
            "url_if_web": url,
            "role_index": pos["role_index"],
            "role_ordinal": pos["role_ordinal"],
            "context_before": pos["context_before"],
            "context_after": pos["context_after"],
        }

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

    elif hasattr(obj, "IAccessibleObject"):
        backend = "IAccessible"
        primary = {
            "accRole": obj.role,
            "windowClassName": getattr(obj, "windowClassName", "") or "",
        }
        if hasattr(obj, "IAccessibleChildID"):
            fast_path["childId"] = obj.IAccessibleChildID

    return _build_signature_result(backend, primary, fast_path, fuzzy)

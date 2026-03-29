import time
from typing import Any, Dict, Optional, Callable

from logHandler import log  # type: ignore
from .storage import is_stable_document_identifier

_TIMING_ENABLED = True

_CHUNK_BUDGET_S = 0.008  # 8 ms per chunk — leaves ~8 ms headroom in a 16 ms frame
_CHUNK_MAX = 200

# Maximum wall-clock milliseconds to spend fetching IA2 attributes for one node
# before giving up. COMError -2147418110 (RPC_E_CALL_CANCELED / message filter)
# means the browser is busy and each blocked call wastes 200-500 ms. We cut out
# at 50 ms — fast enough for a healthy COM call (<1 ms) but tight enough to
# escape immediately when the message filter is active.
_IA2_ATTR_TIMEOUT_MS = 50

# Sentinel stored in the per-resolve DOM hint cache when a node's attributes
# timed out. Subsequent phases see this and skip the COM call entirely.
_DOM_HINT_MISS: Dict[str, str] = {}


class _OperationCancelled(Exception):
    pass


def _log_timing(method: str, elapsed_ms: float, **kwargs) -> None:
    if not _TIMING_ENABLED:
        return
    extras = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    log.debugWarning(
        f"REM Timing: {method} took {elapsed_ms:.2f}ms{extras and ', ' + extras}"
    )


def _checkpoint(
    progress_controller, progress_prompt: Optional[Callable[[], bool]] = None
) -> None:
    if progress_controller is None:
        return
    if progress_controller.consume_timeout_request():
        if progress_prompt is None or not progress_prompt():
            progress_controller.cancel()
    if not progress_controller.checkpoint():
        raise _OperationCancelled()


def _normalized_name(obj) -> str:
    try:
        return (getattr(obj, "name", "") or "").strip()
    except Exception:
        return ""


def _browse_doc_matches_target(ti, target_url: str) -> bool:
    target_url = str(target_url or "").strip()
    if not target_url or not is_stable_document_identifier(target_url):
        return True
    doc_id = str(getattr(ti, "documentConstantIdentifier", "") or "") if ti else ""
    if not doc_id or not is_stable_document_identifier(doc_id):
        return True
    return doc_id == target_url


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


def _get_browse_dom_hints(
    obj, cache: Optional[Dict[int, Dict[str, str]]] = None
) -> Dict[str, str]:
    """
    Fetch IA2/DOM attribute hints for obj, with optional per-resolve caching.

    cache: dict keyed by id(node) that lives for one resolve call. Pass the
           same dict to every node so each node's COM attributes are fetched
           at most once across all phases. None = compute fresh (used at mark
           time by the signature module).

    Returns an empty dict when attributes are unavailable or timed out.
    Callers must treat an empty result as "no hints available for this node"
    — i.e. skip the DOM-hint match, not reject the node.
    """
    nid = id(obj)
    if cache is not None:
        cached = cache.get(nid)
        if cached is not None:
            # _DOM_HINT_MISS means we tried and the COM call timed out
            return cached if cached is not _DOM_HINT_MISS else {}

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

    # If the tag lookup already burned the COM budget, record miss and return.
    if (time.perf_counter() - t0) * 1000 > _IA2_ATTR_TIMEOUT_MS:
        log.debugWarning(
            "REM _get_browse_dom_hints: tag lookup exceeded budget, skipping attrs"
        )
        if cache is not None:
            cache[nid] = _DOM_HINT_MISS
        return hints

    raw_attrs = None
    for attr_name in ("IA2Attributes", "IA2Attribs", "attributes"):
        if (time.perf_counter() - t0) * 1000 > _IA2_ATTR_TIMEOUT_MS:
            log.debugWarning(
                f"REM _get_browse_dom_hints: attr loop timed out at {attr_name!r}"
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
        cache[nid] = hints if hints else _DOM_HINT_MISS
    return hints


def _matches_dom_hints(
    obj,
    dom_hints: Dict[str, str],
    cache: Optional[Dict[int, Dict[str, str]]] = None,
) -> bool:
    if not dom_hints:
        return False
    obj_hints = _get_browse_dom_hints(obj, cache=cache)
    if not obj_hints:
        return False
    for key, value in dom_hints.items():
        if obj_hints.get(key, "") != value:
            return False
    return True


def _get_browse_root(root_obj):
    ti = getattr(root_obj, "treeInterceptor", None) or (
        root_obj if hasattr(root_obj, "rootNVDAObject") else None
    )
    root = getattr(ti, "rootNVDAObject", None) if ti else None
    if root is None:
        root = root_obj
    return ti, root


def _path_step_matches(node, step: Dict[str, Any]) -> bool:
    if getattr(node, "role", None) != step.get("role"):
        return False
    return _normalized_name(node) == (step.get("name", "") or "").strip()


def _rank_path_children(children, step: Dict[str, Any]):
    expected_index = step.get("childIndex", -1)
    exact_matches = []
    role_only_matches = []
    for index, child in enumerate(children):
        if _path_step_matches(child, step):
            exact_matches.append(
                (
                    abs(index - expected_index) if expected_index >= 0 else index,
                    index,
                    child,
                )
            )
            continue
        if getattr(child, "role", None) == step.get("role"):
            role_only_matches.append(
                (
                    abs(index - expected_index) if expected_index >= 0 else index,
                    index,
                    child,
                )
            )
    exact_matches.sort(key=lambda item: (item[0], item[1]))
    role_only_matches.sort(key=lambda item: (item[0], item[1]))
    if exact_matches:
        return [child for _, _, child in exact_matches]
    return [child for _, _, child in role_only_matches]


def _browse_candidate_matches_primary(obj, primary: Dict[str, Any]) -> bool:
    if obj is None:
        return False
    if getattr(obj, "role", None) != primary.get("role"):
        return False
    return _normalized_name(obj) == (primary.get("name", "") or "").strip()


def _follow_browse_path(node, path, path_index: int, primary: Dict[str, Any]):
    if path_index >= len(path):
        return node if _browse_candidate_matches_primary(node, primary) else None
    children = list(_iter_children(node))
    if not children:
        return None
    for child in _rank_path_children(children, path[path_index]):
        result = _follow_browse_path(child, path, path_index + 1, primary)
        if result is not None:
            return result
    return None


def _schedule_main_thread(func, *args) -> None:
    import wx  # type: ignore

    wx.CallLater(0, func, *args)


def _browsemode_path_resolve_sync(
    primary: Dict[str, Any],
    fast_path: Dict[str, Any],
    root_obj,
    progress_controller=None,
    progress_prompt: Optional[Callable[[], bool]] = None,
    hint_cache: Optional[Dict[int, Dict[str, str]]] = None,
) -> Optional[Any]:
    path = fast_path.get("browsePath")
    if not path and path != []:
        return None
    try:
        ti, root = _get_browse_root(root_obj)
        target_url = (primary.get("url_if_web", "") or "").strip()
        if not _browse_doc_matches_target(ti, target_url):
            log.debugWarning("REM browse path fast-path: URL mismatch.")
            return None
        stack = [(root, 0)]
        while stack:
            _checkpoint(progress_controller, progress_prompt)
            node, path_index = stack.pop()
            if node is None:
                continue
            if path_index >= len(path):
                if _browse_candidate_matches_primary(node, primary):
                    dom_hints = fast_path.get("domHints", {})
                    if dom_hints and not _matches_dom_hints(
                        node, dom_hints, cache=hint_cache
                    ):
                        continue
                    log.debugWarning("REM BrowseMode path fast-path succeeded.")
                    return node
                continue
            children = list(_iter_children(node))
            for child in reversed(_rank_path_children(children, path[path_index])):
                stack.append((child, path_index + 1))
        return None
    except _OperationCancelled:
        return None
    except Exception as e:
        log.debugWarning(f"REM browse path fast-path exception: {e}")
        return None


def _browsemode_dom_resolve_sync(
    primary: Dict[str, Any],
    fast_path: Dict[str, Any],
    root_obj,
    progress_controller=None,
    progress_prompt: Optional[Callable[[], bool]] = None,
    hint_cache: Optional[Dict[int, Dict[str, str]]] = None,
) -> Optional[Any]:
    dom_hints = fast_path.get("domHints", {})
    if not dom_hints:
        return None
    try:
        ti, root = _get_browse_root(root_obj)
        target_url = (primary.get("url_if_web", "") or "").strip()
        if not _browse_doc_matches_target(ti, target_url):
            return None
        target_role = primary.get("role")
        target_name = (primary.get("name", "") or "").strip()
        stored_index = primary.get("role_index", -1)
        stored_role_ordinal = primary.get("role_ordinal", -1)
        stack = [root]
        visited = set()
        name_counter = 0
        role_counter = 0
        candidates = []
        while stack:
            _checkpoint(progress_controller, progress_prompt)
            node = stack.pop()
            if node is None:
                continue
            nid = id(node)
            if nid in visited:
                continue
            visited.add(nid)
            if getattr(node, "role", None) == target_role:
                current_role_ordinal = role_counter
                role_counter += 1
                node_name = _normalized_name(node)
                current_name_index = -1
                if node_name == target_name:
                    current_name_index = name_counter
                    name_counter += 1
                if _matches_dom_hints(node, dom_hints, cache=hint_cache):
                    candidates.append((current_name_index, current_role_ordinal, node))
                    if stored_index >= 0 and current_name_index == stored_index:
                        return node
                    if (
                        stored_index < 0
                        and stored_role_ordinal >= 0
                        and current_role_ordinal == stored_role_ordinal
                    ):
                        return node
            children = list(_iter_children(node))
            for child in reversed(children):
                stack.append(child)
        if len(candidates) == 1:
            return candidates[0][2]
        if stored_index >= 0:
            for name_idx, _, node in candidates:
                if name_idx == stored_index:
                    return node
        if stored_index < 0 and stored_role_ordinal >= 0:
            for _, role_ordinal, node in candidates:
                if role_ordinal == stored_role_ordinal:
                    return node
        return None
    except _OperationCancelled:
        return None
    except Exception as e:
        log.debugWarning(f"REM browse DOM fast-path exception: {e}")
        return None


def _browsemode_vbuf_resolve_sync(
    primary: Dict[str, Any],
    root_obj,
    progress_controller=None,
    progress_prompt: Optional[Callable[[], bool]] = None,
) -> Optional[Any]:
    try:
        import textInfos  # type: ignore

        ti = getattr(root_obj, "treeInterceptor", None) or (
            root_obj if hasattr(root_obj, "rootNVDAObject") else None
        )
        if ti is None or not getattr(ti, "isReady", False):
            return None
        target_url = (primary.get("url_if_web", "") or "").strip()
        if not _browse_doc_matches_target(ti, target_url):
            log.debugWarning("REM vbuf fast-path: URL mismatch.")
            return None
        target_role = primary.get("role")
        target_name = (primary.get("name", "") or "").strip()
        stored_index = primary.get("role_index", -1)
        stored_role_ordinal = primary.get("role_ordinal", -1)
        doc_info = ti.makeTextInfo(textInfos.POSITION_ALL)
        fields = doc_info.getTextWithFields({})
        name_counter = 0
        role_counter = 0
        candidates = []
        role_candidates = []
        for field in fields:
            _checkpoint(progress_controller, progress_prompt)
            if not isinstance(field, textInfos.FieldCommand):
                continue
            if field.command != "controlStart":
                continue
            attrs = field.field
            if attrs is None:
                continue
            field_role = attrs.get("role")
            if field_role != target_role:
                continue
            current_role_ordinal = role_counter
            role_counter += 1
            field_name = (attrs.get("name", "") or "").strip()
            current_index = -1
            if field_name == target_name:
                current_index = name_counter
                name_counter += 1
            obj = attrs.get("obj")
            if obj is None:
                obj = attrs.get("_startOfNode") or attrs.get(
                    "focusableNVDAObjectAtStart"
                )
            if not hasattr(obj, "role"):
                continue
            role_candidates.append((current_role_ordinal, obj))
            if current_index >= 0:
                candidates.append((current_index, current_role_ordinal, obj))
            if stored_index >= 0 and current_index == stored_index:
                log.debugWarning(
                    f"REM vbuf fast-path: early exit at name_index={current_index}"
                )
                return obj
            if (
                stored_index < 0
                and stored_role_ordinal >= 0
                and current_role_ordinal == stored_role_ordinal
            ):
                log.debugWarning(
                    f"REM vbuf fast-path: early exit at role_ordinal={current_role_ordinal} (no role_index)"
                )
                return obj
        log.debugWarning(
            f"REM vbuf fast-path: {len(candidates)} name candidates, "
            f"{len(role_candidates)} role candidates, stored_index={stored_index}, "
            f"stored_role_ordinal={stored_role_ordinal}"
        )
        if stored_index >= 0:
            for idx, role_ordinal, obj in candidates:
                if idx == stored_index:
                    return obj
        if stored_index < 0 and stored_role_ordinal >= 0:
            for role_ordinal, obj in role_candidates:
                if role_ordinal == stored_role_ordinal:
                    return obj
        if stored_index < 0 and stored_role_ordinal < 0:
            if len(candidates) == 1:
                log.debugWarning("REM vbuf: unique name candidate, no stored index.")
                return candidates[0][2]
            if len(role_candidates) == 1:
                log.debugWarning("REM vbuf: unique role candidate, no stored index.")
                return role_candidates[0][1]
        return None
    except _OperationCancelled:
        return None
    except Exception as e:
        log.debugWarning(f"REM vbuf fast-path exception: {e}")
        return None


def _browsemode_walk_resolve_sync(
    primary: Dict[str, Any],
    root_obj,
    progress_controller=None,
    progress_prompt: Optional[Callable[[], bool]] = None,
) -> Optional[Any]:
    state = _create_browsemode_state(primary, root_obj)
    if state is None:
        return None
    try:
        stack = state["stack"]
        visited = state["visited"]
        target_role = primary.get("role")
        target_name = (primary.get("name", "") or "").strip()
        stored_index = primary.get("role_index", -1)
        stored_role_ordinal = primary.get("role_ordinal", -1)
        while stack:
            _checkpoint(progress_controller, progress_prompt)
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
                state["role_candidates"].append((current_role_ordinal, node))
                if node_name == target_name:
                    idx = state["name_counter"]
                    state["name_counter"] += 1
                    state["candidates"].append((idx, current_role_ordinal, node))
                    if stored_index >= 0 and idx == stored_index:
                        return node
                if (
                    stored_index < 0
                    and stored_role_ordinal >= 0
                    and current_role_ordinal == stored_role_ordinal
                ):
                    return node
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
        return _finish_browsemode_resolve(state)
    except _OperationCancelled:
        return None


def _tree_walk_sync(
    backend: str,
    primary: Dict[str, Any],
    root_obj,
    progress_controller=None,
    progress_prompt: Optional[Callable[[], bool]] = None,
) -> Optional[Any]:
    stack = [root_obj]
    while stack:
        _checkpoint(progress_controller, progress_prompt)
        obj = stack.pop()
        if obj is None:
            continue
        if _matches(backend, primary, obj):
            return obj
        children = []
        try:
            child = obj.firstChild
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
    return None


def resolve_element(
    marker_data: Dict[str, Any],
    root_obj,
    on_done: Callable,
    progress_controller=None,
    progress_prompt: Optional[Callable[[], bool]] = None,
) -> None:
    """
    Search for the element using its saved primary signature.
    Must be called from NVDA's main thread.

    A hint_cache dict is created here and shared across path and DOM phases so
    each node's IA2/DOM attributes are fetched via COM at most once per call,
    even if both phases visit the same node.
    """
    backend = marker_data.get("backend")
    primary = marker_data.get("primarySignature", {})
    fast_path = marker_data.get("fastPathHints", {})

    log.debugWarning(
        f"REM resolve_element: backend={backend}, primary={primary}, "
        f"root_type={type(root_obj).__name__!r}, "
        f"root_name={getattr(root_obj, 'name', None)!r}"
    )

    # Shared per-resolve DOM hint cache — avoids redundant COM calls on the
    # same node when path and DOM phases both visit it.
    hint_cache: Dict[int, Dict[str, str]] = {}

    if backend == "BrowseMode":
        try:
            _checkpoint(progress_controller, progress_prompt)
        except _OperationCancelled:
            on_done(None)
            return

        if fast_path.get("runtimeId"):
            t0 = time.perf_counter()
            result = _uia_fast_path(fast_path["runtimeId"])
            elapsed = (time.perf_counter() - t0) * 1000
            _log_timing(f"{backend}_UIA_fast_path", elapsed, result=result is not None)
            if result:
                log.debugWarning("REM runtimeId fast-path succeeded.")
                on_done(result)
                return

        t0 = time.perf_counter()
        result = _browsemode_path_resolve_sync(
            primary,
            fast_path,
            root_obj,
            progress_controller,
            progress_prompt,
            hint_cache,
        )
        _log_timing(
            "BrowseMode_path",
            (time.perf_counter() - t0) * 1000,
            result=result is not None,
        )
        if result is not None:
            on_done(result)
            return
        if progress_controller is not None and progress_controller.is_cancelled():
            on_done(None)
            return

        t0 = time.perf_counter()
        result = _browsemode_dom_resolve_sync(
            primary,
            fast_path,
            root_obj,
            progress_controller,
            progress_prompt,
            hint_cache,
        )
        _log_timing(
            "BrowseMode_dom",
            (time.perf_counter() - t0) * 1000,
            result=result is not None,
        )
        if result is not None:
            on_done(result)
            return
        if progress_controller is not None and progress_controller.is_cancelled():
            on_done(None)
            return

        t0 = time.perf_counter()
        result = _browsemode_vbuf_resolve_sync(
            primary, root_obj, progress_controller, progress_prompt
        )
        _log_timing(
            "BrowseMode_vbuf",
            (time.perf_counter() - t0) * 1000,
            result=result is not None,
        )
        if result is not None:
            on_done(result)
            return
        if progress_controller is not None and progress_controller.is_cancelled():
            on_done(None)
            return

        result = _browsemode_walk_resolve_sync(
            primary, root_obj, progress_controller, progress_prompt
        )
        if result is None and not (
            progress_controller is not None and progress_controller.is_cancelled()
        ):
            log.warning(
                "REM BrowseMode walk found no match; falling back to simple tree walk."
            )
            result = _tree_walk_sync(
                "BrowseMode", primary, root_obj, progress_controller, progress_prompt
            )
        on_done(result)
        return

    try:
        _checkpoint(progress_controller, progress_prompt)
    except _OperationCancelled:
        on_done(None)
        return

    if fast_path.get("runtimeId"):
        t0 = time.perf_counter()
        result = _uia_fast_path(fast_path["runtimeId"])
        elapsed = (time.perf_counter() - t0) * 1000
        _log_timing(
            f"{backend or 'Unknown'}_UIA_fast_path", elapsed, result=result is not None
        )
        if result:
            log.debugWarning("REM runtimeId fast-path succeeded.")
            on_done(result)
            return

    on_done(
        _tree_walk_sync(
            backend, primary, root_obj, progress_controller, progress_prompt
        )
    )


def _create_browsemode_state(
    primary: Dict[str, Any], root_obj
) -> Optional[Dict[str, Any]]:
    try:
        ti = getattr(root_obj, "treeInterceptor", None) or (
            root_obj if hasattr(root_obj, "rootNVDAObject") else None
        )
        target_url = primary.get("url_if_web", "") or ""
        if not _browse_doc_matches_target(ti, target_url):
            log.warning("REM BrowseMode resolve: URL mismatch.")
            return None
        root = getattr(ti, "rootNVDAObject", None) if ti else None
        if root is None:
            root = root_obj
        return {
            "primary": primary,
            "root_obj": root_obj,
            "stack": [root],
            "visited": set(),
            "candidates": [],
            "role_candidates": [],
            "role_counter": 0,
            "name_counter": 0,
        }
    except Exception as e:
        log.warning(f"REM BrowseMode resolve setup exception: {e}")
        return None


def _finish_browsemode_resolve(state: Dict[str, Any]) -> Optional[Any]:
    primary = state["primary"]
    candidates = state["candidates"]
    stored_index = primary.get("role_index", -1)
    stored_role_ordinal = primary.get("role_ordinal", -1)
    role_candidates = state["role_candidates"]

    log.debugWarning(
        f"REM BrowseMode resolve: {len(candidates)} name-matching candidates, "
        f"{len(role_candidates)} role candidates, stored_index={stored_index}, "
        f"stored_role_ordinal={stored_role_ordinal}, role_counter_total={state['role_counter']}"
    )

    if stored_index >= 0:
        for name_idx, role_idx, node in candidates:
            if name_idx == stored_index:
                log.debugWarning(f"REM resolved by name_index={name_idx}")
                return node

    if stored_index < 0 and stored_role_ordinal >= 0:
        for role_idx, node in role_candidates:
            if role_idx == stored_role_ordinal:
                log.debugWarning(f"REM resolved by role_ordinal={role_idx}")
                return node

    if stored_index < 0 and stored_role_ordinal < 0:
        if len(candidates) == 1:
            log.debugWarning("REM resolved: only one name-matching candidate.")
            return candidates[0][2]
        if len(role_candidates) == 1:
            log.debugWarning("REM resolved: only one role-matching candidate.")
            return role_candidates[0][1]

    log.warning(f"REM BrowseMode resolve: no match among {len(candidates)} candidates.")
    return None


def _begin_browsemode_resolve(
    primary: Dict[str, Any], root_obj, on_done: Callable
) -> None:
    state = _create_browsemode_state(primary, root_obj)
    if state is None:
        on_done(None)
        return
    _drive_browsemode_resolve(state, on_done, start_time=time.perf_counter())


def _drive_browsemode_resolve(
    state: Dict[str, Any],
    on_done: Callable,
    nodes_visited: int = 0,
    start_time: float = 0,
) -> None:
    import wx  # type: ignore

    try:
        stack = state["stack"]
        visited = state["visited"]
        primary = state["primary"]
        target_role = primary.get("role")
        target_name = (primary.get("name", "") or "").strip()
        stored_index = primary.get("role_index", -1)
        stored_role_ordinal = primary.get("role_ordinal", -1)
        chunk_start = time.perf_counter()
        nodes_this_chunk = 0

        while stack:
            node = stack.pop()
            if node is None:
                continue
            nid = id(node)
            if nid in visited:
                continue
            visited.add(nid)
            nodes_visited += 1
            nodes_this_chunk += 1

            node_role = node.role

            if node_role == target_role:
                current_role_ordinal = state["role_counter"]
                state["role_counter"] += 1
                node_name = (getattr(node, "name", "") or "").strip()
                state["role_candidates"].append((current_role_ordinal, node))

                if node_name == target_name:
                    idx = state["name_counter"]
                    state["name_counter"] += 1
                    state["candidates"].append((idx, current_role_ordinal, node))

                    if stored_index >= 0 and idx == stored_index:
                        elapsed = (time.perf_counter() - start_time) * 1000
                        _log_timing(
                            "BrowseMode_walk_early_exit", elapsed, nodes=nodes_visited
                        )
                        log.debugWarning(
                            f"REM BrowseMode walk: early exit at name_index={idx}"
                        )
                        on_done(node)
                        return

                if (
                    stored_index < 0
                    and stored_role_ordinal >= 0
                    and current_role_ordinal == stored_role_ordinal
                ):
                    elapsed = (time.perf_counter() - start_time) * 1000
                    _log_timing(
                        "BrowseMode_walk_early_exit", elapsed, nodes=nodes_visited
                    )
                    log.debugWarning(
                        f"REM BrowseMode walk: early exit at role_ordinal={current_role_ordinal} (no role_index)"
                    )
                    on_done(node)
                    return

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

            elapsed_chunk = time.perf_counter() - chunk_start
            if elapsed_chunk >= _CHUNK_BUDGET_S or nodes_this_chunk >= _CHUNK_MAX:
                wx.CallLater(
                    0,
                    _drive_browsemode_resolve,
                    state,
                    on_done,
                    nodes_visited,
                    start_time,
                )
                return

        result = _finish_browsemode_resolve(state)
        elapsed = (time.perf_counter() - start_time) * 1000
        _log_timing(
            "BrowseMode_walk", elapsed, nodes=nodes_visited, result=result is not None
        )
        if result is not None:
            log.debugWarning("REM BrowseMode walk succeeded.")
            on_done(result)
            return
        log.warning(
            "REM BrowseMode walk found no match; falling back to chunked tree walk."
        )
        _begin_chunked_tree_walk("BrowseMode", primary, state["root_obj"], on_done)

    except Exception as e:
        log.warning(f"REM BrowseMode resolve exception: {e}")
        on_done(None)


def _begin_chunked_tree_walk(
    backend: str, primary: Dict[str, Any], root_obj, on_done: Callable
) -> None:
    t0 = time.perf_counter()
    walker = _tree_walk_iter(backend, primary, root_obj)
    _drive_walk(walker, on_done, start_time=t0)


def _drive_walk(
    walker, on_done: Callable, nodes_visited: int = 0, start_time: float = 0
) -> None:
    import wx  # type: ignore

    try:
        chunk_start = time.perf_counter()
        nodes_this_chunk = 0

        while True:
            result = next(walker)
            nodes_visited += 1
            nodes_this_chunk += 1

            if result is not None:
                elapsed = (time.perf_counter() - start_time) * 1000
                _log_timing(
                    "chunked_tree_walk", elapsed, nodes=nodes_visited, result=True
                )
                log.debugWarning(f"REM walk resolved found match: {result!r}")
                on_done(result)
                return

            elapsed_chunk = time.perf_counter() - chunk_start
            if elapsed_chunk >= _CHUNK_BUDGET_S or nodes_this_chunk >= _CHUNK_MAX:
                wx.CallLater(0, _drive_walk, walker, on_done, nodes_visited, start_time)
                return

    except StopIteration:
        elapsed = (time.perf_counter() - start_time) * 1000
        _log_timing("chunked_tree_walk", elapsed, nodes=nodes_visited, result=False)
        log.warning("REM tree walk: exhausted all nodes, no match found.")
        on_done(None)


def _tree_walk_iter(backend: str, primary: Dict[str, Any], root_obj):
    log.debugWarning(f"REM tree walk iter start: backend={backend}")

    visited = 0
    stack = [root_obj]

    while stack:
        obj = stack.pop()
        if obj is None:
            continue

        visited += 1

        if _matches(backend, primary, obj):
            log.debugWarning(f"REM tree walk matched after {visited} nodes.")
            yield obj
            return

        children = []
        try:
            child = obj.firstChild
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

        yield None

    log.warning(f"REM tree walk: no match after {visited} nodes.")


def _uia_fast_path(runtime_id) -> Optional[Any]:
    try:
        import UIAHandler  # type: ignore

        if not UIAHandler.handler:
            return None
        condition = UIAHandler.handler.clientObject.CreatePropertyCondition(
            UIAHandler.UIA_RuntimeIdPropertyId,
            runtime_id,
        )
        found = UIAHandler.handler.rootElement.FindFirst(
            UIAHandler.TreeScope_Subtree,
            condition,
        )
        if found:
            import NVDAObjects.UIA as UIA_module  # type: ignore

            return UIA_module.UIA(UIAElement=found)
    except Exception as e:
        log.debugWarning(f"REM UIA fast-path exception: {e}")
    return None


def _matches(backend: str, primary: Dict[str, Any], obj) -> bool:
    try:
        if backend == "UIA":
            return _match_uia(obj, primary)
        elif backend == "IAccessible":
            return _match_iaccessible(obj, primary)
        elif backend == "BrowseMode":
            return _match_browsemode_simple(obj, primary)
    except Exception:
        pass
    return False


def _match_uia(obj, primary: Dict[str, Any]) -> bool:
    stored_automation_id = primary.get("automationId", "")
    stored_control_type = primary.get("controlType", "")
    stored_class_name = primary.get("className", "")
    if not any([stored_automation_id, stored_control_type, stored_class_name]):
        return False
    if (
        stored_automation_id
        and getattr(obj, "UIAAutomationId", "") != stored_automation_id
    ):
        return False
    if (
        stored_control_type
        and getattr(obj, "UIAControlType", "") != stored_control_type
    ):
        return False
    if stored_class_name and getattr(obj, "UIAClassName", "") != stored_class_name:
        return False
    return True


def _match_iaccessible(obj, primary: Dict[str, Any]) -> bool:
    if obj.role != primary.get("accRole"):
        return False
    stored_class = primary.get("windowClassName", "")
    if stored_class and getattr(obj, "windowClassName", "") != stored_class:
        return False
    return True


def _match_browsemode_simple(obj, primary: Dict[str, Any]) -> bool:
    """Tree-walk fallback: role + name only. Runs if all other BrowseMode strategies fail."""
    if obj.role != primary.get("role"):
        return False
    name_hint = (primary.get("name", "") or "").strip()
    obj_name = (getattr(obj, "name", "") or "").strip()
    if obj_name != name_hint:
        return False
    url_hint = primary.get("url_if_web", "")
    if url_hint and is_stable_document_identifier(url_hint):
        ti = getattr(obj, "treeInterceptor", None)
        doc_id = getattr(ti, "documentConstantIdentifier", None) if ti else None
        if (
            doc_id
            and is_stable_document_identifier(doc_id)
            and str(doc_id) != str(url_hint)
        ):
            return False
    return True

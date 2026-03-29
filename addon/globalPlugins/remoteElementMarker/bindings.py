from typing import Optional

try:
    import inputCore  # type: ignore
except Exception:
    inputCore = None


_TOKEN_MAP = {
    "ctrl": "control",
    "control": "control",
    "alt": "alt",
    "shift": "shift",
    "win": "windows",
    "windows": "windows",
    "nvda": "NVDA",
}


def normalize_shortcut(text: str) -> Optional[str]:
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None
    raw = raw.replace(" ", "")
    if ":" not in raw:
        raw = "kb:" + raw
    try:
        if inputCore and hasattr(inputCore, "normalizeGestureIdentifier"):
            return inputCore.normalizeGestureIdentifier(raw)
    except Exception:
        pass

    if ":" not in raw:
        return None
    source, rest = raw.split(":", 1)
    if not rest:
        return None
    parts = [p for p in rest.split("+") if p]
    if not parts:
        return None
    norm_parts = []
    for part in parts:
        pl = part.lower()
        norm_parts.append(_TOKEN_MAP.get(pl, pl))
    return f"{source}:{'+'.join(norm_parts)}"

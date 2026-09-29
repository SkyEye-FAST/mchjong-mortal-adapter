"""Mortal's compressed Q/action indices stay behind the adapter boundary."""

from .contracts import DecisionRequest, LegalAction


def selected_q(request: DecisionRequest, action: LegalAction,
               response: dict, reach_discard: dict | None = None) -> float | None:
    if action.type == "RIICHI" and reach_discard is not None:
        return _q(reach_discard.get("meta"), _discard_index(action.tiles[0]))
    meta = response.get("meta")
    if action.type in ("CLOSED_KAN", "ADDED_KAN") and isinstance(meta, dict):
        selection = meta.get("kan_select")
        if isinstance(selection, dict):
            tile = action.tiles[0]
            index = (tile & ~256) // 4 if action.type == "CLOSED_KAN" else _discard_index(tile)
            return _q(selection, index)
    index = _action_index(request, action)
    return _q(meta, index) if index is not None else None


def _q(meta: object, index: int) -> float | None:
    if not isinstance(meta, dict):
        return None
    mask, values = meta.get("mask_bits"), meta.get("q_values")
    if not isinstance(mask, int) or not isinstance(values, list) or not (mask & (1 << index)):
        return None
    offset = (mask & ((1 << index) - 1)).bit_count()
    return float(values[offset]) if offset < len(values) else None


def _discard_index(tile: int) -> int:
    kind = (tile & ~256) // 4
    return 34 + kind // 9 if tile & 256 else kind


def _action_index(request: DecisionRequest, action: LegalAction) -> int | None:
    kind = action.type
    if kind == "DISCARD":
        return _discard_index(action.tiles[0])
    if request.player_count == 3:
        return {
            "RIICHI": 37, "NUKI": 38, "PON": 39, "OPEN_KAN": 40, "CLOSED_KAN": 40,
            "ADDED_KAN": 40, "RON": 41, "TSUMO": 41,
            "ABORT_NINE": 42, "PASS": 43,
        }.get(kind)
    if kind == "CHI":
        if request.focus is None:
            return None
        called = (request.focus.tile & ~256) // 4
        kinds = [(tile & ~256) // 4 for tile in action.tiles]
        return 38 if called < min(kinds) else 40 if called > max(kinds) else 39
    return {
        "RIICHI": 37, "PON": 41, "OPEN_KAN": 42, "CLOSED_KAN": 42,
        "ADDED_KAN": 42, "RON": 43, "TSUMO": 43,
        "ABORT_NINE": 44, "PASS": 45,
    }.get(kind)

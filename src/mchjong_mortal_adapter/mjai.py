"""Convert MChjong physical tiles, replay events and legal actions to mjai."""

from .contracts import DecisionRequest, GameEvent, LegalAction

HONORS = "ESWNPFC"


def face(tile: int) -> str:
    physical = tile & ~256
    if physical < 0 or physical >= 136 or tile < 0 or tile & ~511:
        raise ValueError(f"invalid physical tile: {tile}")
    kind = physical // 4
    red = bool(tile & 256)
    if red and kind not in (4, 13, 22):
        raise ValueError(f"invalid red tile: {tile}")
    if kind >= 27:
        return HONORS[kind - 27]
    return f"{kind % 9 + 1}{'mps'[kind // 9]}{'r' if red else ''}"


def opening_event(request: DecisionRequest) -> dict:
    opening = request.opening
    count = request.player_count
    if opening.round // count > 3:
        raise ValueError("round is outside the supported four winds")
    hands = [["?"] * 13 for _ in range(count)]
    hands[request.seat] = [face(tile) for tile in opening.hand]
    scores = opening.scores
    return {
        "type": "start_kyoku", "bakaze": HONORS[opening.round // count],
        "kyoku": opening.round % count + 1, "oya": opening.dealer,
        "honba": opening.honba, "kyotaku": opening.riichi_sticks,
        "scores": scores, "tehais": hands, "dora_marker": face(opening.dora_marker),
    }


def event_lines(event: GameEvent, player_count: int) -> list[dict]:
    kind = event.kind
    if kind == "DORA":
        return [{"type": "dora", "dora_marker": face(_required(event.tile))}]
    actor = _required(event.seat)
    if actor < 0 or actor >= player_count:
        raise ValueError("event seat is outside the table")
    if kind == "DRAW":
        return [{"type": "tsumo", "actor": actor, "pai": face(event.tile) if event.tile is not None else "?"}]
    if kind == "DISCARD":
        discard = {"type": "dahai", "actor": actor, "pai": face(_required(event.tile)),
                   "tsumogiri": event.tsumogiri}
        return ([{"type": "reach", "actor": actor}] if event.riichi else []) + [discard]
    if kind == "RIICHI_ACCEPTED":
        return [{"type": "reach_accepted", "actor": actor}]
    if kind == "NUKI":
        return [{"type": "nukidora", "actor": actor, "pai": face(_required(event.tile))}]
    consumed = [face(tile) for tile in event.tiles]
    if kind == "CLOSED_KAN":
        if len(consumed) != 4:
            raise ValueError("closed kan needs four tiles")
        return [{"type": "ankan", "actor": actor, "consumed": consumed}]
    if kind == "ADDED_KAN":
        if len(consumed) != 3:
            raise ValueError("added kan needs original pon tiles")
        return [{"type": "kakan", "actor": actor, "pai": face(_required(event.tile)),
                 "consumed": consumed}]
    count = 3 if kind == "OPEN_KAN" else 2
    if len(consumed) != count:
        raise ValueError(f"{kind} needs {count} consumed tiles")
    target = _required(event.from_seat)
    if target < 0 or target >= player_count:
        raise ValueError("call target is outside the table")
    return [{"type": {"CHI": "chi", "PON": "pon", "OPEN_KAN": "daiminkan"}[kind],
             "actor": actor, "target": target, "pai": face(_required(event.called_tile)),
             "consumed": consumed}]


def match_action(request: DecisionRequest, response: dict, reach: bool = False) -> int:
    kind = response.get("type")
    if reach and kind != "dahai":
        raise ValueError("reach must be followed by a discard")
    expected = {
        "none": "PASS", "dahai": "RIICHI" if reach else "DISCARD",
        "chi": "CHI", "pon": "PON", "daiminkan": "OPEN_KAN",
        "ankan": "CLOSED_KAN", "kakan": "ADDED_KAN", "nukidora": "NUKI",
        "kita": "NUKI", "ryukyoku": "ABORT_NINE",
        "hora": "TSUMO" if request.focus is None else "RON",
    }.get(kind)
    if expected is None:
        raise ValueError(f"unknown mjai action: {kind}")
    if kind not in ("none", "ryukyoku") and response.get("actor") != request.seat:
        raise ValueError("wrong mjai actor")
    matches = [i for i, action in enumerate(request.legal_actions)
               if action.type == expected and _matches(request, action, response)]
    if not matches:
        raise ValueError(f"mjai action has no legal match: {kind}")
    return matches[0]


def _matches(request: DecisionRequest, action: LegalAction, response: dict) -> bool:
    kind = action.type
    if kind in ("PASS", "ABORT_NINE"):
        return True
    if kind in ("RON", "TSUMO"):
        target = request.seat if kind == "TSUMO" else request.focus.seat if request.focus else None
        return response.get("target") == target
    if kind in ("DISCARD", "RIICHI", "ADDED_KAN", "NUKI"):
        if len(action.tiles) != 1 or response.get("pai", "N" if response.get("type") == "kita" else None) != face(action.tiles[0]):
            return False
        if kind == "ADDED_KAN":
            pons = [meld for meld in request.melds
                    if (meld.tiles[0] & ~256) // 4 == (action.tiles[0] & ~256) // 4]
            return len(pons) == 1 and _consumed(response) == sorted(face(tile) for tile in pons[0].tiles)
        if "tsumogiri" in response and request.drawn_tile is not None and kind != "NUKI":
            return response["tsumogiri"] == (action.tiles[0] == request.drawn_tile)
        return True
    if kind == "CLOSED_KAN":
        return sorted(face(tile) for tile in action.tiles) == _consumed(response)
    return (request.focus is not None and response.get("target") == request.focus.seat
            and response.get("pai") == face(request.focus.tile)
            and sorted(face(tile) for tile in action.tiles) == _consumed(response))


def _consumed(response: dict) -> list[str]:
    consumed = response.get("consumed")
    if not isinstance(consumed, list) or not all(isinstance(tile, str) for tile in consumed):
        return []
    return sorted(consumed)


def _required(value: int | None) -> int:
    if value is None:
        raise ValueError("required event field is missing")
    return value

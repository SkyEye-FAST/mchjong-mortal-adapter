"""Sanma's native mjai and historical four-slot libriichi3p shapes."""


def to_libriichi3p(event: dict, *, historical_slots: bool = False) -> dict:
    converted = dict(event)
    if converted.get("type") == "kita":
        converted["type"] = "nukidora"
        converted["pai"] = "N"
    if historical_slots:
        if converted.get("type") == "start_game" and "names" in converted:
            names = converted["names"]
            if len(names) == 3:
                converted["names"] = [*names, ""]
            if converted.get("num_players") == 3:
                converted["num_players"] = 4
        if converted.get("type") == "start_kyoku":
            scores, hands = converted["scores"], converted["tehais"]
            if len(scores) == 3 and len(hands) == 3:
                converted["scores"] = [*scores, 0]
                converted["tehais"] = [*hands, ["?"] * 13]
        if "deltas" in converted and len(converted["deltas"]) == 3:
            converted["deltas"] = [*converted["deltas"], 0]
    return converted


def from_libriichi3p(response: dict, *, akagi_native: bool = True) -> dict:
    converted = dict(response)
    if akagi_native and converted.get("type") == "nukidora":
        converted["type"] = "kita"
        converted.pop("pai", None)
    return converted

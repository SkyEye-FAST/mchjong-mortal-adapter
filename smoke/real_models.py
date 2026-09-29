"""Explicit HTTP smoke for external Mortal checkpoints and native extensions."""

import argparse
import importlib
import sys
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from mchjong_mortal_adapter.api import create_app
from mchjong_mortal_adapter.backends import FourPlayerBackend, ThreePlayerBackend
from mchjong_mortal_adapter.service import DecisionService


def position(players: int) -> dict:
    hand = ([0, 12, 24, 36, 48, 60, 72, 84, 96, 108, 112, 116, 120]
            if players == 4 else [0, 32, 36, 40, 48, 60, 72, 84, 88, 96, 108, 112, 116])
    drawn = 124 if players == 4 else 128
    return {
        "table_id": str(UUID(int=players)),
        "session_id": str(UUID(int=players + 10)),
        "hand_number": 0,
        "seat": 0,
        "protocol_version": 1,
        "bot_id": "mortal-4p" if players == 4 else "mortal-3p",
        "preset": "TENHOU_4" if players == 4 else "TENHOU_3",
        "player_count": players,
        "decision": 1,
        "opening": {
            "round": 0, "dealer": 0, "honba": 0, "riichi_sticks": 0,
            "scores": [25000 if players == 4 else 35000] * players,
            "hand": hand, "dora_marker": 132,
        },
        "events": [{"kind": "DRAW", "seat": 0, "tile": drawn}],
        "legal_actions": [{"type": "DISCARD", "tiles": [tile]} for tile in [*hand, drawn]],
        "drawn_tile": drawn,
        "focus": None,
        "melds": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mortal-checkout", required=True, type=Path)
    parser.add_argument("--model-4p", required=True, type=Path)
    parser.add_argument("--libriichi-4p-path", required=True, type=Path)
    parser.add_argument("--sanma-runtime", required=True, type=Path)
    args = parser.parse_args()

    four = FourPlayerBackend(args.mortal_checkout, args.model_4p, args.libriichi_4p_path)
    four_module = importlib.import_module("libriichi")
    three = ThreePlayerBackend(args.sanma_runtime)
    assert importlib.import_module("libriichi") is four_module
    assert importlib.import_module("libriichi.consts").ACTION_SPACE == 46
    assert importlib.import_module("libriichi3p.consts").ACTION_SPACE == 44
    assert sys.modules["libriichi3p"] is not four_module

    client = TestClient(create_app(DecisionService({four.name: (4, four), three.name: (3, three)})))
    assert client.get("/v1/health").json() == {"protocol_version": 1, "status": "ready", "bots": 2}
    assert len(client.get("/v1/bots").json()["bots"]) == 2
    for players in (4, 3):
        issued = position(players)
        response = client.post("/v1/decisions", json=issued)
        if response.status_code != 200:
            raise AssertionError(f"{players}p decision failed: {response.status_code} {response.text}")
        answer = response.json()
        assert 0 <= answer["action_index"] < len(issued["legal_actions"])
        assert answer["session_id"] == issued["session_id"]
        assert answer["decision"] == issued["decision"]
        assert "action_id" not in answer
        print(f"{players}p real model: PASS, legal action index {answer['action_index']}")
    four_again = position(4)
    four_again["session_id"] = str(UUID(int=44))
    response = client.post("/v1/decisions", json=four_again)
    assert response.status_code == 200, response.text
    assert 0 <= response.json()["action_index"] < len(four_again["legal_actions"])
    print("same-process libriichi/libriichi3p isolation: PASS")


if __name__ == "__main__":
    main()

import sys
from collections import deque
from contextlib import nullcontext
from types import ModuleType, SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from mchjong_mortal_adapter import UPSTREAM_REVISION
from mchjong_mortal_adapter.api import create_app
from mchjong_mortal_adapter.backends import FourPlayerBackend, ThreePlayerBackend, _revision
from mchjong_mortal_adapter.contracts import DecisionRequest
from mchjong_mortal_adapter.mjai import face, match_action
from mchjong_mortal_adapter.qvalues import selected_q
from mchjong_mortal_adapter.sanma_protocol import from_libriichi3p, to_libriichi3p
from mchjong_mortal_adapter.service import DecisionError, DecisionService


TABLE = UUID("00000000-0000-0000-0000-000000000001")
SESSION = UUID("00000000-0000-0000-0000-000000000011")


def request(*, table=TABLE, session=SESSION, hand=0, seat=0, players=4, decision=1, events=None,
            actions=None, focus=None, drawn=None, melds=None):
    drawn = (52 if players == 4 else 80) if drawn is None else drawn
    opening_hand = list(range(0, 52, 4)) if players == 4 else [
        0, 32, 36, 40, 44, 48, 52, 56, 60, 64, 68, 72, 76,
    ]
    return DecisionRequest.model_validate({
        "table_id": str(table), "session_id": str(session), "hand_number": hand, "seat": seat,
        "player_count": players, "decision": decision,
        "opening": {"round": 0, "dealer": 0, "honba": 0, "riichi_sticks": 0,
                    "scores": [25000 if players == 4 else 35000] * players,
                    "hand": opening_hand,
                    "dora_marker": 108},
        "events": events if events is not None else [{"kind": "DRAW", "seat": seat, "tile": 52}],
        "legal_actions": actions if actions is not None else [{"type": "DISCARD", "tiles": [0], "id": "discard-1m"}],
        "focus": focus, "drawn_tile": drawn, "melds": melds or [],
    })


class FakeBackend:
    name = "fake"

    def __init__(self, replies):
        self.replies = deque(replies)
        self.bots = []

    def new_bot(self, seat):
        bot = {"seat": seat, "events": []}
        self.bots.append(bot)
        return bot

    def react(self, bot, event, can_act):
        bot["events"].append((event, can_act))
        return self.replies.popleft() if can_act else None

    def resolve_reach(self, bot, response, seat):
        bot["events"].append(({"type": "reach", "actor": seat}, True))
        return self.replies.popleft(), True


def test_model_loaded_once_for_multiple_seats(monkeypatch, tmp_path):
    checkout = tmp_path / "upstream"
    (checkout / "mortal").mkdir(parents=True)
    model_path = tmp_path / "weights.pth"
    model_path.touch()
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: SimpleNamespace(stdout=UPSTREAM_REVISION + "\n"))
    loads = []
    torch = ModuleType("torch")
    torch.set_num_threads = lambda _: None
    torch.load = lambda *args, **kwargs: (loads.append((args, kwargs)) or {
        "config": {"control": {"version": 4}, "resnet": {"conv_channels": 4, "num_blocks": 1}},
        "mortal": {}, "current_dqn": {},
    })
    monkeypatch.setitem(sys.modules, "torch", torch)

    class Network:
        def __init__(self, **kwargs):
            pass

        def eval(self):
            return self

        def load_state_dict(self, state):
            pass

    model = ModuleType("model")
    model.Brain = Network
    model.DQN = Network
    engine = ModuleType("engine")
    engine.MortalEngine = lambda *args, **kwargs: object()
    bot_module = ModuleType("libriichi.mjai")
    bot_module.Bot = lambda engine, seat: (engine, seat)
    consts = ModuleType("libriichi.consts")
    consts.ACTION_SPACE = 46
    monkeypatch.setitem(sys.modules, "model", model)
    monkeypatch.setitem(sys.modules, "engine", engine)
    monkeypatch.setitem(sys.modules, "libriichi.mjai", bot_module)
    monkeypatch.setitem(sys.modules, "libriichi.consts", consts)
    monkeypatch.setattr("mchjong_mortal_adapter.backends._source_module",
                        lambda _, path: model if path.name == "model.py" else engine)

    backend = FourPlayerBackend(checkout, model_path, checkout / "mortal")
    first, second = backend.new_bot(0), backend.new_bot(1)
    assert first[0] is second[0] is backend.engine
    assert len(loads) == 1
    assert loads[0][1]["weights_only"] is True


def test_model_source_revision_is_strict(monkeypatch, tmp_path):
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: SimpleNamespace(stdout="wrong\n"))
    with pytest.raises(ValueError, match="unsupported official Mortal revision"):
        _revision(tmp_path, UPSTREAM_REVISION, "official Mortal")


def test_sanma_model_loaded_once_for_multiple_seats(monkeypatch, tmp_path):
    checkout = tmp_path / "sanma"
    (checkout / "mortal").mkdir(parents=True)
    model_path = tmp_path / "weights.pth"
    model_path.touch()
    monkeypatch.setattr("mchjong_mortal_adapter.backends._revision", lambda path, *_: path)
    monkeypatch.setattr("mchjong_mortal_adapter.backends._sanma_extension", lambda _: nullcontext())
    loads = []
    torch = ModuleType("torch")
    torch.set_num_threads = lambda _: None
    torch.load = lambda *args, **kwargs: (loads.append(kwargs) or {
        "config": {"control": {"version": 5}, "resnet": {"conv_channels": 4, "num_blocks": 1}},
        "mortal": {}, "current_dqn": {},
    })
    monkeypatch.setitem(sys.modules, "torch", torch)

    class Network:
        def __init__(self, **kwargs):
            pass

        def eval(self):
            return self

        def load_state_dict(self, state):
            pass

    model = SimpleNamespace(Brain=Network, DQN=Network)
    engine = SimpleNamespace(MortalEngine=lambda *args, **kwargs: object())
    monkeypatch.setattr("mchjong_mortal_adapter.backends._source_module",
                        lambda _, path: model if path.name == "model.py" else engine)
    consts = ModuleType("libriichi.consts")
    consts.ACTION_SPACE = 44
    bot_module = ModuleType("libriichi.mjai")
    bot_module.Bot = lambda engine, seat: (engine, seat)
    monkeypatch.setitem(sys.modules, "libriichi.consts", consts)
    monkeypatch.setitem(sys.modules, "libriichi.mjai", bot_module)

    backend = ThreePlayerBackend(checkout, model_path, tmp_path)
    first, second = backend.new_bot(0), backend.new_bot(1)
    assert first[0] is second[0] is backend.engine
    assert len(loads) == 1 and loads[0]["weights_only"] is True


def test_plain_decision_and_http_endpoints():
    backend = FakeBackend([{"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False}])
    client = TestClient(create_app(DecisionService({4: backend})))
    assert client.get("/v1/health").json() == {"status": "ready", "bots": 1}
    assert client.get("/v1/bots").json() == {"bots": [{"id": "fake", "player_count": 4}]}
    body = request().model_dump(mode="json")
    response = client.post("/v1/decisions", json=body)
    assert response.status_code == 200
    assert response.json()["action_index"] == 0
    assert response.json()["action_id"] == "discard-1m"
    assert client.post("/v1/decisions", json=body).json() == response.json()
    assert len(backend.bots) == 1


def test_reach_discard_and_echo_are_one_server_action():
    backend = FakeBackend([
        {"type": "reach", "actor": 0},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False},
        {"type": "dahai", "actor": 0, "pai": "2m", "tsumogiri": False},
    ])
    service = DecisionService({4: backend})
    first = request(actions=[{"type": "RIICHI", "tiles": [0]}])
    assert service.decide(first).action_index == 0
    events = [*first.events, {"kind": "DISCARD", "seat": 0, "tile": 0, "riichi": True},
              {"kind": "DRAW", "seat": 0, "tile": 52}]
    second = request(decision=2, events=events, actions=[{"type": "DISCARD", "tiles": [4]}])
    assert service.decide(second).action_index == 0
    reaches = [event for event, _ in backend.bots[0]["events"] if event["type"] == "reach"]
    assert len(reaches) == 1


def test_sanma_reach_discard_remains_one_server_action():
    backend = FakeBackend([
        {"type": "reach", "actor": 0},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False},
        {"type": "dahai", "actor": 0, "pai": "9m", "tsumogiri": False},
    ])
    service = DecisionService({3: backend})
    first = request(players=3, actions=[{"type": "RIICHI", "tiles": [0]}])
    assert service.decide(first).action_index == 0
    events = [*first.events, {"kind": "DISCARD", "seat": 0, "tile": 0, "riichi": True},
              {"kind": "DRAW", "seat": 0, "tile": 84}]
    second = request(players=3, decision=2, events=events,
                     actions=[{"type": "DISCARD", "tiles": [32]}], drawn=84)
    assert service.decide(second).action_index == 0
    assert sum(event["type"] == "reach" for event, _ in backend.bots[0]["events"]) == 1


def test_claims_and_kan_match_only_server_issued_choices():
    chi = request(events=[{"kind": "DISCARD", "seat": 1, "tile": 8}],
                  focus={"seat": 1, "tile": 8},
                  actions=[{"type": "PASS"}, {"type": "CHI", "tiles": [0, 4]}])
    assert match_action(chi, {"type": "chi", "actor": 0, "target": 1,
                              "pai": "3m", "consumed": ["1m", "2m"]}) == 1
    kan = request(actions=[{"type": "CLOSED_KAN", "tiles": [0, 1, 2, 3]}])
    assert match_action(kan, {"type": "ankan", "actor": 0,
                              "consumed": ["1m"] * 4}) == 0
    added = request(actions=[{"type": "ADDED_KAN", "tiles": [3]}],
                    melds=[{"kind": "PON", "tiles": [0, 1, 2]}])
    assert match_action(added, {"type": "kakan", "actor": 0, "pai": "1m",
                                "consumed": ["1m"] * 3}) == 0


def test_sanma_north_extraction_is_a_separate_backend():
    backend = FakeBackend([{"type": "kita", "actor": 0}])
    service = DecisionService({3: backend})
    north = 120
    position = request(players=3, events=[{"kind": "DRAW", "seat": 0, "tile": north}],
                       actions=[{"type": "NUKI", "tiles": [north]}], drawn=north)
    assert service.decide(position).action_index == 0
    assert face(north) == "N"
    assert service.backends[3] is backend


def test_table_and_seat_sessions_are_isolated():
    backend = FakeBackend([{"type": "none"}, {"type": "none"}, {"type": "none"}])
    service = DecisionService({4: backend})
    other = UUID("00000000-0000-0000-0000-000000000002")
    for table, seat in ((TABLE, 0), (TABLE, 1), (other, 0)):
        position = request(table=table, seat=seat,
                           actions=[{"type": "PASS"}],
                           events=[{"kind": "DISCARD", "seat": (seat + 1) % 4, "tile": 0}])
        assert service.decide(position).action_index == 0
    assert len(backend.bots) == 3
    assert len({id(bot) for bot in backend.bots}) == 3


def test_illegal_action_and_changed_history_are_rejected():
    backend = FakeBackend([
        {"type": "pon", "actor": 0, "target": 1, "pai": "1m", "consumed": ["1m", "1m"]},
        {"type": "none"},
    ])
    service = DecisionService({4: backend})
    with pytest.raises(DecisionError) as error:
        service.decide(request())
    assert error.value.status == 422
    valid = request(events=[{"kind": "DISCARD", "seat": 1, "tile": 0}],
                    actions=[{"type": "PASS"}])
    service.decide(valid)
    with pytest.raises(DecisionError) as error:
        service.decide(request(decision=2, events=[{"kind": "DISCARD", "seat": 1, "tile": 4}],
                               actions=[{"type": "PASS"}]))
    assert error.value.status == 409


def test_q_values_use_mortal_reach_kan_and_sanma_indices():
    red = request(actions=[{"type": "DISCARD", "tiles": [272]}])
    assert selected_q(red, red.legal_actions[0],
                      {"meta": {"mask_bits": 1 << 34, "q_values": [1.25]}}) == 1.25
    reach = request(actions=[{"type": "RIICHI", "tiles": [0]}])
    assert selected_q(reach, reach.legal_actions[0], {},
                      {"meta": {"mask_bits": 1, "q_values": [2.5]}}) == 2.5
    kan = request(actions=[{"type": "CLOSED_KAN", "tiles": [0, 1, 2, 3]}])
    assert selected_q(kan, kan.legal_actions[0],
                      {"meta": {"kan_select": {"mask_bits": 1, "q_values": [3.5]}}}) == 3.5
    sanma = request(players=3, actions=[{"type": "NUKI", "tiles": [120]}])
    assert selected_q(sanma, sanma.legal_actions[0],
                      {"meta": {"mask_bits": 1 << 38, "q_values": [4.5]}}) == 4.5
    sanma_kan = request(players=3, actions=[{"type": "CLOSED_KAN", "tiles": [0, 1, 2, 3]}])
    assert selected_q(sanma_kan, sanma_kan.legal_actions[0],
                      {"meta": {"kan_select": {"mask_bits": 1, "q_values": [5.5]}}}) == 5.5


def test_sanma_native_and_historical_mjai_shapes():
    position = request(players=3, actions=[{"type": "NUKI", "tiles": [120]}])
    from mchjong_mortal_adapter.mjai import opening_event

    native = opening_event(position)
    assert len(native["scores"]) == len(native["tehais"]) == 3
    padded = to_libriichi3p(native, historical_slots=True)
    assert padded["scores"] == [35000, 35000, 35000, 0]
    assert padded["tehais"][3] == ["?"] * 13
    assert native["scores"] == [35000] * 3
    assert to_libriichi3p({"type": "kita", "actor": 0}) == {
        "type": "nukidora", "actor": 0, "pai": "N",
    }
    assert from_libriichi3p({"type": "nukidora", "actor": 0, "pai": "N"}) == {
        "type": "kita", "actor": 0,
    }

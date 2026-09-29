"""Long-lived model and isolated table/seat decision sessions."""

import threading
import time
from dataclasses import dataclass, field
from uuid import UUID

from .backends import BotBackend
from .contracts import PROTOCOL_VERSION, DecisionRequest, DecisionResponse, GameEvent, Opening
from .mjai import event_lines, match_action, opening_event


class DecisionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class _Session:
    hand_number: int
    opening: Opening
    last_used: float = field(default_factory=time.monotonic)
    bot: object | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    events: list[GameEvent] = field(default_factory=list)
    last_decision: int = -1
    last_request: DecisionRequest | None = None
    last_response: DecisionResponse | None = None
    pending_reach: bool = False


class DecisionService:
    SESSION_TTL_SECONDS = 30 * 60

    def __init__(self, backends: dict[str, tuple[int, BotBackend]]):
        if any(bot_id != backend.name for bot_id, (_, backend) in backends.items()):
            raise ValueError("backend registry ID does not match backend name")
        self.backends = backends
        self.sessions: dict[tuple[UUID, UUID, int, str], _Session] = {}
        self.lock = threading.Lock()

    def decide(self, request: DecisionRequest) -> DecisionResponse:
        if request.protocol_version != PROTOCOL_VERSION:
            raise DecisionError(400, f"unsupported protocol version {request.protocol_version}")
        selected = self.backends.get(request.bot_id)
        if selected is None or selected[0] != request.player_count:
            raise DecisionError(503, f"bot {request.bot_id} is not available for {request.player_count} players")
        backend = selected[1]
        if request.preset != ("TENHOU_3" if request.player_count == 3 else "TENHOU_4"):
            raise DecisionError(422, f"bot {request.bot_id} does not support preset {request.preset}")
        key = request.table_id, request.session_id, request.seat, request.bot_id
        while True:
            with self.lock:
                now = time.monotonic()
                for old_key, old_session in list(self.sessions.items()):
                    if now - old_session.last_used > self.SESSION_TTL_SECONDS and not old_session.lock.locked():
                        del self.sessions[old_key]
                session = self.sessions.get(key)
                if session is None:
                    session = _Session(hand_number=request.hand_number, opening=request.opening)
                    self.sessions[key] = session
            with session.lock:
                with self.lock:
                    if self.sessions.get(key) is not session:
                        continue
                    session.last_used = time.monotonic()
                return self._decide_locked(request, backend, key, session)

    def _decide_locked(self, request: DecisionRequest, backend: BotBackend,
                       key: tuple[UUID, UUID, int, str], session: _Session) -> DecisionResponse:
        if request.hand_number > session.hand_number:
            session.bot = None
            session.hand_number = request.hand_number
            session.opening = request.opening
            session.events = []
            session.last_decision = -1
            session.last_request = None
            session.last_response = None
            session.pending_reach = False
        elif request.hand_number < session.hand_number:
            raise DecisionError(409, "stale hand number")
        if request.decision == session.last_decision:
            if request == session.last_request:
                return session.last_response
            raise DecisionError(409, "same decision token has different inputs")
        if request.decision <= session.last_decision:
            raise DecisionError(409, "stale decision token")
        if (request.opening != session.opening
                or request.events[:len(session.events)] != session.events):
            raise DecisionError(409, "hand history changed within a session")
        delta = request.events[len(session.events):]
        if not delta:
            raise DecisionError(409, "a new decision needs a new game event")
        new = session.bot is None
        try:
            if new:
                session.bot = backend.new_bot(request.seat)
                backend.react(session.bot, {"type": "start_game", "id": request.seat}, False)
                backend.react(session.bot, opening_event(request), False)
            result = None
            for event_index, event in enumerate(delta):
                lines = event_lines(event, request.player_count)
                for line_index, line in enumerate(lines):
                    if line["type"] == "reach" and session.pending_reach:
                        if line["actor"] != request.seat:
                            raise ValueError("pending reach actor changed")
                        session.pending_reach = False
                        continue
                    can_act = event_index == len(delta) - 1 and line_index == len(lines) - 1
                    result = backend.react(session.bot, line, can_act)
            if result is None:
                raise ValueError("Mortal did not return a decision")
            reach = result.get("type") == "reach"
            if reach:
                if result.get("actor") != request.seat:
                    raise ValueError("wrong reach actor")
                result, session.pending_reach = backend.resolve_reach(session.bot, result, request.seat)
            index = match_action(request, result, reach=reach)
            answer = DecisionResponse(
                protocol_version=PROTOCOL_VERSION,
                bot_id=request.bot_id,
                table_id=request.table_id, session_id=request.session_id,
                hand_number=request.hand_number,
                seat=request.seat, decision=request.decision,
                action_index=index,
            )
        except Exception as error:
            # The bot may already have consumed events; rebuild from the next full history.
            with self.lock:
                if self.sessions.get(key) is session:
                    del self.sessions[key]
            raise DecisionError(422, str(error)) from error
        session.events = list(request.events)
        session.last_decision = request.decision
        session.last_request = request
        session.last_response = answer
        return answer

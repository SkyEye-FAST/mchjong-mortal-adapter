"""Long-lived model and isolated table/seat decision sessions."""

import threading
from dataclasses import dataclass, field
from uuid import UUID

from .backends import BotBackend
from .contracts import DecisionRequest, DecisionResponse, GameEvent, Opening
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
    bot: object | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    events: list[GameEvent] = field(default_factory=list)
    last_decision: int = -1
    last_request: DecisionRequest | None = None
    last_response: DecisionResponse | None = None
    pending_reach: bool = False


class DecisionService:
    def __init__(self, backends: dict[int, BotBackend]):
        self.backends = backends
        self.sessions: dict[tuple[UUID, UUID, int], _Session] = {}
        self.lock = threading.Lock()

    def decide(self, request: DecisionRequest) -> DecisionResponse:
        backend = self.backends.get(request.player_count)
        if backend is None:
            raise DecisionError(503, f"{request.player_count}-player backend is not configured")
        key = request.table_id, request.session_id, request.seat
        while True:
            with self.lock:
                session = self.sessions.get(key)
                if session is None:
                    session = _Session(hand_number=request.hand_number, opening=request.opening)
                    self.sessions[key] = session
            with session.lock:
                with self.lock:
                    if self.sessions.get(key) is not session:
                        continue
                return self._decide_locked(request, backend, key, session)

    def _decide_locked(self, request: DecisionRequest, backend: BotBackend,
                       key: tuple[UUID, UUID, int], session: _Session) -> DecisionResponse:
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

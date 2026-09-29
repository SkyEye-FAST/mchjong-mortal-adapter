"""Long-lived model and isolated table/seat decision sessions."""

import threading
from dataclasses import dataclass, field
from uuid import UUID

from .backends import BotBackend
from .contracts import DecisionRequest, DecisionResponse, GameEvent, Opening
from .mjai import event_lines, match_action, opening_event
from .qvalues import selected_q


class DecisionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class _Session:
    bot: object
    session_id: UUID
    hand_number: int
    opening: Opening
    events: list[GameEvent] = field(default_factory=list)
    last_decision: int = -1
    last_request: DecisionRequest | None = None
    last_response: DecisionResponse | None = None
    pending_reach: bool = False
    last_q: float | None = None


class DecisionService:
    def __init__(self, backends: dict[int, BotBackend]):
        self.backends = backends
        self.sessions: dict[tuple[UUID, int], _Session] = {}
        self.lock = threading.RLock()

    def decide(self, request: DecisionRequest) -> DecisionResponse:
        backend = self.backends.get(request.player_count)
        if backend is None:
            raise DecisionError(503, f"{request.player_count}-player backend is not configured")
        key = request.table_id, request.seat
        with self.lock:
            session = self.sessions.get(key)
            if session is not None and session.session_id != request.session_id:
                session = None
            elif session is not None and request.hand_number > session.hand_number:
                session = None
            elif session is not None and request.hand_number < session.hand_number:
                raise DecisionError(409, "stale hand number")
            if session is not None and request.decision == session.last_decision:
                if request == session.last_request:
                    return session.last_response
                raise DecisionError(409, "same decision token has different inputs")
            if session is not None and request.decision <= session.last_decision:
                raise DecisionError(409, "stale decision token")
            if session is not None and (request.opening != session.opening
                                        or request.events[:len(session.events)] != session.events):
                raise DecisionError(409, "hand history changed within a session")
            new = session is None
            if new:
                session = _Session(backend.new_bot(request.seat), request.session_id,
                                   request.hand_number, request.opening)
                self.sessions[key] = session
            delta = request.events[len(session.events):]
            if not delta:
                raise DecisionError(409, "a new decision needs a new game event")
            try:
                if new:
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
                initial_response = result
                reach = result.get("type") == "reach"
                if reach:
                    if result.get("actor") != request.seat:
                        raise ValueError("wrong reach actor")
                    result, session.pending_reach = backend.resolve_reach(session.bot, result, request.seat)
                index = match_action(request, result, reach=reach)
                action = request.legal_actions[index]
                q = selected_q(request, action, initial_response, result if reach else None)
                answer = DecisionResponse(
                    table_id=request.table_id, session_id=request.session_id,
                    hand_number=request.hand_number,
                    seat=request.seat, decision=request.decision,
                    action_index=index, action_id=action.id,
                )
            except Exception as error:
                # The bot may already have consumed events; rebuild from the next full history.
                del self.sessions[key]
                raise DecisionError(422, str(error)) from error
            session.events = list(request.events)
            session.last_decision = request.decision
            session.last_request = request
            session.last_response = answer
            session.last_q = q
            return answer

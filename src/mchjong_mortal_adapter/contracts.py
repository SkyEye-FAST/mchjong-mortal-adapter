"""Server-owned game position and action contract; no mjai escapes this module."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


ActionType = Literal[
    "DISCARD", "RIICHI", "CHI", "PON", "OPEN_KAN", "CLOSED_KAN",
    "ADDED_KAN", "NUKI", "RON", "TSUMO", "PASS", "ABORT_NINE",
]
EventType = Literal[
    "DRAW", "DISCARD", "RIICHI_ACCEPTED", "DORA", "CHI", "PON",
    "OPEN_KAN", "CLOSED_KAN", "ADDED_KAN", "NUKI",
]


class Opening(BaseModel):
    round: int = Field(ge=0)
    dealer: int = Field(ge=0)
    honba: int = Field(ge=0, le=255)
    riichi_sticks: int = Field(ge=0, le=255)
    scores: list[int]
    hand: list[int] = Field(min_length=13, max_length=13)
    dora_marker: int


class GameEvent(BaseModel):
    kind: EventType
    seat: int | None = None
    tile: int | None = None
    tsumogiri: bool = False
    riichi: bool = False
    from_seat: int | None = None
    called_tile: int | None = None
    tiles: list[int] = Field(default_factory=list)


class Focus(BaseModel):
    seat: int
    tile: int


class Meld(BaseModel):
    kind: Literal["PON"]
    tiles: list[int] = Field(min_length=3, max_length=3)


class LegalAction(BaseModel):
    type: ActionType
    tiles: list[int] = Field(default_factory=list)


class DecisionRequest(BaseModel):
    table_id: UUID
    session_id: UUID
    hand_number: int = Field(ge=0)
    seat: int = Field(ge=0)
    player_count: Literal[3, 4]
    decision: int = Field(ge=0)
    opening: Opening
    events: list[GameEvent]
    legal_actions: list[LegalAction] = Field(min_length=1)
    focus: Focus | None = None
    drawn_tile: int | None = None
    melds: list[Meld] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_seats(self) -> "DecisionRequest":
        if self.seat >= self.player_count or self.opening.dealer >= self.player_count:
            raise ValueError("seat or dealer is outside the table")
        if len(self.opening.scores) != self.player_count:
            raise ValueError("scores must have one entry per player")
        return self


class DecisionResponse(BaseModel):
    table_id: UUID
    session_id: UUID
    hand_number: int
    seat: int
    decision: int
    action_index: int

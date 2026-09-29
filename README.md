# MChjong Mortal Adapter

A persistent local HTTP service for MChjong Riichi bot decisions. Four-player
inference uses the external [Equim-chan/Mortal](https://github.com/Equim-chan/Mortal)
`Brain`, `DQN`, `MortalEngine` and `libriichi.mjai.Bot` directly. Three-player
inference uses a separate [Mateces/mortal-sanma](https://github.com/Mateces/mortal-sanma)
backend with its own model and `libriichi` build. Models load once at startup;
each table and seat owns independent game state. Only a server-issued legal
action index and optional action ID cross back to MChjong.

The pinned sources are official Mortal
[`0cff2b52982be5b1163aa9a62fb01f03ce91e0d2`](https://github.com/Equim-chan/Mortal/commit/0cff2b52982be5b1163aa9a62fb01f03ce91e0d2)
for four players with a version 4 model and Mateces/mortal-sanma
[`bf69bc320d6072bbeae2abfdc57bf876a5bab2e3`](https://github.com/Mateces/mortal-sanma/commit/bf69bc320d6072bbeae2abfdc57bf876a5bab2e3)
for three players. Startup checks both revisions and the respective action
space sizes (46 and 44). Checkouts, compiled extensions and model files stay
outside the Git repository.

## Run locally

Use Python 3.11, uv and a `libriichi` Python extension built from each pinned
checkout. On Windows, the following commands create local, ignored module
directories. The official crate outputs `riichi.dll`; the Mateces crate outputs
`libriichi.dll`. Both Python modules are named `libriichi` and are isolated by
the adapter at startup.

```powershell
git clone https://github.com/Equim-chan/Mortal.git C:\Java\Mortal
git -C C:\Java\Mortal checkout 0cff2b52982be5b1163aa9a62fb01f03ce91e0d2
git clone https://github.com/Mateces/mortal-sanma.git C:\Java\mortal-sanma
git -C C:\Java\mortal-sanma checkout bf69bc320d6072bbeae2abfdc57bf876a5bab2e3
uv sync --python 3.11
cargo build --manifest-path C:\Java\Mortal\libriichi\Cargo.toml --release --lib
cargo build --manifest-path C:\Java\mortal-sanma\libriichi\Cargo.toml --release --lib
New-Item -ItemType Directory -Force build\libriichi4, build\libriichi3
Copy-Item C:\Java\Mortal\target\release\riichi.dll build\libriichi4\libriichi.pyd
Copy-Item C:\Java\mortal-sanma\target\release\libriichi.dll build\libriichi3\libriichi.pyd
uv run mchjong-mortal-adapter --mortal-checkout C:\Java\Mortal --model-4p C:\models\mortal4.pth --libriichi-4p-path build\libriichi4 --sanma-checkout C:\Java\mortal-sanma --model-3p C:\models\mortal3-v5.pth --libriichi-3p-path build\libriichi3
```

The default listener is `127.0.0.1:8791`; `--host` and `--port` override it.
Omit the three sanma flags to run only official four-player Mortal. Run one
Uvicorn worker so all sessions share each loaded model. The Mateces backend
requires a version 5 checkpoint with 780 observation channels. Older
three-player checkpoints with 775 channels do not match the pinned source.

The three-player protocol layer handles native three-seat mjai, north
extraction, and the historical four-slot `libriichi3p` representation used by
[Akagi-MjaiBot-Mortal's `3p` branch](https://github.com/shinkuan/Akagi-MjaiBot-Mortal/tree/3p).
The active Mateces backend uses three native slots, so it does not add a fourth
slot to its requests. Its 44 action indices differ from the historical Akagi
indices; the active Mateces mapping stays internal to this service.

## HTTP contract

`GET /v1/health` returns `{"status":"ready","bots":2}` when both backends
have loaded (`bots` is 1 in four-player-only mode). `GET /v1/bots` lists IDs
and supported player counts.
`POST /v1/decisions` accepts one server-authorized decision. An example:

```json
{
  "table_id": "00000000-0000-0000-0000-000000000001",
  "session_id": "00000000-0000-0000-0000-000000000011",
  "hand_number": 0,
  "seat": 0,
  "player_count": 4,
  "decision": 12,
  "opening": {
    "round": 0,
    "dealer": 0,
    "honba": 0,
    "riichi_sticks": 0,
    "scores": [25000, 25000, 25000, 25000],
    "hand": [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48],
    "dora_marker": 108
  },
  "events": [{"kind": "DRAW", "seat": 0, "tile": 52}],
  "legal_actions": [
    {"id": "discard-1m", "type": "DISCARD", "tiles": [0]},
    {"id": "discard-5p", "type": "DISCARD", "tiles": [52]}
  ],
  "drawn_tile": 52,
  "focus": null,
  "melds": []
}
```

The response is
`{"table_id":"...","session_id":"...","hand_number":0,"seat":0,"decision":12,"action_index":0,"action_id":"discard-1m"}`
for the first action. `action_id` is `null` when the request did not supply
one. MChjong remains responsible for authorizing the table and seat, issuing
the legal list and decision token, and applying the returned index only if that
decision is still current.

Tile IDs use MChjong's physical convention: `kind * 4 + copy`, with bit `256`
on a red five. `opening.hand` contains only the acting seat's 13 tiles. The
adapter hides the other hands in mjai. `round` is the zero-based hand number
across winds. `events` is the complete chronological list since that opening;
on each request the service verifies the previous prefix and feeds only new
events to the seat's bot. The final new event must offer the current decision.
`session_id` is a fresh UUID for each table runtime. Use a higher `hand_number` and a
new opening for each hand. The service replaces the old bot state for that
table and seat when either value advances, keeping only the current hand.

Event kinds are `DRAW`, `DISCARD`, `RIICHI_ACCEPTED`, `DORA`, `CHI`, `PON`,
`OPEN_KAN`, `CLOSED_KAN`, `ADDED_KAN` and `NUKI`. A draw supplies `seat` and
`tile`; a hidden opponent draw uses `tile: null`. A discard supplies `seat`,
`tile`, `tsumogiri` and `riichi`. Calls supply `seat`, `from_seat`,
`called_tile` and `tiles` consumed from the caller's hand. A closed kan supplies
all four tiles; an added kan supplies the added `tile` plus the original three
pon `tiles`; a north extraction supplies its `tile`. `DORA` supplies `tile`
only. A reaction request supplies `focus` with the claiming source seat and
tile. `melds` lists the acting seat's existing pon tiles when an added kan is
legal. `drawn_tile` disambiguates an ordinary discard from tsumogiri.

The adapter resolves Mortal's `reach` followed by `dahai` into one `RIICHI`
choice, matches call source and consumed tiles, handles kan selection and sanma
north extraction, and keeps compressed Q-value indexing inside the service.
No mjai event or Q-value is returned to MChjong. Identical physical copies
with the same visible face choose the first server-issued matching index.

An unavailable backend returns `503`; a stale decision or changed hand history
returns `409`; an unknown or illegal Mortal action returns `422`. A failed
session is dropped so a later request can rebuild it from the full history.
Repeated identical requests for the last decision return the cached answer.

## Verify

```powershell
uv run pytest -q
```

The tests cover one-time model loading, normal decisions, reach/discard,
chi/kan selection, sanma north extraction, Q-value indices, isolated sessions
and illegal-action rejection. Live inference additionally needs compatible
external checkpoints. The local v4 three-player checkpoint with 775 input
channels is incompatible with the pinned Mateces version 5 backend.

This repository is licensed under AGPL-3.0-or-later. Both upstream projects
remain independent checkouts under their own AGPL-3.0 licenses.

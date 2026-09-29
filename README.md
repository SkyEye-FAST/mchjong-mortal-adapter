# MChjong Mortal Adapter

A persistent local HTTP service for MChjong Riichi bot decisions. Four-player
inference loads `Brain`, `DQN`, `MortalEngine` and `libriichi.mjai.Bot` from
[Equim-chan/Mortal](https://github.com/Equim-chan/Mortal). Three-player inference
loads the external [Akagi-MjaiBot-Mortal](https://github.com/shinkuan/Akagi-MjaiBot-Mortal)
`release3p` model code, checkpoint and `libriichi3p` extension. The adapter owns
the MChjong API, mjai translation and independent table sessions; model code,
extensions and weights remain outside the repository. The
[Mateces/mortal-sanma](https://github.com/Mateces/mortal-sanma) repository is a
source and protocol reference for sanma.

## Verified runtime inputs

| Players | Inference code and extension | Checkpoint | Format |
| --- | --- | --- | --- |
| 4 | Official Mortal [`0cff2b52982be5b1163aa9a62fb01f03ce91e0d2`](https://github.com/Equim-chan/Mortal/commit/0cff2b52982be5b1163aa9a62fb01f03ce91e0d2), compiled `libriichi` | Akagi [`v0.1.0/release4p.zip`](https://github.com/shinkuan/Akagi-MjaiBot-Mortal/releases/download/v0.1.0/release4p.zip), SHA-256 `757d3cceca9212e7f88e7614157bd404dd8dee682d3007428f66e02d2f6ff670` | PyTorch `mortal.pth`, version 4, 1012 observation channels, 46 actions |
| 3 | Akagi [`v0.1.0/release3p.zip`](https://github.com/shinkuan/Akagi-MjaiBot-Mortal/releases/download/v0.1.0/release3p.zip), SHA-256 `6890345121062f2d21c3c8e688f7c641a9e92ec2ca79122be8f9cd62ebdbcf3d`; includes `model.py` and `libriichi3p` | `mortal.pth` in the same release asset | PyTorch checkpoint, version 4, 775 observation channels, 44 actions |

The Akagi hashes identify the tested release assets, whose bundled files are
the runtime inputs. The three-player backend uses the bundle's `model.py` and
its platform-specific `libriichi3p` binary. Its four-slot mjai shape is handled
at the adapter boundary. The two extensions have distinct Python module names;
both stay loaded in the same process without replacing `sys.modules` entries.

## Run locally

Use Python 3.11, uv and a Rust toolchain for the official four-player extension.
The following PowerShell commands keep checkouts, archives and extracted runtime
files in local paths outside the Git index:

```powershell
git clone https://github.com/Equim-chan/Mortal.git C:\Java\Mortal
git -C C:\Java\Mortal checkout 0cff2b52982be5b1163aa9a62fb01f03ce91e0d2
cargo build --manifest-path C:\Java\Mortal\libriichi\Cargo.toml --release --lib
New-Item -ItemType Directory -Force build\libriichi4
Copy-Item C:\Java\Mortal\target\release\riichi.dll build\libriichi4\libriichi.pyd
Invoke-WebRequest https://github.com/shinkuan/Akagi-MjaiBot-Mortal/releases/download/v0.1.0/release4p.zip -OutFile build\release4p.zip
Invoke-WebRequest https://github.com/shinkuan/Akagi-MjaiBot-Mortal/releases/download/v0.1.0/release3p.zip -OutFile build\release3p.zip
Get-FileHash build\release4p.zip, build\release3p.zip -Algorithm SHA256
Expand-Archive build\release4p.zip build\akagi4
Expand-Archive build\release3p.zip build\akagi3
uv sync --python 3.11
uv run mchjong-mortal-adapter --mortal-checkout C:\Java\Mortal --model-4p build\akagi4\mortal.pth --libriichi-4p-path build\libriichi4 --sanma-runtime build\akagi3
```

Compare both archive hashes with the table before extraction. The service
listens on `127.0.0.1:8791` by default; `--host` and `--port` override it.
Omit `--sanma-runtime` to serve four-player games only. Run one Uvicorn worker
so each model loads once and all seat sessions share it. On other platforms,
build the official `libriichi` extension for that Python interpreter and place
it under `--libriichi-4p-path`; the Akagi bundle selects its matching
`libriichi3p` binary from its `libriichi/` directory.

## HTTP contract

`GET /v1/health` returns
`{"protocol_version":1,"status":"ready","bots":2}` when both backends
have loaded (`bots` is 1 in four-player-only mode). `GET /v1/bots` returns
`protocol_version: 1` and Bot entries with stable `id`, display `name`,
`player_count`, and exact `presets`. The four-player model advertises
`mortal-4p` / `TENHOU_4`; the three-player model advertises
`mortal-3p` / `TENHOU_3`. `POST /v1/decisions` accepts one server-authorized
decision:

```json
{
  "protocol_version": 1,
  "bot_id": "mortal-4p",
  "preset": "TENHOU_4",
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
    {"type": "DISCARD", "tiles": [0]},
    {"type": "DISCARD", "tiles": [52]}
  ],
  "drawn_tile": 52,
  "focus": null,
  "melds": []
}
```

The response echoes `protocol_version`, `bot_id`, `table_id`, `session_id`, `hand_number`, `seat` and
`decision`, and returns `action_index` into the issued `legal_actions`. MChjong
authorizes the table and seat, supplies the legal list, and applies the index
only while the decision token remains current. Its current Bot Service client
consumes this response directly.

Tile IDs use MChjong's physical convention: `kind * 4 + copy`, with bit `256`
on a red five. `opening.hand` contains the acting seat's 13 tiles. The adapter
hides the other hands in mjai. `round` is the zero-based hand number across
winds. `events` is the complete chronological list since the opening; each
request verifies the previous prefix and feeds only new events to its bot. The
final new event must offer the current decision. `session_id` identifies one
table runtime; session state is keyed by `(table_id, session_id, seat, bot_id)`. Each
session serializes its own requests while other sessions can infer concurrently.
Idle session state is removed after 30 minutes when the service receives a request.
Advance `hand_number` and send a new opening for each hand.

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
choice, matches call source and consumed tiles, and handles kan selection and
sanma north extraction. Identical physical copies with the same visible face
choose the first server-issued matching index. An unavailable backend returns
`503`; an incompatible protocol version returns `400`; an unsupported preset
or illegal Mortal action returns `422`. A failed session is dropped so a later
request can rebuild it from the full history. Repeated identical requests for
the last decision return the cached answer.

## Verify

GitHub Actions uses Python 3.11, `uv sync --locked`, `uv run pytest -q` and
`uv build`. The fast suite uses test doubles. Run the
explicit real-model smoke after installing the inputs above:

```powershell
uv run python smoke\real_models.py --mortal-checkout C:\Java\Mortal --model-4p build\akagi4\mortal.pth --libriichi-4p-path build\libriichi4 --sanma-runtime build\akagi3
```

The smoke loads both checkpoints and native extensions in one process, calls
`start_game` and `start_kyoku` through `/v1/decisions`, checks the returned
legal index for both player counts, then exercises four-player inference again
after three-player inference. It is separate from the default pytest suite.

This repository is licensed under AGPL-3.0-or-later. Upstream projects remain
independent checkouts and release assets under their respective licenses.

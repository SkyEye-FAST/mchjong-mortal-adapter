"""Load external Mortal code and share each model across seat-local bots."""

import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Protocol

from . import UPSTREAM_REVISION
from .sanma_protocol import from_libriichi3p, to_libriichi3p


class BotBackend(Protocol):
    name: str

    def new_bot(self, seat: int) -> object: ...
    def react(self, bot: object, event: dict, can_act: bool) -> dict | None: ...
    def resolve_reach(self, bot: object, response: dict, seat: int) -> tuple[dict, bool]: ...


def _import_path(path: Path) -> None:
    if not path.is_dir():
        raise ValueError(f"module directory does not exist: {path}")
    sys.path.insert(0, str(path))


def _revision(checkout: Path, expected: str, name: str) -> Path:
    checkout = checkout.resolve(strict=True)
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if revision != expected:
        raise ValueError(f"unsupported {name} revision {revision}; expected {expected}")
    return checkout


def _source_module(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"source module is missing: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FourPlayerBackend:
    name = "mortal-4p"

    def __init__(self, checkout: Path, model_path: Path, libriichi_path: Path):
        checkout = _revision(checkout, UPSTREAM_REVISION, "official Mortal")
        libriichi_path = libriichi_path.resolve(strict=True)
        _import_path(libriichi_path)
        import torch

        extension = importlib.import_module("libriichi")
        if not Path(extension.__file__).resolve().is_relative_to(libriichi_path):
            raise ValueError("libriichi was loaded from a different runtime")
        consts = importlib.import_module("libriichi.consts")
        if consts.ACTION_SPACE != 46:
            raise ValueError(f"official Mortal action space must be 46, got {consts.ACTION_SPACE}")
        Bot = importlib.import_module("libriichi.mjai").Bot
        model = _source_module("_mchjong_mortal4_model", checkout / "mortal" / "model.py")
        engine_module = _source_module("_mchjong_mortal4_engine", checkout / "mortal" / "engine.py")

        torch.set_num_threads(1)
        state = torch.load(model_path.resolve(strict=True), weights_only=True, map_location="cpu")
        config = state["config"]
        version = config["control"]["version"]
        if version != 4:
            raise ValueError(f"official Mortal model version must be 4, got {version}")
        brain = model.Brain(version=version, **config["resnet"]).eval()
        dqn = model.DQN(version=version).eval()
        brain.load_state_dict(state["mortal"])
        dqn.load_state_dict(state["current_dqn"])
        self.engine = engine_module.MortalEngine(
            brain, dqn, is_oracle=False, version=version,
            enable_rule_based_agari_guard=True,
        )
        self.Bot = Bot
        self.version = version

    def new_bot(self, seat: int) -> object:
        return self.Bot(self.engine, seat)

    def react(self, bot: object, event: dict, can_act: bool) -> dict | None:
        result = bot.react(json.dumps(event, separators=(",", ":")), can_act=can_act)
        return json.loads(result) if result is not None else None

    def resolve_reach(self, bot: object, response: dict, seat: int) -> tuple[dict, bool]:
        result = self.react(bot, {"type": "reach", "actor": seat}, True)
        if result is None:
            raise ValueError("Mortal did not choose a reach discard")
        return result, True


class ThreePlayerBackend:
    """Akagi release3p model with its distinctly named libriichi3p extension."""

    name = "mortal-3p"

    def __init__(self, runtime: Path):
        runtime = runtime.resolve(strict=True)
        _import_path(runtime)
        import torch

        torch.set_num_threads(1)
        model = _source_module("_mchjong_akagi3_model", runtime / "model.py")
        extension = importlib.import_module("libriichi3p")
        if not Path(extension.__file__).resolve().is_relative_to(runtime):
            raise ValueError("libriichi3p was loaded from a different runtime")
        consts = importlib.import_module("libriichi3p.consts")
        if consts.ACTION_SPACE != 44 or consts.obs_shape(4) != (775, 34):
            raise ValueError("Akagi sanma runtime must use 44 actions and 775 observation channels")
        state = torch.load(runtime / "mortal.pth", weights_only=True, map_location="cpu")
        version = state["config"]["control"]["version"]
        if version != 4:
            raise ValueError(f"Akagi sanma model version must be 4, got {version}")
        brain = model.Brain(version=version, **state["config"]["resnet"]).eval()
        dqn = model.DQN(version=version).eval()
        brain.load_state_dict(state["mortal"])
        dqn.load_state_dict(state["current_dqn"])
        model.ot_settings["online"] = False
        self.engine = model.MortalEngine(
            brain, dqn, is_oracle=False, version=version,
            enable_rule_based_agari_guard=True, name="mortal3p",
        )
        self.Bot = model.Bot
        self.version = version

    def new_bot(self, seat: int) -> object:
        return self.Bot(self.engine, seat)

    def react(self, bot: object, event: dict, can_act: bool) -> dict | None:
        result = bot.react(json.dumps(to_libriichi3p(event), separators=(",", ":")),
                           can_act=can_act)
        return from_libriichi3p(json.loads(result)) if result is not None else None

    def resolve_reach(self, bot: object, response: dict, seat: int) -> tuple[dict, bool]:
        result = self.react(bot, {"type": "reach", "actor": seat}, True)
        if result is None:
            raise ValueError("sanma Mortal did not choose a reach discard")
        return result, True

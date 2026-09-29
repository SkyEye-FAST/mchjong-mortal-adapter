"""Start one local process with one model instance per configured backend."""

import argparse
from pathlib import Path

import uvicorn

from .api import create_app
from .backends import FourPlayerBackend, ThreePlayerBackend
from .service import DecisionService


def main() -> None:
    parser = argparse.ArgumentParser(description="MChjong Mortal local inference service")
    parser.add_argument("--mortal-checkout", required=True, type=Path)
    parser.add_argument("--model-4p", required=True, type=Path)
    parser.add_argument("--libriichi-4p-path", required=True, type=Path)
    parser.add_argument("--sanma-checkout", type=Path)
    parser.add_argument("--model-3p", type=Path)
    parser.add_argument("--libriichi-3p-path", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()

    backends = {4: FourPlayerBackend(args.mortal_checkout, args.model_4p, args.libriichi_4p_path)}
    sanma_args = (args.sanma_checkout, args.model_3p, args.libriichi_3p_path)
    if any(sanma_args) and not all(sanma_args):
        parser.error("--sanma-checkout, --model-3p and --libriichi-3p-path must be provided together")
    if all(sanma_args):
        backends[3] = ThreePlayerBackend(*sanma_args)
    uvicorn.run(create_app(DecisionService(backends)), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()

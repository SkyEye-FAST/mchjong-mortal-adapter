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
    parser.add_argument("--sanma-runtime", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()

    four = FourPlayerBackend(args.mortal_checkout, args.model_4p, args.libriichi_4p_path)
    backends = {four.name: (4, four)}
    if args.sanma_runtime:
        three = ThreePlayerBackend(args.sanma_runtime)
        backends[three.name] = (3, three)
    uvicorn.run(create_app(DecisionService(backends)), host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()

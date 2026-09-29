"""Small loopback HTTP API for MChjong's server-owned decisions."""

from fastapi import FastAPI, HTTPException

from .contracts import PROTOCOL_VERSION, DecisionRequest, DecisionResponse
from .service import DecisionError, DecisionService


def create_app(service: DecisionService) -> FastAPI:
    app = FastAPI(title="MChjong Mortal Adapter", version="0.1.0")

    @app.get("/v1/health")
    def health() -> dict:
        return {"protocol_version": PROTOCOL_VERSION, "status": "ready", "bots": len(service.backends)}

    @app.get("/v1/bots")
    def bots() -> dict:
        return {"protocol_version": PROTOCOL_VERSION, "bots": [
            {"id": backend.name, "name": backend.name.replace("-", " ").title(),
             "player_count": count, "presets": ["TENHOU_3" if count == 3 else "TENHOU_4"]}
            for count, backend in sorted(service.backends.items())]}

    @app.post("/v1/decisions", response_model=DecisionResponse)
    def decide(request: DecisionRequest) -> DecisionResponse:
        try:
            return service.decide(request)
        except DecisionError as error:
            raise HTTPException(error.status, error.detail) from error

    return app

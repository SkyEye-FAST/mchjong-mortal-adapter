"""Small loopback HTTP API for MChjong's server-owned decisions."""

from fastapi import FastAPI, HTTPException

from .contracts import DecisionRequest, DecisionResponse
from .service import DecisionError, DecisionService


def create_app(service: DecisionService) -> FastAPI:
    app = FastAPI(title="MChjong Mortal Adapter", version="0.1.0")

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ready", "bots": len(service.backends)}

    @app.get("/v1/bots")
    def bots() -> dict:
        return {"bots": [{"id": backend.name, "player_count": count}
                         for count, backend in sorted(service.backends.items())]}

    @app.post("/v1/decisions", response_model=DecisionResponse)
    def decide(request: DecisionRequest) -> DecisionResponse:
        try:
            return service.decide(request)
        except DecisionError as error:
            raise HTTPException(error.status, error.detail) from error

    return app

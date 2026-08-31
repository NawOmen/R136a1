from fastapi import FastAPI

from .schemas import (
    AllocationRequest,
    CoalitionRequest,
    CoalitionResponse,
    OptimizationResponse,
    OpportunityScoreIn,
    OpportunityScoreOut,
)
from .solver import calculate_opportunity_score, evaluate_coalition, optimize_allocations

app = FastAPI(title="Matching and Resilience Optimizer", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ok", "solver": "or-tools-cp-sat"}


@app.post("/api/v1/optimize/allocations", response_model=OptimizationResponse)
async def allocations(data: AllocationRequest):
    return optimize_allocations(data)


@app.post("/api/v1/optimize/coalition", response_model=CoalitionResponse)
async def coalition(data: CoalitionRequest):
    return evaluate_coalition(data)


@app.post("/api/v1/score/opportunity", response_model=OpportunityScoreOut)
async def opportunity_score(data: OpportunityScoreIn):
    return calculate_opportunity_score(data)

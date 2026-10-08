from fastapi import Depends, FastAPI
from .security import require_service_token

from .schemas import (
    AllocationRequest,
    CoalitionRequest,
    CoalitionResponse,
    OptimizationResponse,
    OpportunityScoreIn,
    OpportunityScoreOut,
    ResilienceRequest,
    ResilienceResponse,
)
from .solver import (
    calculate_opportunity_score,
    calculate_resilience,
    evaluate_coalition,
    optimize_allocations,
)

app = FastAPI(title="Matching and Resilience Optimizer", version="1.0.0")


@app.get("/health")
async def health():
    return {"status": "ok", "solver": "or-tools-cp-sat"}


@app.post("/api/v1/optimize/allocations", response_model=OptimizationResponse, dependencies=[Depends(require_service_token)])
def allocations(data: AllocationRequest):
    return optimize_allocations(data)


@app.post("/api/v1/optimize/coalition", response_model=CoalitionResponse, dependencies=[Depends(require_service_token)])
def coalition(data: CoalitionRequest):
    return evaluate_coalition(data)


@app.post("/api/v1/score/opportunity", response_model=OpportunityScoreOut, dependencies=[Depends(require_service_token)])
def opportunity_score(data: OpportunityScoreIn):
    return calculate_opportunity_score(data)


@app.post("/api/v1/optimize/resilience", response_model=ResilienceResponse, dependencies=[Depends(require_service_token)])
def resilience(data: ResilienceRequest):
    return calculate_resilience(data)

from .money import MoneyWireMiddleware
app.add_middleware(MoneyWireMiddleware, exact_prefix='/api/v2')
app.post('/api/v2/optimize/allocations', response_model=OptimizationResponse, dependencies=[Depends(require_service_token)])(allocations)
app.post('/api/v2/optimize/coalition', response_model=CoalitionResponse, dependencies=[Depends(require_service_token)])(coalition)
app.post('/api/v2/optimize/resilience', response_model=ResilienceResponse, dependencies=[Depends(require_service_token)])(resilience)

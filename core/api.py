"""FastAPI control API and operator UI for the AI control layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .logging_utils import setup_logging
from .metrics import render_metrics
from .orchestrator import Orchestrator
from .schemas import ActionResult, AgentRunRecord, AgentRunRequest, BotStatus, BotSummary, HealthResponse


settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings)
    yield


app = FastAPI(
    title="Crypto System Control API",
    version="0.1.0",
    description="Control layer and operator UI for crypto-system.",
    lifespan=lifespan,
)
app.state.orchestrator = Orchestrator(settings=settings)


def get_orchestrator() -> Orchestrator:
    return app.state.orchestrator


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def operator_ui(request: Request):
    return templates.TemplateResponse(
        request,
        "operator.html",
        {
            "request": request,
            "title": "Panel operatorski AI",
        },
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(**get_orchestrator().health())


@app.get("/bots", response_model=list[BotSummary])
async def list_bots() -> list[BotSummary]:
    return [BotSummary(**bot) for bot in get_orchestrator().list_bots()]


@app.post("/bots/{bot_id}/start", response_model=ActionResult)
async def start_bot(bot_id: str) -> ActionResult:
    try:
        status = get_orchestrator().start_bot(bot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ActionResult(
        bot_id=bot_id,
        accepted=True,
        message=f"Bot '{bot_id}' started with state '{status['state']}'.",
    )


@app.post("/bots/{bot_id}/stop", response_model=ActionResult)
async def stop_bot(bot_id: str) -> ActionResult:
    try:
        status = get_orchestrator().stop_bot(bot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ActionResult(
        bot_id=bot_id,
        accepted=True,
        message=f"Bot '{bot_id}' stopped with state '{status['state']}'.",
    )


@app.get("/bots/{bot_id}/status", response_model=BotStatus)
async def bot_status(bot_id: str) -> BotStatus:
    try:
        return BotStatus(**get_orchestrator().get_bot_status(bot_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/bots/{bot_id}/logs")
async def bot_logs(
    bot_id: str,
    tail: int = Query(default=200, ge=1, le=1000),
) -> JSONResponse:
    try:
        logs = get_orchestrator().get_bot_logs(bot_id, tail=tail)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"bot_id": bot_id, "logs": logs})


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    payload, content_type = render_metrics(get_orchestrator().list_bots())
    return PlainTextResponse(payload.decode("utf-8"), media_type=content_type)


@app.get("/ops/agents", include_in_schema=False)
async def ops_agents() -> JSONResponse:
    return JSONResponse(get_orchestrator().list_agents())


@app.get("/ops/runs", include_in_schema=False)
async def ops_runs(limit: int = Query(default=50, ge=1, le=200)) -> JSONResponse:
    return JSONResponse(get_orchestrator().list_runs(limit=limit))


@app.get("/ops/runs/{run_id}", response_model=AgentRunRecord, include_in_schema=False)
async def ops_run(run_id: str) -> AgentRunRecord:
    try:
        return AgentRunRecord(**get_orchestrator().get_run(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/ops/runs", response_model=AgentRunRecord, include_in_schema=False)
async def ops_create_run(request: AgentRunRequest) -> AgentRunRecord:
    record = get_orchestrator().create_agent_run(request.model_dump())
    return AgentRunRecord(**record)


@app.post("/ops/runs/{run_id}/approve", response_model=AgentRunRecord, include_in_schema=False)
async def ops_approve_run(run_id: str) -> AgentRunRecord:
    try:
        record = get_orchestrator().approve_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AgentRunRecord(**record)


@app.post("/ops/runs/{run_id}/stop", response_model=AgentRunRecord, include_in_schema=False)
async def ops_stop_run(run_id: str) -> AgentRunRecord:
    try:
        record = get_orchestrator().stop_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AgentRunRecord(**record)


@app.get("/ops/logs/ai-control", include_in_schema=False)
async def ops_control_logs(
    tail: int = Query(default=200, ge=1, le=1000),
) -> JSONResponse:
    log_file = settings.log_file
    if not log_file.exists():
        return JSONResponse({"logs": []})
    lines = log_file.read_text(encoding="utf-8").splitlines()
    return JSONResponse({"logs": lines[-tail:]})

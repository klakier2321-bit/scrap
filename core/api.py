"""FastAPI control API and operator UI for the AI control layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from crewai.events.listeners.tracing.utils import mark_first_execution_done

from .config import get_settings
from .logging_utils import setup_logging
from .metrics import render_metrics
from .orchestrator import Orchestrator
from .schemas import (
    ActionResult,
    AutopilotStatusResponse,
    AgentRunRecord,
    AgentRunRequest,
    CandidateAssessmentResponse,
    CandidateDryRunResponse,
    ControlStatusResponse,
    RegimeStatusResponse,
    BotStatus,
    BotSummary,
    CodingReviewDecisionRequest,
    CodingStatusResponse,
    CodingTaskCreateRequest,
    CodingTaskRecord,
    CodingWorkspaceRecord,
    DryRunHealthResponse,
    DryRunSmokeResponse,
    DryRunSnapshotResponse,
    HealthResponse,
    StrategyReportResponse,
)
from .tracing import setup_tracing, suppress_crewai_trace_console


settings = get_settings()
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
request_logger = logging.getLogger("crypto_system.control_api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(settings)
    if os.getenv("CREWAI_TRACING_ENABLED", "").lower() != "true":
        # Prevent CrewAI's one-time interactive trace prompt inside the server runtime.
        mark_first_execution_done(user_consented=False)
        suppress_crewai_trace_console()
    setup_tracing(app, settings)
    if settings.agent_autopilot_enabled:
        get_orchestrator().start_autopilot()
    if settings.agent_coding_enabled and settings.agent_coding_auto_start:
        get_orchestrator().start_coding_supervisor()
    yield
    get_orchestrator().stop_autopilot()
    get_orchestrator().stop_coding_supervisor()


app = FastAPI(
    title="Crypto System Control API",
    version="0.1.0",
    description="Control layer and operator UI for crypto-system.",
    lifespan=lifespan,
)
app.state.orchestrator = Orchestrator(settings=settings)


def get_orchestrator() -> Orchestrator:
    return app.state.orchestrator


@app.middleware("http")
async def log_control_api_requests(request: Request, call_next):
    start = monotonic()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        if request.url.path == "/metrics":
            continue_logging = False
        else:
            continue_logging = True
        if not continue_logging:
            pass
        else:
            duration_ms = round((monotonic() - start) * 1000, 2)
            request_logger.info(
                "Control API request handled.",
                extra={
                    "run_id": request.path_params.get("run_id"),
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": getattr(response, "status_code", 500),
                    "duration_ms": duration_ms,
                    "event": "control_api_request",
                },
            )


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
    latest_dry_run_snapshot = get_orchestrator().get_latest_dry_run_snapshot(
        refresh_if_stale=True
    )
    payload, content_type = render_metrics(
        get_orchestrator().list_bots(),
        get_orchestrator().get_latest_strategy_report_with_assessment(),
        get_orchestrator().list_strategy_report_history(limit=20),
        get_orchestrator().get_dry_run_health(),
        latest_dry_run_snapshot,
        get_orchestrator().get_executive_report(),
    )
    return PlainTextResponse(payload.decode("utf-8"), media_type=content_type)


@app.get("/ops/agents", include_in_schema=False)
async def ops_agents() -> JSONResponse:
    return JSONResponse(get_orchestrator().list_agents())


@app.get("/ops/executive/report", include_in_schema=False)
async def ops_executive_report() -> JSONResponse:
    return JSONResponse(get_orchestrator().get_executive_report())


@app.get(
    "/ops/control-status/latest",
    response_model=ControlStatusResponse,
    include_in_schema=False,
)
async def ops_control_status_latest(refresh: bool = Query(default=False)) -> ControlStatusResponse:
    report = get_orchestrator().get_control_status(refresh_if_missing=refresh)
    if report is None:
        raise HTTPException(status_code=404, detail="Control status report is not available yet.")
    return ControlStatusResponse(**report)


@app.post(
    "/ops/control-status/generate",
    response_model=ControlStatusResponse,
    include_in_schema=False,
)
async def ops_control_status_generate() -> ControlStatusResponse:
    return ControlStatusResponse(**get_orchestrator().generate_control_status())


@app.get(
    "/ops/coding-status",
    response_model=CodingStatusResponse,
    include_in_schema=False,
)
async def ops_coding_status() -> CodingStatusResponse:
    return CodingStatusResponse(**get_orchestrator().coding_status())


@app.post(
    "/ops/coding-status/start",
    response_model=CodingStatusResponse,
    include_in_schema=False,
)
async def ops_coding_status_start() -> CodingStatusResponse:
    return CodingStatusResponse(**get_orchestrator().start_coding_supervisor())


@app.post(
    "/ops/coding-status/stop",
    response_model=CodingStatusResponse,
    include_in_schema=False,
)
async def ops_coding_status_stop() -> CodingStatusResponse:
    return CodingStatusResponse(**get_orchestrator().stop_coding_supervisor())


@app.get(
    "/ops/coding-tasks",
    response_model=list[CodingTaskRecord],
    include_in_schema=False,
)
async def ops_coding_tasks(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CodingTaskRecord]:
    return [CodingTaskRecord(**task) for task in get_orchestrator().list_coding_tasks(limit=limit)]


@app.post(
    "/ops/coding-tasks",
    response_model=CodingTaskRecord,
    include_in_schema=False,
)
async def ops_create_coding_task(request: CodingTaskCreateRequest) -> CodingTaskRecord:
    try:
        task = get_orchestrator().create_coding_task(
            module_id=request.module_id,
            goal_override=request.goal_override,
            business_reason=request.business_reason,
            target_files_override=request.target_files_override,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CodingTaskRecord(**task)


@app.get(
    "/ops/coding-tasks/{task_id}",
    response_model=CodingTaskRecord,
    include_in_schema=False,
)
async def ops_coding_task(task_id: str) -> CodingTaskRecord:
    try:
        return CodingTaskRecord(**get_orchestrator().get_coding_task(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/ops/coding-tasks/{task_id}/approve-review",
    response_model=CodingTaskRecord,
    include_in_schema=False,
)
async def ops_approve_coding_review(task_id: str) -> CodingTaskRecord:
    try:
        return CodingTaskRecord(**get_orchestrator().approve_coding_review(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/ops/coding-tasks/{task_id}/reject-review",
    response_model=CodingTaskRecord,
    include_in_schema=False,
)
async def ops_reject_coding_review(
    task_id: str,
    request: CodingReviewDecisionRequest,
) -> CodingTaskRecord:
    try:
        return CodingTaskRecord(
            **get_orchestrator().reject_coding_review(task_id, reason=request.reason)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/ops/workspaces",
    response_model=list[CodingWorkspaceRecord],
    include_in_schema=False,
)
async def ops_workspaces() -> list[CodingWorkspaceRecord]:
    return [CodingWorkspaceRecord(**workspace) for workspace in get_orchestrator().list_workspaces()]


@app.get(
    "/ops/workspaces/{task_id}/diff",
    response_model=CodingWorkspaceRecord,
    include_in_schema=False,
)
async def ops_workspace_diff(task_id: str) -> CodingWorkspaceRecord:
    try:
        return CodingWorkspaceRecord(**get_orchestrator().get_workspace_diff(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/ops/workspaces/{task_id}/reset",
    response_model=CodingTaskRecord,
    include_in_schema=False,
)
async def ops_workspace_reset(task_id: str) -> CodingTaskRecord:
    try:
        return CodingTaskRecord(**get_orchestrator().reset_workspace(task_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/ops/runs", include_in_schema=False)
async def ops_runs(limit: int = Query(default=50, ge=1, le=200)) -> JSONResponse:
    return JSONResponse(get_orchestrator().list_runs(limit=limit))


@app.get(
    "/ops/autopilot/status",
    response_model=AutopilotStatusResponse,
    include_in_schema=False,
)
async def ops_autopilot_status() -> AutopilotStatusResponse:
    return AutopilotStatusResponse(**get_orchestrator().autopilot_status())


@app.post(
    "/ops/autopilot/start",
    response_model=AutopilotStatusResponse,
    include_in_schema=False,
)
async def ops_autopilot_start() -> AutopilotStatusResponse:
    return AutopilotStatusResponse(**get_orchestrator().start_autopilot())


@app.post(
    "/ops/autopilot/stop",
    response_model=AutopilotStatusResponse,
    include_in_schema=False,
)
async def ops_autopilot_stop() -> AutopilotStatusResponse:
    return AutopilotStatusResponse(**get_orchestrator().stop_autopilot())


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


@app.get(
    "/ops/strategy-report/latest",
    response_model=StrategyReportResponse,
    include_in_schema=False,
)
async def ops_latest_strategy_report(
    strategy_name: str | None = Query(default=None),
) -> StrategyReportResponse:
    report = get_orchestrator().get_latest_strategy_report_with_assessment(
        strategy_name=strategy_name
    )
    if report is None:
        raise HTTPException(status_code=404, detail="No strategy report is available yet.")
    return StrategyReportResponse(**report)


@app.get("/ops/strategy-report/history", include_in_schema=False)
async def ops_strategy_report_history(
    strategy_name: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    history = get_orchestrator().list_strategy_report_history(
        strategy_name=strategy_name,
        limit=limit,
    )
    return JSONResponse({"reports": history})


@app.post(
    "/ops/strategy-report/generate",
    response_model=StrategyReportResponse,
    include_in_schema=False,
)
async def ops_generate_strategy_report(
    strategy_name: str | None = Query(default=None),
) -> StrategyReportResponse:
    try:
        get_orchestrator().generate_strategy_assessment(strategy_name=strategy_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    merged = get_orchestrator().get_latest_strategy_report_with_assessment(
        strategy_name=strategy_name
    )
    if merged is None:
        raise HTTPException(status_code=404, detail="No strategy report is available yet.")
    return StrategyReportResponse(**merged)


@app.get(
    "/ops/candidates",
    response_model=list[CandidateAssessmentResponse],
    include_in_schema=False,
)
async def ops_candidates() -> list[CandidateAssessmentResponse]:
    return [
        CandidateAssessmentResponse(**candidate)
        for candidate in get_orchestrator().list_candidate_assessments()
    ]


@app.get(
    "/ops/candidates/{candidate_id}/assessment",
    response_model=CandidateAssessmentResponse,
    include_in_schema=False,
)
async def ops_candidate_assessment(candidate_id: str) -> CandidateAssessmentResponse:
    try:
        return CandidateAssessmentResponse(**get_orchestrator().get_candidate_assessment(candidate_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/ops/candidates/{candidate_id}/dry-run",
    response_model=CandidateDryRunResponse,
    include_in_schema=False,
)
async def ops_candidate_dry_run(candidate_id: str) -> CandidateDryRunResponse:
    try:
        return CandidateDryRunResponse(**get_orchestrator().get_candidate_dry_run(candidate_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/ops/regime/latest",
    response_model=RegimeStatusResponse,
    include_in_schema=False,
)
async def ops_regime_latest(
    refresh: bool = Query(default=False),
) -> RegimeStatusResponse:
    report = (
        get_orchestrator().generate_regime_report()
        if refresh
        else get_orchestrator().get_latest_regime_report()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="No regime report is available yet.")
    return RegimeStatusResponse(**report)


@app.post(
    "/ops/regime/generate",
    response_model=RegimeStatusResponse,
    include_in_schema=False,
)
async def ops_regime_generate() -> RegimeStatusResponse:
    return RegimeStatusResponse(**get_orchestrator().generate_regime_report())


@app.get("/ops/regime/history", include_in_schema=False)
async def ops_regime_history(
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    return JSONResponse({"reports": get_orchestrator().list_regime_history(limit=limit)})


@app.get(
    "/ops/dry-run/health",
    response_model=DryRunHealthResponse,
    include_in_schema=False,
)
async def ops_dry_run_health(
    bot_id: str = Query(default="freqtrade"),
) -> DryRunHealthResponse:
    try:
        return DryRunHealthResponse(**get_orchestrator().get_dry_run_health(bot_id=bot_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/ops/dry-run/snapshot",
    response_model=DryRunSnapshotResponse,
    include_in_schema=False,
)
async def ops_dry_run_snapshot(
    bot_id: str = Query(default="freqtrade"),
) -> DryRunSnapshotResponse:
    try:
        return DryRunSnapshotResponse(**get_orchestrator().create_dry_run_snapshot(bot_id=bot_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/ops/dry-run/snapshot/latest",
    response_model=DryRunSnapshotResponse,
    include_in_schema=False,
)
async def ops_latest_dry_run_snapshot(
    bot_id: str = Query(default="freqtrade"),
) -> DryRunSnapshotResponse:
    snapshot = get_orchestrator().get_latest_dry_run_snapshot(bot_id=bot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No dry run snapshot is available yet.")
    return DryRunSnapshotResponse(**snapshot)


@app.get("/ops/dry-run/snapshot/history", include_in_schema=False)
async def ops_dry_run_snapshot_history(
    bot_id: str = Query(default="freqtrade"),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    return JSONResponse(
        {
            "snapshots": get_orchestrator().list_dry_run_snapshot_history(
                bot_id=bot_id,
                limit=limit,
            )
        }
    )


@app.post(
    "/ops/dry-run/smoke",
    response_model=DryRunSmokeResponse,
    include_in_schema=False,
)
async def ops_dry_run_smoke(
    bot_id: str = Query(default="freqtrade"),
) -> DryRunSmokeResponse:
    try:
        return DryRunSmokeResponse(**get_orchestrator().run_dry_run_smoke_test(bot_id=bot_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

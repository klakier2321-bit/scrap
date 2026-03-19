FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-ai-control.txt /app/requirements-ai-control.txt
COPY ai_agents/requirements.txt /app/ai_agents/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements-ai-control.txt

COPY core /app/core
COPY ai_agents /app/ai_agents
COPY docs /app/docs
COPY monitoring /app/monitoring
COPY AGENT_BOUNDARIES.md /app/AGENT_BOUNDARIES.md
COPY AGENT_BUILD_FLOW.md /app/AGENT_BUILD_FLOW.md
COPY AGENT_REVIEW_FLOW.md /app/AGENT_REVIEW_FLOW.md
COPY AGENT_SYSTEM_PLAN.md /app/AGENT_SYSTEM_PLAN.md
COPY AGENT_WORKFLOW.md /app/AGENT_WORKFLOW.md
COPY BOT_DECISION_FLOW.md /app/BOT_DECISION_FLOW.md
COPY PROJECT_RULES.md /app/PROJECT_RULES.md
COPY CONFIGURATION_POLICY.md /app/CONFIGURATION_POLICY.md
COPY RISK_RULES.md /app/RISK_RULES.md
COPY README.md /app/README.md

CMD ["uvicorn", "core.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

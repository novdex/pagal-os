"""Pydantic request models shared across route modules."""

from typing import Any

from pydantic import BaseModel


class CreateAgentRequest(BaseModel):
    """Request body for creating an agent."""

    description: str
    model: str | None = None


class RunAgentRequest(BaseModel):
    """Request body for running an agent."""

    task: str
    async_mode: bool = False


class SettingsUpdate(BaseModel):
    """Request body for updating settings."""

    openrouter_api_key: str | None = None
    default_model: str | None = None
    ollama_url: str | None = None


class RateAgentRequest(BaseModel):
    """Request body for rating a marketplace agent."""

    rating: int
    review: str = ""


class CloneAgentRequest(BaseModel):
    """Request body for cloning an agent."""

    new_name: str


class ForkAgentRequest(BaseModel):
    """Request body for forking an agent."""

    new_name: str
    changes: dict[str, Any] = {}


class RegisterWebhookRequest(BaseModel):
    """Request body for registering a webhook."""

    agent_name: str
    event_type: str = "http"
    config: dict[str, Any] = {}


class ImportAgentRequest(BaseModel):
    """Request body for importing a shared agent."""

    file_path: str


class RollbackRequest(BaseModel):
    """Request body for rolling back an agent version."""

    version: int


class StartHandRequest(BaseModel):
    """Request body for starting a scheduled hand."""

    agent: str
    schedule: str
    task: str


class CreateWorkflowRequest(BaseModel):
    """Request body for creating a workflow from description."""

    description: str


class RunWorkflowRequest(BaseModel):
    """Request body for running a workflow."""

    input_data: str = ""


class SetGoalRequest(BaseModel):
    """Request body for setting a goal."""

    agent_name: str
    goal: str


class StartDebugRequest(BaseModel):
    """Request body for starting a debug session."""

    agent_name: str
    task: str


class SetBreakpointRequest(BaseModel):
    """Request body for setting a breakpoint."""

    on: str


class ModifyContextRequest(BaseModel):
    """Request body for injecting a message into a debug session."""

    message: str


class CreateTeamRequest(BaseModel):
    """Request body for creating a team."""

    name: str
    agents: list[str]
    coordinator: str
    goal: str = ""


class RunTeamRequest(BaseModel):
    """Request body for running a team task."""

    task: str


class MCPConnectRequest(BaseModel):
    """Request body for connecting to an MCP server."""

    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


class A2ARegisterRequest(BaseModel):
    """Request body for registering a remote agent."""

    agent_name: str
    url: str


class A2ACallRequest(BaseModel):
    """Request body for calling a remote agent."""

    agent_name: str
    task: str


class UpdatePermissionsRequest(BaseModel):
    """Request body for updating agent permissions."""

    permissions: dict[str, Any] = {}


class CreateBatchRequest(BaseModel):
    """Request body for creating a batch job."""

    agent_name: str
    items: list[str]


class RunBatchRequest(BaseModel):
    """Request body for running a batch job."""

    parallel: bool = False
    workers: int = 3


class RestoreBackupRequest(BaseModel):
    """Request body for restoring a backup."""

    path: str


class SetRateLimitRequest(BaseModel):
    """Request body for setting rate limits."""

    per_minute: int = 30
    per_hour: int = 500


class MigrateImportRequest(BaseModel):
    """Request body for importing a migration package."""

    path: str

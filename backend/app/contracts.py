"""Strict command payloads; one transport rather than a route per use case."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(StrictModel):
    owner: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=32760)


class Input(StrictModel):
    owner: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=32760)
    bytes_base64: str = Field(max_length=90_000_000)


class CreateWorkspace(StrictModel):
    name: str = Field(default="New workspace", min_length=1, max_length=120)
    mode: Literal["synthetic", "game"] = "synthetic"
    game_id: Literal["eu5", "ck3"] = "eu5"
    target_platform: Literal["macos", "windows"] | None = None
    sources: list[Source] = Field(default_factory=list, max_length=1000)
    fixture_path: str | None = Field(default=None, min_length=1, max_length=32760)


class Scan(StrictModel):
    fixture_id: str | None = None
    inputs: list[Input] = Field(default_factory=list, max_length=50000)
    playset: list[str] = Field(default_factory=list, max_length=1000)
    baselines: dict | None = None
    profile_id: str | None = None


class DiscoverCK3(StrictModel):
    platform: Literal["macos", "windows"] | None = None
    steam_roots: list[str] | None = Field(default=None, max_length=100)
    user_data_path: str | None = Field(default=None, min_length=1, max_length=32760)
    installation_path: str | None = Field(default=None, min_length=1, max_length=32760)
    playset_id: str | None = Field(default=None, min_length=1, max_length=200)
    root_overrides: dict[str, str] = Field(default_factory=dict, max_length=1000)


class ImportCK3(StrictModel):
    discovery_id: str = Field(min_length=1, max_length=200)


class Stage(StrictModel):
    scan_id: str


class Decision(StrictModel):
    scan_id: str
    choice: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=4000)
    value: str | int | None = None
    obligation_id: str | None = None
    definition_id: str | None = None


class Validate(StrictModel):
    candidate_id: str


class Export(Validate):
    kind: Literal["experimental_bundle", "validated_managed_release"] = "experimental_bundle"


class Rollback(StrictModel):
    release_id: str | None = None
    preview: bool = True


class Investigate(Stage):
    mode: Literal["replay", "live"] = "replay"
    replay: list[dict] = Field(default_factory=list, max_length=100)


class AgentIndex(StrictModel):
    scan_id: str


class AgentCheck(StrictModel):
    context_id: str


class AgentPrepare(StrictModel):
    index_id: str
    issue_id: str
    combined_base64: str | None = Field(default=None, max_length=180000)


class AgentProposal(StrictModel):
    proposal_id: str


class Cancel(StrictModel):
    job_id: str


class Backup(StrictModel):
    pass


class RuntimeProbe(StrictModel):
    recipe: dict = Field(default_factory=dict)


class InvestigationBudgets(StrictModel):
    max_calls: int = Field(default=8, ge=1, le=32)
    max_tool_calls: int = Field(default=24, ge=0, le=256)
    max_source_bytes: int = Field(default=131072, ge=1024, le=1048576)
    max_tokens: int = Field(default=64000, ge=1024, le=262144)
    max_seconds: int = Field(default=120, ge=1, le=600)


class InferencePolicy(StrictModel):
    enabled: bool = False
    model: str = Field(default="", max_length=200)
    allowed_providers: list[str] = Field(default_factory=list, max_length=20)
    excluded_patterns: list[str] = Field(default_factory=list, max_length=100)
    budgets: InvestigationBudgets = Field(default_factory=InvestigationBudgets)
    tools_supported: bool = False
    source_policy_confirmed: bool = False
    provider_policy_confirmed: bool = False


PAYLOADS = {
    "agent_index": AgentIndex, "agent_prepare": AgentPrepare, "agent_check": AgentCheck,
    "agent_apply": AgentProposal, "agent_test": AgentProposal, "agent_undo": AgentProposal,
    "discover_ck3": DiscoverCK3, "import_ck3": ImportCK3,
    "create_workspace": CreateWorkspace, "scan": Scan, "stage": Stage,
    "decision": Decision, "validate": Validate, "export": Export,
    "rollback": Rollback, "investigate": Investigate, "cancel": Cancel,
    "backup": Backup, "runtime_probe": RuntimeProbe,
    "configure_inference": InferencePolicy,
}

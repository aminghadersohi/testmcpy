"""
API routes for the Test Execution Agent.
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    """Request to start an agent run."""

    prompt: str = Field(..., min_length=1, description="Natural language instruction")
    test_path: str | None = Field(None, description="Path to test file or directory")
    mcp_profile: str | None = Field(None, description="MCP service profile ID")
    mcp_url: str | None = Field(None, description="Direct MCP service URL")
    models: list[str] = Field(default_factory=list, description="Models to test")
    max_turns: int = Field(50, ge=1, le=200, description="Maximum agent turns")
    agent_model: str | None = Field(None, description="Model for the agent itself")
    llm_profile: str | None = Field(
        None, description="LLM profile ID to source the Claude auth token from"
    )


class AgentRunResponse(BaseModel):
    """Response from an agent run."""

    run_id: str
    status: str
    report: dict[str, Any] | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Storage for agent reports
# ---------------------------------------------------------------------------


def _resolve_cli_token(
    llm_profile_id: str | None,
    model: str | None = None,
) -> str | None:
    """Resolve the Claude auth token from an LLM profile's default provider.

    Returns a compatible Claude SDK credential when configured. An explicit
    missing or incompatible profile is a configuration error; a compatible
    profile without a token intentionally uses the host's ``claude`` login.
    """
    if not llm_profile_id:
        return None
    from testmcpy.llm_profiles import (
        LLMProfileConfigError,
        LLMProfileNotFoundError,
        get_llm_profile_config,
        load_llm_profile,
        resolve_llm_provider_selection,
    )
    from testmcpy.scrubber import register_secret
    from testmcpy.src.llm_integration import CLAUDE_SDK_PROVIDERS

    profile_config = get_llm_profile_config()
    if profile_config.load_error:
        raise LLMProfileConfigError(
            f"Invalid LLM profile configuration: {profile_config.load_error}"
        )
    profile = load_llm_profile(llm_profile_id)
    if not profile:
        raise LLMProfileNotFoundError(f"LLM profile '{llm_profile_id}' was not found")
    if not any(provider.provider in CLAUDE_SDK_PROVIDERS for provider in profile.providers):
        raise ValueError(f"LLM profile '{llm_profile_id}' has no Claude SDK provider")
    _, _, provider_config = resolve_llm_provider_selection(
        provider="claude-sdk",
        model=model,
        profile_id=llm_profile_id,
    )
    token = provider_config.get("api_key")
    if not isinstance(token, str):
        return None
    register_secret(token)
    return token


def _get_reports_dir() -> Path:
    """Get or create the agent reports directory."""
    reports_dir = Path.cwd() / "tests" / ".agent_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir


def _save_report(run_id: str, report: dict[str, Any]) -> Path:
    """Save an agent report to disk."""
    from testmcpy.scrubber import scrub_obj

    reports_dir = _get_reports_dir()
    report_file = reports_dir / f"{run_id}.json"
    report_file.write_text(json.dumps(scrub_obj(report), indent=2, default=str))
    return report_file


def _load_report(run_id: str) -> dict[str, Any] | None:
    """Load an agent report from disk."""
    from testmcpy.scrubber import scrub_obj

    reports_dir = _get_reports_dir()
    report_file = reports_dir / f"{run_id}.json"
    if report_file.exists():
        report = scrub_obj(json.loads(report_file.read_text()))
        return report if isinstance(report, dict) else None
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(request: AgentRunRequest):
    """Start an agent run and return the report.

    The agent processes the prompt synchronously and returns results.
    """
    from testmcpy.agent.orchestrator import TestExecutionAgent
    from testmcpy.scrubber import scrub_obj, scrub_text

    # Build effective prompt
    effective_prompt = request.prompt
    if request.test_path:
        effective_prompt += f"\n\nTest files are at: {request.test_path}"

    # Resolve MCP profile if not provided
    mcp_profile = request.mcp_profile
    if not mcp_profile and not request.mcp_url:
        try:
            from testmcpy.server.helpers.mcp_config import load_mcp_yaml

            mcp_config = load_mcp_yaml()
            mcp_profile = mcp_config.get("default")
        except (FileNotFoundError, KeyError):
            pass

    try:
        agent = TestExecutionAgent(
            mcp_profile=mcp_profile,
            mcp_url=request.mcp_url,
            models=request.models,
            max_turns=request.max_turns,
            agent_model=request.agent_model,
            cli_token=_resolve_cli_token(request.llm_profile, request.agent_model),
        )

        report = await agent.run(effective_prompt)
        report_dict = scrub_obj(report.to_dict())

        # Save report to disk
        _save_report(report.run_id, report_dict)

        return AgentRunResponse(
            run_id=report.run_id,
            status="completed",
            report=report_dict,
        )

    except ImportError as e:
        raise HTTPException(
            status_code=501,
            detail=scrub_text(str(e)),
        ) from e
    except (ConnectionError, TimeoutError, OSError) as e:
        return AgentRunResponse(
            run_id="",
            status="error",
            error=f"Connection error: {scrub_text(str(e))}",
        )
    except ValueError as e:
        from testmcpy.llm_profiles import LLMProfileNotFoundError

        if isinstance(e, LLMProfileNotFoundError):
            raise HTTPException(status_code=404, detail=scrub_text(str(e))) from e
        raise HTTPException(
            status_code=400,
            detail=f"Configuration error: {scrub_text(str(e))}",
        ) from e


@router.get("/report/{run_id}")
async def get_agent_report(run_id: str):
    """Get an agent run report by ID."""
    report = _load_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report not found: {run_id}")
    return report


@router.get("/reports")
async def list_agent_reports(limit: int = 20):
    """List recent agent run reports."""
    reports_dir = _get_reports_dir()
    report_files = sorted(reports_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

    reports = []
    for report_file in report_files[:limit]:
        try:
            data = json.loads(report_file.read_text())
            reports.append(
                {
                    "run_id": data.get("run_id", report_file.stem),
                    "started_at": data.get("started_at"),
                    "tests_run": data.get("tests_run", 0),
                    "tests_passed": data.get("tests_passed", 0),
                    "tests_failed": data.get("tests_failed", 0),
                    "total_cost_usd": data.get("total_cost_usd", 0.0),
                    "num_turns": data.get("num_turns", 0),
                }
            )
        except (json.JSONDecodeError, KeyError):
            continue

    return {"reports": reports, "total": len(reports)}


@router.get("/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(run_id: str):
    """Get an agent run status and report by run ID.

    Returns status (completed/not_found) and the report if available.
    """
    report = _load_report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Agent run not found: {run_id}")
    return AgentRunResponse(
        run_id=run_id,
        status="completed",
        report=report,
    )

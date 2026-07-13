"""
Authentication flow debugger with rich console output.

This module provides detailed logging and visualization for OAuth, JWT,
and other authentication flows to help debug authentication issues.
"""

import ipaddress
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.tree import Tree


class AuthDebugger:
    """Debug authentication flows with detailed logging."""

    def __init__(self, enabled: bool = False, recorder=None):
        """Initialize the auth debugger.

        Args:
            enabled: Whether debugging is enabled
            recorder: Optional AuthFlowRecorder instance for recording flows
        """
        self.enabled = enabled
        self.console = Console()
        self.steps: list[dict[str, Any]] = []
        self.start_time = time.time()
        self.recorder = recorder
        self._current_flow_name: str | None = None
        self._current_auth_type: Literal["oauth", "jwt", "bearer"] | None = None

    def start_flow_recording(
        self,
        flow_name: str,
        auth_type: Literal["oauth", "jwt", "bearer"],
        protocol_version: str | None = None,
    ) -> None:
        """Start recording an authentication flow.

        Args:
            flow_name: Name/description of the flow
            auth_type: Type of authentication
            protocol_version: Version of the auth protocol
        """
        self._current_flow_name = flow_name
        self._current_auth_type = auth_type
        if self.recorder:
            self.recorder.start_recording(
                flow_name=flow_name,
                auth_type=auth_type,
                protocol_version=protocol_version,
            )

    def log_step(
        self,
        step_name: str,
        data: dict[str, Any],
        success: bool = True,
        step_type: Literal[
            "request", "response", "validation", "extraction", "error"
        ] = "validation",
    ):
        """Log a step in the auth flow.

        Args:
            step_name: Name of the authentication step
            data: Data associated with the step
            success: Whether the step was successful
            step_type: Type of step (for recorder)
        """
        if not self.enabled:
            return

        timestamp = time.time() - self.start_time
        sanitized_data = self._sanitize_data(data)

        self.steps.append(
            {
                "step": step_name,
                "data": sanitized_data,
                "success": success,
                "timestamp": timestamp,
            }
        )

        # Record to recorder if available
        if self.recorder and self.recorder.current_recording:
            self.recorder.record_step(
                step_name=step_name,
                step_type=step_type,
                data=sanitized_data.copy(),
                success=success,
            )

        # Pretty print the step
        color = "green" if success else "red"
        icon = "✓" if success else "✗"

        self.console.print(f"\n[{color}]{icon} {step_name}[/{color}]")

        self.console.print(
            Panel(
                Syntax(json.dumps(sanitized_data, indent=2), "json"),
                title=f"{step_name} Details",
                border_style=color,
            )
        )

    def _sanitize_data(self, data: Any) -> Any:
        """Sanitize sensitive data for display.

        Args:
            data: Data to sanitize recursively

        Returns:
            Sanitized data with the original container shape
        """
        if isinstance(data, list):
            return [self._sanitize_data(item) for item in data]
        if not isinstance(data, dict):
            return data

        sanitized = {}
        sensitive_keys = ["client_secret", "api_secret", "password"]
        sensitive_token_keys = {
            "access_token",
            "api_key",
            "api_token",
            "authorization",
            "id_token",
            "refresh_token",
            "secret",
            "token",
        }

        for key, value in data.items():
            key_lower = key.lower()
            key_normalized = key_lower.replace("-", "_")

            # Check if it's a sensitive key (but not token_length or token_preview)
            is_sensitive = any(sensitive in key_lower for sensitive in sensitive_keys)
            is_token = key_normalized in sensitive_token_keys | {
                "cookie",
                "proxy_authorization",
                "set_cookie",
                "x_api_key",
            }

            if is_sensitive or is_token:
                sanitized[key] = "[REDACTED]" if value is not None else None
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_data(value)
            elif isinstance(value, list):
                sanitized[key] = self._sanitize_data(value)
            elif key_lower in {"raw_response", "response_body"} and isinstance(value, str):
                sanitized[key] = self._sanitize_serialized_payload(value)
            else:
                sanitized[key] = value

        return sanitized

    def _sanitize_serialized_payload(self, value: str) -> str:
        """Redact credential fields inside JSON response strings."""
        prefix, separator, body = value.rpartition("\n\n")
        prefix = re.sub(
            r"(?im)^(set-cookie|cookie|authorization|proxy-authorization):[^\r\n]*",
            r"\1: [REDACTED]",
            prefix,
        )
        candidate = body if separator else value
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            if separator:
                return f"{prefix}{separator}[REDACTED NON-JSON RESPONSE BODY]"
            return "[REDACTED NON-JSON RESPONSE BODY]"
        redacted = json.dumps(self._sanitize_data(parsed))
        return f"{prefix}{separator}{redacted}" if separator else redacted

    def log_oauth_flow(self, flow_type: str, steps: dict[str, dict[str, Any]]):
        """Log complete OAuth flow with tree visualization.

        Args:
            flow_type: Type of OAuth flow (e.g., "Client Credentials")
            steps: Dictionary of steps and their data
        """
        if not self.enabled:
            return

        tree = Tree(f"[cyan]OAuth {flow_type} Flow[/cyan]")

        for step_name, step_data in steps.items():
            branch = tree.add(f"[green]{step_name}[/green]")
            sanitized_data = self._sanitize_data(step_data)
            for key, value in sanitized_data.items():
                branch.add(f"{key}: {value}")

        self.console.print(tree)

    def summarize(self) -> dict[str, Any]:
        """Print summary of all auth steps and return summary data.

        Returns:
            Summary dictionary with flow statistics
        """
        if not self.enabled or not self.steps:
            return {}

        total_time = time.time() - self.start_time
        success_count = sum(1 for step in self.steps if step["success"])
        failure_count = len(self.steps) - success_count

        self.console.print("\n[cyan]Authentication Flow Summary[/cyan]")
        for i, step in enumerate(self.steps, 1):
            icon = "✓" if step["success"] else "✗"
            color = "green" if step["success"] else "red"
            self.console.print(f"  [{color}]{i}. {icon} {step['step']}[/{color}]")

        self.console.print(f"\n[dim]Total time: {total_time:.2f}s[/dim]")

        if failure_count == 0:
            self.console.print("\n[bold green]Authentication successful![/bold green]")
        else:
            self.console.print(
                f"\n[bold red]Authentication failed ({failure_count} error(s))[/bold red]"
            )

        return {
            "total_steps": len(self.steps),
            "successful_steps": success_count,
            "failed_steps": failure_count,
            "total_time": total_time,
            "steps": self.steps,
        }

    def get_trace(self) -> dict[str, Any]:
        """Get the complete debug trace.

        Returns:
            Dictionary containing all debug information
        """
        return {
            "enabled": self.enabled,
            "steps": self.steps,
            "total_time": time.time() - self.start_time if self.steps else 0,
        }

    def clear(self) -> None:
        """Clear all logged steps.

        Useful for resetting the debugger state between different authentication
        attempts or test runs.

        Example:
            ```python
            debugger = AuthDebugger(enabled=True)
            # ... log some steps ...
            debugger.summarize()
            debugger.clear()  # Reset for next authentication flow
            ```
        """
        self.steps = []
        self.start_time = time.time()

    def get_steps(self) -> list[dict[str, Any]]:
        """Get all logged steps.

        Returns:
            List of step dictionaries, each containing 'step', 'data', 'success', and 'timestamp' keys.

        Example:
            ```python
            debugger = AuthDebugger(enabled=True)
            # ... log some steps ...
            steps = debugger.get_steps()
            assert len(steps) == 4
            assert steps[0]['success'] is True
            ```
        """
        return self.steps.copy()

    def has_failures(self) -> bool:
        """Check if any logged step failed.

        Returns:
            True if any step has success=False, False otherwise.

        Example:
            ```python
            debugger = AuthDebugger(enabled=True)
            debugger.log_step("Token Fetch", {"error": "timeout"}, success=False)
            assert debugger.has_failures() is True
            ```
        """
        return any(not step["success"] for step in self.steps)

    def get_failure_steps(self) -> list[dict[str, Any]]:
        """Get all steps that failed.

        Returns:
            List of step dictionaries where success=False.

        Example:
            ```python
            debugger = AuthDebugger(enabled=True)
            # ... log some steps ...
            failures = debugger.get_failure_steps()
            for failure in failures:
                print(f"Failed: {failure['step']}")
            ```
        """
        return [step for step in self.steps if not step["success"]]

    def export_trace(self, filepath: str) -> None:
        """Export the complete debug trace to a JSON file.

        Args:
            filepath: Path to the output JSON file

        Example:
            ```python
            debugger = AuthDebugger(enabled=True)
            # ... log some steps ...
            debugger.export_trace("auth-trace.json")
            ```
        """
        import json
        from pathlib import Path

        trace = self.get_trace()
        Path(filepath).write_text(json.dumps(trace, indent=2))

        if self.enabled:
            self.console.print(f"\n[dim]Debug trace saved to: {filepath}[/dim]")

    def save_flow_recording(
        self, success: bool = True, error: str | None = None, filename: str | None = None
    ) -> Path | None:
        """Save the current flow recording.

        Args:
            success: Whether the overall flow was successful
            error: Error message if flow failed
            filename: Optional custom filename

        Returns:
            Path to the saved recording file, or None if no recorder is active

        Example:
            ```python
            debugger = AuthDebugger(enabled=True, recorder=recorder)
            debugger.start_flow_recording("OAuth Login", "oauth")
            # ... log some steps ...
            filepath = debugger.save_flow_recording(success=True)
            ```
        """
        if not self.recorder or not self.recorder.current_recording:
            return None

        recording = self.recorder.stop_recording(success=success, error=error, auto_save=False)
        filepath = self.recorder.save_recording(recording, filename=filename)

        if self.enabled:
            self.console.print(f"\n[green]Flow recording saved to: {filepath}[/green]")

        return filepath


async def discover_oauth_endpoints(
    mcp_url: str,
    debugger: AuthDebugger | None = None,
    insecure: bool = False,
) -> dict[str, Any]:
    """Discover MCP OAuth metadata using RFC 9728 and RFC 8414.

    Args:
        mcp_url: The MCP service URL to discover OAuth config from
        debugger: Optional AuthDebugger instance
        insecure: Skip SSL certificate verification

    Returns:
        Dictionary with OAuth server metadata including token_endpoint, etc.

    Raises:
        Exception: If discovery fails
    """
    if debugger is None:
        debugger = AuthDebugger(enabled=False)

    _validate_oauth_endpoint(mcp_url, "MCP URL")
    parsed = urlparse(mcp_url)

    # RFC 8707 resource indicators do not contain fragments. Preserve the
    # path because MCP authorization servers commonly distinguish /mcp from
    # other protected resources on the same host.
    resource_url = urlunparse(parsed._replace(fragment=""))
    base_url = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))

    debugger.log_step(
        "1. OAuth Discovery Started",
        {
            "mcp_url": mcp_url,
            "resource": resource_url,
            "base_url": base_url,
        },
        step_type="request",
    )

    try:
        async with httpx.AsyncClient(verify=not insecure, follow_redirects=True) as client:
            probe_headers = {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-06-18",
                "User-Agent": "testmcpy/1.0",
            }
            probe_body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "testmcpy-auth-debugger", "version": "1.0"},
                },
            }
            debugger.log_step(
                "2. Probing Protected MCP Resource",
                {
                    "url": resource_url,
                    "method": "POST",
                    "headers": probe_headers,
                    "raw_request": (
                        f"POST {resource_url} HTTP/1.1\n"
                        "Accept: application/json, text/event-stream\n"
                        "Content-Type: application/json\n\n"
                        f"{json.dumps(probe_body)}"
                    ),
                },
                step_type="request",
            )
            probe_response = await client.post(
                resource_url,
                headers=probe_headers,
                json=probe_body,
                timeout=10.0,
            )
            www_authenticate = probe_response.headers.get("www-authenticate", "")
            resource_metadata_hint = _extract_www_auth_parameter(
                www_authenticate, "resource_metadata"
            )
            challenge_scope = _extract_www_auth_parameter(www_authenticate, "scope")
            debugger.log_step(
                "3. Protected Resource Challenge Received",
                {
                    "status_code": probe_response.status_code,
                    "www_authenticate": www_authenticate or None,
                    "resource_metadata": resource_metadata_hint,
                    "scope": challenge_scope,
                },
                success=True,
                step_type="response",
            )

            protected_metadata = None
            protected_metadata_url = None
            for candidate in _protected_resource_metadata_urls(
                resource_url, resource_metadata_hint
            ):
                _validate_oauth_endpoint(candidate, "protected resource metadata URL")
                debugger.log_step(
                    "4. Fetching Protected Resource Metadata",
                    {"url": candidate, "method": "GET"},
                    step_type="request",
                )
                response = await client.get(
                    candidate,
                    headers={
                        "Accept": "application/json",
                        "MCP-Protocol-Version": "2025-06-18",
                        "User-Agent": "testmcpy/1.0",
                    },
                    timeout=10.0,
                )
                if response.status_code != 200:
                    debugger.log_step(
                        "4. Protected Resource Metadata Candidate Unavailable",
                        {"url": candidate, "status_code": response.status_code},
                        success=True,
                        step_type="response",
                    )
                    continue
                try:
                    candidate_metadata = response.json()
                except json.JSONDecodeError:
                    debugger.log_step(
                        "4. Protected Resource Metadata Candidate Invalid",
                        {"url": candidate, "error": "Response is not valid JSON"},
                        success=True,
                        step_type="validation",
                    )
                    continue
                configured_resource = candidate_metadata.get("resource")
                if not configured_resource:
                    debugger.log_step(
                        "4. Protected Resource Metadata Missing Resource",
                        {"url": candidate, "error": "Required resource field is missing"},
                        success=True,
                        step_type="validation",
                    )
                    continue
                if not _resource_matches(resource_url, configured_resource):
                    debugger.log_step(
                        "4. Protected Resource Metadata Resource Mismatch",
                        {
                            "url": candidate,
                            "expected_resource": resource_url,
                            "metadata_resource": configured_resource,
                        },
                        success=True,
                        step_type="validation",
                    )
                    continue
                protected_metadata = candidate_metadata
                protected_metadata_url = candidate
                debugger.log_step(
                    "5. Protected Resource Metadata Parsed",
                    {
                        "metadata_url": candidate,
                        "resource": configured_resource,
                        "authorization_servers": candidate_metadata.get(
                            "authorization_servers", []
                        ),
                        "scopes_supported": candidate_metadata.get("scopes_supported", []),
                        "bearer_methods_supported": candidate_metadata.get(
                            "bearer_methods_supported", []
                        ),
                    },
                    step_type="extraction",
                )
                break

            authorization_servers = (
                protected_metadata.get("authorization_servers", []) if protected_metadata else []
            )
            authorization_server = authorization_servers[0] if authorization_servers else None
            metadata_urls = _authorization_server_metadata_urls(authorization_server, resource_url)
            metadata = None
            metadata_url = None
            request_headers = {
                "Accept": "application/json",
                "MCP-Protocol-Version": "2025-06-18",
                "User-Agent": "testmcpy/1.0",
            }
            for candidate in metadata_urls:
                _validate_oauth_endpoint(candidate, "authorization metadata URL")
                debugger.log_step(
                    "6. Fetching OAuth Server Metadata",
                    {
                        "url": candidate,
                        "method": "GET",
                        "headers": request_headers,
                        "raw_request": (
                            f"GET {candidate} HTTP/1.1\nAccept: application/json\n"
                            "MCP-Protocol-Version: 2025-06-18\nUser-Agent: testmcpy/1.0"
                        ),
                    },
                    step_type="request",
                )
                response = await client.get(candidate, headers=request_headers, timeout=10.0)
                if response.status_code != 200:
                    debugger.log_step(
                        "6. OAuth Metadata Candidate Unavailable",
                        {"url": candidate, "status_code": response.status_code},
                        success=True,
                        step_type="response",
                    )
                    continue
                try:
                    candidate_metadata = response.json()
                except json.JSONDecodeError:
                    continue
                if (
                    authorization_server
                    and candidate_metadata.get("issuer") != authorization_server
                ):
                    debugger.log_step(
                        "6. OAuth Metadata Issuer Mismatch",
                        {
                            "url": candidate,
                            "expected_issuer": authorization_server,
                            "metadata_issuer": candidate_metadata.get("issuer"),
                        },
                        success=True,
                        step_type="validation",
                    )
                    continue
                metadata = candidate_metadata
                metadata_url = candidate
                break

            if metadata is None:
                attempted = ", ".join(metadata_urls)
                raise Exception(f"OAuth discovery failed; no valid metadata at: {attempted}")

            metadata["protected_resource_metadata"] = protected_metadata
            metadata["protected_resource_metadata_url"] = protected_metadata_url
            metadata["www_authenticate"] = {
                "value": www_authenticate or None,
                "resource_metadata": resource_metadata_hint,
                "scope": challenge_scope,
            }
            metadata["resource"] = resource_url

            debugger.log_step(
                "7. OAuth Metadata Parsed",
                {
                    "metadata_url": metadata_url,
                    "issuer": metadata.get("issuer"),
                    "token_endpoint": metadata.get("token_endpoint"),
                    "authorization_endpoint": metadata.get("authorization_endpoint"),
                    "registration_endpoint": metadata.get("registration_endpoint"),
                    "scopes_supported": metadata.get("scopes_supported", []),
                    "grant_types_supported": metadata.get("grant_types_supported", []),
                    "response_types_supported": metadata.get("response_types_supported", []),
                },
                success=True,
                step_type="extraction",
            )

            return metadata

    except httpx.HTTPError as e:
        error_data = {
            "error": str(e),
            "error_type": type(e).__name__,
        }
        if hasattr(e, "response") and e.response is not None:
            error_data["status_code"] = e.response.status_code
            error_data["response_body"] = e.response.text[:500]

        debugger.log_step("ERROR: Discovery HTTP Request Failed", error_data, success=False)
        raise Exception(f"OAuth discovery failed: {e}")
    except json.JSONDecodeError as e:
        debugger.log_step(
            "ERROR: Invalid JSON in Discovery Response",
            {"error": str(e)},
            success=False,
        )
        raise Exception(f"OAuth discovery returned invalid JSON: {e}")
    except Exception as e:
        if "OAuth discovery failed" in str(e):
            raise
        debugger.log_step(
            "ERROR: Unexpected Discovery Error",
            {"error": str(e), "error_type": type(e).__name__},
            success=False,
        )
        raise


def _extract_www_auth_parameter(header: str, field_name: str) -> str | None:
    """Extract a quoted or token value from a WWW-Authenticate challenge."""
    if not header:
        return None
    pattern = rf'{re.escape(field_name)}=(?:"([^"\\]*(?:\\.[^"\\]*)*)"|([^\s,]+))'
    match = re.search(pattern, header, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return re.sub(r"\\(.)", r"\1", value) if match.group(1) is not None else value


def _protected_resource_metadata_urls(resource_url: str, challenge_url: str | None) -> list[str]:
    """Build the RFC 9728/MCP protected-resource discovery fallback chain."""
    parsed = urlparse(resource_url)
    base_url = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    candidates = []
    if challenge_url:
        candidates.append(challenge_url)
    if parsed.path and parsed.path != "/":
        candidates.append(urljoin(base_url, f"/.well-known/oauth-protected-resource{parsed.path}"))
    candidates.append(urljoin(base_url, "/.well-known/oauth-protected-resource"))
    return list(dict.fromkeys(candidates))


def _authorization_server_metadata_urls(
    authorization_server: str | None, resource_url: str
) -> list[str]:
    """Build RFC 8414 and OIDC discovery candidates in protocol order."""
    if authorization_server is None:
        parsed = urlparse(resource_url)
        base_url = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        return [
            f"{base_url}/.well-known/oauth-authorization-server",
            f"{base_url}/.well-known/openid-configuration",
        ]

    target = authorization_server or resource_url
    parsed = urlparse(target)
    base_url = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    path = parsed.path.rstrip("/")
    if path:
        candidates = [
            f"{base_url}/.well-known/oauth-authorization-server{path}",
            f"{base_url}/.well-known/openid-configuration{path}",
            f"{base_url}{path}/.well-known/openid-configuration",
        ]
    else:
        candidates = [
            f"{base_url}/.well-known/oauth-authorization-server",
            f"{base_url}/.well-known/openid-configuration",
        ]
    return list(dict.fromkeys(candidates))


def _resource_matches(requested_resource: str, configured_resource: str) -> bool:
    """Apply MCP's hierarchical resource match while enforcing the same origin."""
    requested = urlparse(requested_resource)
    configured = urlparse(configured_resource)
    if (
        requested.scheme.lower(),
        requested.netloc.lower(),
    ) != (
        configured.scheme.lower(),
        configured.netloc.lower(),
    ):
        return False
    requested_path = requested.path.rstrip("/") + "/"
    configured_path = configured.path.rstrip("/") + "/"
    return requested_path.startswith(configured_path)


async def debug_oauth_auto_discover_flow(
    mcp_url: str,
    debugger: AuthDebugger | None = None,
    insecure: bool = False,
) -> dict[str, Any]:
    """Debug OAuth metadata discovery for an MCP protected resource.

    Args:
        mcp_url: The MCP service URL
        debugger: Optional AuthDebugger instance
        insecure: Skip SSL certificate verification

    Returns:
        Dictionary with discovered OAuth metadata

    Raises:
        Exception: If discovery fails
    """
    if debugger is None:
        debugger = AuthDebugger(enabled=False)

    # Discover OAuth endpoints
    metadata = await discover_oauth_endpoints(mcp_url, debugger, insecure)

    # Check for required endpoints
    if not metadata.get("token_endpoint"):
        debugger.log_step(
            "5. Missing Token Endpoint",
            {
                "error": "OAuth metadata does not include token_endpoint",
                "available_fields": list(metadata.keys()),
            },
            success=False,
            step_type="validation",
        )
        raise Exception("OAuth discovery succeeded but no token_endpoint found")

    # Check for registration endpoint (needed for dynamic client registration)
    if metadata.get("registration_endpoint"):
        debugger.log_step(
            "5. Dynamic Client Registration Available",
            {
                "registration_endpoint": metadata["registration_endpoint"],
                "note": "Server supports dynamic client registration (RFC 7591)",
            },
            success=True,
            step_type="validation",
        )
    else:
        debugger.log_step(
            "5. No Dynamic Client Registration",
            {
                "note": "Server does not support dynamic client registration",
                "action_required": "Manual client_id and client_secret required",
            },
            success=True,
            step_type="validation",
        )

    debugger.log_step(
        "6. OAuth Discovery Complete",
        {
            "token_endpoint": metadata.get("token_endpoint"),
            "authorization_endpoint": metadata.get("authorization_endpoint"),
            "scopes_supported": metadata.get("scopes_supported", []),
            "grant_types_supported": metadata.get("grant_types_supported", []),
        },
        success=True,
        step_type="validation",
    )

    return metadata


async def prepare_oauth_authorization_flow(
    mcp_url: str,
    redirect_uri: str,
    scopes: list[str] | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    debugger: AuthDebugger | None = None,
    insecure: bool = False,
) -> dict[str, Any]:
    """Discover, dynamically register, and prepare an authorization request.

    The returned dictionary contains server-side transaction material such as
    the PKCE verifier. Callers must not serialize it directly to a browser.
    """
    if debugger is None:
        debugger = AuthDebugger(enabled=False)

    metadata = await debug_oauth_auto_discover_flow(mcp_url, debugger, insecure)
    authorization_endpoint = metadata.get("authorization_endpoint")
    token_endpoint = metadata.get("token_endpoint")
    if not authorization_endpoint:
        raise Exception("OAuth metadata does not include authorization_endpoint")
    _validate_oauth_endpoint(authorization_endpoint, "authorization_endpoint")
    _validate_oauth_endpoint(token_endpoint, "token_endpoint")
    _validate_oauth_endpoint(redirect_uri, "redirect_uri")

    requested_scopes = _select_oauth_scopes(metadata, scopes)
    token_endpoint_auth_method = "none"
    if client_id:
        token_endpoint_auth_method = _select_token_endpoint_auth_method(
            metadata,
            has_client_secret=bool(client_secret),
        )
        client_information = {
            "client_id": client_id,
            "client_secret": client_secret,
            "token_endpoint_auth_method": token_endpoint_auth_method,
        }
        debugger.log_step(
            "8. Using Configured OAuth Client",
            {
                "client_id": client_id,
                "token_endpoint_auth_method": client_information["token_endpoint_auth_method"],
            },
            step_type="validation",
        )
    else:
        registration_endpoint = metadata.get("registration_endpoint")
        if not registration_endpoint:
            raise Exception(
                "OAuth server does not advertise dynamic client registration; provide a client_id"
            )
        _validate_oauth_endpoint(registration_endpoint, "registration_endpoint")
        registration_data: dict[str, Any] = {
            "client_name": "testmcpy Auth Debugger",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        if requested_scopes:
            registration_data["scope"] = " ".join(requested_scopes)
        debugger.log_step(
            "8. Dynamic Client Registration Request",
            {
                "url": registration_endpoint,
                "method": "POST",
                "body": registration_data,
            },
            step_type="request",
        )
        async with httpx.AsyncClient(verify=not insecure, follow_redirects=False) as http_client:
            response = await http_client.post(
                registration_endpoint,
                json=registration_data,
                headers={"Accept": "application/json"},
                timeout=15.0,
            )
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            response_data = {}
        safe_response = _redact_oauth_payload(response_data)
        debugger.log_step(
            "9. Dynamic Client Registration Response",
            {
                "status_code": response.status_code,
                "response_body": safe_response,
                "raw_response": (
                    f"HTTP/1.1 {response.status_code} {response.reason_phrase}\n"
                    "Content-Type: application/json\n\n"
                    f"{json.dumps(safe_response)}"
                ),
            },
            success=response.status_code in (200, 201),
            step_type="response",
        )
        if response.status_code not in (200, 201):
            raise Exception(f"Dynamic client registration failed with HTTP {response.status_code}")
        if not response_data.get("client_id"):
            raise Exception("Dynamic client registration returned no client_id")
        client_information = response_data

    token_endpoint_auth_method = client_information.get(
        "token_endpoint_auth_method", token_endpoint_auth_method
    )
    from testmcpy.src.oauth_flows import PKCEFlow

    pkce = PKCEFlow.generate_pkce_pair()
    state = secrets.token_urlsafe(32)
    resource = metadata.get("resource") or mcp_url
    authorization_params = {
        "response_type": "code",
        "client_id": client_information["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": pkce.code_challenge,
        "code_challenge_method": "S256",
        "resource": resource,
    }
    if requested_scopes:
        authorization_params["scope"] = " ".join(requested_scopes)
    separator = "&" if "?" in authorization_endpoint else "?"
    authorization_url = f"{authorization_endpoint}{separator}{urlencode(authorization_params)}"
    debugger.log_step(
        "10. Authorization Request Prepared",
        {
            "authorization_url": authorization_url,
            "redirect_uri": redirect_uri,
            "resource": resource,
            "scopes": requested_scopes,
            "state": state,
            "code_challenge": pkce.code_challenge,
            "code_challenge_method": "S256",
        },
        step_type="request",
    )

    return {
        "authorization_url": authorization_url,
        "state": state,
        "code_verifier": pkce.code_verifier,
        "redirect_uri": redirect_uri,
        "resource": resource,
        "mcp_url": mcp_url,
        "token_endpoint": token_endpoint,
        "client_id": client_information["client_id"],
        "client_secret": client_information.get("client_secret"),
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "scopes": requested_scopes,
        "insecure": insecure,
    }


async def complete_oauth_authorization_flow(
    preparation: dict[str, Any],
    authorization_code: str,
    debugger: AuthDebugger | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code and validate the token with the MCP server."""
    if debugger is None:
        debugger = AuthDebugger(enabled=False)

    token_data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": preparation["redirect_uri"],
        "client_id": preparation["client_id"],
        "code_verifier": preparation["code_verifier"],
        "resource": preparation["resource"],
    }
    auth = None
    auth_method = preparation.get("token_endpoint_auth_method") or "none"
    client_secret = preparation.get("client_secret")
    if auth_method == "client_secret_basic":
        if not client_secret:
            raise Exception("OAuth client requires client_secret_basic but has no client_secret")
        auth = httpx.BasicAuth(preparation["client_id"], client_secret)
    elif auth_method == "client_secret_post":
        if not client_secret:
            raise Exception("OAuth client requires client_secret_post but has no client_secret")
        token_data["client_secret"] = client_secret
    elif auth_method != "none":
        raise Exception(f"Unsupported token endpoint authentication method: {auth_method}")

    debugger.log_step(
        "11. Authorization Callback Validated",
        {
            "redirect_uri": preparation["redirect_uri"],
            "authorization_code": "[REDACTED]",
            "state_valid": True,
        },
        step_type="validation",
    )
    debugger.log_step(
        "12. Token Exchange Request",
        {
            "url": preparation["token_endpoint"],
            "method": "POST",
            "token_endpoint_auth_method": auth_method,
            "body": {
                **token_data,
                "code": "[REDACTED]",
                "code_verifier": "[REDACTED]",
                **({"client_secret": "[REDACTED]"} if "client_secret" in token_data else {}),
            },
        },
        step_type="request",
    )
    async with httpx.AsyncClient(
        verify=not preparation.get("insecure", False), follow_redirects=False
    ) as http_client:
        response = await http_client.post(
            preparation["token_endpoint"],
            data=token_data,
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=20.0,
        )
    try:
        response_data = response.json()
    except json.JSONDecodeError:
        response_data = {}
    debugger.log_step(
        "13. Token Exchange Response",
        {
            "status_code": response.status_code,
            "response_body": _redact_oauth_payload(response_data),
        },
        success=response.status_code == 200,
        step_type="response",
    )
    if response.status_code != 200:
        raise Exception(f"OAuth token exchange failed with HTTP {response.status_code}")
    access_token = response_data.get("access_token")
    if not access_token:
        raise Exception("OAuth token response does not include access_token")
    debugger.log_step(
        "14. Token Extracted",
        {
            "token_length": len(access_token),
            "token_type": response_data.get("token_type"),
            "expires_in": response_data.get("expires_in"),
            "scope": response_data.get("scope"),
            "refresh_token_received": bool(response_data.get("refresh_token")),
        },
        step_type="extraction",
    )
    await _validate_oauth_token_with_mcp(
        access_token,
        preparation["mcp_url"],
        debugger,
        insecure=preparation.get("insecure", False),
    )
    return response_data


def _validate_oauth_endpoint(url: str | None, field_name: str) -> None:
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise Exception(f"OAuth {field_name} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise Exception(f"OAuth {field_name} must not contain credentials or a fragment")
    if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname):
        raise Exception(f"OAuth {field_name} must use HTTPS unless it is a loopback URL")


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _select_oauth_scopes(metadata: dict[str, Any], requested_scopes: list[str] | None) -> list[str]:
    if requested_scopes:
        return [scope for scope in requested_scopes if scope]
    challenge_scope = (metadata.get("www_authenticate") or {}).get("scope")
    if challenge_scope:
        return challenge_scope.split()
    protected_metadata = metadata.get("protected_resource_metadata") or {}
    return list(
        protected_metadata.get("scopes_supported") or metadata.get("scopes_supported") or []
    )


def _select_token_endpoint_auth_method(
    metadata: dict[str, Any],
    *,
    has_client_secret: bool,
) -> str:
    if not has_client_secret:
        return "none"
    supported = metadata.get("token_endpoint_auth_methods_supported") or []
    if "client_secret_basic" in supported:
        return "client_secret_basic"
    if not supported:
        # RFC 8414 and OIDC discovery both default confidential clients to
        # HTTP Basic when this optional metadata field is omitted.
        return "client_secret_basic"
    if "client_secret_post" in supported:
        return "client_secret_post"
    raise Exception("OAuth server does not advertise a supported client-secret auth method")


def _redact_oauth_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: (
                "[REDACTED]"
                if key.lower() in {"access_token", "refresh_token", "id_token", "client_secret"}
                else _redact_oauth_payload(value)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_redact_oauth_payload(value) for value in payload]
    return payload


async def _validate_oauth_token_with_mcp(
    token: str,
    mcp_url: str,
    debugger: AuthDebugger,
    insecure: bool,
) -> None:
    initialize_body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "testmcpy-auth-debugger", "version": "1.0"},
        },
    }
    debugger.log_step(
        "15. Testing Token Against MCP Resource",
        {"url": mcp_url, "method": "POST", "authorization": "Bearer [REDACTED]"},
        step_type="request",
    )
    async with httpx.AsyncClient(verify=not insecure) as http_client:
        response = await http_client.post(
            mcp_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json=initialize_body,
            timeout=15.0,
        )
    debugger.log_step(
        "16. OAuth Flow Complete",
        {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "mcp_url": mcp_url,
        },
        success=response.status_code == 200,
        step_type="response",
    )
    if response.status_code != 200:
        raise Exception(f"MCP server rejected OAuth token with HTTP {response.status_code}")


async def debug_oauth_flow(
    client_id: str,
    client_secret: str,
    token_url: str,
    scopes: list[str] | None = None,
    debugger: AuthDebugger | None = None,
) -> str:
    """Debug OAuth client credentials flow.

    Args:
        client_id: OAuth client ID
        client_secret: OAuth client secret
        token_url: OAuth token endpoint URL
        scopes: Optional list of OAuth scopes
        debugger: Optional AuthDebugger instance

    Returns:
        OAuth access token

    Raises:
        Exception: If token fetch fails
    """
    if debugger is None:
        debugger = AuthDebugger(enabled=False)

    # Step 1: Prepare request
    request_data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": " ".join(scopes) if scopes else "",
    }

    # Build raw request for display
    request_body = f"grant_type=client_credentials&client_id={client_id}&client_secret=***&scope={' '.join(scopes) if scopes else ''}"
    raw_request = f"POST {token_url} HTTP/1.1\nContent-Type: application/x-www-form-urlencoded\n\n{request_body}"

    debugger.log_step(
        "1. OAuth Request Prepared",
        {
            **request_data,
            "raw_request": raw_request,
        },
        step_type="request",
    )

    try:
        async with httpx.AsyncClient() as client:
            # Step 2: Send request
            debugger.log_step(
                "2. Sending POST to Token Endpoint",
                {
                    "url": token_url,
                    "method": "POST",
                    "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                    "body": request_body,
                },
                step_type="request",
            )

            response = await client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": " ".join(scopes) if scopes else "",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )

            # Capture raw response
            raw_response = f"HTTP/1.1 {response.status_code} {response.reason_phrase}\n"
            for key, value in response.headers.items():
                raw_response += f"{key}: {value}\n"
            raw_response += f"\n{response.text[:2000]}"

            # Step 3: Response received
            debugger.log_step(
                "3. Response Received",
                {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "raw_response": raw_response,
                    "response_body": response.text[:2000],
                },
                step_type="response",
            )

            response.raise_for_status()
            data = response.json()

            # Step 4: Token extracted
            if "access_token" not in data:
                debugger.log_step(
                    "4. Token Extraction Failed",
                    {
                        "error": "No access_token found in response",
                        "response_keys": list(data.keys()),
                    },
                    success=False,
                )
                raise Exception("No access_token found in OAuth response")

            token = data["access_token"]
            debugger.log_step(
                "4. Token Extracted",
                {
                    "access_token": token,
                    "expires_in": data.get("expires_in", "unknown"),
                    "scope": data.get("scope", "unknown"),
                    "token_type": data.get("token_type", "unknown"),
                },
                success=True,
            )

            return token

    except httpx.HTTPError as e:
        error_data = {
            "error": str(e),
            "error_type": type(e).__name__,
        }
        if hasattr(e, "response"):
            error_data["status_code"] = e.response.status_code
            error_data["response_body"] = e.response.text[:500]  # Limit response size

        debugger.log_step("ERROR: HTTP Request Failed", error_data, success=False)
        raise
    except Exception as e:
        debugger.log_step(
            "ERROR: Unexpected Error",
            {"error": str(e), "error_type": type(e).__name__},
            success=False,
        )
        raise


async def debug_jwt_flow(
    api_url: str,
    api_token: str,
    api_secret: str,
    debugger: AuthDebugger | None = None,
    insecure: bool = False,
) -> str:
    """Debug JWT dynamic token fetch flow.

    Args:
        api_url: JWT API endpoint URL
        api_token: API token for authentication
        api_secret: API secret for authentication
        debugger: Optional AuthDebugger instance
        insecure: Skip SSL certificate verification

    Returns:
        JWT access token

    Raises:
        Exception: If token fetch fails
    """
    if debugger is None:
        debugger = AuthDebugger(enabled=False)

    # Step 1: Prepare request
    request_data = {
        "name": api_token,
        "secret": api_secret,
    }

    # Build raw request for display (mask secret)
    request_body_display = json.dumps({"name": api_token, "secret": "***"}, indent=2)
    raw_request = f"POST {api_url} HTTP/1.1\nContent-Type: application/json\nAccept: application/json\n\n{request_body_display}"

    debugger.log_step(
        "1. JWT Request Prepared",
        {
            **request_data,
            "raw_request": raw_request,
        },
        step_type="request",
    )

    try:
        async with httpx.AsyncClient(verify=not insecure) as client:
            # Step 2: Send request
            debugger.log_step(
                "2. Sending POST to JWT Endpoint",
                {
                    "url": api_url,
                    "method": "POST",
                    "headers": {"Content-Type": "application/json", "Accept": "application/json"},
                    "body": request_body_display,
                },
                step_type="request",
            )

            response = await client.post(
                api_url,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json=request_data,
                timeout=10.0,
            )

            # Capture raw response
            raw_response = f"HTTP/1.1 {response.status_code} {response.reason_phrase}\n"
            for key, value in response.headers.items():
                raw_response += f"{key}: {value}\n"
            raw_response += f"\n{response.text[:2000]}"

            # Step 3: Response received
            debugger.log_step(
                "3. Response Received",
                {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "raw_response": raw_response,
                    "response_body": response.text[:2000],
                },
                step_type="response",
            )

            response.raise_for_status()
            data = response.json()

            # Step 4: Token extracted
            # Supports both {"payload": {"access_token": "..."}} and {"access_token": "..."}
            token = None
            if "payload" in data and "access_token" in data["payload"]:
                token = data["payload"]["access_token"]
            elif "access_token" in data:
                token = data["access_token"]

            if not token:
                debugger.log_step(
                    "4. Token Extraction Failed",
                    {
                        "error": "No access_token found in response",
                        "response_keys": list(data.keys()),
                    },
                    success=False,
                )
                raise Exception("No access_token found in JWT response")

            debugger.log_step(
                "4. Token Extracted",
                {
                    "access_token": token,
                },
                success=True,
            )

            return token

    except httpx.HTTPError as e:
        error_data = {
            "error": str(e),
            "error_type": type(e).__name__,
        }
        if hasattr(e, "response"):
            error_data["status_code"] = e.response.status_code
            error_data["response_body"] = e.response.text[:500]  # Limit response size

        debugger.log_step("ERROR: HTTP Request Failed", error_data, success=False)
        raise
    except Exception as e:
        debugger.log_step(
            "ERROR: Unexpected Error",
            {"error": str(e), "error_type": type(e).__name__},
            success=False,
        )
        raise


async def debug_bearer_token(
    token: str, mcp_url: str | None = None, debugger: AuthDebugger | None = None
) -> str:
    """Debug bearer token authentication by testing against MCP endpoint.

    Args:
        token: Bearer token
        mcp_url: MCP endpoint URL to test against
        debugger: Optional AuthDebugger instance

    Returns:
        The bearer token

    Raises:
        Exception: If token validation fails
    """
    if debugger is None:
        debugger = AuthDebugger(enabled=False)

    debugger.log_step(
        "1. Bearer Token Provided",
        {
            "access_token": token,
        },
        success=True,
    )

    if not mcp_url:
        debugger.log_step(
            "2. No MCP URL provided",
            {
                "warning": "Cannot validate token without MCP URL",
            },
            success=True,
        )
        return token

    # Test the token against MCP endpoint
    try:
        debugger.log_step(
            "2. Testing token against MCP endpoint",
            {
                "mcp_url": mcp_url,
            },
            success=True,
        )

        async with httpx.AsyncClient() as client:
            # Send tools/list request to MCP
            response = await client.post(
                mcp_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                timeout=10.0,
            )

            debugger.log_step(
                "3. Response Received",
                {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                },
                success=response.status_code == 200,
            )

            if response.status_code == 401:
                debugger.log_step(
                    "4. Token Rejected",
                    {
                        "error": "Unauthorized - token is invalid or expired",
                        "response_body": response.text[:500],
                    },
                    success=False,
                )
                raise Exception("Bearer token rejected by MCP server (401 Unauthorized)")

            if response.status_code != 200:
                debugger.log_step(
                    "4. Request Failed",
                    {
                        "error": f"HTTP {response.status_code}",
                        "response_body": response.text[:500],
                    },
                    success=False,
                )
                raise Exception(f"MCP request failed with status {response.status_code}")

            # Parse response - handle both JSON and SSE formats
            content_type = response.headers.get("content-type", "")
            response_text = response.text

            if "text/event-stream" in content_type:
                # SSE format - parse the data lines
                tools_count = 0
                for line in response_text.split("\n"):
                    if line.startswith("data:"):
                        try:
                            import json

                            data = json.loads(line[5:].strip())
                            if "result" in data and "tools" in data["result"]:
                                tools_count = len(data["result"]["tools"])
                                break
                        except json.JSONDecodeError:
                            pass

                debugger.log_step(
                    "4. Token Validated Successfully",
                    {
                        "tools_available": tools_count,
                        "response_format": "SSE",
                        "response": response_text,
                    },
                    success=True,
                )
            else:
                # JSON format
                data = response.json()
                tools_count = len(data.get("result", {}).get("tools", []))

                debugger.log_step(
                    "4. Token Validated Successfully",
                    {
                        "tools_available": tools_count,
                        "response_format": "JSON",
                        "response": data,
                    },
                    success=True,
                )

            return token

    except httpx.HTTPError as e:
        debugger.log_step(
            "ERROR: HTTP Request Failed",
            {
                "error": str(e),
                "error_type": type(e).__name__,
            },
            success=False,
        )
        raise
    except Exception as e:
        if "Bearer token rejected" in str(e) or "MCP request failed" in str(e):
            raise
        debugger.log_step(
            "ERROR: Unexpected Error",
            {
                "error": str(e),
                "error_type": type(e).__name__,
            },
            success=False,
        )
        raise

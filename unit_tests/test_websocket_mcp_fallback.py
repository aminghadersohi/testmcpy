"""
Unit tests for the WebSocket's MCP-profile fallback that supplies the
AssistantProvider's workspace_hash / domain / JWT auth when the user's
`.llm_providers.yaml` doesn't declare an `assistant` entry.

The CLI takes these as flags (--workspace-hash, --domain, --jwt-*).
The WebSocket has no flag-equivalent — without this fallback, every UI
attempt to run a chatbot YAML against a workspace whose LLM profile is
just "Claude + OpenAI" (the default `.llm_providers.yaml` template)
crashes inside AssistantProvider.__init__.
"""

from testmcpy.server.websocket import _derive_workspace_and_domain_from_mcp_url


class TestDeriveWorkspaceAndDomain:
    """`workspace.domain.tld/path` → (workspace, domain.tld) decomposition."""

    def test_preset_staging_url(self):
        """Matches the URL shape the Preset MCP server uses in staging."""
        ws, dom = _derive_workspace_and_domain_from_mcp_url(
            "https://ae9f22f4.us1a.app-stg.preset.io/mcp"
        )
        assert ws == "ae9f22f4"
        assert dom == "us1a.app-stg.preset.io"

    def test_preset_prod_url(self):
        """Production hostnames look the same (workspace.<domain>.preset.io)."""
        ws, dom = _derive_workspace_and_domain_from_mcp_url(
            "https://deadbeef.us1a.app.preset.io/mcp"
        )
        assert ws == "deadbeef"
        assert dom == "us1a.app.preset.io"

    def test_url_with_port(self):
        """Ports must not bleed into the domain (urlparse strips them)."""
        ws, dom = _derive_workspace_and_domain_from_mcp_url("https://abc123.app.preset.io:8443/mcp")
        assert ws == "abc123"
        assert dom == "app.preset.io"

    def test_localhost_returns_none(self):
        """A bare host with no dot can't be split into workspace.domain —
        signal "no fallback" and let the caller emit a clear error."""
        ws, dom = _derive_workspace_and_domain_from_mcp_url("http://localhost:5008/mcp")
        assert ws is None
        assert dom is None

    def test_empty_url_returns_none(self):
        ws, dom = _derive_workspace_and_domain_from_mcp_url("")
        assert (ws, dom) == (None, None)

    def test_none_url_returns_none(self):
        ws, dom = _derive_workspace_and_domain_from_mcp_url(None)  # type: ignore[arg-type]
        assert (ws, dom) == (None, None)

    def test_malformed_url_returns_none(self):
        ws, dom = _derive_workspace_and_domain_from_mcp_url("not a url at all")
        assert (ws, dom) == (None, None)

    def test_url_without_path(self):
        """Trailing /mcp isn't required — workspace.domain.tld alone parses."""
        ws, dom = _derive_workspace_and_domain_from_mcp_url("https://foo.bar.example.com")
        assert ws == "foo"
        assert dom == "bar.example.com"

    def test_url_with_only_workspace_and_tld(self):
        """workspace.example.com still has one dot — derive both parts."""
        ws, dom = _derive_workspace_and_domain_from_mcp_url("https://workspace.example.com/mcp")
        assert ws == "workspace"
        assert dom == "example.com"

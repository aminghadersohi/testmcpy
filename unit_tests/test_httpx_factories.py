"""Regression tests for custom MCP HTTP client factories."""

import ssl
from unittest.mock import patch

import httpx

from testmcpy.src.mcp_client import create_insecure_httpx_factory, create_mtls_httpx_factory


def test_insecure_factory_accepts_fastmcp_and_future_client_options():
    factory = create_insecure_httpx_factory()
    timeout = httpx.Timeout(10)
    limits = httpx.Limits(max_connections=5)
    future_option = object()

    with patch("testmcpy.src.mcp_client.httpx.AsyncClient") as async_client:
        factory(
            headers={"X-Test": "value"},
            timeout=timeout,
            auth=None,
            follow_redirects=True,
            limits=limits,
            future_option=future_option,
        )

    async_client.assert_called_once_with(
        headers={"X-Test": "value"},
        timeout=timeout,
        auth=None,
        follow_redirects=True,
        limits=limits,
        future_option=future_option,
        verify=False,
    )


def test_insecure_factory_does_not_allow_verify_override():
    factory = create_insecure_httpx_factory()

    with patch("testmcpy.src.mcp_client.httpx.AsyncClient") as async_client:
        factory(verify=True)

    assert async_client.call_args.kwargs["verify"] is False


def test_mtls_factory_accepts_fastmcp_and_future_client_options(tmp_path):
    cert = tmp_path / "client.pem"
    cert.write_text("CERT")
    timeout = httpx.Timeout(10)
    limits = httpx.Limits(max_connections=5)
    future_option = object()

    with (
        patch("ssl.SSLContext.load_cert_chain"),
        patch("testmcpy.src.mcp_client.httpx.AsyncClient") as async_client,
    ):
        factory = create_mtls_httpx_factory(str(cert))
        factory(
            headers={"X-Test": "value"},
            timeout=timeout,
            auth=None,
            follow_redirects=True,
            limits=limits,
            future_option=future_option,
        )

    kwargs = async_client.call_args.kwargs
    assert kwargs["headers"] == {"X-Test": "value"}
    assert kwargs["timeout"] is timeout
    assert kwargs["auth"] is None
    assert kwargs["follow_redirects"] is True
    assert kwargs["limits"] is limits
    assert kwargs["future_option"] is future_option
    assert isinstance(kwargs["verify"], ssl.SSLContext)


def test_mtls_factory_does_not_allow_verify_override(tmp_path):
    cert = tmp_path / "client.pem"
    cert.write_text("CERT")

    with (
        patch("ssl.SSLContext.load_cert_chain"),
        patch("testmcpy.src.mcp_client.httpx.AsyncClient") as async_client,
    ):
        factory = create_mtls_httpx_factory(str(cert))
        factory(verify=False)

    assert isinstance(async_client.call_args.kwargs["verify"], ssl.SSLContext)

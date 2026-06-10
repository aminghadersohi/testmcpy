"""
testmcpy - MCP Testing Framework

A comprehensive testing framework for validating LLM tool calling
capabilities with MCP (Model Context Protocol) services.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("testmcpy")
except PackageNotFoundError:
    # Running from a bare checkout without an installed package — use an
    # obviously-not-a-release marker instead of a stale hardcoded version.
    __version__ = "0.0.0+unknown"

__author__ = "testmcpy Contributors"

"""
Unit tests for the optimize-docs API endpoint.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from testmcpy.server.api import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_llm_provider():
    """Mock LLM provider for testing."""
    mock_provider = AsyncMock()
    mock_provider.initialize = AsyncMock()
    mock_provider.close = AsyncMock()
    return mock_provider


@pytest.fixture
def sample_tool_request():
    """Sample tool documentation request."""
    return {
        "tool_name": "search_data",
        "description": "Searches for data in the system",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results"
                }
            },
            "required": ["query"]
        },
        "model": "claude-haiku-4-5",
        "provider": "anthropic"
    }


@pytest.fixture
def sample_llm_response():
    """Sample LLM analysis response."""
    return {
        "response": json.dumps({
            "clarity_score": 45,
            "issues": [
                {
                    "category": "clarity",
                    "severity": "high",
                    "issue": "Description is too vague",
                    "current": "Searches for data in the system",
                    "suggestion": "Specify what type of data and what system"
                }
            ],
            "improved_description": "Searches the internal database for records matching a text query.",
            "improvements": [
                {
                    "issue": "Vague system reference",
                    "before": "data in the system",
                    "after": "records in the internal database",
                    "explanation": "More specific about what and where"
                }
            ]
        }),
        "tool_calls": [],
        "token_usage": {"prompt": 100, "completion": 150, "total": 250},
        "cost": 0.0023,
        "duration": 3.45
    }


class TestOptimizeDocsEndpoint:
    """Tests for the optimize-docs endpoint."""

    @patch("testmcpy.server.api.create_llm_provider")
    def test_successful_analysis(
        self, mock_create_provider, client, mock_llm_provider, sample_tool_request, sample_llm_response
    ):
        """Test successful documentation analysis."""
        # Setup mocks
        mock_create_provider.return_value = mock_llm_provider
        mock_llm_provider.generate_with_tools.return_value = MagicMock(**sample_llm_response)

        # Make request
        response = client.post("/api/mcp/optimize-docs", json=sample_tool_request)

        # Assertions
        assert response.status_code == 200
        result = response.json()

        # Check analysis structure
        assert "analysis" in result
        assert result["analysis"]["score"] == 45
        assert result["analysis"]["clarity"] == "poor"
        assert len(result["analysis"]["issues"]) == 1

        # Check suggestions
        assert "suggestions" in result
        assert "improved_description" in result["suggestions"]
        assert len(result["suggestions"]["improvements"]) == 1

        # Check original data is preserved
        assert result["original"]["tool_name"] == "search_data"

        # Check metadata
        assert result["cost"] == 0.0023
        assert result["duration"] == 3.45

    @patch("testmcpy.server.api.create_llm_provider")
    def test_json_parsing_with_code_blocks(
        self, mock_create_provider, client, mock_llm_provider, sample_tool_request
    ):
        """Test that JSON extraction works with markdown code blocks."""
        # Setup mocks with JSON in code block
        response_with_codeblock = {
            "response": """Here's my analysis:

```json
{
  "clarity_score": 60,
  "issues": [],
  "improved_description": "Better description here",
  "improvements": []
}
```

That's my suggestion.""",
            "tool_calls": [],
            "token_usage": {"total": 100},
            "cost": 0.001,
            "duration": 2.0
        }

        mock_create_provider.return_value = mock_llm_provider
        mock_llm_provider.generate_with_tools.return_value = MagicMock(**response_with_codeblock)

        # Make request
        response = client.post("/api/mcp/optimize-docs", json=sample_tool_request)

        # Should successfully parse JSON from code block
        assert response.status_code == 200
        result = response.json()
        assert result["analysis"]["score"] == 60

    @patch("testmcpy.server.api.create_llm_provider")
    def test_fallback_on_invalid_json(
        self, mock_create_provider, client, mock_llm_provider, sample_tool_request
    ):
        """Test fallback behavior when LLM returns invalid JSON."""
        # Setup mocks with invalid JSON
        invalid_response = {
            "response": "This is not valid JSON at all",
            "tool_calls": [],
            "token_usage": {"total": 100},
            "cost": 0.001,
            "duration": 2.0
        }

        mock_create_provider.return_value = mock_llm_provider
        mock_llm_provider.generate_with_tools.return_value = MagicMock(**invalid_response)

        # Make request
        response = client.post("/api/mcp/optimize-docs", json=sample_tool_request)

        # Should still return 200 with fallback data
        assert response.status_code == 200
        result = response.json()

        # Should have default fallback values
        assert result["analysis"]["score"] == 50
        assert len(result["analysis"]["issues"]) >= 1
        assert result["suggestions"]["improved_description"] == sample_tool_request["description"]

    def test_missing_model_config(self, client):
        """Test error when model/provider not configured."""
        request_data = {
            "tool_name": "test_tool",
            "description": "Test description",
            "input_schema": {"type": "object"}
            # No model or provider
        }

        with patch("testmcpy.server.api.config") as mock_config:
            mock_config.default_model = None
            mock_config.default_provider = None

            response = client.post("/api/mcp/optimize-docs", json=request_data)

            assert response.status_code == 400
            assert "Model and provider must be configured" in response.json()["detail"]

    @patch("testmcpy.server.api.create_llm_provider")
    def test_uses_haiku_for_cost_efficiency(
        self, mock_create_provider, client, mock_llm_provider, sample_tool_request
    ):
        """Test that endpoint uses Haiku when Anthropic provider is used."""
        mock_create_provider.return_value = mock_llm_provider
        mock_llm_provider.generate_with_tools.return_value = MagicMock(
            response=json.dumps({"clarity_score": 70, "issues": [], "improved_description": "Better", "improvements": []}),
            tool_calls=[],
            token_usage={"total": 100},
            cost=0.001,
            duration=2.0
        )

        # Request with Sonnet model
        request_data = sample_tool_request.copy()
        request_data["model"] = "claude-sonnet-4-5"

        response = client.post("/api/mcp/optimize-docs", json=request_data)

        # Should call create_llm_provider with Haiku instead
        mock_create_provider.assert_called_once_with("anthropic", "claude-haiku-4-5")

    @patch("testmcpy.server.api.create_llm_provider")
    def test_clarity_rating_calculation(
        self, mock_create_provider, client, mock_llm_provider, sample_tool_request
    ):
        """Test clarity rating is calculated correctly from score."""
        mock_create_provider.return_value = mock_llm_provider

        test_cases = [
            (85, "good"),   # >= 75
            (60, "fair"),   # 50-74
            (40, "poor"),   # < 50
        ]

        for score, expected_clarity in test_cases:
            mock_llm_provider.generate_with_tools.return_value = MagicMock(
                response=json.dumps({
                    "clarity_score": score,
                    "issues": [],
                    "improved_description": "Test",
                    "improvements": []
                }),
                tool_calls=[],
                token_usage={"total": 100},
                cost=0.001,
                duration=2.0
            )

            response = client.post("/api/mcp/optimize-docs", json=sample_tool_request)
            result = response.json()

            assert result["analysis"]["clarity"] == expected_clarity, \
                f"Score {score} should give clarity '{expected_clarity}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

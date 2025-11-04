#!/bin/bash
# Test script for the optimize-docs API endpoint using curl

echo "======================================"
echo "LLM Docs Optimization - cURL Test"
echo "======================================"
echo ""
echo "Testing POST /api/mcp/optimize-docs"
echo ""

# Sample tool with vague documentation
curl -X POST "http://localhost:8000/api/mcp/optimize-docs" \
  -H "Content-Type: application/json" \
  -d '{
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
  }' | python3 -m json.tool

echo ""
echo "======================================"
echo "Test completed"
echo "======================================"

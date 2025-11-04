#!/usr/bin/env python3
"""
Test script for the optimize-docs API endpoint.

This script tests the LLM Docs Optimization feature by sending
a sample tool to the API and displaying the analysis results.
"""

import asyncio
import json

import httpx


async def test_optimize_docs():
    """Test the optimize-docs endpoint with a sample tool."""

    # Sample tool with intentionally vague documentation
    tool_data = {
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

    print("Testing /api/mcp/optimize-docs endpoint")
    print("=" * 60)
    print(f"\nTool Name: {tool_data['tool_name']}")
    print(f"Current Description: {tool_data['description']}")
    print(f"\nSchema: {json.dumps(tool_data['input_schema'], indent=2)}")
    print("\n" + "=" * 60)
    print("Sending request to API...\n")

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                "http://localhost:8000/api/mcp/optimize-docs",
                json=tool_data
            )

            if response.status_code == 200:
                result = response.json()

                print("✓ API Request Successful!")
                print("=" * 60)

                # Display analysis
                analysis = result["analysis"]
                print(f"\n📊 ANALYSIS")
                print(f"   Score: {analysis['score']}/100")
                print(f"   Clarity: {analysis['clarity']}")
                print(f"   Issues Found: {len(analysis['issues'])}")

                # Display issues
                if analysis['issues']:
                    print(f"\n⚠️  ISSUES IDENTIFIED:")
                    for i, issue in enumerate(analysis['issues'], 1):
                        print(f"\n   {i}. {issue['issue']}")
                        print(f"      Category: {issue['category']}")
                        print(f"      Severity: {issue['severity']}")
                        print(f"      Current: \"{issue['current']}\"")
                        print(f"      Suggestion: {issue['suggestion']}")

                # Display improved description
                suggestions = result["suggestions"]
                print(f"\n✨ IMPROVED DESCRIPTION:")
                print(f"   {suggestions['improved_description']}")

                # Display specific improvements
                if suggestions['improvements']:
                    print(f"\n📝 SPECIFIC IMPROVEMENTS:")
                    for i, improvement in enumerate(suggestions['improvements'], 1):
                        print(f"\n   {i}. {improvement['issue']}")
                        print(f"      Before: \"{improvement['before']}\"")
                        print(f"      After: \"{improvement['after']}\"")
                        print(f"      Why: {improvement['explanation']}")

                # Display metadata
                print(f"\n💰 METADATA:")
                print(f"   Cost: ${result['cost']:.4f}")
                print(f"   Duration: {result['duration']:.2f}s")

                print("\n" + "=" * 60)
                print("✓ Test completed successfully!")

            else:
                print(f"✗ API Error: {response.status_code}")
                print(f"Response: {response.text}")

        except httpx.ConnectError:
            print("✗ Connection Error: Could not connect to the API server.")
            print("Make sure the server is running on http://localhost:8000")
        except Exception as e:
            print(f"✗ Unexpected Error: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("LLM Docs Optimization - Test Script")
    print("=" * 60)
    asyncio.run(test_optimize_docs())

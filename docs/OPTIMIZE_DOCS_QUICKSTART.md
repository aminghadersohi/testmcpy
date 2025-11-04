# LLM Docs Optimization - Quick Start Guide

## What is This?

The LLM Docs Optimization feature helps you write better documentation for MCP tools. It uses AI to analyze your tool descriptions and suggest improvements that make it easier for LLMs to understand when and how to call your tools.

## Quick Example

**Before Optimization:**
```
Tool: search_data
Description: "Searches for data in the system"
```

**After Optimization:**
```
Tool: search_data
Description: "Searches the internal database for records matching a text query.
Use this when you need to find specific data entries by keyword, name, or ID.
The query parameter supports exact matches and wildcards (*). Results are
sorted by relevance and limited by the 'limit' parameter (default 10, max 100)."
```

## Usage

### 1. Start the Server

```bash
cd testmcpy
python -m testmcpy.cli web
```

Server starts at: http://localhost:8000

### 2. Make a Request

**Using cURL:**
```bash
curl -X POST "http://localhost:8000/api/mcp/optimize-docs" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "your_tool_name",
    "description": "Your current tool description",
    "input_schema": {
      "type": "object",
      "properties": {
        "param1": {"type": "string"}
      }
    }
  }'
```

**Using Python:**
```python
import httpx
import asyncio

async def optimize():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/mcp/optimize-docs",
            json={
                "tool_name": "your_tool",
                "description": "Your description",
                "input_schema": {"type": "object", "properties": {}}
            }
        )
        print(response.json())

asyncio.run(optimize())
```

### 3. Understand the Response

The API returns:

```json
{
  "analysis": {
    "score": 45,              // 0-100 clarity score
    "clarity": "poor",        // good/fair/poor
    "issues": [               // List of problems found
      {
        "category": "clarity",
        "severity": "high",
        "issue": "Description is too vague",
        "current": "Searches for data",
        "suggestion": "Specify what type of data"
      }
    ]
  },
  "suggestions": {
    "improved_description": "Complete rewrite...",
    "improvements": [         // Specific before/after examples
      {
        "issue": "Vague reference",
        "before": "data in system",
        "after": "records in database",
        "explanation": "More specific"
      }
    ]
  },
  "cost": 0.0023,            // API cost in USD
  "duration": 3.45           // Time taken in seconds
}
```

## What Gets Analyzed

The AI checks your documentation for:

1. **Clarity** (Is the purpose clear?)
   - ❌ "Manages data"
   - ✅ "Creates a new dataset with specified columns and initial values"

2. **Completeness** (Are parameters explained?)
   - ❌ "query: Search query"
   - ✅ "query: Text to search for. Supports wildcards (*). Example: 'user_*'"

3. **Actionability** (When should an LLM use this?)
   - ❌ "Updates data"
   - ✅ "Updates an existing dataset by ID. For new data, use create_dataset"

4. **Examples** (Are there concrete examples?)
   - ❌ No examples given
   - ✅ "Example: {id: 'ds_123', data: {name: 'New Name'}}"

5. **Constraints** (What are the limitations?)
   - ❌ No constraints mentioned
   - ✅ "Max 10MB result set. Read-only (no INSERT/UPDATE/DELETE)"

## Common Issues Detected

### 1. Too Vague
```diff
- "Processes information"
+ "Validates email addresses against RFC 5322 standard"
```

### 2. Missing Context
```diff
- "Creates a user"
+ "Creates a new user account. Use this for new users. For updating existing users, use update_user"
```

### 3. Unclear Parameters
```diff
- "data: User data"
+ "data: Object with name (string), email (string, required), role (string: 'admin'|'user')"
```

### 4. No Examples
```diff
- "Searches logs"
+ "Searches logs. Example: query='ERROR' returns all error logs from past 24 hours"
```

## Configuration

### Option 1: Environment Variables
```bash
export DEFAULT_MODEL=claude-haiku-4-5
export DEFAULT_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

### Option 2: Config File (~/.testmcpy)
```
DEFAULT_MODEL=claude-haiku-4-5
DEFAULT_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

### Option 3: In Request
```json
{
  "tool_name": "...",
  "description": "...",
  "input_schema": {},
  "model": "claude-haiku-4-5",
  "provider": "anthropic"
}
```

## Cost Optimization

The endpoint automatically uses Claude Haiku (fastest/cheapest) for analysis:

- **Claude Haiku**: ~$0.001-0.003 per analysis
- **Claude Sonnet**: ~$0.005-0.015 per analysis
- **Average**: ~$0.002 per tool

**Tip**: For batch analysis of 100 tools = ~$0.20

## Testing

### Test with Example Tool
```bash
# Run the test script
python test_optimize_docs.py

# Or use curl
./test_optimize_docs_curl.sh
```

### Verify It's Working
Look for:
- ✅ Score between 0-100
- ✅ At least 1 issue identified
- ✅ Improved description provided
- ✅ Cost < $0.01

## Troubleshooting

### Error: "Model and provider must be configured"
**Solution**: Set DEFAULT_MODEL and DEFAULT_PROVIDER in config

### Error: "Connection refused"
**Solution**: Make sure server is running on http://localhost:8000

### Error: "API key not found"
**Solution**: Set ANTHROPIC_API_KEY (or OPENAI_API_KEY for OpenAI)

### Analysis returns score of 50 with generic issue
**Solution**: This is fallback behavior when LLM response couldn't be parsed. Check API logs.

## Best Practices

### 1. Analyze Before Test Generation
Optimize docs first, then generate tests with better prompts:
```bash
# 1. Optimize docs
POST /api/mcp/optimize-docs { tool_data }

# 2. Copy improved description

# 3. Generate tests with improved description
POST /api/tests/generate { tool_data with improved description }
```

### 2. Batch Process Multiple Tools
```python
tools = [tool1, tool2, tool3]
for tool in tools:
    result = await optimize_docs(tool)
    if result['analysis']['score'] < 60:
        print(f"⚠️  {tool['name']}: {result['analysis']['score']}")
```

### 3. Focus on High-Severity Issues First
```python
high_severity_issues = [
    issue for issue in result['analysis']['issues']
    if issue['severity'] == 'high'
]
```

### 4. Use Improved Descriptions in Your MCP Server
```python
# Before
@mcp.tool()
def search_data(query: str):
    """Searches for data"""
    ...

# After
@mcp.tool()
def search_data(query: str):
    """Searches the internal database for records matching a text query.
    Supports wildcards (*). Returns up to 100 results sorted by relevance."""
    ...
```

## Next Steps

1. **Try it out**: Run `python test_optimize_docs.py`
2. **Optimize your tools**: Analyze your MCP tool documentation
3. **Generate better tests**: Use improved descriptions in test generation
4. **Monitor results**: Track how improved docs affect test success rates

## Need Help?

- **API Reference**: See `docs/OPTIMIZE_DOCS_API.md`
- **Implementation Details**: See `docs/OPTIMIZE_DOCS_IMPLEMENTATION.md`
- **Feature Plan**: See `docs/LLM_DOCS_OPTIMIZATION_PLAN.md`

## Feedback

This feature is designed to improve over time. If you find:
- Common issues that aren't being detected
- Suggestions that aren't helpful
- Edge cases that break parsing

Please report them so we can improve the analysis prompts!

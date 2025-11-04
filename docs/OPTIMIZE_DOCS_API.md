# LLM Docs Optimization API - Implementation Documentation

## Overview

The LLM Docs Optimization API endpoint analyzes MCP tool documentation and provides AI-powered suggestions for improvement. This feature helps developers write better tool descriptions that enable LLMs to call tools more accurately.

## Endpoint

```
POST /api/mcp/optimize-docs
```

## Request Format

### Request Body (JSON)

```json
{
  "tool_name": "string (required)",
  "description": "string (required)",
  "input_schema": "object (required)",
  "model": "string (optional)",
  "provider": "string (optional)"
}
```

### Request Parameters

- **tool_name** (string, required): The name of the MCP tool to analyze
- **description** (string, required): The current description/documentation of the tool
- **input_schema** (object, required): The JSON schema defining the tool's parameters
- **model** (string, optional): LLM model to use for analysis. Defaults to `DEFAULT_MODEL` from config
- **provider** (string, optional): LLM provider to use. Defaults to `DEFAULT_PROVIDER` from config

### Example Request

```json
{
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
```

## Response Format

### Response Body (JSON)

```json
{
  "analysis": {
    "score": "number (0-100)",
    "clarity": "string (good|fair|poor)",
    "issues": [
      {
        "category": "string",
        "severity": "string (high|medium|low)",
        "issue": "string",
        "current": "string",
        "suggestion": "string"
      }
    ]
  },
  "suggestions": {
    "improved_description": "string",
    "improvements": [
      {
        "issue": "string",
        "before": "string",
        "after": "string",
        "explanation": "string"
      }
    ]
  },
  "original": {
    "tool_name": "string",
    "description": "string",
    "input_schema": "object"
  },
  "cost": "number",
  "duration": "number"
}
```

### Response Fields

#### analysis
- **score** (number): Overall clarity score from 0-100
- **clarity** (string): Rating of "good" (≥75), "fair" (50-74), or "poor" (<50)
- **issues** (array): List of identified documentation issues

#### analysis.issues[]
- **category** (string): Type of issue - one of:
  - `clarity`: Purpose is unclear or ambiguous
  - `completeness`: Missing important information
  - `actionability`: Doesn't help LLM decide when to use
  - `examples`: Lacks concrete usage examples
  - `constraints`: Missing limitations or prerequisites
- **severity** (string): Impact level - "high", "medium", or "low"
- **issue** (string): Brief description of the problem
- **current** (string): The problematic part of current documentation
- **suggestion** (string): How to fix the issue

#### suggestions
- **improved_description** (string): Complete rewrite of tool description addressing all issues
- **improvements** (array): List of specific before/after examples

#### suggestions.improvements[]
- **issue** (string): Brief description of what was improved
- **before** (string): Original problematic text
- **after** (string): Improved version
- **explanation** (string): Why the improvement is better

#### original
- **tool_name** (string): Echo of input tool name
- **description** (string): Echo of input description
- **input_schema** (object): Echo of input schema

#### Metadata
- **cost** (number): API cost in USD for the analysis
- **duration** (number): Time taken in seconds

### Example Response

```json
{
  "analysis": {
    "score": 45,
    "clarity": "poor",
    "issues": [
      {
        "category": "clarity",
        "severity": "high",
        "issue": "Description is too vague",
        "current": "Searches for data in the system",
        "suggestion": "Specify what type of data, what system, and what search methods are supported"
      },
      {
        "category": "actionability",
        "severity": "high",
        "issue": "No context for when to use this tool",
        "current": "Searches for data in the system",
        "suggestion": "Explain when to use this vs other search/query tools"
      },
      {
        "category": "completeness",
        "severity": "medium",
        "issue": "Parameter descriptions are minimal",
        "current": "query: Search query",
        "suggestion": "Explain what query syntax is supported, provide examples"
      }
    ]
  },
  "suggestions": {
    "improved_description": "Searches the internal database for records matching a text query. Use this when you need to find specific data entries by keyword, name, or ID. The query parameter supports exact matches and wildcards (*). Results are sorted by relevance and limited by the 'limit' parameter (default 10, max 100).",
    "improvements": [
      {
        "issue": "Vague system reference",
        "before": "Searches for data in the system",
        "after": "Searches the internal database for records",
        "explanation": "Specifies exactly what system/database is being searched"
      },
      {
        "issue": "Missing query syntax info",
        "before": "query: Search query",
        "after": "query: Text to search for. Supports exact matches and wildcards (*). Example: 'user_*' or 'john.doe@example.com'",
        "explanation": "Provides concrete information about supported syntax with examples"
      }
    ]
  },
  "original": {
    "tool_name": "search_data",
    "description": "Searches for data in the system",
    "input_schema": { ... }
  },
  "cost": 0.0023,
  "duration": 3.45
}
```

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Model and provider must be configured. Set DEFAULT_MODEL and DEFAULT_PROVIDER in config."
}
```

### 500 Internal Server Error
```json
{
  "detail": "Failed to optimize documentation: <error message>"
}
```

## Implementation Details

### Analysis Criteria

The endpoint uses an LLM to evaluate tool documentation against these criteria:

1. **Clarity**: Is the purpose immediately clear?
   - Tool name makes sense
   - Description is specific, not vague
   - No ambiguous language

2. **Completeness**: Are all parameters well-explained?
   - Each parameter has clear description
   - Types and constraints are documented
   - Required vs optional is clear

3. **Actionability**: Would an LLM know when to use this?
   - When to use vs alternatives is explained
   - Use cases are mentioned
   - Prerequisites are stated

4. **Examples**: Are there concrete usage examples?
   - Parameter value examples
   - Common use case scenarios
   - Expected outputs mentioned

5. **Constraints**: Are limitations clearly stated?
   - Error conditions explained
   - Rate limits or quotas mentioned
   - Data size limits specified

### Common Issues Detected

The analysis identifies these common documentation problems:

- **Too Vague**: Generic descriptions like "manages data" or "processes information"
- **Missing Context**: No explanation of when to use this tool vs alternatives
- **Parameter Confusion**: Unclear what each parameter does or what values are valid
- **Type Ambiguity**: Parameters without clear type information or constraints
- **No Examples**: Abstract descriptions without concrete usage scenarios
- **Jargon Heavy**: Technical terms without explanation
- **Ambiguous Language**: Multiple possible interpretations

### Model Selection

For cost efficiency, the endpoint automatically uses Claude Haiku for analysis when an Anthropic provider is specified. You can override this by explicitly setting the model parameter.

**Default behavior:**
- If `provider=anthropic` and model is Sonnet/Opus → Uses Claude Haiku 4.5
- Otherwise → Uses specified or default model

**Estimated costs:**
- Claude Haiku 4.5: ~$0.001-0.003 per analysis
- Claude Sonnet 4.5: ~$0.005-0.015 per analysis

### Performance

- **Average duration**: 3-5 seconds per tool
- **Timeout**: 45 seconds
- **Concurrent requests**: Supported (stateless endpoint)

## Usage Examples

### Python (httpx)

```python
import httpx
import asyncio

async def optimize_tool_docs():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/mcp/optimize-docs",
            json={
                "tool_name": "create_user",
                "description": "Creates a user",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"}
                    }
                },
                "model": "claude-haiku-4-5",
                "provider": "anthropic"
            }
        )
        result = response.json()
        print(f"Score: {result['analysis']['score']}")
        print(f"Improved: {result['suggestions']['improved_description']}")

asyncio.run(optimize_tool_docs())
```

### cURL

```bash
curl -X POST "http://localhost:8000/api/mcp/optimize-docs" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "create_user",
    "description": "Creates a user",
    "input_schema": {
      "type": "object",
      "properties": {
        "name": {"type": "string"},
        "email": {"type": "string"}
      }
    }
  }'
```

### JavaScript (fetch)

```javascript
const response = await fetch('http://localhost:8000/api/mcp/optimize-docs', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    tool_name: 'create_user',
    description: 'Creates a user',
    input_schema: {
      type: 'object',
      properties: {
        name: { type: 'string' },
        email: { type: 'string' }
      }
    }
  })
});

const result = await response.json();
console.log('Score:', result.analysis.score);
console.log('Improved:', result.suggestions.improved_description);
```

## Testing

### Running the Test Script

```bash
# Python test (requires httpx)
python3 test_optimize_docs.py

# Or using curl
./test_optimize_docs_curl.sh
```

### Test Data

The test scripts include a sample tool with intentionally vague documentation:

```json
{
  "tool_name": "search_data",
  "description": "Searches for data in the system",
  "input_schema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Search query"},
      "limit": {"type": "integer", "description": "Maximum results"}
    },
    "required": ["query"]
  }
}
```

Expected analysis should identify:
- Vague "data" and "system" references
- Missing context about search methods
- Minimal parameter descriptions
- No examples or constraints

## Integration with Frontend

The frontend can integrate this endpoint in the Explorer view:

1. Add "Optimize Docs" button to tool detail panel
2. On click, send tool info to `/api/mcp/optimize-docs`
3. Display analysis in a modal with:
   - Score badge
   - Issue list with severity indicators
   - Before/After comparison for improved description
   - Copy button to clipboard
   - Option to use in test generation

See `docs/LLM_DOCS_OPTIMIZATION_PLAN.md` for detailed UI specifications.

## Future Enhancements

- **Caching**: Cache results for 24 hours to save costs
- **Batch Analysis**: Endpoint to analyze multiple tools at once
- **Learning Mode**: Track which suggestions users accept/reject
- **Streaming**: Real-time streaming of analysis progress
- **Templates**: Pre-built templates for common tool types
- **Severity Filtering**: Option to only show high-severity issues

## Related Endpoints

- `POST /api/tests/generate` - Generate tests (can use improved descriptions)
- `GET /api/mcp/tools` - List all tools (potential optimization candidates)
- `POST /api/chat` - Chat endpoint (benefits from better tool docs)

## Configuration

Required environment variables:
```bash
DEFAULT_MODEL=claude-haiku-4-5
DEFAULT_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Or set in `~/.testmcpy`:
```
DEFAULT_MODEL=claude-haiku-4-5
DEFAULT_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

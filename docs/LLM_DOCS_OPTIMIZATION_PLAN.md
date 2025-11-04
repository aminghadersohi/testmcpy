# LLM Docs Optimization Feature - Implementation Plan

## Overview

The **LLM Docs Optimization** feature analyzes MCP tool descriptions and suggests improvements to help LLMs call them correctly. This feature uses an LLM to critique tool documentation and provide actionable recommendations.

## User Flow

1. User navigates to **Explorer** page
2. User expands a tool to see details
3. User clicks **"Optimize LLM Docs"** button
4. Modal opens showing:
   - Current tool description
   - Analysis in progress (loading state)
   - AI-generated suggestions for improvement
   - Optional: Before/After comparison
   - Copy button to copy optimized description

## What Makes Good Tool Documentation for LLMs?

### Key Principles

1. **Clear Purpose**: One-sentence description of what the tool does
2. **When to Use**: Explicit scenarios where this tool is appropriate
3. **Parameter Clarity**: Each parameter's purpose, type, and constraints
4. **Examples**: Concrete examples of valid inputs
5. **Error Handling**: What errors might occur and why
6. **Constraints**: Any limitations or prerequisites
7. **Related Tools**: Mention related tools for context

### Common Issues to Detect

- **Too Vague**: "Manages data" → "Creates a new dataset with specified columns and initial values"
- **Missing Context**: No explanation of when to use vs alternatives
- **Parameter Confusion**: Unclear parameter names or purposes
- **Type Ambiguity**: Parameters without clear type information
- **No Examples**: Abstract descriptions without concrete usage
- **Jargon Heavy**: Technical terms without explanation
- **Ambiguous Language**: Multiple interpretations possible

## Technical Architecture

### Backend API Endpoint

```python
@app.post("/api/mcp/optimize-docs")
async def optimize_tool_docs(request: OptimizeDocsRequest):
    """
    Analyze tool documentation and suggest improvements.

    Args:
        request: Contains tool_name, description, input_schema

    Returns:
        {
            "analysis": {
                "issues": [...],
                "score": 0-100,
                "clarity": "good" | "fair" | "poor"
            },
            "suggestions": {
                "improved_description": "...",
                "improvements": [
                    {
                        "issue": "Vague purpose",
                        "suggestion": "Be more specific about...",
                        "before": "...",
                        "after": "..."
                    }
                ]
            }
        }
    """
```

### LLM Prompt Template

```
You are an expert at writing tool documentation for LLMs. Analyze this MCP tool and suggest improvements.

Tool Name: {tool_name}
Current Description: {description}
Parameters: {input_schema}

Analyze the documentation for:
1. Clarity: Is the purpose immediately clear?
2. Completeness: Are all parameters well-explained?
3. Actionability: Would an LLM know exactly when to use this?
4. Examples: Are there concrete usage examples?
5. Constraints: Are limitations clearly stated?

Provide:
1. A clarity score (0-100)
2. List of specific issues found
3. An improved version of the description
4. Specific before/after examples for each issue

Format as JSON.
```

### Request Model

```python
class OptimizeDocsRequest(BaseModel):
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    model: str | None = None
    provider: str | None = None
```

### Response Model

```python
class OptimizeDocsResponse(BaseModel):
    analysis: dict[str, Any]
    suggestions: dict[str, Any]
    original: dict[str, Any]
    cost: float
    duration: float
```

## Frontend UI Components

### OptimizeDocsModal Component

```jsx
<OptimizeDocsModal
  tool={selectedTool}
  onClose={() => setShowOptimize(false)}
/>
```

**Features:**
- Side-by-side comparison (Before/After)
- Highlighted differences
- Copy optimized version button
- Apply to test generation (pre-fill with better description)
- Save suggestions for later review

### Modal Layout

```
┌──────────────────────────────────────────────┐
│  Optimize Tool Documentation                 │
│  ─────────────────────────────────────────  │
│                                              │
│  Tool: create_chart                         │
│                                              │
│  📊 Analysis Score: 65/100                   │
│  ⚠️  Issues Found: 3                         │
│                                              │
│  ┌──────────────┬──────────────┐            │
│  │   Current    │   Optimized  │            │
│  ├──────────────┼──────────────┤            │
│  │ Creates a    │ Creates a    │            │
│  │ chart for    │ bar, line, or│            │
│  │ data visual- │ pie chart... │            │
│  │ ization      │ (more detail)│            │
│  └──────────────┴──────────────┘            │
│                                              │
│  💡 Suggestions                              │
│  ┌────────────────────────────────────────┐ │
│  │ 1. Add specific chart types            │ │
│  │ 2. Clarify when to use vs other tools  │ │
│  │ 3. Add example parameters              │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  [Copy Optimized] [Use in Test Gen] [Close] │
└──────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Backend Analysis (Week 1)
- [ ] Create `/api/mcp/optimize-docs` endpoint
- [ ] Implement LLM prompt for documentation analysis
- [ ] Add request/response models
- [ ] Test with various tool descriptions
- [ ] Add caching for repeated analyses

### Phase 2: Frontend Modal (Week 1)
- [ ] Create `OptimizeDocsModal.jsx` component
- [ ] Design before/after comparison view
- [ ] Add loading states
- [ ] Implement copy-to-clipboard
- [ ] Wire up to Explorer button

### Phase 3: Integration & Polish (Week 2)
- [ ] Connect to test generation (pre-fill improved description)
- [ ] Add suggestion history/storage
- [ ] Add batch optimization for all tools
- [ ] Add export functionality (markdown, JSON)
- [ ] Performance optimization (parallel requests)

### Phase 4: Advanced Features (Future)
- [ ] Learn from user edits (which suggestions were accepted)
- [ ] Tool documentation templates by category
- [ ] Integration with MCP server development flow
- [ ] Automatic PR creation with improved docs

## Example Use Cases

### Use Case 1: Vague Tool Description

**Before:**
```
Tool: update_data
Description: Updates data in the system
Parameters: {data: object, id: string}
```

**After Optimization:**
```
Tool: update_data
Description: Updates an existing dataset's values by ID. Use this when
modifying data that already exists (created with create_dataset). For new
data, use create_dataset instead.

Parameters:
- id (string, required): The unique identifier of the dataset to update
- data (object, required): Key-value pairs to update. Only specified
  fields will be changed, others remain unchanged.

Example: To update a dataset's name: {id: "ds_123", data: {name: "New Name"}}
```

**Issues Fixed:**
1. Added specificity (what kind of data, what system)
2. Clarified when to use vs alternatives
3. Explained parameter behavior (partial updates)
4. Added concrete example

### Use Case 2: Missing Context

**Before:**
```
Tool: execute_query
Description: Executes a SQL query
Parameters: {query: string}
```

**After Optimization:**
```
Tool: execute_query
Description: Executes a read-only SQL SELECT query against the data warehouse.
Use this to retrieve data for analysis or reporting. For data modifications,
this tool is not available - use the data API tools instead.

Parameters:
- query (string, required): SELECT statement (read-only). Supports standard
  SQL syntax including WHERE, JOIN, GROUP BY, etc. Maximum 10MB result set.

Common use cases:
- Aggregating metrics: "SELECT COUNT(*) FROM users WHERE created > '2024-01-01'"
- Joining data: "SELECT a.*, b.name FROM orders a JOIN customers b ON a.customer_id = b.id"

Errors:
- Will fail if query contains INSERT, UPDATE, DELETE, or DROP statements
- Times out after 30 seconds for long-running queries
```

**Issues Fixed:**
1. Specified query type (SELECT only)
2. Added use cases and examples
3. Clarified constraints (read-only, size limits)
4. Listed common errors

## Success Metrics

- **Adoption Rate**: % of tools that get optimized
- **Improvement Score**: Average clarity score increase
- **Test Success Rate**: Do tests pass more often after optimization?
- **User Satisfaction**: Do users find suggestions helpful?
- **Time Saved**: Reduction in time spent debugging tool calls

## Technical Considerations

### Cost Management
- Cache optimization results for 24 hours
- Use cheaper models (Claude Haiku) for analysis
- Batch optimize all tools in one request
- Estimate: ~$0.01-0.05 per tool optimization

### Privacy
- Don't send API keys or sensitive data in analysis
- Mask any credentials in parameter examples
- Option to run locally with Ollama

### Performance
- Async processing for batch operations
- Real-time streaming for single tool
- Show progress for multiple tools
- Parallel requests with rate limiting

## Future Enhancements

1. **Learning Mode**: Track which suggestions users accept/reject
2. **Auto-Fix**: Automatically apply improvements to MCP server
3. **CI/CD Integration**: Run on PR to check documentation quality
4. **Template Library**: Pre-built templates for common tool types
5. **Multi-Language**: Support for non-English descriptions
6. **A/B Testing**: Test improved docs against original in test suite

## Related Features

- **Test Generation**: Use optimized descriptions for better test prompts
- **Explorer**: Show documentation quality score for each tool
- **Reports**: Include documentation quality in test reports
- **CI/CD**: Fail builds if documentation quality is below threshold

## Questions to Resolve

1. Should we store optimization results in the database?
2. How do we handle tools that are already well-documented?
3. Should this feature work offline with Ollama?
4. Do we need version control for documentation iterations?
5. Should we support custom optimization criteria per team?

## References

- [OpenAI Function Calling Best Practices](https://platform.openai.com/docs/guides/function-calling)
- [Anthropic Tool Use Guide](https://docs.anthropic.com/claude/docs/tool-use)
- [MCP Protocol Spec](https://spec.modelcontextprotocol.io/)

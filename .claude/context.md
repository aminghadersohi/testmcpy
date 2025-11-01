# MCP Testing Framework Context

## Project Overview
This is a comprehensive testing framework for validating LLM tool calling capabilities with MCP (Model Context Protocol) services, specifically designed for testing Superset operations. The framework provides tools to evaluate how well different LLMs can successfully interact with MCP services and call appropriate tools.

## Key Design Principles

### Cost Consciousness
The system is designed to work primarily with cost-effective options:
- Local LLMs via Ollama (llama3.1:8b, mistral-nemo, qwen2.5:7b)
- Free/local inference engines
- Minimal external API dependencies

### Architecture
- **Modular Design**: Core functionality is separated into distinct modules (mcp_client.py, llm_integration.py, test_runner.py)
- **Provider Abstraction**: Support for multiple LLM providers through a unified interface
- **Evaluation Framework**: Comprehensive set of evaluators for different test scenarios
- **CLI Interface**: User-friendly command-line interface using typer and rich

## Project Structure
```
testmcpy/
├── src/                    # Core framework modules
│   ├── mcp_client.py      # MCP protocol client implementation
│   ├── llm_integration.py # LLM provider abstraction layer
│   └── test_runner.py     # Test execution engine
├── evals/                  # Evaluation functions
│   └── base_evaluators.py # Standard evaluators for test validation
├── tests/                  # Test case definitions (YAML/JSON)
├── reports/                # Generated test reports
├── my_mcp_tests/          # Example test configurations
├── research/              # Research scripts and prototypes
└── cli.py                 # Main CLI interface
```

## Core Components

### MCP Client (`src/mcp_client.py`)
Handles communication with MCP services, including:
- Tool discovery and listing
- Tool execution
- Error handling and retries
- Protocol compliance

### LLM Integration (`src/llm_integration.py`)
Provides unified interface for different LLM providers:
- Ollama integration for local models
- OpenAI API support (when explicitly needed)
- Custom model configurations
- Token usage tracking

### Test Runner (`src/test_runner.py`)
Orchestrates test execution:
- YAML test case parsing
- Test execution workflow
- Result collection and reporting
- Evaluation pipeline

### Evaluators (`evals/base_evaluators.py`)
Standard evaluation functions including:
- `was_mcp_tool_called`: Verify specific MCP tools were invoked
- `execution_successful`: Check for successful test completion
- `final_answer_contains`: Validate response content
- `within_time_limit`: Performance validation
- `token_usage_reasonable`: Cost/efficiency checks

## Development Practices

### Testing Philosophy
- Focus on real-world MCP tool calling scenarios
- Test different LLM models for capability comparison
- Validate both successful and failure cases
- Measure performance and cost metrics

### Code Quality
- Type hints throughout the codebase
- Comprehensive error handling
- Clear separation of concerns
- Extensive logging for debugging

### Configuration Management
- YAML-based test definitions
- Environment-specific configurations
- Default settings for common use cases

## Usage Patterns

### Research Mode
Used to validate basic LLM tool calling capabilities before running full test suites.

### Test Execution
Run predefined test suites against MCP services with different LLM models.

### Comparison Mode
Compare results across different models and configurations.

### Development Mode
Create and validate new test cases and evaluators.

## Integration Points

### Superset Integration
This framework is designed to work with Superset MCP services for:
- Chart creation and management
- SQL query execution
- Dashboard operations
- Data exploration tasks

### Local Development
Optimized for local development workflows with:
- No external dependencies on paid services
- Fast iteration cycles
- Comprehensive local testing

## Future Considerations
- CI/CD integration for automated testing
- Performance profiling and optimization
- Extended evaluator library
- Multi-language support for test definitions

## Important Notes
- NEVER introduce dependencies on paid API services when possible
- Always test with local Ollama models first
- Focus on practical MCP tool calling scenarios
- Maintain backward compatibility with existing test definitions
- Prefer free/local resources for development and testing
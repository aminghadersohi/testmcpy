# MCP Testing & Validation Framework

A comprehensive testing framework for validating LLM tool calling capabilities with MCP (Model Context Protocol) services, specifically designed for testing Superset operations.

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Phase 0: Research & Validate Tool Calling

Test if your LLM can successfully call tools:

```bash
# Test Ollama with llama3.1:8b
python cli.py research --model llama3.1:8b --provider ollama

# Test with different models
python cli.py research --model mistral-nemo:latest
python cli.py research --model qwen2.5:7b
```

### Run Tests

```bash
# Run a single test file
python cli.py run tests/basic_test.yaml

# Run all tests in a directory
python cli.py run tests/

# Run with specific model
python cli.py run tests/ --model llama3.1:8b --provider ollama

# Save results to a report
python cli.py run tests/ --output reports/test_results.yaml
```

### List MCP Tools

```bash
# List available tools from MCP service
python cli.py tools --mcp-url http://localhost:5008/mcp

# Output as JSON
python cli.py tools --format json
```

### Compare Reports

```bash
# Compare results from different models
python cli.py report reports/llama3.1_results.yaml reports/mistral_results.yaml
```

### Initialize a New Project

```bash
# Create project structure with example tests
python cli.py init my_mcp_tests
cd my_mcp_tests
```

## Framework Structure

```
mcp_testing/
├── research/               # Research scripts for testing LLM capabilities
│   └── test_ollama_tools.py
├── src/                    # Core framework modules
│   ├── mcp_client.py      # MCP protocol client
│   ├── llm_integration.py # LLM provider abstraction
│   └── test_runner.py     # Test execution engine
├── evals/                  # Evaluation functions
│   └── base_evaluators.py # Standard evaluators
├── tests/                  # Test cases (YAML/JSON)
│   ├── basic_test.yaml
│   └── example_mcp_tests.yaml
├── reports/                # Test reports and comparisons
└── cli.py                  # CLI interface

```

## Writing Test Cases

Test cases are defined in YAML files:

```yaml
version: "1.0"
name: "My Test Suite"

tests:
  - name: "test_chart_creation"
    prompt: "Create a bar chart showing sales by region"
    expected_tools:
      - "create_chart"
    evaluators:
      - name: "was_mcp_tool_called"
        args:
          tool_name: "create_chart"
      - name: "execution_successful"
      - name: "final_answer_contains"
        args:
          expected_content: ["chart", "created"]
      - name: "within_time_limit"
        args:
          max_seconds: 30
```

## Available Evaluators

### Generic Evaluators
- `was_mcp_tool_called` - Verify MCP tool was called
- `execution_successful` - Check for successful execution
- `final_answer_contains` - Validate response content
- `answer_contains_link` - Check for links in response
- `within_time_limit` - Verify performance
- `token_usage_reasonable` - Check token/cost efficiency

### Superset-Specific Evaluators
- `was_superset_chart_created` - Verify chart creation
- `sql_query_valid` - Validate SQL syntax

## Supported LLM Providers

- **Ollama** - Local models with tool calling support
  - llama3.1:8b (recommended)
  - mistral-nemo
  - qwen2.5:7b
- **OpenAI** - GPT models via API
- **Local** - Transformers-based local models

## Configuration

Create `mcp_test_config.yaml`:

```yaml
mcp_url: "http://localhost:5008/mcp"
default_model: "llama3.1:8b"
default_provider: "ollama"
evaluators:
  timeout: 30
  max_tokens: 2000
  max_cost: 0.10
```

## Development Status

### Phase 0: Research & Prototype ✅
- [x] Research local LLM options with tool calling
- [x] Build minimal Python script for LLM+MCP integration
- [x] Validate tool calling with selected LLM
- [x] Create basic framework structure

### Phase 1: Foundation (In Progress)
- [x] CLI framework with typer + rich
- [x] Basic test execution engine
- [x] MCP protocol client
- [x] LLM provider abstraction
- [x] Core evaluation functions
- [ ] Integration with existing Superset tests

### Phase 2: Core Features (Planned)
- [ ] Multi-model comparison support
- [ ] Advanced reporting with charts
- [ ] Test suite versioning
- [ ] Parallel test execution

### Phase 3: Advanced Capabilities (Future)
- [ ] CI/CD integration
- [ ] Interactive test development mode
- [ ] Performance profiling
- [ ] Cost optimization insights

## Known Limitations

- Claude Code currently has bugs with MCP tool calling, hence the need for local LLMs
- Ollama models require specific formatting for reliable tool calling
- CPU-only execution may be slow for larger models
- Tool calling accuracy varies by model

## Contributing

This framework follows the patterns established by promptimize and superset-sup. When contributing:

1. Use modern Python practices (type hints, async/await)
2. Follow the existing code style
3. Add tests for new evaluators
4. Document new features in this README

## License

Same as the parent promptimize project.
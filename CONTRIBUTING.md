# Contributing to MCP Testing Framework

Thank you for your interest in contributing to the MCP Testing Framework! This document provides guidelines and information for contributors.

## Development Setup

### Prerequisites
- Python 3.8 or higher
- [Ollama](https://ollama.ai/) installed for local LLM testing
- Git

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/preset-io/testmcpy.git
   cd testmcpy
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

5. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

## Code Quality Standards

### Code Formatting
We use [Black](https://black.readthedocs.io/) for code formatting with a line length of 100 characters.

Run formatting:
```bash
black .
```

### Linting
We use [Flake8](https://flake8.pycqa.org/) for linting.

Run linting:
```bash
flake8 .
```

### Type Checking
We encourage the use of type hints throughout the codebase. Consider using [mypy](http://mypy-lang.org/) for type checking.

## Testing

### Running Tests
```bash
# Run all tests
python cli.py run tests/

# Run specific test file
python cli.py run tests/basic_test.yaml

# Run with specific model
python cli.py run tests/ --model llama3.1:8b --provider ollama
```

### Writing Tests
Test cases are defined in YAML format. See `tests/basic_test.yaml` for examples.

Example test structure:
```yaml
version: "1.0"
name: "Example Test Suite"

tests:
  - name: "test_example"
    prompt: "Your test prompt here"
    expected_tools:
      - "tool_name"
    evaluators:
      - name: "was_mcp_tool_called"
        args:
          tool_name: "tool_name"
      - name: "execution_successful"
```

### Adding New Evaluators
Evaluators should be added to `evals/base_evaluators.py`. Each evaluator should:
- Take a test result and configuration as input
- Return a boolean indicating pass/fail
- Include clear documentation of its purpose
- Handle edge cases gracefully

## Contributing Guidelines

### Pull Request Process
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Run tests and ensure they pass
5. Run code formatting and linting
6. Commit your changes with clear, descriptive messages
7. Push to your fork
8. Create a pull request

### Commit Message Guidelines
- Use the imperative mood ("Add feature" not "Added feature")
- Keep the first line under 50 characters
- Include a detailed description if necessary
- Reference issues and pull requests when applicable

Example:
```
Add support for custom evaluator plugins

This commit introduces a plugin system for custom evaluators,
allowing users to extend the framework with domain-specific
validation logic.

Fixes #123
```

### Code Review Process
- All contributions require code review
- Address feedback promptly and respectfully
- Be open to suggestions and improvements
- Ensure your code follows the project's style and conventions

## Important Principles

### No Paid API Dependencies
This framework is designed to work entirely with free/local resources:
- **NEVER** introduce dependencies on Claude API, OpenAI API, or other paid services
- Always test with local Ollama models first
- Maintain the cost-free nature of the framework

### Design Philosophy
- **Modularity**: Keep components loosely coupled and highly cohesive
- **Testability**: Write code that can be easily tested
- **Documentation**: Document public APIs and complex logic
- **Performance**: Consider performance implications, especially for test execution
- **Usability**: Prioritize user experience in CLI design

## Areas for Contribution

### High Priority
- Additional evaluators for common testing scenarios
- Support for more LLM providers (local/free only)
- Performance optimizations
- Documentation improvements

### Medium Priority
- Enhanced reporting capabilities
- Parallel test execution
- CLI usability improvements
- Example test cases for different domains

### Lower Priority
- Advanced configuration options
- Integration with CI/CD systems
- Web-based result visualization

## Getting Help

- Check existing [issues](https://github.com/preset-io/testmcpy/issues)
- Create a new issue for bugs or feature requests
- Join discussions in existing issues
- Read the documentation in the README

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.

## Recognition

All contributors will be recognized in the project's documentation and release notes.

Thank you for contributing to the MCP Testing Framework!
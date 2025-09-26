#!/bin/bash

# MCP Testing Framework Setup Script

echo "MCP Testing Framework - Setup"
echo "=============================="
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing requirements..."
pip install -r requirements.txt

# Check Ollama installation
echo ""
echo "Checking Ollama installation..."
if command -v ollama &> /dev/null; then
    echo "✓ Ollama is installed"
    ollama list
else
    echo "✗ Ollama not found. Please install from https://ollama.ai"
    echo "After installing, run: ollama pull llama3.1:8b"
fi

# Check MCP service
echo ""
echo "Checking MCP service at localhost:5008..."
if curl -s -o /dev/null -w "%{http_code}" http://localhost:5008/mcp | grep -q "200\|404"; then
    echo "✓ MCP service appears to be running"
else
    echo "✗ MCP service not responding at http://localhost:5008/mcp"
    echo "Please ensure the MCP service is running"
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Ensure Ollama is installed and running"
echo "2. Pull a model: ollama pull llama3.1:8b"
echo "3. Start MCP service at localhost:5008"
echo "4. Run: python cli.py research"
echo ""
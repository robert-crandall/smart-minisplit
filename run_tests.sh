#!/bin/bash

echo "Running Smart Mini Split Controller tests..."

# Check if virtual environment exists and activate it
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
else
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
fi

# Install test dependencies if needed
if [ "$1" = "--install" ]; then
    echo "Installing test dependencies..."
    pip install -r requirements_test.txt
fi

# Run pytest with coverage
python -m pytest tests/test_*.py -v --cov=custom_components/smart_mini_split

# Inform user how to manually activate the environment
echo ""
echo "To manually activate the virtual environment, run:"
echo "    source venv/bin/activate"
echo ""

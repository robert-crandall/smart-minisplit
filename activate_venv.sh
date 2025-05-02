#!/bin/bash
# Simple helper script to activate the virtual environment

if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
    echo "Virtual environment activated! You can deactivate by typing 'deactivate'."
else
    echo "Virtual environment not found. Creating one..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Virtual environment created and activated!"
    echo "You can deactivate by typing 'deactivate'."
fi

# Print info about the activated environment
echo ""
echo "Python version:"
python --version
echo ""
echo "Virtual environment location:"
which python

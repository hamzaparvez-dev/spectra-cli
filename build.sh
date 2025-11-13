#!/bin/bash
set -e

# Try to use Python 3.11 if available, otherwise use default python3
if command -v python3.11 &> /dev/null; then
    PYTHON=python3.11
elif command -v python3 &> /dev/null; then
    PYTHON=python3
else
    PYTHON=python
fi

echo "Using Python: $($PYTHON --version)"

# Upgrade pip
$PYTHON -m pip install --upgrade pip

# Install dependencies
$PYTHON -m pip install -r api/requirements.txt


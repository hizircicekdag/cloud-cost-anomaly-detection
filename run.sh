#!/bin/bash

# Cloud Cost Anomaly Detection Application Runner
# This script sets up a Python virtual environment, installs dependencies,
# runs the validation suite, and launches the FastAPI backend and dashboard.

PROJECT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$PROJECT_DIR"

echo "=================================================="
echo " Starting Cloud Cost Anomaly Detection Runner "
echo "=================================================="

# 1. Setup Virtualenv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment 'venv'..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

# 2. Install dependencies
echo "Installing dependencies from backend/requirements.txt..."
pip install --upgrade pip
pip install -r backend/requirements.txt

# 3. Run automated verification tests
echo "Running automated verification suite..."
python3 backend/verify.py

if [ $? -ne 0 ]; then
    echo "❌ Error: Verification tests failed. Aborting startup."
    exit 1
fi

# 4. Start the backend server
echo ""
echo "🚀 Starting FastAPI server on http://127.0.0.1:8000"
echo "Open this URL in your web browser to view the interactive dashboard!"
echo "Press Ctrl+C to stop the server."
echo ""

cd backend
python3 main.py

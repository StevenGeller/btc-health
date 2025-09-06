#!/bin/bash
# Run all collectors for Bitcoin Health Scorecard
# This script is meant to be called from cron

# Set up environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PATH="${PROJECT_DIR}/venv"

# Activate virtual environment
source "${VENV_PATH}/bin/activate"

# Change to project directory
cd "${PROJECT_DIR}"

# Export Python path
export PYTHONPATH="${PROJECT_DIR}:${PYTHONPATH}"

# Function to run a collector
run_collector() {
    local module=$1
    echo "Running ${module}..."
    python -m "app.collectors.${module}"
    if [ $? -eq 0 ]; then
        echo "${module} completed successfully"
    else
        echo "${module} failed with exit code $?"
    fi
}

# Parse command line arguments
if [ $# -eq 0 ]; then
    echo "Usage: $0 [collector_name|all|compute]"
    echo "Available collectors: mempool, bitnodes, coingecko, blockchain_charts, forkmonitor"
    exit 1
fi

case "$1" in
    all)
        # Run all collectors
        run_collector mempool
        run_collector coingecko
        run_collector blockchain_charts
        run_collector forkmonitor
        # Bitnodes has strict rate limits, run less frequently
        if [ "$(date +%H)" = "00" ] || [ "$(date +%H)" = "12" ]; then
            run_collector bitnodes
        fi
        ;;
    compute)
        # Run computation pipeline
        echo "Running metric calculations..."
        python -m app.compute.formulas
        
        echo "Running normalization..."
        python -m app.compute.normalize
        
        echo "Calculating scores..."
        python -m app.compute.scores
        ;;
    mempool|bitnodes|coingecko|blockchain_charts|forkmonitor)
        run_collector "$1"
        ;;
    *)
        echo "Unknown collector: $1"
        exit 1
        ;;
esac

echo "Collector run completed at $(date)"

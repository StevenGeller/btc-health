#!/bin/bash
# Bitcoin Health Data Collection Script

cd /home/steven/projects/btc-health

# Ensure Tor is running for Bitcoin Core collector
/home/steven/projects/btc-health/start_tor.sh

# Run data collection
/home/steven/projects/btc-health/venv/bin/python3 init_and_collect.py >> /home/steven/projects/btc-health/data/collection.log 2>&1
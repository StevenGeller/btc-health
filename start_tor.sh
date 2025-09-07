#!/bin/bash
# Start Tor for Bitcoin Core collector

# Check if Tor is already running
if pgrep -x "tor" > /dev/null; then
    echo "Tor is already running"
else
    echo "Starting Tor..."
    mkdir -p /tmp/tor-btc
    tor -f /tmp/torrc --DataDirectory /tmp/tor-btc --SocksPort 9050 --quiet &
    
    # Wait for Tor to start
    sleep 5
    
    # Check if it started successfully
    if ss -tlnp 2>/dev/null | grep -q 9050; then
        echo "Tor started successfully on port 9050"
    else
        echo "Failed to start Tor"
        exit 1
    fi
fi
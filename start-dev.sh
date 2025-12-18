#!/bin/bash
# Development startup script
# The local models package is already installed during Docker build

echo "Starting Music Assistant..."
python -m music_assistant --data-dir /data --log-level debug

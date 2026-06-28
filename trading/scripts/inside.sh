#!/bin/bash
# Run F1/F2/F3 scripts inside the Docker container
# Usage:  ./scripts/inside.sh python /app/brackets/okx_bracket.py [args]
# Example: ./scripts/inside.sh python /app/confluence/confluence.py --symbol BTC-USDT --json

docker compose exec vt "$@"

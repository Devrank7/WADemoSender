#!/usr/bin/env bash
# Stop hook — sends Telegram notification when a Claude Code session/skill completes.

set -euo pipefail

# Load .env.local
ENV_FILE="$(cd "$(dirname "$0")/../.." && pwd)/.env.local"
if [ ! -f "$ENV_FILE" ]; then
    exit 0
fi

BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d'=' -f2 | tr -d "'" | tr -d '"')
CHAT_IDS=$(grep '^TELEGRAM_REPORT_CHAT_ID=' "$ENV_FILE" | cut -d'=' -f2 | tr -d "'" | tr -d '"')

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_IDS" ]; then
    exit 0
fi

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
PROJECT=$(basename "$(cd "$(dirname "$0")/../.." && pwd)")
MSG="🏁 Claude Code session completed\n📁 Project: ${PROJECT}\n🕐 ${TIMESTAMP}"

# Send to each chat ID
IFS=',' read -ra IDS <<< "$CHAT_IDS"
for CHAT_ID in "${IDS[@]}"; do
    CHAT_ID=$(echo "$CHAT_ID" | tr -d ' ')
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${CHAT_ID}\",\"text\":\"${MSG}\"}" \
        > /dev/null 2>&1 &
done

exit 0

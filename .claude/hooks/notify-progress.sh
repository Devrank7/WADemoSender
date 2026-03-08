#!/usr/bin/env bash
# PostToolUse hook — sends Telegram notifications for WADemoSender operations.
# Fires after every Bash tool call. Only notifies for recognized commands.

set -euo pipefail

PAYLOAD=$(cat)

COMMAND=$(echo "$PAYLOAD" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    cmd = data.get('tool_input', {}).get('command', '')
    print(cmd)
except:
    print('')
" 2>/dev/null)

# Only process WA-related commands
case "$COMMAND" in
    *save-message*|*save-prompt*|*send_wa.py\ send*)
        ;;
    *)
        exit 0
        ;;
esac

ENV_FILE="$(cd "$(dirname "$0")/../.." && pwd)/.env.local"
if [ ! -f "$ENV_FILE" ]; then
    exit 0
fi

BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d'=' -f2 | tr -d "'" | tr -d '"')
CHAT_IDS=$(grep '^TELEGRAM_REPORT_CHAT_ID=' "$ENV_FILE" | cut -d'=' -f2 | tr -d "'" | tr -d '"')

if [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_IDS" ]; then
    exit 0
fi

MSG=""
case "$COMMAND" in
    *save-message*)
        ROW=$(echo "$COMMAND" | grep -oE 'save-message\s+\S+\s+([0-9]+)' | grep -oE '[0-9]+$' || echo "?")
        MSG="📝 WA message saved (row $ROW)"
        ;;
    *save-prompt*)
        ROW=$(echo "$COMMAND" | grep -oE 'save-prompt\s+\S+\s+([0-9]+)' | grep -oE '[0-9]+$' || echo "?")
        MSG="🧠 System prompt saved (row $ROW)"
        ;;
    *send_wa.py\ send*)
        MSG="📱 WhatsApp batch sending started"
        ;;
esac

if [ -z "$MSG" ]; then
    exit 0
fi

IFS=',' read -ra IDS <<< "$CHAT_IDS"
for CHAT_ID in "${IDS[@]}"; do
    CHAT_ID=$(echo "$CHAT_ID" | tr -d ' ')
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\":\"${CHAT_ID}\",\"text\":\"${MSG}\"}" \
        > /dev/null 2>&1 &
done

exit 0

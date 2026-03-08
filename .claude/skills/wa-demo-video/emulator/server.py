#!/usr/bin/env python3
"""
WhatsApp Chat Emulator — Local proxy server.

Serves the emulator HTML/CSS/JS and proxies chat requests to winbixai.com.
Styled as a WhatsApp chat interface for recording demo videos.

Usage:
    python3 server.py                  # Start on default port 8889
    python3 server.py --port 9999      # Custom port
    python3 server.py --stop           # Stop running server
"""

import json
import os
import signal
import sys
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add _shared to import path for load_env()
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

try:
    from _shared import load_env
    ENV = load_env()
except Exception:
    ENV = {}

PORT = int(sys.argv[sys.argv.index("--port") + 1] if "--port" in sys.argv else os.environ.get("WA_EMULATOR_PORT", "8889"))
# WA emulator reuses the same API as IG emulator (shared backend).
# Check WA-specific vars first, fall back to IG vars for backward compatibility.
_DEFAULT_API_URL = "https://winbixai.com/api/instagram-config/context"
API_BASE = ENV.get("WA_DEMO_API_URL", ENV.get("IG_DEMO_API_URL", _DEFAULT_API_URL)).rsplit("/api/", 1)[0]
CHAT_URL = f"{API_BASE}/api/emulator/chat"
CONFIGURE_URL = ENV.get("WA_DEMO_API_URL", ENV.get("IG_DEMO_API_URL", _DEFAULT_API_URL))
CONFIGURE_TOKEN = ENV.get("WA_DEMO_API_TOKEN", ENV.get("IG_DEMO_API_TOKEN", ""))
PID_FILE = Path(__file__).resolve().parent / ".server.pid"

# WhatsApp-specific demo prompt suffix
DEMO_PROMPT_SUFFIX = """

CRITICAL DEMO RESPONSE RULES — follow these exactly:
- You are replying in a WhatsApp chat, NOT Instagram DM.
- Reply in 1-3 SHORT sentences MAX. Never write paragraphs.
- Sound like the actual business owner quickly replying between tasks.
- Use conversational style. Informal tone appropriate for WhatsApp.
- Use 1-2 fitting emoji only when natural (✨ 😊 👍 🙏).
- Do NOT list all services or prices. Only answer what was specifically asked.
- Do NOT give a formal pitch. Be warm, helpful, and direct.
- ALWAYS end with a question or next-step suggestion. Never dead-end the conversation.
- If someone shows interest, guide toward booking: "when were you thinking?" or "I have openings this week, want me to book you in?"
- If asked about availability, suggest specific times.
- If asked about pricing, give the range briefly and suggest a consultation.
"""

AVATARS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output" / "wa_avatars"

MIME_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
}


class WhatsAppEmulatorHandler(SimpleHTTPRequestHandler):
    """Serves static files + proxies /proxy/chat to AI API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(Path(__file__).resolve().parent), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/proxy/wa-avatar":
            self._serve_wa_avatar(parsed)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/proxy/chat":
            self._proxy_chat()
        elif self.path == "/proxy/configure-prompt":
            self._proxy_configure_prompt()
        else:
            self.send_error(404, "Not Found")

    def _serve_wa_avatar(self, parsed):
        """Serve a cached WhatsApp avatar by phone number."""
        try:
            qs = parse_qs(parsed.query)
            phone = qs.get("phone", [""])[0].strip()
            if not phone:
                self.send_error(400, "phone parameter required")
                return

            # Normalize phone: keep only digits
            phone_norm = "".join(c for c in phone if c.isdigit())
            if not phone_norm:
                self.send_error(400, "invalid phone")
                return

            # Look for cached avatar file
            avatar_path = None
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                candidate = AVATARS_DIR / f"{phone_norm}{ext}"
                if candidate.exists():
                    avatar_path = candidate
                    break

            if not avatar_path:
                self.send_error(404, "avatar not found")
                return

            # Serve the file
            data = avatar_path.read_bytes()
            ext = avatar_path.suffix.lower()
            ct = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")

            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        except Exception as e:
            print(f"  [wa-avatar] Error: {e}")
            self.send_error(500, str(e))

    def _proxy_chat(self):
        """Proxy chat request to AI API."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body)

            data = json.dumps({
                "message": payload.get("message", ""),
                "conversationHistory": payload.get("conversationHistory", []),
                "sessionId": payload.get("sessionId", "wa_emulator"),
            }).encode("utf-8")

            req = urllib.request.Request(
                CHAT_URL,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode("utf-8"))
            self._json_response(200, result)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            print(f"  API error {e.code}: {error_body[:200]}")
            self._json_response(e.code, {"success": False, "error": f"API error: {e.code}"})
        except Exception as e:
            print(f"  Proxy error: {e}")
            self._json_response(500, {"success": False, "error": str(e)})

    def _proxy_configure_prompt(self):
        """Configure AI system prompt from spreadsheet row."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            payload = json.loads(body)

            spreadsheet_id = payload.get("spreadsheetId", "")
            row_number = int(payload.get("row", 0))

            if not spreadsheet_id or not row_number:
                self._json_response(400, {"success": False, "error": "spreadsheetId and row required"})
                return

            if not CONFIGURE_TOKEN:
                self._json_response(500, {"success": False, "error": "WA_DEMO_API_TOKEN (or IG_DEMO_API_TOKEN) not configured"})
                return

            from _shared import get_sheets_service, read_sheet, find_columns

            service = get_sheets_service()
            rows = read_sheet(service, spreadsheet_id)
            columns = find_columns(rows[0])

            data_idx = row_number - 1
            if data_idx < 1 or data_idx >= len(rows):
                self._json_response(400, {"success": False, "error": f"Row {row_number} out of range"})
                return

            row = rows[data_idx]
            prompt_col = columns.get("system_prompt", {}).get("index")
            if prompt_col is None:
                self._json_response(400, {"success": False, "error": "No system_prompt column found"})
                return

            prompt = row[prompt_col].strip() if prompt_col < len(row) else ""
            if not prompt:
                self._json_response(400, {"success": False, "error": f"No system prompt in row {row_number}"})
                return

            # Append WhatsApp-specific demo suffix
            demo_prompt = prompt + DEMO_PROMPT_SUFFIX

            data = json.dumps({"text": demo_prompt}).encode("utf-8")
            req = urllib.request.Request(
                CONFIGURE_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {CONFIGURE_TOKEN}",
                },
                method="PUT",
            )
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read().decode("utf-8"))

            if not result.get("success"):
                self._json_response(500, {"success": False, "error": f"API returned: {result}"})
                return

            print(f"  [configure] Row {row_number}: prompt configured ({len(prompt)} chars)")
            self._json_response(200, {"success": True, "promptLength": len(prompt)})

        except SystemExit:
            print(f"  [configure] Sheet access error for row {payload.get('row', '?')}")
            self._json_response(500, {"success": False, "error": "Failed to access spreadsheet"})
        except Exception as e:
            print(f"  [configure] Error: {e}")
            self._json_response(500, {"success": False, "error": str(e)})

    def _json_response(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        """Cleaner logging."""
        msg = str(args[0]) if args else ""
        if "/proxy/chat" in msg:
            print(f"  [proxy] {msg}")
        elif msg.startswith("GET"):
            pass
        else:
            print(f"  {msg}")


def write_pid():
    PID_FILE.write_text(str(os.getpid()))


def stop_server():
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"  Stopped server (PID {pid})")
        except ProcessLookupError:
            print(f"  Server not running (stale PID {pid})")
        PID_FILE.unlink(missing_ok=True)
    else:
        print("  No server PID file found")


def main():
    if "--stop" in sys.argv:
        stop_server()
        return

    print(f"\n{'='*50}")
    print(f"  WhatsApp Chat Emulator Server")
    print(f"{'='*50}")
    print(f"  URL:     http://localhost:{PORT}")
    print(f"  API:     {CHAT_URL}")
    print(f"  PID:     {os.getpid()}")
    print(f"{'='*50}")
    print(f"\n  Open in browser:")
    print(f"  http://localhost:{PORT}/?name=Test+Business&phone=5511999990000\n")

    write_pid()

    try:
        server = HTTPServer(("0.0.0.0", PORT), WhatsAppEmulatorHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Server stopped.")
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

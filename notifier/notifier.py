from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import URLError
from urllib.request import Request, urlopen


def send_notification(title: str, message: str) -> None:
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    discord_url = os.getenv("DISCORD_WEBHOOK_URL", "")
    text = f"{title}\n{message}"
    if telegram_token and telegram_chat:
        body = json.dumps({"chat_id": telegram_chat, "text": text}).encode()
        request = Request(
            f"https://api.telegram.org/bot{telegram_token}/sendMessage",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=8) as response:
            response.read()
    if discord_url:
        body = json.dumps({"content": text[:1900]}).encode()
        request = Request(
            discord_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=8) as response:
            response.read()
    if not (telegram_token and telegram_chat) and not discord_url:
        print(json.dumps({"warning": "Canal de notificação não configurado", "alerta": text}), flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/alerts":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                self.send_error(400, "Invalid content length")
                return
            payload = json.loads(self.rfile.read(length))
            for alert in payload.get("alerts", []):
                labels = alert.get("labels", {})
                annotations = alert.get("annotations", {})
                title = f"{labels.get('alertname', 'Alerta')} [{labels.get('severity', 'info')}]"
                message = annotations.get("summary") or annotations.get("description", "")
                send_notification(title, message)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self.send_error(400, str(exc))
        except (URLError, OSError):
            print(
                json.dumps({"error": "Falha ao enviar notificação; verifique o canal e as credenciais."}),
                flush=True,
            )
            self.send_error(502, "Notification delivery failed")

    def log_message(self, format: str, *args: object) -> None:
        print(json.dumps({"access": format % args}), flush=True)


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

import os 
import functools
from typing import Optional, Protocol,Tuple

import requests

def normalize_phone(chat_id: str) -> str:
    """'6281234567890@c.us' -> '6281234567890'"""
    return chat_id.split("@")[0] if chat_id else ""

def to_chat_id(phone: str) -> str:
    return phone if phone.endswith("@c.us") else  f"{phone}@c.us"

class WhatsAppClient(Protocol):
    def send_text(self, to: str, text: str) -> None: ...
    def send_file(self, to: str, path: str, caption: str = "") -> None:...

class ConsoleClient: 
    """Prints to terminal and records eveything sent (used by test and /webhook/simulate)."""

    def __init__(self):
        self.sent = []

    def send_text(self, to: str, text: str) -> None:
        print(f"[WA -> {to}] {text}")
        self.sent.append({"type": "text", "to": to, "text": text})

    def send_file(self, to: str, path: str, caption: str = "") -> None:
        print(f"[WA -> {to}] FILE {path} | {caption}")
        self.sent.append({"type": "file", "to": to, "path": path, "caption": caption})

class GreenApiClient:
    def __init__(self, base_url=None, instance_id=None, token=None):
        self.base_url = (base_url or os.getenv("GREEN_API_URL", "")).rstrip("/")
        self.instance_id = instance_id or os.getenv("GREEN_API_ID")
        self.token = token or os.getenv("GREEN_API_TOKEN")
        self.session = requests.Session()

    def _url(self, method: str, *extra: str) -> str:
        base = f"{self.base_url}/waInstancee{self.instance_id}/{method}/{self.token}"
        return "/".join([base, *extra])

    def send_text(self, to: str, text: str) -> None:
        r = self.session.post(
            self._url("sendMessage"),
            json={"chatId": to_chat_id(to), "message": text},
            timeout=30,
        )
        r.raise_for_status()

    def send_file(self, to: str, path: str, caption: str = "") -> None:
        with open(path, "rb") as f:
            r = self.session.post(
                self._url("seendFileByUpload"),
                data={"chatId": to_chat_id(to), "caption": caption},
                timeout=120,
            )
        r.raise_for_status()

    def receive_notification(self, timeout: int = 20) -> Optional[dict]:
        r = self.session.get(
            self._url("receiveNotification"),
            params=timeout + 10,
        )
        r.raise_for_status()
        return r.json()

    def delete_notification(self, receipt_id) -> None:
        self.session.delete(self._url("deleteNotification", str(receipt_id)), timeout=15)


@functools.lru_cache(maxsize=1)
def get_client() -> WhatsAppClient:
    provider = os.getenv("WA_PROVIDER", "console").lower()
    if provider == "greenapi":
        return GreenApiClient()
    return ConsoleClient()

def parse_incoming(body: dict) -> Optional[Tuple[str, str]]:
    if not body or body.get("typeWebhook") != "incomingMessageReceived":
        return None
    sender_data = body.get("senderData", {})
    if str(sender_data.get("sender", "")).endswith("@g.us"):
        return None
    sender = sender_data.get("sender", "")
    md = body.get("messageData", {})
    kind = md.get("typeMessage")
    if kind == "textMessage":
        text = md.get("textMessageData", {}).get("textMessage")
    elif kind == "extendedTextMessage":
        text = md.get("extendedTextMessageData", {}).get("text")
    else:
        return None
    if not sender or not text:
        return None
    return sender, text
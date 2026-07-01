"""
Discord webhook notifier — reference adapter.

Usage:
    notifier = DiscordNotifier(webhook_url=os.environ["DISCORD_WEBHOOK_URL"])
    checker = CheckerAPI(ledger=ledger, verifier_id="validator", token=token, notifier=notifier)
"""
import urllib.request
import json
import os


class DiscordNotifier:
    """
    Sends Attestor alerts to a Discord channel via webhook.
    Set DISCORD_WEBHOOK_URL in the validator's environment.
    Never put the webhook URL in maker agent context.
    """

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
        if not self.webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL required for DiscordNotifier")

    def alert(self, message: str) -> None:
        payload = json.dumps({"content": message}).encode()
        req = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as e:
            print(f"[DiscordNotifier] Failed to send alert: {e}\nMessage: {message}")

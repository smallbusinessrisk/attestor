"""stdout notifier — default. Prints alerts to the terminal."""
from datetime import datetime

class StdoutNotifier:
    def alert(self, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] ATTESTOR ALERT: {message}")

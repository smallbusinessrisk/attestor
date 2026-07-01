"""
attestor.core.watchdog
----------------------
Validator dead-man's switch.

Silence is not success. If the validator stops reporting within its expected
window, that is an alert — not a green light.

This is the missing layer in most implementations: they monitor the work
but not the monitor itself. A crashed validator looks identical to a clean run.
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional


HEARTBEAT_FILE_ENV = "ATTESTOR_HEARTBEAT_FILE"
DEFAULT_HEARTBEAT_FILE = "/tmp/attestor_validator_heartbeat"


class Watchdog:
    """
    Two-part dead-man's switch:

    1. Validator calls heartbeat() after each successful run.
    2. Monitor process calls check() to verify the validator ran within its window.
       If check() returns False, the notifier fires an alert.

    Usage in validator:
        watchdog = Watchdog()
        watchdog.heartbeat()  # call this at the end of every successful validator run

    Usage in monitor (separate cron):
        watchdog = Watchdog(max_age_minutes=60, notifier=my_notifier)
        watchdog.check()
    """

    def __init__(self,
                 heartbeat_file: Optional[str] = None,
                 max_age_minutes: int = 60,
                 notifier=None):
        self.heartbeat_file = heartbeat_file or os.environ.get(
            HEARTBEAT_FILE_ENV, DEFAULT_HEARTBEAT_FILE
        )
        self.max_age_minutes = max_age_minutes
        self.notifier = notifier

    def heartbeat(self) -> None:
        """Record that the validator ran successfully right now."""
        with open(self.heartbeat_file, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())

    def check(self) -> bool:
        """
        Check whether the validator has run within the expected window.

        Returns True if the validator is healthy.
        Returns False and fires an alert if the validator is overdue.
        """
        try:
            with open(self.heartbeat_file) as f:
                last_run = datetime.fromisoformat(f.read().strip())
            age = datetime.now(timezone.utc) - last_run
            if age > timedelta(minutes=self.max_age_minutes):
                self._alert(f"Validator overdue: last ran {int(age.total_seconds() / 60)}m ago "
                            f"(threshold: {self.max_age_minutes}m). "
                            f"Silent validator = undetected fabrication.")
                return False
            return True
        except FileNotFoundError:
            self._alert(f"Validator heartbeat file not found at {self.heartbeat_file}. "
                        f"Has the validator ever run? Silent validator = undetected fabrication.")
            return False
        except Exception as e:
            self._alert(f"Watchdog check error: {e}")
            return False

    def _alert(self, message: str) -> None:
        msg = f"⚠️  ATTESTOR WATCHDOG: {message}"
        if self.notifier:
            self.notifier.alert(msg)
        else:
            print(msg)

    def last_run(self) -> Optional[datetime]:
        """Return the timestamp of the validator's last heartbeat, or None."""
        try:
            with open(self.heartbeat_file) as f:
                return datetime.fromisoformat(f.read().strip())
        except Exception:
            return None

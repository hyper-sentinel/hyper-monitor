"""Alert Dispatch — Desktop Notifications & Sound

macOS native notifications via pync, system sounds by severity,
voice alerts for critical, cooldown management.
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone

from risk_engine import Alert, AlertLevel
from state import MonitorState
from config import ALERT_COOLDOWN

logger = logging.getLogger(__name__)

# ──────────────────────── Alert History (in-memory) ──────────────────

_alert_log: list[tuple[str, Alert]] = []  # (timestamp_str, alert)
MAX_ALERT_LOG = 50


def get_recent_alerts(n: int = 10) -> list[tuple[str, Alert]]:
    """Return the last N alerts for display."""
    return _alert_log[-n:]


# ──────────────────────── Cooldown Check ─────────────────────────────


def _is_cooled_down(alert: Alert, state: MonitorState) -> bool:
    """Check if this alert key is past its cooldown period."""
    last_fired = state.alerts_sent.get(alert.key)
    if last_fired is None:
        return True

    try:
        last_dt = datetime.fromisoformat(last_fired)
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return elapsed >= ALERT_COOLDOWN
    except (ValueError, TypeError):
        return True


def _mark_fired(alert: Alert, state: MonitorState) -> None:
    """Record that this alert was just fired."""
    state.alerts_sent[alert.key] = datetime.now(timezone.utc).isoformat()


# ──────────────────────── Notification Dispatch ──────────────────────


SOUNDS = {
    AlertLevel.INFO: "Pop",
    AlertLevel.WARNING: "Purr",
    AlertLevel.DANGER: "Sosumi",
    AlertLevel.CRITICAL: "Basso",
}


def _send_desktop_notification(alert: Alert) -> None:
    """Send macOS native notification via pync."""
    try:
        import pync
        pync.notify(
            alert.message,
            title=f"🔔 HL Monitor: {alert.title}",
            sound=SOUNDS.get(alert.level, "Pop"),
            group="hl-monitor",
        )
    except ImportError:
        logger.debug("pync not available — skipping desktop notification")
    except Exception as exc:
        logger.debug("Desktop notification failed: %s", exc)


def _speak_alert(message: str) -> None:
    """Use macOS say command for voice alerts on critical."""
    try:
        subprocess.run(
            ["say", "-v", "Samantha", message],
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        logger.debug("'say' command not available")
    except Exception as exc:
        logger.debug("Voice alert failed: %s", exc)


# ──────────────────────── Main Dispatch ──────────────────────────────


def dispatch_alerts(alerts: list[Alert], state: MonitorState,
                    quiet: bool = False) -> list[Alert]:
    """Process a list of alerts: apply cooldowns, fire notifications.

    Returns the list of alerts that actually fired (passed cooldown).
    """
    fired: list[Alert] = []

    for alert in alerts:
        if not _is_cooled_down(alert, state):
            continue

        _mark_fired(alert, state)
        fired.append(alert)

        # Log to in-memory history
        ts = datetime.now().strftime("%H:%M")
        _alert_log.append((ts, alert))
        if len(_alert_log) > MAX_ALERT_LOG:
            _alert_log.pop(0)

        logger.info("ALERT [%s] %s: %s", alert.level.value, alert.title, alert.message)

        if not quiet:
            _send_desktop_notification(alert)

            # Voice alert for critical
            if alert.level == AlertLevel.CRITICAL:
                _speak_alert(alert.message)

    return fired

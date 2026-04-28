"""State Persistence

JSON-backed state file for baselines, HWM, alert cooldowns, and equity history.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent / "monitor_state.json"
MAX_HISTORY_ENTRIES = 2880  # ~24h at 30s interval


@dataclass
class MonitorState:
    # Wallet address (persisted so user only enters once)
    wallet_address: str = ""

    # Divergence tracker baselines
    baseline_equity: float = 0.0
    baseline_notional: float = 0.0
    baseline_timestamp: str = ""

    # Leverage ratchet
    best_leverage: float = 999.0

    # High water mark
    high_water_mark: float = 0.0
    hwm_timestamp: str = ""

    # Alert cooldowns: {alert_key: ISO timestamp of last fire}
    alerts_sent: dict[str, str | None] = field(default_factory=dict)

    # Last-seen margin milestone index (for directional milestones)
    last_margin_milestone_idx: int = -1

    # Equity history (list of dicts)
    equity_history: list[dict] = field(default_factory=list)

    # BTC action levels already triggered (set of price levels)
    btc_action_triggered: list[int] = field(default_factory=list)


def load_state() -> MonitorState:
    """Load state from disk, or return fresh state."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return MonitorState(
                wallet_address=data.get("wallet_address", ""),
                baseline_equity=data.get("baseline_equity", 0.0),
                baseline_notional=data.get("baseline_notional", 0.0),
                baseline_timestamp=data.get("baseline_timestamp", ""),
                best_leverage=data.get("best_leverage", 999.0),
                high_water_mark=data.get("high_water_mark", 0.0),
                hwm_timestamp=data.get("hwm_timestamp", ""),
                alerts_sent=data.get("alerts_sent", {}),
                last_margin_milestone_idx=data.get("last_margin_milestone_idx", -1),
                equity_history=data.get("equity_history", []),
                btc_action_triggered=data.get("btc_action_triggered", []),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Corrupt state file, starting fresh: %s", exc)
    return MonitorState()


def save_state(state: MonitorState) -> None:
    """Persist state to disk."""
    STATE_FILE.write_text(json.dumps(asdict(state), indent=2, default=str))


def record_equity(state: MonitorState, equity: float, notional: float,
                  leverage: float) -> None:
    """Append an equity reading and trim old entries."""
    now = datetime.now(timezone.utc).isoformat()
    state.equity_history.append({
        "timestamp": now,
        "equity": equity,
        "notional": notional,
        "leverage": leverage,
    })
    # Trim to keep memory bounded
    if len(state.equity_history) > MAX_HISTORY_ENTRIES:
        state.equity_history = state.equity_history[-MAX_HISTORY_ENTRIES:]


def update_hwm(state: MonitorState, equity: float) -> bool:
    """Update high water mark if equity is a new peak.  Returns True if new HWM."""
    if equity > state.high_water_mark:
        state.high_water_mark = equity
        state.hwm_timestamp = datetime.now(timezone.utc).isoformat()
        return True
    return False


def get_drawdown(state: MonitorState, equity: float) -> float:
    """Calculate drawdown from HWM as a percentage (negative number)."""
    if state.high_water_mark <= 0:
        return 0.0
    return (equity - state.high_water_mark) / state.high_water_mark * 100


def reset_baseline(state: MonitorState, equity: float, notional: float) -> None:
    """Reset the divergence tracker baseline."""
    state.baseline_equity = equity
    state.baseline_notional = notional
    state.baseline_timestamp = datetime.now(timezone.utc).isoformat()
    state.best_leverage = 999.0  # reset ratchet too
    logger.info("Baseline reset — equity: $%.2f, notional: $%.2f", equity, notional)


def should_init_baseline(state: MonitorState) -> bool:
    """Check if baseline needs initialization."""
    return state.baseline_equity == 0.0 or state.baseline_notional == 0.0

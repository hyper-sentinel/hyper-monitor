"""Risk Engine — All alert logic

Divergence tracker (priority #1), leverage/margin alerts, position-level
monitoring, funding alerts, drawdown alerts, BTC action levels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from hl_api import PortfolioState, Position
from state import MonitorState, get_drawdown
import config

logger = logging.getLogger(__name__)


# ──────────────────────────── Alert Types ─────────────────────────────

class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    DANGER = "danger"
    CRITICAL = "critical"


@dataclass
class Alert:
    level: AlertLevel
    key: str          # unique key for cooldown grouping
    title: str
    message: str
    emoji: str = ""

    def __str__(self) -> str:
        return f"{self.emoji} {self.title}: {self.message}"


# ──────────────────────────── Engine ──────────────────────────────────


def run_all_checks(portfolio: PortfolioState,
                   state: MonitorState) -> list[Alert]:
    """Run every risk check and return all triggered alerts."""
    alerts: list[Alert] = []

    alerts.extend(check_divergence(portfolio, state))
    alerts.extend(check_leverage(portfolio))
    alerts.extend(check_margin(portfolio, state))
    alerts.extend(check_account_ratio(portfolio))
    alerts.extend(check_liquidation_proximity(portfolio))
    alerts.extend(check_position_pnl(portfolio))
    alerts.extend(check_concentration(portfolio))
    alerts.extend(check_scale_out_targets(portfolio))
    alerts.extend(check_btc_action_levels(portfolio, state))
    alerts.extend(check_drawdown(portfolio, state))
    alerts.extend(check_leverage_ratchet(portfolio, state))
    alerts.extend(check_graduation(portfolio))
    alerts.extend(check_book_size(portfolio))
    alerts.extend(check_equity_floor(portfolio))

    return alerts


# ──────────────── 1. DIVERGENCE TRACKER (MOST IMPORTANT) ─────────────


def check_divergence(portfolio: PortfolioState,
                     state: MonitorState) -> list[Alert]:
    """Track when notional growth outpaces equity growth."""
    alerts: list[Alert] = []

    if state.baseline_equity <= 0 or state.baseline_notional <= 0:
        return alerts

    equity_change_pct = (
        (portfolio.equity - state.baseline_equity) / state.baseline_equity * 100
    )
    notional_change_pct = (
        (portfolio.total_notional - state.baseline_notional) / state.baseline_notional * 100
    )
    divergence = notional_change_pct - equity_change_pct

    # Auto-reset when things normalize
    if divergence < 5:
        if state.baseline_equity != portfolio.equity:
            # Only reset if we had a meaningful divergence before
            pass  # baseline stays — divergence is healthy
        return alerts

    thresholds = [
        (config.DIVERGENCE_CRITICAL, AlertLevel.CRITICAL, "💀",
         "This is how you blew up last time — DERISK NOW"),
        (config.DIVERGENCE_DANGER, AlertLevel.DANGER, "🔴",
         "Leverage spiral detected — notional {div:.0f}%+ ahead of equity"),
        (config.DIVERGENCE_CAUTION, AlertLevel.WARNING, "🔶",
         "Significant leverage expansion — consider trimming"),
        (config.DIVERGENCE_WARNING, AlertLevel.WARNING, "⚠️",
         "Notional growing faster than equity — leverage creeping"),
    ]

    for threshold, level, emoji, msg_template in thresholds:
        if divergence >= threshold:
            alerts.append(Alert(
                level=level,
                key=f"divergence_{threshold}",
                title="Leverage Divergence",
                message=msg_template.format(div=divergence),
                emoji=emoji,
            ))
            break  # only fire the highest threshold

    return alerts


# ──────────────── 2. LEVERAGE ALERTS ─────────────────────────────────


def check_leverage(portfolio: PortfolioState) -> list[Alert]:
    alerts: list[Alert] = []
    lev = portfolio.unified_leverage

    if lev >= config.LEVERAGE_CRITICAL:
        alerts.append(Alert(
            AlertLevel.CRITICAL, "leverage_30x",
            "Leverage CRITICAL",
            f"CRITICAL: Leverage above {config.LEVERAGE_CRITICAL}x ({lev:.1f}x) — derisk immediately",
            "💀",
        ))
    elif lev >= config.LEVERAGE_DANGER:
        alerts.append(Alert(
            AlertLevel.DANGER, "leverage_25x",
            "Leverage DANGER",
            f"DANGER: Leverage above {config.LEVERAGE_DANGER}x ({lev:.1f}x)",
            "🔴",
        ))
    elif lev >= config.LEVERAGE_WARNING:
        alerts.append(Alert(
            AlertLevel.WARNING, "leverage_20x",
            "Leverage High",
            f"Leverage above {config.LEVERAGE_WARNING}x ({lev:.1f}x)",
            "⚠️",
        ))

    return alerts


# ──────────────── 3. MARGIN ALERTS ───────────────────────────────────


def check_margin(portfolio: PortfolioState,
                 state: MonitorState) -> list[Alert]:
    alerts: list[Alert] = []
    avail = portfolio.available_margin
    equity = portfolio.equity

    # Critically low margin
    if equity > 0 and (avail / equity * 100) < config.MARGIN_LOW_PCT:
        alerts.append(Alert(
            AlertLevel.WARNING, "margin_low",
            "Margin Low",
            f"Available margin critically low: ${avail:.2f} ({avail/equity*100:.1f}% of equity)",
            "⚠️",
        ))

    # Margin milestones (directional — only fire on crossing UP)
    current_idx = -1
    for i, milestone in enumerate(config.MARGIN_MILESTONES):
        if avail >= milestone:
            current_idx = i

    if current_idx > state.last_margin_milestone_idx and current_idx >= 0:
        milestone_val = config.MARGIN_MILESTONES[current_idx]
        if state.last_margin_milestone_idx >= 0:  # don't alert on first run
            alerts.append(Alert(
                AlertLevel.INFO, f"margin_milestone_{milestone_val}",
                "Margin Milestone",
                f"Available margin milestone: ${milestone_val:,.0f} (current: ${avail:.2f})",
                "🟢",
            ))
        state.last_margin_milestone_idx = current_idx
    elif current_idx < state.last_margin_milestone_idx:
        # Margin dropped — update index but don't alert (alert on recovery)
        state.last_margin_milestone_idx = current_idx

    return alerts


# ──────────────── 4. ACCOUNT RATIO ───────────────────────────────────


def check_account_ratio(portfolio: PortfolioState) -> list[Alert]:
    alerts: list[Alert] = []
    ratio = portfolio.account_ratio

    if ratio >= config.ACCOUNT_RATIO_CRITICAL:
        alerts.append(Alert(
            AlertLevel.CRITICAL, "ratio_critical",
            "Account Ratio CRITICAL",
            f"CRITICAL: Approaching liquidation — ratio {ratio:.1f}%",
            "💀",
        ))
    elif ratio >= config.ACCOUNT_RATIO_WARNING:
        alerts.append(Alert(
            AlertLevel.WARNING, "ratio_warning",
            "Account Ratio High",
            f"Account ratio above {config.ACCOUNT_RATIO_WARNING}% ({ratio:.1f}%)",
            "⚠️",
        ))

    return alerts


# ──────────────── 5. LIQUIDATION PROXIMITY ───────────────────────────


def check_liquidation_proximity(portfolio: PortfolioState) -> list[Alert]:
    alerts: list[Alert] = []

    for pos in portfolio.positions:
        if pos.liquidation_price <= 0 or pos.mark_price <= 0:
            continue

        # Distance to liquidation
        if pos.size > 0:  # long — liq is below
            dist_pct = (pos.mark_price - pos.liquidation_price) / pos.mark_price * 100
        else:  # short — liq is above
            dist_pct = (pos.liquidation_price - pos.mark_price) / pos.mark_price * 100

        if dist_pct < config.LIQ_CRITICAL_PCT:
            alerts.append(Alert(
                AlertLevel.CRITICAL, f"liq_{pos.coin}_3pct",
                f"{pos.coin} Liquidation IMMINENT",
                f"LIQUIDATION WARNING: {pos.coin} — liq {dist_pct:.1f}% away (${pos.liquidation_price:,.2f})",
                "💀",
            ))
        elif dist_pct < config.LIQ_WARNING_PCT:
            if pos.coin == "BTC":
                alerts.append(Alert(
                    AlertLevel.DANGER, f"liq_BTC_5pct",
                    "BTC Liquidation Close",
                    f"BTC liquidation price within {dist_pct:.1f}% (${pos.liquidation_price:,.2f})",
                    "🔴",
                ))
            else:
                alerts.append(Alert(
                    AlertLevel.DANGER, f"liq_{pos.coin}_5pct",
                    f"{pos.coin} Liquidation Close",
                    f"{pos.coin} liquidation price within {dist_pct:.1f}%",
                    "🔴",
                ))

    return alerts


# ──────────────── 6. POSITION PnL ────────────────────────────────────


def check_position_pnl(portfolio: PortfolioState) -> list[Alert]:
    alerts: list[Alert] = []

    for pos in portfolio.positions:
        pnl = pos.unrealized_pnl

        for threshold in sorted(config.PNL_THRESHOLDS, reverse=True):
            if pnl >= threshold:
                alerts.append(Alert(
                    AlertLevel.INFO, f"pnl_{pos.coin}_+{threshold}",
                    f"{pos.coin} Profit",
                    f"{pos.coin} unrealized PnL above +${threshold:,} (+${pnl:,.2f})",
                    "💰",
                ))
                break  # only highest
            elif pnl <= -threshold:
                alerts.append(Alert(
                    AlertLevel.WARNING, f"pnl_{pos.coin}_-{threshold}",
                    f"{pos.coin} Loss",
                    f"{pos.coin} unrealized PnL below -${threshold:,} (-${abs(pnl):,.2f})",
                    "📉",
                ))
                break

    return alerts


# ──────────────── 7. CONCENTRATION ───────────────────────────────────


def check_concentration(portfolio: PortfolioState) -> list[Alert]:
    alerts: list[Alert] = []

    if portfolio.total_notional <= 0:
        return alerts

    for pos in portfolio.positions:
        pct = pos.position_value / portfolio.total_notional * 100
        if pct > config.MAX_SINGLE_POSITION_PCT:
            alerts.append(Alert(
                AlertLevel.WARNING, f"concentration_{pos.coin}",
                "Position Concentration",
                f"{pos.coin} is {pct:.1f}% of total notional — Hard Rule #3 violated",
                "⚠️",
            ))

    return alerts


# ──────────────── 8. SCALE-OUT TARGETS ───────────────────────────────


def check_scale_out_targets(portfolio: PortfolioState) -> list[Alert]:
    alerts: list[Alert] = []

    for pos in portfolio.positions:
        targets = config.SCALE_OUT_TARGETS.get(pos.coin)
        if not targets or pos.mark_price <= 0:
            continue

        for target in targets:
            proximity = abs(pos.mark_price - target) / target * 100
            if proximity <= config.SCALE_OUT_PROXIMITY_PCT:
                alerts.append(Alert(
                    AlertLevel.INFO, f"scaleout_{pos.coin}_{target}",
                    f"{pos.coin} Scale-Out",
                    f"{pos.coin} approaching scale-out at ${target:,} — current ${pos.mark_price:,.2f}",
                    "🎯",
                ))

    return alerts


# ──────────────── 9. BTC ACTION LEVELS ───────────────────────────────


def check_btc_action_levels(portfolio: PortfolioState,
                            state: MonitorState) -> list[Alert]:
    alerts: list[Alert] = []

    btc_pos = None
    for pos in portfolio.positions:
        if pos.coin == "BTC":
            btc_pos = pos
            break

    if not btc_pos or btc_pos.mark_price <= 0:
        return alerts

    mark = btc_pos.mark_price

    for level, (label, action) in sorted(config.BTC_ACTION_LEVELS.items(), reverse=True):
        if mark <= level and level not in state.btc_action_triggered:
            alerts.append(Alert(
                AlertLevel.CRITICAL if "EMERGENCY" in label or "LIQUIDATION" in label else AlertLevel.DANGER,
                f"btc_action_{level}",
                f"BTC {label}",
                f"BTC at ${mark:,.0f} — {action}",
                label.split(" ")[0],  # use the emoji from the label
            ))
            state.btc_action_triggered.append(level)

    # Reset triggered levels when price recovers above them
    state.btc_action_triggered = [
        lvl for lvl in state.btc_action_triggered if mark <= lvl
    ]

    return alerts


# ──────────────── 10. DRAWDOWN ───────────────────────────────────────


def check_drawdown(portfolio: PortfolioState,
                   state: MonitorState) -> list[Alert]:
    alerts: list[Alert] = []

    dd = get_drawdown(state, portfolio.equity)
    if dd >= 0:
        return alerts  # no drawdown

    for threshold in config.DRAWDOWN_THRESHOLDS:
        if abs(dd) >= threshold:
            level = AlertLevel.CRITICAL if threshold >= 40 else (
                AlertLevel.DANGER if threshold >= 30 else AlertLevel.WARNING
            )
            alerts.append(Alert(
                level, f"drawdown_{threshold}",
                f"Drawdown Alert",
                f"Equity down {dd:.1f}% from high water mark (${state.high_water_mark:,.2f})",
                "📉" if threshold < 30 else "🔴" if threshold < 40 else "💀",
            ))
            break  # only highest threshold

    return alerts


# ──────────────── 11. LEVERAGE RATCHET ───────────────────────────────


def check_leverage_ratchet(portfolio: PortfolioState,
                           state: MonitorState) -> list[Alert]:
    """Alert when current leverage exceeds the best-seen leverage by threshold gaps."""
    alerts: list[Alert] = []
    current = portfolio.unified_leverage

    # Update best leverage
    if current < state.best_leverage:
        state.best_leverage = current

    gap = current - state.best_leverage

    for threshold in sorted(config.LEVERAGE_RATCHET_GAPS, reverse=True):
        if gap >= threshold:
            alerts.append(Alert(
                AlertLevel.WARNING if threshold <= 3 else AlertLevel.DANGER,
                f"ratchet_{threshold}",
                "Leverage Ratchet",
                f"Current leverage {current:.1f}x is {gap:.1f} points above best ({state.best_leverage:.1f}x)",
                "📈",
            ))
            break

    return alerts


# ──────────────── 12. GRADUATION ─────────────────────────────────────


def check_graduation(portfolio: PortfolioState) -> list[Alert]:
    """Alert when equity crosses the graduation HWM for this phase."""
    alerts: list[Alert] = []
    hwm = config.GRADUATION_HWM
    trim_to = config.GRADUATION_TRIM_TO

    if hwm is None:
        return alerts  # Saylor mode — no graduation

    if portfolio.equity >= hwm:
        alerts.append(Alert(
            AlertLevel.INFO, f"graduation_phase{config.ACTIVE_PHASE}",
            "🎓 GRADUATION",
            f"Equity ${portfolio.equity:,.0f} crossed ${hwm:,.0f} — execute {trim_to}x trim to enter Phase {config.ACTIVE_PHASE + 1}",
            "🎓",
        ))

    return alerts


# ──────────────── 13. BOOK SIZE ──────────────────────────────────────


def check_book_size(portfolio: PortfolioState) -> list[Alert]:
    """Alert when total notional drifts outside the phase anchor band."""
    alerts: list[Alert] = []
    _P = config.PHASES[config.ACTIVE_PHASE]
    low = _P["book_anchor_low"]
    high = _P["book_anchor_high"]
    ntl = portfolio.total_notional

    if ntl > high:
        alerts.append(Alert(
            AlertLevel.WARNING, "book_above_anchor",
            "Book Oversized",
            f"Notional ${ntl:,.0f} above Phase {config.ACTIVE_PHASE} anchor ceiling ${high:,.0f} — trim or expect higher vol",
            "📏",
        ))
    elif ntl < low:
        alerts.append(Alert(
            AlertLevel.INFO, "book_below_anchor",
            "Book Undersized",
            f"Notional ${ntl:,.0f} below Phase {config.ACTIVE_PHASE} anchor floor ${low:,.0f} — room to add",
            "📐",
        ))

    return alerts


# ──────────────── 14. EQUITY FLOOR ───────────────────────────────────


def check_equity_floor(portfolio: PortfolioState) -> list[Alert]:
    """Alert when equity drops below the phase floor — risk of phase regression."""
    alerts: list[Alert] = []
    _P = config.PHASES[config.ACTIVE_PHASE]
    floor = _P["equity_floor"]

    if portfolio.equity < floor:
        alerts.append(Alert(
            AlertLevel.DANGER, "equity_below_floor",
            "Equity Below Phase Floor",
            f"Equity ${portfolio.equity:,.0f} below Phase {config.ACTIVE_PHASE} floor ${floor:,.0f} — phase regression risk",
            "🔻",
        ))

    return alerts

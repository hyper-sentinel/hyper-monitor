"""Rich Terminal Dashboard

Beautiful live-updating terminal display using the rich library.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import config
from hl_api import PortfolioState
from state import MonitorState, get_drawdown
from alerts import get_recent_alerts

logger = logging.getLogger(__name__)
console = Console()

# ─────────────────────── Color Helpers ───────────────────────────────


def _pnl_color(val: float) -> str:
    if val > 0:
        return "green"
    elif val < 0:
        return "red"
    return "white"


def _pnl_str(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}${val:,.2f}"


def _pct_str(val: float) -> str:
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def _leverage_color(lev: float) -> str:
    if lev >= config.LEVERAGE_CRITICAL:
        return "bold red"
    elif lev >= config.LEVERAGE_DANGER:
        return "red"
    elif lev >= config.LEVERAGE_WARNING:
        return "yellow"
    elif lev >= config.LEVERAGE_CEILING:
        return "bright_yellow"
    elif lev >= config.LEVERAGE_OPERATING:
        return "cyan"
    return "green"


# ─────────────────────── Sparkline ───────────────────────────────────

SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 20) -> str:
    """Generate a mini sparkline from a list of values."""
    if not values:
        return ""
    recent = values[-width:]
    if len(recent) < 2:
        return SPARK_CHARS[4] * len(recent)

    mn, mx = min(recent), max(recent)
    rng = mx - mn
    if rng == 0:
        return SPARK_CHARS[4] * len(recent)

    return "".join(
        SPARK_CHARS[int((v - mn) / rng * (len(SPARK_CHARS) - 1))]
        for v in recent
    )


# ─────────────────────── Dashboard Sections ──────────────────────────


def _build_header(portfolio: PortfolioState) -> Panel:
    ts = portfolio.timestamp.astimezone().strftime("%I:%M:%S %p %Z")
    return Panel(
        Text("HYPERLIQUID PORTFOLIO MONITOR", style="bold cyan", justify="center"),
        subtitle=f"Last Update: {ts}",
        style="bright_cyan",
    )


def _build_summary(portfolio: PortfolioState, state: MonitorState) -> Panel:
    lev = portfolio.unified_leverage
    dd = get_drawdown(state, portfolio.equity)

    grid = Table.grid(padding=(0, 3))
    grid.add_column(justify="right", style="bright_white")
    grid.add_column(style="bold")
    grid.add_column(justify="right", style="bright_white")
    grid.add_column(style="bold")
    grid.add_column(justify="right", style="bright_white")
    grid.add_column(style="bold")

    # Row 1: Core metrics (matches Hyperliquid UI naming)
    grid.add_row(
        "Portfolio Value:", f"[bright_green]${portfolio.equity:,.2f}[/]",
        "Unified Leverage:", f"[{_leverage_color(lev)}]{lev:.2f}x[/]",
        "Account Ratio:", f"[{'red' if portfolio.account_ratio > 60 else 'yellow' if portfolio.account_ratio > 40 else 'green'}]{portfolio.account_ratio:.1f}%[/]",
    )
    # Row 2: Margin details
    grid.add_row(
        "Available:", f"[bright_cyan]${portfolio.available_margin:,.2f}[/]",
        "Maint Margin:", f"${portfolio.maintenance_margin:,.2f}",
        "Total Notional:", f"${portfolio.total_notional:,.2f}",
    )
    # Row 3: PnL & drawdown
    unreal_color = _pnl_color(portfolio.unrealized_pnl)
    hwm_str = f"${state.high_water_mark:,.2f}" if state.high_water_mark > 0 else "—"
    dd_str = f"{dd:.1f}%" if state.high_water_mark > 0 else "—"

    grid.add_row(
        "Unrealized PnL:", f"[{unreal_color}]{_pnl_str(portfolio.unrealized_pnl)}[/]",
        "High Water Mark:", f"[bright_yellow]{hwm_str}[/]",
        "Drawdown:", f"[{'red' if dd < -20 else 'yellow' if dd < -10 else 'green'}]{dd_str}[/]",
    )

    # Row 4: Phase + sparkline
    phase = config.ACTIVE_PHASE
    grad_hwm = config.GRADUATION_HWM
    if grad_hwm:
        progress = f"${portfolio.equity:,.0f} / ${grad_hwm:,.0f}"
        pct_done = min(100, portfolio.equity / grad_hwm * 100)
        phase_str = f"Phase {phase} │ {progress} ({pct_done:.0f}%)"
    else:
        phase_str = f"Phase {phase} │ Saylor Mode 🏦"

    equity_vals = [e["equity"] for e in state.equity_history]
    spark = sparkline(equity_vals)
    grid.add_row(
        "Phase:", f"[bright_magenta]{phase_str}[/]",
        "Trend:", f"[dim cyan]{spark}[/]" if spark else "[dim]—[/]",
        "", "",
    )

    return Panel(grid, title="[bold]Unified Account Summary[/]", border_style="bright_blue")


def _build_divergence(portfolio: PortfolioState, state: MonitorState) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style="bright_white")
    grid.add_column()

    if state.baseline_equity > 0 and state.baseline_notional > 0:
        eq_delta = (portfolio.equity - state.baseline_equity) / state.baseline_equity * 100
        nt_delta = (portfolio.total_notional - state.baseline_notional) / state.baseline_notional * 100
        div = nt_delta - eq_delta

        if div < 5:
            status = "[bold green]✅ HEALTHY — notional lagging equity (good)[/]"
        elif div < 10:
            status = "[yellow]⚠️  WATCH — divergence building[/]"
        elif div < 20:
            status = "[bold yellow]🔶 CAUTION — leverage expanding[/]"
        elif div < 30:
            status = "[bold red]🔴 DANGER — leverage spiral[/]"
        else:
            status = "[bold red blink]💀 CRITICAL — DERISK NOW[/]"

        grid.add_row("Baseline Equity:", f"${state.baseline_equity:,.2f}")
        grid.add_row("Baseline Notional:", f"${state.baseline_notional:,.2f}")
        grid.add_row(
            "Equity Δ:",
            f"[{_pnl_color(eq_delta)}]{_pct_str(eq_delta)}[/]",
        )
        grid.add_row(
            "Notional Δ:",
            f"[{_pnl_color(nt_delta)}]{_pct_str(nt_delta)}[/]",
        )
        grid.add_row(
            "Divergence:",
            f"[{'red' if div > 10 else 'yellow' if div > 5 else 'green'}]{_pct_str(div)}[/]",
        )
        grid.add_row("Status:", status)

        best_lev = state.best_leverage if state.best_leverage < 999 else portfolio.unified_leverage
        gap = portfolio.unified_leverage - best_lev
        grid.add_row(
            "Lever Ratchet:",
            f"Best {best_lev:.1f}x │ Current {portfolio.unified_leverage:.1f}x │ Gap {_pct_str(gap)} pts",
        )
    else:
        grid.add_row("", "[dim]Baseline not set — run --reset-baseline[/]")

    return Panel(grid, title="[bold]Divergence Tracker[/]", border_style="magenta")


def _build_positions(portfolio: PortfolioState) -> Panel:
    table = Table(
        show_header=True, header_style="bold bright_white",
        border_style="dim", box=None, padding=(0, 1),
    )
    table.add_column("Coin", style="bold cyan", width=6)
    table.add_column("Size", justify="right")
    table.add_column("Entry", justify="right")
    table.add_column("Mark", justify="right")
    table.add_column("Lev", justify="right", width=4)
    table.add_column("PnL", justify="right")
    table.add_column("ROE", justify="right")
    table.add_column("Liq Px", justify="right")
    table.add_column("Notional", justify="right")
    table.add_column("Funding", justify="right")

    # Sort by position value descending
    sorted_pos = sorted(portfolio.positions, key=lambda p: p.position_value, reverse=True)

    for pos in sorted_pos:
        pnl_c = _pnl_color(pos.unrealized_pnl)
        roe_pct = pos.roe * 100
        funding_c = _pnl_color(-pos.funding_rate)  # negative funding = you're paying

        # Format size intelligently
        if abs(pos.size) >= 100:
            size_str = f"{pos.size:,.0f}"
        elif abs(pos.size) >= 1:
            size_str = f"{pos.size:,.2f}"
        else:
            size_str = f"{pos.size:,.4f}"

        # Format entry price
        if pos.entry_price >= 1000:
            entry_str = f"${pos.entry_price:,.0f}"
        elif pos.entry_price >= 1:
            entry_str = f"${pos.entry_price:,.2f}"
        else:
            entry_str = f"${pos.entry_price:,.4f}"

        # Format mark price
        if pos.mark_price >= 1000:
            mark_str = f"${pos.mark_price:,.0f}"
        elif pos.mark_price >= 1:
            mark_str = f"${pos.mark_price:,.2f}"
        else:
            mark_str = f"${pos.mark_price:,.4f}"

        # Format liq price
        if pos.liquidation_price >= 1000:
            liq_str = f"${pos.liquidation_price:,.0f}"
        elif pos.liquidation_price >= 1:
            liq_str = f"${pos.liquidation_price:,.2f}"
        else:
            liq_str = f"${pos.liquidation_price:,.4f}"

        table.add_row(
            pos.coin,
            size_str,
            entry_str,
            mark_str,
            f"[{_leverage_color(pos.leverage)}]{pos.leverage}x[/]",
            f"[{pnl_c}]{_pnl_str(pos.unrealized_pnl)}[/]",
            f"[{pnl_c}]{_pct_str(roe_pct)}[/]",
            liq_str,
            f"${pos.position_value:,.0f}",
            f"[{funding_c}]${pos.funding_rate:,.2f}[/]",
        )

    return Panel(table, title="[bold]Positions[/]", border_style="bright_green")


def _build_alerts_panel() -> Panel:
    recent = get_recent_alerts(10)

    if not recent:
        content = Text("No alerts yet", style="dim")
    else:
        lines = Text()
        for ts, alert in reversed(recent):
            color = {
                "info": "green",
                "warning": "yellow",
                "danger": "red",
                "critical": "bold red",
            }.get(alert.level.value, "white")
            lines.append(f"  {ts} ", style="dim")
            lines.append(f"{alert.emoji} ", style=color)
            lines.append(f"{alert.message}\n", style=color)
        content = lines

    return Panel(content, title="[bold]Recent Alerts[/]", border_style="bright_yellow")


# ─────────────────────── Full Dashboard ──────────────────────────────


def render_dashboard(portfolio: PortfolioState, state: MonitorState) -> Layout:
    """Build the full dashboard layout."""
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="alerts", size=14),
    )

    layout["body"].split_column(
        Layout(name="summary", size=7),
        Layout(name="middle"),
        Layout(name="positions"),
    )

    layout["middle"].split_row(
        Layout(name="divergence"),
    )

    layout["header"].update(_build_header(portfolio))
    layout["summary"].update(_build_summary(portfolio, state))
    layout["divergence"].update(_build_divergence(portfolio, state))
    layout["positions"].update(_build_positions(portfolio))
    layout["alerts"].update(_build_alerts_panel())

    return layout


def print_snapshot(portfolio: PortfolioState, state: MonitorState) -> None:
    """Print a one-shot snapshot (non-live)."""
    console.print()
    console.print(_build_header(portfolio))
    console.print(_build_summary(portfolio, state))
    console.print(_build_divergence(portfolio, state))
    console.print(_build_positions(portfolio))
    console.print(_build_alerts_panel())
    console.print()


def print_history(state: MonitorState) -> None:
    """Print equity history as ASCII chart."""
    history = state.equity_history

    if not history:
        console.print("[yellow]No equity history recorded yet.[/]")
        return

    equities = [e["equity"] for e in history]
    leverages = [e["leverage"] for e in history]

    console.print()
    console.print(Panel(
        f"[bold]Equity History[/] — {len(history)} readings\n\n"
        f"  Current:  ${equities[-1]:,.2f}\n"
        f"  Peak:     ${max(equities):,.2f}\n"
        f"  Low:      ${min(equities):,.2f}\n"
        f"  Avg:      ${sum(equities)/len(equities):,.2f}\n\n"
        f"  Trend:    {sparkline(equities, 40)}\n"
        f"  Leverage: {sparkline(leverages, 40)}\n\n"
        f"  First: {history[0]['timestamp']}\n"
        f"  Last:  {history[-1]['timestamp']}",
        title="[bold cyan]Equity Curve[/]",
        border_style="cyan",
    ))
    console.print()

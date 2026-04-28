#!/usr/bin/env python3
"""Hyperliquid Portfolio Monitor — Main Entrypoint

Usage:
    uv run monitor.py                   # live dashboard (default)
    uv run monitor.py --snapshot        # one-shot print & exit
    uv run monitor.py --reset-baseline  # reset divergence baseline
    uv run monitor.py --history         # show equity history chart
    uv run monitor.py --alert COIN PX   # set custom price alert
    uv run monitor.py --quiet           # no desktop notifications
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.live import Live

import config
from hl_api import get_portfolio, set_wallet_address, PortfolioState
from state import (
    MonitorState, load_state, save_state, record_equity,
    update_hwm, reset_baseline, should_init_baseline,
)
from risk_engine import run_all_checks
from alerts import dispatch_alerts
from dashboard import render_dashboard, print_snapshot, print_history, console

logger = logging.getLogger(__name__)

# ─────────────────────── Globals ─────────────────────────────────────

_running = True


def _shutdown(signum, frame):
    global _running
    _running = False
    console.print("\n[yellow]Shutting down gracefully…[/]")


# ─────────────────────── CLI ─────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hyperliquid Portfolio Monitor — leverage divergence tracker & risk alerts",
    )
    parser.add_argument(
        "--snapshot", action="store_true",
        help="One-shot: print current state and exit",
    )
    parser.add_argument(
        "--reset-baseline", action="store_true",
        help="Reset the divergence tracker baseline to current values",
    )
    parser.add_argument(
        "--history", action="store_true",
        help="Show equity history / drawdown chart",
    )
    parser.add_argument(
        "--alert", nargs=2, metavar=("COIN", "PRICE"),
        help="Set a custom price alert (e.g., --alert FARTCOIN 0.25)",
    )
    parser.add_argument(
        "--wallet", type=str, metavar="0x...",
        help="Wallet address to monitor (overrides saved address)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="No desktop notifications, terminal-only",
    )
    parser.add_argument(
        "--log-level", default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: WARNING)",
    )
    return parser.parse_args()


# ─────────────────────── Wallet Resolution ───────────────────────────

_ETH_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _validate_address(addr: str) -> bool:
    """Check if string looks like a valid Ethereum address."""
    return bool(_ETH_ADDR_RE.match(addr.strip()))


def resolve_wallet(args: argparse.Namespace, state: MonitorState) -> str:
    """Determine wallet address.  Priority: --wallet flag > HL_WALLET env > saved state > prompt."""

    # 1. CLI flag
    if args.wallet:
        addr = args.wallet.strip()
        if not _validate_address(addr):
            console.print(f"[red]Invalid address: {addr}[/]")
            sys.exit(1)
        return addr

    # 2. Environment variable
    env_addr = os.environ.get("HL_WALLET", "").strip()
    if env_addr:
        if not _validate_address(env_addr):
            console.print(f"[red]Invalid HL_WALLET env var: {env_addr}[/]")
            sys.exit(1)
        return env_addr

    # 3. Saved in state file
    if state.wallet_address and _validate_address(state.wallet_address):
        return state.wallet_address

    # 4. Interactive prompt
    console.print()
    console.print("[bold cyan]╭─────────────────────────────────────────╮[/]")
    console.print("[bold cyan]│   HYPERLIQUID PORTFOLIO MONITOR SETUP   │[/]")
    console.print("[bold cyan]╰─────────────────────────────────────────╯[/]")
    console.print()
    console.print("[dim]Enter your Hyperliquid wallet address (read-only, no auth needed).[/]")
    console.print("[dim]This is the 0x... address shown on your Hyperliquid portfolio page.[/]")
    console.print()

    while True:
        addr = console.input("[bold yellow]  Wallet address → [/]").strip()
        if _validate_address(addr):
            return addr
        console.print("[red]  Invalid Ethereum address. Must be 0x followed by 40 hex characters.[/]")
        console.print("[dim]  Example: 0x000000000000000000000000000000000000dEaD[/]")
        console.print()


# ─────────────────────── Core Loop ───────────────────────────────────


def poll_once(state: MonitorState, quiet: bool = False) -> PortfolioState | None:
    """Fetch portfolio, run risk checks, dispatch alerts, update state."""
    try:
        portfolio = get_portfolio()
    except Exception as exc:
        logger.error("Poll failed: %s — retrying next cycle", exc)
        return None

    # Initialize baseline on first run if needed
    if should_init_baseline(state):
        reset_baseline(state, portfolio.equity, portfolio.total_notional)

    # Update high water mark
    update_hwm(state, portfolio.equity)

    # Record equity reading
    record_equity(state, portfolio.equity, portfolio.total_notional,
                  portfolio.unified_leverage)

    # Run all risk checks
    alerts = run_all_checks(portfolio, state)

    # Dispatch (apply cooldowns, send notifications)
    dispatch_alerts(alerts, state, quiet=quiet)

    # Persist state
    save_state(state)

    return portfolio


def run_live(state: MonitorState, quiet: bool = False) -> None:
    """Run the live dashboard with polling."""
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    console.print("[bold cyan]Starting Hyperliquid Portfolio Monitor…[/]")
    console.print(f"[dim]Polling every {config.POLL_INTERVAL_SECONDS}s • Ctrl+C to stop[/]\n")

    # Initial poll
    portfolio = poll_once(state, quiet)
    if portfolio is None:
        console.print("[red]Failed to fetch initial portfolio — check your connection.[/]")
        return

    with Live(render_dashboard(portfolio, state), console=console,
              refresh_per_second=0.5, screen=True) as live:
        last_poll = time.time()

        while _running:
            now = time.time()

            if now - last_poll >= config.POLL_INTERVAL_SECONDS:
                new_portfolio = poll_once(state, quiet)
                if new_portfolio is not None:
                    portfolio = new_portfolio
                last_poll = now

            live.update(render_dashboard(portfolio, state))
            time.sleep(1)

    console.print("[green]Monitor stopped.[/]")
    save_state(state)


# ─────────────────────── Entry Point ─────────────────────────────────


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    state = load_state()

    # ─── Resolve wallet address ───
    wallet = resolve_wallet(args, state)
    set_wallet_address(wallet)

    # Persist if new or changed
    if state.wallet_address != wallet:
        state.wallet_address = wallet
        save_state(state)
        console.print(f"[green]✅ Wallet saved: {wallet}[/]")
        console.print(f"[dim]   (stored in monitor_state.json — won't ask again)[/]\n")

    # ─── --history ───
    if args.history:
        print_history(state)
        return

    # ─── --reset-baseline ───
    if args.reset_baseline:
        try:
            portfolio = get_portfolio()
        except Exception as exc:
            console.print(f"[red]API error: {exc}[/]")
            sys.exit(1)
        reset_baseline(state, portfolio.equity, portfolio.total_notional)
        save_state(state)
        console.print(f"[green]✅ Baseline reset — equity: ${portfolio.equity:,.2f}, notional: ${portfolio.total_notional:,.2f}[/]")
        return

    # ─── --alert COIN PRICE ───
    if args.alert:
        coin, px = args.alert
        try:
            price = float(px)
        except ValueError:
            console.print(f"[red]Invalid price: {px}[/]")
            sys.exit(1)
        # Add to scale-out targets
        targets = config.SCALE_OUT_TARGETS.setdefault(coin.upper(), [])
        targets.append(price)
        targets.sort()
        console.print(f"[green]✅ Alert set: {coin.upper()} at ${price:,.4f}[/]")
        console.print(f"[dim]Note: custom alerts are session-only. Edit config.py for persistence.[/]")
        return

    # ─── --snapshot ───
    if args.snapshot:
        try:
            portfolio = get_portfolio()
        except Exception as exc:
            console.print(f"[red]API error: {exc}[/]")
            sys.exit(1)

        if should_init_baseline(state):
            reset_baseline(state, portfolio.equity, portfolio.total_notional)

        update_hwm(state, portfolio.equity)
        record_equity(state, portfolio.equity, portfolio.total_notional,
                      portfolio.unified_leverage)

        alerts = run_all_checks(portfolio, state)
        dispatch_alerts(alerts, state, quiet=True)  # no notifications for snapshot
        save_state(state)

        print_snapshot(portfolio, state)
        return

    # ─── default: live dashboard ───
    run_live(state, quiet=args.quiet)


if __name__ == "__main__":
    main()

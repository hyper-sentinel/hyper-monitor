"""Hyperliquid API Client

All HTTP calls to the Hyperliquid Info API.  Returns typed dataclasses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

from config import API_URL

logger = logging.getLogger(__name__)

# ──────────────────────── Wallet Address (set at runtime) ─────────────

_wallet_address: str = ""


def set_wallet_address(address: str) -> None:
    """Set the wallet address for all API calls."""
    global _wallet_address
    _wallet_address = address


def get_wallet_address() -> str:
    """Get the currently configured wallet address."""
    return _wallet_address


# ──────────────────────────── Data Models ─────────────────────────────


@dataclass
class Position:
    coin: str
    size: float             # signed (negative = short)
    entry_price: float
    mark_price: float
    leverage: int
    position_value: float   # notional
    unrealized_pnl: float
    roe: float
    liquidation_price: float
    margin_used: float
    funding_rate: float     # cumFunding.sinceOpen


@dataclass
class SpotBalance:
    coin: str
    total: float            # total balance held
    hold: float             # amount pledged as perps collateral
    free: float             # total - hold (usable / withdrawable)
    mark_price: float       # USD per unit
    usd_value: float        # total * mark_price


# Stablecoins that back the unified account at $1 (extend as needed)
STABLE_COINS = {"USDC", "USDE", "USDT", "USDT0", "USDH", "DAI", "USDB"}


@dataclass
class PortfolioState:
    timestamp: datetime
    equity: float
    available_margin: float
    maintenance_margin: float
    unified_leverage: float
    account_ratio: float
    total_notional: float
    unrealized_pnl: float
    positions: list[Position] = field(default_factory=list)
    spot_balances: list[SpotBalance] = field(default_factory=list)


# ──────────────────────────── API Calls ───────────────────────────────


def _post(payload: dict) -> dict | list:
    """POST to the Hyperliquid info endpoint."""
    resp = requests.post(API_URL, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ─── Max leverage cache (fetched once per session) ──────────────────
_max_leverage_cache: dict[str, int] = {}


def _get_max_leverages() -> dict[str, int]:
    """Fetch and cache per-asset max leverage from HL meta endpoint."""
    global _max_leverage_cache
    if _max_leverage_cache:
        return _max_leverage_cache
    try:
        meta = _post({"type": "meta"})
        for u in meta.get("universe", []):
            _max_leverage_cache[u["name"]] = int(u.get("maxLeverage", 50))
        logger.info("Cached max leverage for %d assets", len(_max_leverage_cache))
    except Exception as exc:
        logger.warning("Failed to fetch meta for max leverages: %s", exc)
    return _max_leverage_cache


def fetch_clearinghouse_state(dex: str = "") -> dict:
    """Raw clearinghouseState response. Use dex='xyz' for xyz positions."""
    payload = {"type": "clearinghouseState", "user": _wallet_address}
    if dex:
        payload["dex"] = dex
    return _post(payload)


def fetch_spot_state() -> dict:
    """Raw spotClearinghouseState response — spot balances for unified account."""
    return _post({"type": "spotClearinghouseState", "user": _wallet_address})


def fetch_open_orders() -> list:
    """Raw openOrders response."""
    return _post({"type": "openOrders", "user": _wallet_address})


def fetch_funding_history(start_time_ms: int | None = None) -> list:
    """Raw userFunding response.  start_time_ms defaults to 24h ago."""
    if start_time_ms is None:
        start_time_ms = int((time.time() - 86400) * 1000)
    return _post({
        "type": "userFunding",
        "user": _wallet_address,
        "startTime": start_time_ms,
    })


def fetch_all_mids() -> dict[str, str]:
    """Fetch all mid prices.  Returns {coin: mid_price_string}."""
    return _post({"type": "allMids"})


# ──────────────────────────── Parsing ─────────────────────────────────


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def parse_portfolio(raw: dict, mids: dict[str, str] | None = None) -> PortfolioState:
    """Parse clearinghouseState response into a PortfolioState."""
    margin = raw.get("marginSummary", {})

    equity = _safe_float(margin.get("accountValue"))
    total_notional = _safe_float(margin.get("totalNtlPos"))
    margin_used = _safe_float(margin.get("totalMarginUsed"))

    # Available to trade — match the HL UI calculation
    # HL UI uses: equity - sum(positionValue / maxLeverageForAsset)
    # where maxLeverage is the EXCHANGE's per-asset cap (e.g. BTC=40x, SOL=20x)
    # We compute this after parsing positions; use initial margin as fallback
    _initial_margin_used = margin_used

    # Use MAINTENANCE margin for account ratio (this is what determines liquidation)
    # totalMarginUsed = initial margin (much higher, not liquidation-relevant)
    # crossMaintenanceMarginUsed = maintenance margin (this triggers liquidation)
    maintenance_margin = _safe_float(raw.get("crossMaintenanceMarginUsed", 0))

    # Unified leverage = total notional / equity
    unified_leverage = total_notional / equity if equity > 0 else 0.0

    # Account ratio = maintenance_margin / equity * 100
    # Liquidation occurs when this approaches 100%
    account_ratio = (maintenance_margin / equity * 100) if equity > 0 else 0.0

    positions: list[Position] = []
    total_unrealized = 0.0

    for asset in raw.get("assetPositions", []):
        pos = asset.get("position", {})
        coin = pos.get("coin", "???")
        # Clean up xyz: prefix for display (xyz:SP500 → S&P500)
        display_coin = coin
        if coin.startswith("xyz:"):
            raw_name = coin[4:]  # strip "xyz:" prefix
            # Map API names to human-friendly names
            display_coin = {"SP500": "S&P500"}.get(raw_name, raw_name)
        size = _safe_float(pos.get("szi"))
        if size == 0:
            continue  # skip empty positions

        entry_px = _safe_float(pos.get("entryPx"))
        pos_value = _safe_float(pos.get("positionValue"))
        pnl = _safe_float(pos.get("unrealizedPnl"))
        roe = _safe_float(pos.get("returnOnEquity"))
        liq_px = _safe_float(pos.get("liquidationPx"))

        lev_data = pos.get("leverage", {})
        lev = int(_safe_float(lev_data.get("value", 1)))

        mu = _safe_float(pos.get("marginUsed"))
        funding = _safe_float(
            pos.get("cumFunding", {}).get("sinceOpen", 0)
        )

        # Get mark price from allMids if available
        mark = 0.0
        if mids and coin in mids:
            mark = _safe_float(mids.get(coin))
        elif mids and display_coin in mids:
            mark = _safe_float(mids.get(display_coin))
        elif entry_px and size != 0 and pos_value > 0:
            mark = pos_value / abs(size)

        total_unrealized += pnl

        positions.append(Position(
            coin=display_coin,
            size=size,
            entry_price=entry_px,
            mark_price=mark,
            leverage=lev,
            position_value=pos_value,
            unrealized_pnl=pnl,
            roe=roe,
            liquidation_price=liq_px,
            margin_used=mu,
            funding_rate=funding,
        ))

    # Available to trade — matches HL UI
    # totalMarginUsed includes both position margin AND open order margin reserves
    available = max(0.0, equity - _initial_margin_used)

    return PortfolioState(
        timestamp=datetime.now(timezone.utc),
        equity=equity,
        available_margin=available,
        maintenance_margin=maintenance_margin,
        unified_leverage=unified_leverage,
        account_ratio=account_ratio,
        total_notional=total_notional,
        unrealized_pnl=total_unrealized,
        positions=positions,
    )


def parse_spot_balances(raw: dict, mids: dict[str, str] | None = None) -> list[SpotBalance]:
    """Parse spotClearinghouseState into valued SpotBalance rows.

    Stablecoins priced at $1. For non-stables we try allMids lookup; HL uses
    a 'U' prefix for tokenized spot (e.g. UBTC, UETH, USOL) so we fall back
    to the perps mid by stripping the leading 'U'.
    """
    out: list[SpotBalance] = []
    for b in raw.get("balances", []):
        total = _safe_float(b.get("total"))
        if total <= 0:
            continue
        coin = b.get("coin", "???")
        hold = _safe_float(b.get("hold"))
        free = max(0.0, total - hold)

        if coin in STABLE_COINS:
            mark = 1.0
        else:
            mark = 0.0
            if mids:
                # Try direct lookup first, then strip 'U' prefix (UBTC → BTC)
                mark = _safe_float(mids.get(coin))
                if mark == 0.0 and coin.startswith("U") and len(coin) > 1:
                    mark = _safe_float(mids.get(coin[1:]))
            if mark == 0.0:
                logger.warning("No mark price for spot %s — valuing at $0", coin)

        out.append(SpotBalance(
            coin=coin,
            total=total,
            hold=hold,
            free=free,
            mark_price=mark,
            usd_value=total * mark,
        ))
    return out


def get_portfolio() -> PortfolioState:
    """High-level: fetch + parse portfolio from both main and xyz dexes, plus spot."""
    if not _wallet_address:
        raise RuntimeError("Wallet address not set — call set_wallet_address() first")
    try:
        raw = fetch_clearinghouse_state()
        mids = fetch_all_mids()
    except requests.RequestException as exc:
        logger.error("API request failed: %s", exc)
        raise

    portfolio = parse_portfolio(raw, mids)

    # Merge xyz dex (S&P500, etc.) — separate clearinghouse on Hyperliquid
    try:
        xyz_raw = fetch_clearinghouse_state(dex="xyz")
        xyz_positions = xyz_raw.get("assetPositions", [])
        if xyz_positions:
            xyz_portfolio = parse_portfolio(xyz_raw, mids)
            # Merge: add xyz positions, sum up account metrics
            portfolio = PortfolioState(
                timestamp=portfolio.timestamp,
                equity=portfolio.equity + xyz_portfolio.equity,
                available_margin=portfolio.available_margin,  # keep main dex available
                maintenance_margin=portfolio.maintenance_margin + xyz_portfolio.maintenance_margin,
                unified_leverage=0.0,  # recalculate below
                account_ratio=0.0,     # recalculate below
                total_notional=portfolio.total_notional + xyz_portfolio.total_notional,
                unrealized_pnl=portfolio.unrealized_pnl + xyz_portfolio.unrealized_pnl,
                positions=portfolio.positions + xyz_portfolio.positions,
            )
            # Recalculate unified metrics
            if portfolio.equity > 0:
                portfolio = PortfolioState(
                    timestamp=portfolio.timestamp,
                    equity=portfolio.equity,
                    available_margin=portfolio.available_margin,
                    maintenance_margin=portfolio.maintenance_margin,
                    unified_leverage=portfolio.total_notional / portfolio.equity,
                    account_ratio=portfolio.maintenance_margin / portfolio.equity * 100,
                    total_notional=portfolio.total_notional,
                    unrealized_pnl=portfolio.unrealized_pnl,
                    positions=portfolio.positions,
                )
            logger.info("Merged %d xyz position(s) into portfolio", len(xyz_portfolio.positions))
    except requests.RequestException:
        logger.debug("xyz dex fetch failed — skipping")
    except Exception as exc:
        logger.debug("xyz merge error: %s", exc)

    # ── Spot state (unified account rolls spot into total equity) ────
    try:
        spot_raw = fetch_spot_state()
        spot_balances = parse_spot_balances(spot_raw, mids)

        # Free stablecoin balances back both equity and tradable margin
        free_stable = sum(
            b.free for b in spot_balances if b.coin in STABLE_COINS
        )
        # Non-stable spot tokens count toward equity only (not available margin)
        non_stable_value = sum(
            b.usd_value for b in spot_balances if b.coin not in STABLE_COINS
        )

        new_equity = portfolio.equity + free_stable + non_stable_value
        new_available = portfolio.available_margin + free_stable

        new_lev = (
            portfolio.total_notional / new_equity if new_equity > 0 else 0.0
        )
        new_ratio = (
            portfolio.maintenance_margin / new_equity * 100
            if new_equity > 0 else 0.0
        )

        portfolio = PortfolioState(
            timestamp=portfolio.timestamp,
            equity=new_equity,
            available_margin=new_available,
            maintenance_margin=portfolio.maintenance_margin,
            unified_leverage=new_lev,
            account_ratio=new_ratio,
            total_notional=portfolio.total_notional,   # perps notional only
            unrealized_pnl=portfolio.unrealized_pnl,
            positions=portfolio.positions,
            spot_balances=spot_balances,
        )
        if spot_balances:
            logger.info(
                "Merged spot: %d balance(s), +$%.2f stable / +$%.2f non-stable",
                len(spot_balances), free_stable, non_stable_value,
            )
    except requests.RequestException:
        logger.debug("spot state fetch failed — skipping")
    except Exception as exc:
        logger.debug("spot merge error: %s", exc)

    return portfolio


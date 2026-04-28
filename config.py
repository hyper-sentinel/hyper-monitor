"""hyper-monitor — Configuration

All thresholds and magic numbers in one place.
Edit these to match YOUR portfolio and risk tolerance.

──────────────────────────────────────────────────────────────────────
PHASE-AWARE CONFIG
──────────────────────────────────────────────────────────────────────
The monitor supports three operating phases. Flip ACTIVE_PHASE when
you graduate. Downstream constants (LEVERAGE_WARNING, MIN_AVAILABLE_PCT,
etc.) are derived from PHASES[ACTIVE_PHASE] at import time, so the
rest of the codebase doesn't need to change.

  Phase 2:     $7–15K equity,  15–18x operating, aggressive rebuild
                     Graduation: HWM $15K + execute 8x trim → Phase 3
  Phase 3:     $15–25K equity, 10–12x operating, swing + take-profit
                     Graduation: cross $30K + execute 6x trim → Phase 4
  Phase 4 (Saylor): $30–50K equity, 4–8x operating, rotation account
"""

# ─── API ──────────────────────────────────────────────────────────────
API_URL = "https://api.hyperliquid.xyz/info"

# ─── Polling ──────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 1  # near-realtime; HL info endpoint is permissive

# ─── Active phase ─────────────────────────────────────────────────────
# Flip this ONLY after executing the graduation ritual trim.
# Phase 2 → 3: HWM $15K + first 8x trim
# Phase 3 → 4: cross $30K + first 6x trim
ACTIVE_PHASE = 2

PHASES = {
    2: {
        # Equity band
        "equity_floor": 7_000,
        "equity_ceiling": 15_000,
        # Leverage bands (ascending severity)
        "lev_safe": 12,        # 🟢 deep in profit / reload zone
        "lev_operating": 15,   # 🔵 normal operating
        "lev_ceiling": 18,     # 🟡 aggressive risk-on (holding OK)
        "lev_holding": 22,     # 🟠 aggressive and holding (22–24x)
        "lev_warning": 22,     # ⚠️  approaching derisk rapidly
        "lev_danger": 25,      # 🔴 DERISK NOW (25–30x band)
        "lev_critical": 30,    # 💀 voice alert
        # Book & margin
        "book_anchor_low": 130_000,
        "book_anchor_high": 160_000,
        "min_avail_pct": 20,
        # Graduation target (the "next HWM" milestone)
        "graduation_hwm": 15_000,
        "graduation_trim_to": 8,   # drop to 8x on graduation
    },
    3: {
        "equity_floor": 15_000,
        "equity_ceiling": 25_000,
        "lev_safe": 6,
        "lev_operating": 10,
        "lev_ceiling": 12,
        "lev_holding": 13,
        "lev_warning": 13,
        "lev_danger": 15,
        "lev_critical": 18,
        "book_anchor_low": 150_000,
        "book_anchor_high": 180_000,
        "min_avail_pct": 30,
        "graduation_hwm": 30_000,
        "graduation_trim_to": 6,
    },
    4: {
        "equity_floor": 30_000,
        "equity_ceiling": 50_000,
        "lev_safe": 4,
        "lev_operating": 6,
        "lev_ceiling": 8,
        "lev_holding": 9,
        "lev_warning": 9,
        "lev_danger": 10,
        "lev_critical": 12,
        "book_anchor_low": 200_000,
        "book_anchor_high": 250_000,
        "min_avail_pct": 50,
        "graduation_hwm": None,   # Saylor mode — no further graduation
        "graduation_trim_to": None,
    },
}

# Resolved phase config (used by downstream modules)
_P = PHASES[ACTIVE_PHASE]

# ─── Leverage thresholds (derived from ACTIVE_PHASE) ──────────────────
LEVERAGE_SAFE = _P["lev_safe"]
LEVERAGE_OPERATING = _P["lev_operating"]
LEVERAGE_CEILING = _P["lev_ceiling"]
LEVERAGE_WARNING = _P["lev_warning"]      # ⚠️  approaching derisk rapidly
LEVERAGE_DANGER = _P["lev_danger"]        # 🔴 DERISK NOW
LEVERAGE_CRITICAL = _P["lev_critical"]    # 💀 voice alert — Mac yells at you

# ─── Available margin milestones (ascending) ─────────────────────────
MARGIN_MILESTONES = [0, 500, 1000, 2000, 5000]

# ─── Divergence thresholds (%) ───────────────────────────────────────
# The divergence tracker is the most important feature.
# It catches when your notional grows faster than your equity.
DIVERGENCE_WARNING = 10    # ⚠️  leverage creeping
DIVERGENCE_CAUTION = 20    # 🔶 significant expansion
DIVERGENCE_DANGER = 30     # 🔴 leverage spiral
DIVERGENCE_CRITICAL = 50   # 💀 you're about to blow up

# ─── Drawdown thresholds (%) ─────────────────────────────────────────
DRAWDOWN_THRESHOLDS = [10, 20, 30, 40, 50]

# ─── Notification cooldown (seconds) ─────────────────────────────────
ALERT_COOLDOWN = 300  # don't repeat same alert within 5 minutes

# ─── Scale-out targets by coin ───────────────────────────────────────
# Price levels where you want a 🎯 alert when price is within
# SCALE_OUT_PROXIMITY_PCT of any target.
# 💡 CUSTOMIZE THESE for your own positions.
SCALE_OUT_TARGETS = {
    # "BTC": [80000, 85000, 90000, 95000, 100000],
    # "SOL": [90, 100, 120, 150],
    # "ETH": [2000, 2200, 2500, 3000],
}

# ─── BTC downside action levels ──────────────────────────────────────
# Price levels where you should take action on BTC longs.
# 💡 CUSTOMIZE THESE to match your current BTC entry and liquidation prices.
BTC_ACTION_LEVELS = {
    # Example (uncomment and edit to match YOUR position):
    # 74400: ("🟡 HEADS UP",    "BTC below $74,400 — watch for follow-through"),
    # 74055: ("🟠 BELOW ENTRY", "At entry — tighten stance, no new adds"),
    # 73700: ("🔴 CRITICAL",    "BTC below $73,700 — DERISK NOW"),
    # 72500: ("🔴 MAX PAIN",    "3% below mark, 2% above liq — 60% BTC derisk"),
    # 71500: ("💀 EMERGENCY",   "Approaching liquidation — close BTC leg"),
}

# ─── Hard rules ──────────────────────────────────────────────────────
MAX_SINGLE_POSITION_PCT = 60        # alert if one position > 60% of total notional
MIN_AVAILABLE_PCT = _P["min_avail_pct"]   # derived from phase

# ─── Runner minimums (never sell below these sizes) ──────────────────
RUNNER_MINIMUMS = {
    # "BTC": 0.1,
    # "ETH": 1.0,
}

# ─── PnL alert thresholds per position ($) ───────────────────────────
PNL_THRESHOLDS = [100, 250, 500, 1000, 1500, 2000, 5000, 7500, 10000]

# ─── Liquidation proximity thresholds (%) ────────────────────────────
LIQ_WARNING_PCT = 5    # 🔴 within 5% of liquidation
LIQ_CRITICAL_PCT = 3   # 💀 within 3% of liquidation

# ─── Account ratio thresholds (%) ────────────────────────────────────
ACCOUNT_RATIO_WARNING = 60   # ⚠️  margin usage above 60%
ACCOUNT_RATIO_CRITICAL = 80  # 💀 approaching liquidation

# ─── Available margin critically low (% of equity) ──────────────────
MARGIN_LOW_PCT = 10

# ─── Scale-out proximity (%) ─────────────────────────────────────────
SCALE_OUT_PROXIMITY_PCT = 2  # alert when price is within 2% of target

# ─── Funding rate daily threshold (% of position value) ─────────────
FUNDING_DAILY_THRESHOLD_PCT = 1

# ─── Leverage ratchet gap thresholds ─────────────────────────────────
LEVERAGE_RATCHET_GAPS = [2, 3, 5]

# ─── Graduation milestones (from active phase) ───────────────────────
GRADUATION_HWM = _P["graduation_hwm"]
GRADUATION_TRIM_TO = _P["graduation_trim_to"]

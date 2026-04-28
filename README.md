<p align="center">
  <h1 align="center">⚡ hyper-monitor</h1>
  <p align="center">
    Real-time leverage surveillance for Hyperliquid perpetual futures.<br/>
    Detects leverage spirals before they liquidate you.
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.13+-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/platform-macOS-lightgrey?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
  <img src="https://img.shields.io/badge/auth-none_required-brightgreen?style=flat-square" />
  <img src="https://img.shields.io/badge/by-Sentinel_Labs-blueviolet?style=flat-square" />
</p>

---

A terminal dashboard that polls the public Hyperliquid API **every second**, runs 14 risk checks on your portfolio, and alerts you through desktop notifications and voice alerts when things go wrong. **Read-only** — no API keys, no credentials, no trading.
```
╭──────────── HYPERLIQUID PORTFOLIO MONITOR ──────────────╮
│              Last Update: 12:39:34 PM CDT                │
╠──────────── Account Summary ─────────────────────────────╣
│ EQUITY: $5,097.53   LEVERAGE: 16.71x   RATIO: 95.2%     │
│ AVAIL:  $0.00       MAINT:    $4,853    NOTIONAL: $85,178│
│ UNREAL: +$1,941.84  HWM:      $5,097    DD: 0.0%        │
╠──────────── Positions ───────────────────────────────────╣
│ BTC    0.0500  $72,414  33x  +$1,194.55  +85.9%         │
│ SOL    220     $84.47   20x  +$421.25    +46.4%          │
│ HYPE   120     $39.93   10x  +$327.95    +73.4%          │
╠──────────── Recent Alerts ───────────────────────────────╣
│ 12:39 🎯 BTC approaching scale-out at $73,500            │
│ 12:39 ⚠️  BTC is 55.3% of total notional                 │
│ 12:39 💀 CRITICAL: Approaching liquidation — ratio 95.2% │
╰──────────────────────────────────────────────────────────╯
```

## Quick Start

```bash
git clone https://github.com/hyper-sentinel/hyper-monitor.git
cd hyper-monitor
uv sync
uv run monitor.py
```

On first run, paste your wallet address when prompted. That's it.

```
╭─────────────────────────────────────────╮
│   HYPERLIQUID PORTFOLIO MONITOR SETUP   │
╰─────────────────────────────────────────╯

  Enter your Hyperliquid wallet address (read-only, no auth needed).
  This is the 0x... address shown on your Hyperliquid portfolio page.

  Wallet address → 0xYOUR_ADDRESS_HERE

✅ Wallet saved (stored in monitor_state.json — won't ask again)
```

## What It Watches

| Check | Alert | What It Catches |
|-------|-------|----------------|
| Leverage Divergence | ⚠️→💀 | Notional growing faster than equity — the silent killer |
| Leverage Level | ⚠️ 20x / 🔴 25x / 💀 30x | Overall account leverage |
| Account Ratio | ⚠️ 60% / 💀 80% | How close to liquidation |
| Available Margin | ⚠️ < 10% of equity | No cushion to absorb losses |
| Liquidation Proximity | 🔴 < 5% / 💀 < 3% | Price nearing liq price |
| Position PnL | 💰 / 📉 | Any position crosses ±$100 / $500 / $1K |
| Concentration | ⚠️ > 50% | One position dominates the portfolio |
| Scale-Out Targets | 🎯 | Price approaching your take-profit levels |
| BTC Action Levels | 🟡→☠️ | BTC drops into predefined danger zones |
| Drawdown from ATH | 📉→💀 | Equity fallen 10%+ from peak |
| Leverage Ratchet | 📈 | Leverage drifted far from its best |

## Commands

```bash
uv run monitor.py                          # Live dashboard (Ctrl+C to stop)
uv run monitor.py --snapshot               # Print once and exit
uv run monitor.py --reset-baseline         # Reset divergence tracker
uv run monitor.py --history                # Show equity curve
uv run monitor.py --alert COIN PRICE      # Custom price alert
uv run monitor.py --wallet 0x...          # Override wallet address
uv run monitor.py --quiet                  # No desktop/voice notifications
```

## Setup (from scratch)

Assumes a fresh Mac. Skip any steps you've already done.

### 1. Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install Python

```bash
brew install python
```

### 3. Install uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen your terminal after installing, then verify:
```bash
uv --version
```

### 4. Clone and install dependencies

```bash
git clone https://github.com/hyper-sentinel/hyper-monitor.git
cd hyper-monitor
uv sync
```

### 5. (Optional) Desktop notifications

```bash
brew install terminal-notifier
```

This enables macOS notification banners. Without it, alerts still show in the terminal.

### 6. Run it

```bash
uv run monitor.py
```

### Configure Your Wallet

**First run:** the monitor prompts for your wallet address and saves it. Never asks again.

**Change wallet later:**
```bash
uv run monitor.py --wallet 0xNEW_ADDRESS        # one-time override
HL_WALLET=0xNEW_ADDRESS uv run monitor.py       # env var
rm monitor_state.json && uv run monitor.py      # re-prompt
```

> **This is read-only.** The API requires no authentication — it just reads public portfolio state. Your funds are safe.

## Understanding the Metrics

The dashboard uses the **exact same metrics** as the Hyperliquid UI. Here's what each one means:

### Unified Account Summary

| Dashboard | Hyperliquid UI | What It Is |
|-----------|---------------|------------|
| **Portfolio Value** | Portfolio Value | Your total account equity — deposits + unrealized PnL |
| **Unified Leverage** | Unified Account Leverage | Total notional exposure ÷ portfolio value. Higher = more risk. |
| **Account Ratio** | Unified Account Ratio | Maintenance margin ÷ portfolio value. **Liquidation happens when this hits 100%.** |
| **Available** | (not shown directly) | How much margin you can still use. $0 = no cushion. |
| **Maint Margin** | Perps Maintenance Margin | The minimum collateral required to keep your positions open. |
| **Total Notional** | (sum of position values) | The dollar value of all your positions combined. |
| **Unrealized PnL** | Unrealized PNL | Total profit/loss across all open positions. |

### What the Numbers Mean

- **Portfolio Value = $5,300** → You have $5,300 in your account
- **Unified Leverage = 17x** → For every $1 of equity, you control $17 of positions
- **Account Ratio = 42%** → Your maintenance margin uses 42% of your equity. At 100% you get liquidated. **This is NOT the same as initial margin usage** — maintenance margin is lower.
- **Available = $0** → You can't open new positions, but existing ones are safe as long as account ratio stays below 100%
- **Maint Margin = $2,222** → Hyperliquid requires this much collateral minimum. If your equity drops below this, liquidation starts.

### Extra Metrics (not on Hyperliquid UI)

| Metric | What It Is |
|--------|-----------| 
| **High Water Mark** | The highest your portfolio value has ever been |
| **Drawdown** | How far you've fallen from the peak (negative %) |
| **Trend** | Sparkline showing your equity direction over recent readings |
| **Divergence** | Whether notional is growing faster than equity (see below) |

## How Notifications Work


| Method | When | Requires |
|--------|------|----------|
| **Terminal alerts** | Always on | Nothing |
| **Desktop popups** | All levels | `brew install terminal-notifier` |
| **Voice alerts** | 💀 CRITICAL only | macOS (uses `say` command) |

**No emails.** No webhooks. No cloud. Everything runs locally on your machine.

Each alert has a **5-minute cooldown** so you don't get spammed.

Run `--quiet` to disable everything except terminal alerts.

### Alert Sounds

| Level | macOS Sound | Voice? |
|-------|------------|--------|
| 🟢 INFO | Pop | No |
| ⚠️ WARNING | Purr | No |
| 🔴 DANGER | Sosumi | No |
| 💀 CRITICAL | Basso | **Yes** — your Mac speaks the alert |

## The Divergence Tracker

This is **the most important feature**. It catches the silent leverage spiral that liquidates portfolios.

### The Problem

With leveraged perps, when price moves in your favor:
1. ✅ Your equity goes up (unrealized PnL)
2. ❌ Your notional exposure ALSO goes up (same position, higher price)
3. If notional grows faster than equity → **your effective leverage is increasing silently**
4. A small pullback that was fine at 10x now liquidates you at 25x

### How It Works

```
                  Baseline        →        Current
Equity:           $3,710         →        $4,179  (+12.6%)
Notional:         $89,500        →        $92,364 (+3.2%)
Divergence:       3.2% - 12.6%  =        -9.4% ✅ HEALTHY
```

- **Negative divergence = good** — equity growing faster than exposure
- **Positive divergence = DANGER** — leverage is silently increasing

| Divergence | Status | Action |
|-----------|--------|--------|
| < 5% | ✅ Healthy | None |
| 10% | ⚠️ Warning | Watch it |
| 20% | 🔶 Caution | Consider trimming |
| 30% | 🔴 Danger | Trim now |
| 50% | 💀 Critical | DERISK NOW |

**Reset the baseline** after taking profits or changing positions: `uv run main.py --reset-baseline`

## Configuration

All thresholds live in [`config.py`](config.py) with inline comments. Key settings:

```python
POLL_INTERVAL_SECONDS = 1     # Near-realtime (HL info endpoint is permissive)
ALERT_COOLDOWN = 300          # Seconds before same alert repeats
LEVERAGE_WARNING = 20         # ⚠️ threshold
LEVERAGE_DANGER = 25          # 🔴 threshold
LEVERAGE_CRITICAL = 30        # 💀 threshold (triggers voice alert)
MAX_SINGLE_POSITION_PCT = 50  # Concentration limit
```

Add your own scale-out targets and BTC action levels in `config.py`.

## Files

```
├── main.py           # Run this
├── monitor.py        # CLI + poll loop
├── hl_api.py         # Hyperliquid API client
├── risk_engine.py    # 11 risk checks
├── alerts.py         # Desktop + voice notifications
├── dashboard.py      # Terminal UI (Rich)
├── state.py          # JSON persistence
├── config.py         # All thresholds (edit this)
└── monitor_state.json  # Auto-generated (gitignored)
```

## FAQ

**Is this safe?** Yes. It's read-only. No API keys. No signing. It just reads public clearinghouse state from the Hyperliquid API.

**Does it trade for me?** No. It only monitors and alerts.

**Does it work on Linux/Windows?** The core dashboard works everywhere Python runs. Desktop notifications and voice alerts are macOS-only (they degrade gracefully).

**How do I change my wallet?** Run with `--wallet 0xNEW` or delete `monitor_state.json`.

**How do I stop the voice alerts?** Run with `--quiet`.

## License

MIT — [Sentinel Labs](https://github.com/hyper-sentinel)

---

<p align="center">
  <sub>Built by <a href="https://github.com/hyper-sentinel">Sentinel Labs</a> — open-source tools for DeFi risk management.</sub>
</p>

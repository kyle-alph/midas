import os
from dotenv import load_dotenv
load_dotenv()

# API credentials
COINBASE_API_KEY    = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# Runtime flags
DRY_RUN    = os.getenv("DRY_RUN", "true").lower() == "true"
PHASE      = int(os.getenv("PHASE", "1"))
SYMBOL     = "BTC-USD"
PAUSE_FILE = "PAUSED"

# Phase 1 caps
PHASE1_MAX_TRADE_USD        = 200.0
PHASE1_DAILY_DEPLOYED_LIMIT = 200.0
PHASE1_DAILY_LOSS_HALT      = 100.0

# Phase 2 caps (wired but inactive until PHASE=2)
PHASE2_DAILY_CAP_PCT   = 0.30
PHASE2_DAILY_CAP_MAX   = 500.0
PHASE2_DAILY_LOSS_HALT = 500.0

# Phase 1 strategy thresholds — PLACEHOLDER, see DECISIONS.md
# Do not treat as final. Recalibrate after Week 1 log review.
DIP_THRESHOLD_PCT = -0.002   # -0.2%: buy trigger
TAKE_PROFIT_PCT   =  0.0015  # +0.15%: sell trigger above avg entry
STOP_LOSS_PCT     = -0.008   # -0.8%: stop loss below avg entry

# DO NOT hardcode a specific approach — scaffold as configurable
REFERENCE_PRICE_MODE = os.getenv("REFERENCE_PRICE_MODE", "last_candle")

# Loop timing
WEBSOCKET_RECONNECT_DELAY_SEC  = 5
CLAUDE_ASSESSMENT_INTERVAL_SEC = 1800   # 30 min — TK, may change with final strategy
PAUSE_CHECK_INTERVAL_SEC       = 30
DAILY_RESET_HOUR               = 9

# Claude model
CLAUDE_MODEL = "claude-sonnet-4-6"

# Alerting
HOURLY_SUMMARY_ENABLED = True   # Only fires if trades occurred that hour
EOD_SUMMARY_HOUR       = 8      # 8AM EoD summary before 9AM reset

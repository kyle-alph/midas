import argparse
import json
import sys

import config
from logger.decision_log import DecisionLog
from state.daily_state import DailyState


def cmd_logs(n: int) -> None:
    log = DecisionLog()
    log.print_recent(n)


def cmd_status() -> None:
    try:
        state = DailyState.load_or_create(account_value=0.0)
    except Exception as exc:
        print(f"Could not load state: {exc}")
        sys.exit(1)

    # Try to get live position from broker for display
    position_line = "Position: none"
    try:
        from broker.coinbase_broker import CoinbaseBroker
        broker = CoinbaseBroker()
        pos = broker.get_open_position(config.SYMBOL)
        if pos:
            value = pos["current_value_usd"]
            position_line = (
                f"Position: {pos['btc_amount']:.8f} BTC "
                f"@ avg ${pos['avg_entry_price']:,.0f} "
                f"(value: ${value:.2f})"
            )
    except Exception:
        pass

    halted_str = "Yes" if state.halted else "No"
    pnl = state.net_pnl_today()
    pnl_sign = "+" if pnl >= 0 else ""

    print("── Midas Status ──────────────────────────────")
    print(f"Phase: {config.PHASE}    DRY_RUN: {str(config.DRY_RUN).lower()}")
    print(f"Date:  {state.date}")
    print(
        f"Cap:   ${state.daily_cap:.2f}  "
        f"Deployed: ${state.deployed_today:.2f}  "
        f"Remaining: ${state.remaining_budget():.2f}"
    )
    print(
        f"PnL:  {pnl_sign}${pnl:.2f}   "
        f"Loss: ${state.realized_loss_today:.2f}   "
        f"Profit: ${state.realized_profit_today:.2f}"
    )
    print(f"Trades: {state.trade_count_today}      Halted: {halted_str}")
    print(position_line)
    print("─────────────────────────────────────────────────────")


def main() -> None:
    parser = argparse.ArgumentParser(prog="cli.py", description="Midas CLI")
    subparsers = parser.add_subparsers(dest="command")

    logs_parser = subparsers.add_parser("logs", help="Show recent decision log entries")
    logs_parser.add_argument("--n", type=int, default=20, help="Number of entries to show")

    subparsers.add_parser("status", help="Show current daily state")

    args = parser.parse_args()

    if args.command == "logs":
        cmd_logs(args.n)
    elif args.command == "status":
        cmd_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

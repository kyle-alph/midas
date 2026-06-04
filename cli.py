import argparse
import json
import sys

import config
from logger.decision_log import DecisionLog
from state.daily_state import DailyState


def cmd_logs(n: int, trades_only: bool = False, agent_id: str | None = None) -> None:
    log = DecisionLog()
    log.print_recent(n, trades_only=trades_only, agent_id=agent_id)


def _print_status_block(state: DailyState, label: str | None = None) -> None:
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
    header = f"── Midas Status [{label}] " if label else "── Midas Status "
    bar = "─" * 53

    print(f"{header}{bar[len(header):]}")
    print(f"Phase: {config.PHASE}    DRY_RUN: {str(config.DRY_RUN).lower()}    Paper trading: {str(config.PAPER_TRADING).lower()}")
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
    print(bar)


def cmd_status(agent_id: str | None = None, show_all: bool = False) -> None:
    if show_all:
        import yaml
        try:
            with open("agents.yaml") as f:
                data = yaml.safe_load(f)
            for a in data["agents"]:
                aid = a["id"]
                state_file = f"state_{aid}.json"
                try:
                    state = DailyState.load_or_create(
                        account_value=0.0, state_file=state_file
                    )
                    _print_status_block(state, label=aid)
                except Exception as exc:
                    print(f"[{aid}] Could not load state: {exc}")
        except FileNotFoundError:
            print("agents.yaml not found — use --all only with orchestrator setup.")
            sys.exit(1)
        return

    if agent_id:
        state_file = f"state_{agent_id}.json"
        label = agent_id
    else:
        state_file = "state.json"
        label = None

    try:
        state = DailyState.load_or_create(account_value=0.0, state_file=state_file)
    except Exception as exc:
        print(f"Could not load state: {exc}")
        sys.exit(1)

    _print_status_block(state, label=label)


def main() -> None:
    parser = argparse.ArgumentParser(prog="cli.py", description="Midas CLI")
    subparsers = parser.add_subparsers(dest="command")

    logs_parser = subparsers.add_parser("logs", help="Show recent decision log entries")
    logs_parser.add_argument("--n", type=int, default=20, help="Number of entries to show")
    logs_parser.add_argument("--trades-only", action="store_true", help="Show only BUY/SELL entries")
    logs_parser.add_argument("--agent", help="Filter by agent ID")

    status_parser = subparsers.add_parser("status", help="Show current daily state")
    status_parser.add_argument("--agent", help="Show state for a specific agent ID")
    status_parser.add_argument("--all", action="store_true", help="Show status for all agents in agents.yaml")

    args = parser.parse_args()

    if args.command == "logs":
        cmd_logs(args.n, trades_only=args.trades_only, agent_id=args.agent)
    elif args.command == "status":
        cmd_status(agent_id=args.agent, show_all=args.all)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

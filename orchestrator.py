"""
Midas multi-agent orchestrator.

Usage:
  python3 orchestrator.py --config agents.yaml
  python3 orchestrator.py --config agents.yaml --agents conservative
  python3 orchestrator.py --config agents.yaml --agents conservative,aggressive
"""

import argparse
import logging
import multiprocessing
import os
import signal
import sys
import time
from dataclasses import dataclass, field

import yaml

from shared.price_feed import SharedPriceFeed
from workers.agent_worker import run_agent

_RESTART_BACKOFF_BASE_SEC = 10
_RESTART_BACKOFF_MAX_SEC = 300
_CIRCUIT_BREAK_THRESHOLD = 5   # consecutive crashes before stopping auto-restart
_CIRCUIT_BREAK_WINDOW_SEC = 120
_HEARTBEAT_STALE_SEC = 60
_HEARTBEAT_CHECK_INTERVAL_SEC = 15


@dataclass
class _AgentRestartState:
    crash_times: list = field(default_factory=list)
    backoff_sec: float = _RESTART_BACKOFF_BASE_SEC
    circuit_broken: bool = False
    circuit_alert_sent: bool = False


def _setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fh = logging.FileHandler("logs/orchestrator.log")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _load_agents(config_path: str, filter_ids: list[str] | None) -> list[dict]:
    with open(config_path) as f:
        data = yaml.safe_load(f)
    agents = data["agents"]

    ids = [a["id"] for a in agents]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate agent IDs in {config_path}: {ids}")

    if filter_ids:
        agents = [a for a in agents if a["id"] in filter_ids]
        missing = set(filter_ids) - {a["id"] for a in agents}
        if missing:
            raise ValueError(f"Unknown agent IDs: {missing}")

    return agents


def main() -> None:
    _setup_logging()
    logger = logging.getLogger("orchestrator")

    parser = argparse.ArgumentParser(prog="orchestrator.py")
    parser.add_argument("--config", default="agents.yaml")
    parser.add_argument(
        "--agents",
        help="Comma-separated agent IDs to run (default: all defined in config)",
    )
    args = parser.parse_args()

    filter_ids = [x.strip() for x in args.agents.split(",")] if args.agents else None
    agents = _load_agents(args.config, filter_ids)

    symbols = {a["symbol"] for a in agents}
    if len(symbols) > 1:
        raise ValueError(f"Multi-symbol support not implemented. Found: {symbols}")
    symbol = next(iter(symbols))

    logger.info(
        "Orchestrator starting — agents=%s symbol=%s",
        [a["id"] for a in agents],
        symbol,
    )

    feed = SharedPriceFeed(symbol=symbol)

    agent_queues: dict[str, multiprocessing.Queue] = {}
    for agent_cfg in agents:
        agent_queues[agent_cfg["id"]] = feed.register_queue()

    feed.start()

    processes: dict[str, multiprocessing.Process] = {}
    restart_states: dict[str, _AgentRestartState] = {a["id"]: _AgentRestartState() for a in agents}
    pending_restart: dict[str, float] = {}  # agent_id → earliest restart timestamp
    last_heartbeat_check = 0.0

    def _spawn(agent_cfg: dict) -> multiprocessing.Process:
        q = agent_queues[agent_cfg["id"]]
        p = multiprocessing.Process(
            target=run_agent,
            args=(agent_cfg, q),
            name=f"worker-{agent_cfg['id']}",
            daemon=False,
        )
        p.start()
        logger.info("Spawned agent %s (pid=%d)", agent_cfg["id"], p.pid)
        return p

    def _send_circuit_break_alert(aid: str) -> None:
        try:
            import config as _cfg
            import requests as _req
            msg = (
                f"MIDAS CIRCUIT BREAK\n"
                f"Agent '{aid}' has crashed {_CIRCUIT_BREAK_THRESHOLD}x "
                f"in {_CIRCUIT_BREAK_WINDOW_SEC}s — auto-restart disabled.\n"
                f"Manual intervention required."
            )
            _req.post(
                f"https://api.telegram.org/bot{_cfg.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": _cfg.TELEGRAM_CHAT_ID, "text": msg},
                timeout=10,
            )
        except Exception as exc:
            logger.error("Circuit break Telegram alert failed: %s", exc)

    def _handle_crash(agent_cfg: dict, exit_code: int) -> None:
        aid = agent_cfg["id"]
        rs = restart_states[aid]
        now = time.time()

        rs.crash_times.append(now)
        rs.crash_times = [t for t in rs.crash_times if now - t <= _CIRCUIT_BREAK_WINDOW_SEC]

        logger.warning(
            "Agent %s exited (exitcode=%s) — crashes in last %ds: %d",
            aid, exit_code, _CIRCUIT_BREAK_WINDOW_SEC, len(rs.crash_times),
        )

        if len(rs.crash_times) >= _CIRCUIT_BREAK_THRESHOLD:
            rs.circuit_broken = True
            logger.error(
                "Agent %s circuit-broken after %d crashes — halting auto-restart",
                aid, _CIRCUIT_BREAK_THRESHOLD,
            )
            if not rs.circuit_alert_sent:
                _send_circuit_break_alert(aid)
                rs.circuit_alert_sent = True
            return

        rs.backoff_sec = min(rs.backoff_sec * 2, _RESTART_BACKOFF_MAX_SEC)
        pending_restart[aid] = now + rs.backoff_sec
        logger.info("Agent %s will restart in %.0fs", aid, rs.backoff_sec)

    def _kill_and_respawn(agent_cfg: dict, reason: str) -> None:
        aid = agent_cfg["id"]
        p = processes.get(aid)
        if p and p.is_alive():
            logger.warning("Agent %s — %s — sending SIGTERM", aid, reason)
            p.terminate()
            p.join(timeout=5)
            if p.is_alive():
                logger.warning("Agent %s did not terminate — killing", aid)
                p.kill()
                p.join()
        if not _shutdown[0]:
            processes[aid] = _spawn(agent_cfg)

    for agent_cfg in agents:
        processes[agent_cfg["id"]] = _spawn(agent_cfg)

    _shutdown = [False]

    def _handle_signal(signum, _frame):
        logger.info("Received signal %d — initiating graceful shutdown", signum)
        _shutdown[0] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not _shutdown[0]:
        now = time.time()

        # --- process death check ---
        for agent_cfg in agents:
            aid = agent_cfg["id"]
            p = processes[aid]
            if not p.is_alive() and aid not in pending_restart:
                rs = restart_states[aid]
                if not rs.circuit_broken:
                    _handle_crash(agent_cfg, p.exitcode)

        # --- pending restart: fire when backoff has elapsed ---
        for agent_cfg in agents:
            aid = agent_cfg["id"]
            if aid in pending_restart and now >= pending_restart[aid]:
                del pending_restart[aid]
                if not _shutdown[0] and not restart_states[aid].circuit_broken:
                    processes[aid] = _spawn(agent_cfg)

        # --- reset backoff for agents that have been stable long enough ---
        for agent_cfg in agents:
            aid = agent_cfg["id"]
            rs = restart_states[aid]
            if rs.crash_times:
                rs.crash_times = [t for t in rs.crash_times if now - t <= _CIRCUIT_BREAK_WINDOW_SEC]
                if not rs.crash_times:
                    rs.backoff_sec = _RESTART_BACKOFF_BASE_SEC

        # --- heartbeat staleness check ---
        if now - last_heartbeat_check >= _HEARTBEAT_CHECK_INTERVAL_SEC:
            last_heartbeat_check = now
            for agent_cfg in agents:
                aid = agent_cfg["id"]
                if restart_states[aid].circuit_broken or aid in pending_restart:
                    continue
                hb_file = f"logs/{aid}.heartbeat"
                try:
                    mtime = os.path.getmtime(hb_file)
                    age = now - mtime
                    if age > _HEARTBEAT_STALE_SEC and processes[aid].is_alive():
                        logger.error(
                            "Agent %s heartbeat stale (%.0fs) — worker appears hung, restarting",
                            aid, age,
                        )
                        _kill_and_respawn(agent_cfg, f"heartbeat stale {age:.0f}s")
                except FileNotFoundError:
                    pass  # worker may not have written first heartbeat yet

        time.sleep(1)

    logger.info("Shutting down all agents...")
    feed.stop()
    for aid, p in processes.items():
        if p.is_alive():
            p.terminate()
            p.join(timeout=5)
        if p.is_alive():
            logger.warning("Agent %s did not terminate — killing", aid)
            p.kill()
            p.join()

    logger.info("Orchestrator exited cleanly.")


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()

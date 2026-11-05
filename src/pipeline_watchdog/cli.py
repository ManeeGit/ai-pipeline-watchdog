from __future__ import annotations

import argparse
import json
import logging
import sys
import sqlite3
import threading
import time
from pathlib import Path

from .ai import explain_with_ollama
from .demo import SCENARIOS, create_demo, set_scenario
from .service import Watchdog
from .web import make_server


def positive(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return result


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="pipeline-watchdog", description="Local-first data contracts, incident correlation, and safe AI triage.")
    cli.add_argument("--verbose", action="store_true")
    commands = cli.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Create a new synthetic workspace with 12 healthy historical scans")
    demo.add_argument("--workspace", type=Path, default=Path("demo-workspace"))
    demo.add_argument("--scenario", choices=SCENARIOS, default="cascade")
    scenario = commands.add_parser("scenario", help="Change only a generated demo's synthetic fixtures and scan")
    scenario.add_argument("name", choices=SCENARIOS)
    scenario.add_argument("--workspace", type=Path, default=Path("demo-workspace"))
    for name in ("scan", "watch", "serve", "report", "explain", "backup", "prune"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--config", type=Path, default=Path("demo-workspace/watchdog.json"))
        cmd.add_argument("--db", type=Path, help="Defaults to watchdog.db alongside config")
        if name == "backup":
            cmd.add_argument("--output", type=Path, required=True)
        if name == "prune":
            cmd.add_argument("--retain-days", type=positive, default=30)
            cmd.add_argument("--apply", action="store_true", help="Delete eligible history; default only previews")
        if name in {"watch", "serve"}:
            cmd.add_argument("--interval", type=positive, default=30, help="Seconds between scans; minimum 5")
        if name == "watch":
            cmd.add_argument("--cycles", type=positive, default=1, help="Bounded by default")
            cmd.add_argument("--forever", action="store_true", help="Run until Ctrl+C")
        if name == "serve":
            cmd.add_argument("--port", type=int, default=8765)
            cmd.add_argument("--watch", action="store_true", help="Also scan in the foreground process")
        if name == "scan":
            cmd.add_argument("--fail-on-incident", action="store_true", help="Exit 2 if an incident is open (CI integration)")
        if name == "explain":
            cmd.add_argument("--provider", choices=("deterministic", "ollama"), default="deterministic")
            cmd.add_argument("--model", default="qwen2.5:3b")
            cmd.add_argument("--timeout", type=float, default=15)
    commands.add_parser("evaluate", help="Run the deterministic fixture evaluation without external services")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    try:
        if args.command == "demo":
            result = create_demo(args.workspace, args.scenario)
        elif args.command == "scenario":
            result = set_scenario(args.workspace, args.name)
        elif args.command == "evaluate":
            from .evaluation import evaluate
            result = evaluate()
            print(json.dumps(result, indent=2))
            return 0 if result["passed"] else 1
        else:
            app = Watchdog(args.config, args.db or args.config.resolve().parent / "watchdog.db")
            if args.command == "scan":
                result = app.scan()
                print(json.dumps(result, indent=2))
                return 2 if args.fail_on_incident and result["open_incidents"] else 0
            if args.command == "backup":
                result = app.store.backup(args.output)
            elif args.command == "prune":
                result = app.store.prune(args.retain_days, args.apply)
            elif args.command == "report":
                result = app.summary()
            elif args.command == "explain":
                result = app.summary()["triage"]
                if args.provider == "ollama":
                    result = explain_with_ollama(app.store.incidents("open"), result, args.model, args.timeout)
            elif args.command in {"watch", "serve"}:
                if args.interval < 5:
                    raise ValueError("Scan interval must be at least 5 seconds")
                if args.command == "watch":
                    count = 0
                    while args.forever or count < args.cycles:
                        started = time.monotonic()
                        print(json.dumps(app.scan()), flush=True)
                        count += 1
                        if args.forever or count < args.cycles:
                            time.sleep(max(0, args.interval - (time.monotonic() - started)))
                    return 0
                if not 0 <= args.port <= 65535:
                    raise ValueError("Invalid port")
                server = make_server(app, args.port)
                stop = threading.Event()
                def worker():
                    while not stop.is_set():
                        try:
                            app.scan()
                        except Exception:
                            logging.getLogger("watchdog").exception("scan_failed")
                        stop.wait(args.interval)
                thread = None
                if args.watch:
                    thread = threading.Thread(target=worker, daemon=True)
                    thread.start()
                print(f"Read-only dashboard: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)", flush=True)
                try:
                    server.serve_forever()
                finally:
                    stop.set()
                    server.server_close()
                    if thread:
                        thread.join(timeout=6)
                return 0
        print(json.dumps(result, indent=2))
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

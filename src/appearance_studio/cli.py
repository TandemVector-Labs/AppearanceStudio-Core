from __future__ import annotations
import argparse, json
from .engine import apply, plan, status
from .diagnostics import report as diagnostic_report

def main(argv=None):
    parser = argparse.ArgumentParser(prog="appearance-studio", description="Appearance Studio desktop appearance center")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("diagnostics")
    sub.add_parser("monitor")
    sub.add_parser("system-monitor")
    sub.add_parser("system-monitor-diagnostic")
    planned = sub.add_parser("plan")
    planned.add_argument("theme")
    planned.add_argument("--mode", choices=("dark", "light"))
    applied = sub.add_parser("apply")
    applied.add_argument("theme")
    applied.add_argument("--mode", choices=("dark", "light"))
    args = parser.parse_args(argv)
    if args.command == "status":
        result = status()
    elif args.command == "diagnostics":
        result = diagnostic_report()
    elif args.command == "monitor":
        from .monitor import run
        return run()
    elif args.command == "system-monitor":
        from .system_monitor import main as monitor_main
        return monitor_main([])
    elif args.command == "system-monitor-diagnostic":
        from .system_monitor_model import Collector, DEFAULTS, diagnostic
        print(json.dumps(diagnostic(Collector().collect(DEFAULTS), DEFAULTS), ensure_ascii=False, indent=2))
        return 0
    elif args.command == "plan":
        result = plan(args.theme, args.mode)
    else:
        result = apply(args.theme, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

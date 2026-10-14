from __future__ import annotations
import sys

def main():
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        return cli_main(sys.argv[1:])
    from .ui import main as ui_main
    return ui_main()

if __name__ == "__main__":
    raise SystemExit(main())

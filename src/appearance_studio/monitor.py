from __future__ import annotations
import json, selectors, subprocess, time
from .engine import apply, ApplyError
from .paths import runtime_state

QUIET_SECONDS = 0.8
MIN_APPLY_GAP = 1.5

def active_theme():
    path = runtime_state() / "last-apply.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("theme")
        return value if isinstance(value, str) and value else None
    except Exception:
        return None

def _write_error(message):
    state=runtime_state(); state.mkdir(parents=True,exist_ok=True)
    payload={"schema":1,"at_unix":time.time(),"error":str(message)[:500]}
    tmp=state/"monitor-error.json.new"
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(state/"monitor-error.json")

def run():
    process = subprocess.Popen(
        ["gsettings","monitor","org.gnome.desktop.interface","color-scheme"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1
    )
    selector=selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    pending_at=None
    last_apply=0.0
    while process.poll() is None:
        for key,_ in selector.select(timeout=0.25):
            line=key.fileobj.readline()
            if line:
                pending_at=time.monotonic()
        now=time.monotonic()
        if pending_at is None or now-pending_at < QUIET_SECONDS:
            continue
        if now-last_apply < MIN_APPLY_GAP:
            continue
        pending_at=None
        theme=active_theme()
        if not theme:
            continue
        try:
            apply(theme)
            last_apply=time.monotonic()
        except Exception as exc:
            _write_error(exc)
            last_apply=time.monotonic()
    return process.returncode or 0

if __name__=="__main__":
    raise SystemExit(run())

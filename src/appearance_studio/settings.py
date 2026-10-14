from __future__ import annotations
import ast, subprocess

class SettingsError(RuntimeError):
    pass

def _run(args, timeout=4):
    try:
        return subprocess.run([str(x) for x in args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SettingsError("desktop settings service did not respond") from exc

def get(schema, key):
    proc = _run(["gsettings", "get", schema, key])
    if proc.returncode:
        raise SettingsError((proc.stderr or proc.stdout).strip())
    return proc.stdout.strip()

def equivalent(current, requested):
    current, requested = str(current).strip(), str(requested).strip()
    if current == requested:
        return True
    try:
        return ast.literal_eval(current) == ast.literal_eval(requested)
    except Exception:
        pass
    return len(current) >= 2 and current[0] == current[-1] == "'" and current[1:-1] == requested

def set_if_changed(schema, key, value):
    if isinstance(value, bool):
        value = "true" if value else "false"
    value = str(value)
    before = get(schema, key)
    if equivalent(before, value):
        return False
    proc = _run(["gsettings", "set", schema, key, value])
    if proc.returncode:
        raise SettingsError((proc.stderr or proc.stdout).strip())
    return True

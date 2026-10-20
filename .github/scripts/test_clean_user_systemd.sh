#!/usr/bin/env bash
# Only a fresh GitHub-hosted Linux runner may run this. NEVER run on owner desktops.
# Test the EXACT official Core user-unit names under a newly created user manager.
set -euo pipefail
if [[ "$(printenv GITHUB_ACTIONS || :)" != true ||
      "$(printenv RUNNER_ENVIRONMENT || :)" != github-hosted ||
      "$(printenv RUNNER_OS || :)" != Linux ||
      ! "$(printenv GITHUB_RUN_ID || :)" =~ ^[0-9]+$ ]]; then
  echo "Refusing: dedicated GitHub-hosted Linux runner required" >&2
  exit 2
fi
if [[ "$(id -u)" == 0 ]]; then echo "Refusing root caller" >&2; exit 2; fi
if [[ "$(ps -p 1 -o comm= | xargs)" != systemd ]]; then
  echo "Real systemd PID 1 unavailable" >&2; exit 2
fi
for binary in loginctl systemctl sudo useradd userdel tar; do
  command -v "$binary" >/dev/null || { echo "Missing $binary" >&2; exit 2; }
done
tester="ascore$(printf '%s' "$GITHUB_RUN_ID" | tail -c 7)"
home="/home/$tester"
if getent passwd "$tester" >/dev/null || [[ -e "$home" ]]; then
  echo "Refusing pre-existing test user/home" >&2; exit 2
fi
created=0
uid=""
cleanup() {
  result=$?
  trap - EXIT
  if [[ "$created" == 1 ]]; then
    if [[ -n "$uid" ]]; then
      sudo loginctl disable-linger "$tester" >/dev/null 2>&1 || :
      sudo loginctl terminate-user "$tester" >/dev/null 2>&1 || :
      sudo systemctl stop "user@$uid.service" >/dev/null 2>&1 || :
    fi
    sudo userdel -r "$tester" >/dev/null 2>&1 || {
      echo "WARNING: could not remove disposable CI user" >&2
      result=1
    }
  fi
  exit "$result"
}
trap cleanup EXIT
sudo useradd --create-home --shell /bin/bash "$tester"
created=1
uid="$(id -u "$tester")"
echo "CI_TEST_USER_UID=$uid"
sudo install -d -m 0700 -o "$tester" -g "$tester" "$home/source"
tar --exclude=.git -C "$GITHUB_WORKSPACE" -cf - . | sudo tar -C "$home/source" -xf -
sudo chown -R "$tester:$tester" "$home/source"
sudo loginctl enable-linger "$tester"
sudo systemctl start "user@$uid.service"
runtime="/run/user/$uid"
# A newly created user with no login often has no active user bus socket;
# bootstrap only that dedicated CI account's dbus.socket, never the runner's.
if ! sudo -u "$tester" -H env "XDG_RUNTIME_DIR=$runtime" \
  systemctl --user start dbus.socket; then
  echo "Dedicated user manager could not start dbus.socket" >&2
fi
for _ in $(seq 1 40); do
  # The 0700 runtime directory cannot be traversed by the runner user.
  # Inspect the socket as its actual owner; NEVER loosen runtime permissions.
  sudo -u "$tester" -H test -S "$runtime/bus" && break
  sleep .25
done
if ! sudo -u "$tester" -H test -S "$runtime/bus"; then
  echo "Dedicated user bus not running" >&2
  sudo systemctl status "user@$uid.service" --no-pager --full || :
  sudo -u "$tester" -H env "XDG_RUNTIME_DIR=$runtime" \
    systemctl --user status dbus.socket --no-pager --full || :
  sudo journalctl -u "user@$uid.service" --no-pager -n 35 || :
  sudo ls -la "$runtime" || :
  exit 1
fi
as_user() {
  sudo -u "$tester" -H env \
    "HOME=$home" \
    "XDG_CONFIG_HOME=$home/.config" \
    "XDG_DATA_HOME=$home/.local/share" \
    "XDG_STATE_HOME=$home/.local/state" \
    "XDG_RUNTIME_DIR=$runtime" \
    "DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime/bus" \
    "GSETTINGS_BACKEND=keyfile" \
    "$@"
}
# Explicitly isolate unit environments too: user@UID.service can inherit the
# runner's XDG_CONFIG_HOME even when the CLI is called with sudo -H.
as_user systemctl --user set-environment \
  "HOME=$home" "XDG_CONFIG_HOME=$home/.config" \
  "XDG_DATA_HOME=$home/.local/share" \
  "XDG_STATE_HOME=$home/.local/state" \
  "GSETTINGS_BACKEND=keyfile" \
  "DBUS_SESSION_BUS_ADDRESS=unix:path=$runtime/bus"
source="$home/source"
unit_theme="appearance-studio-theme-monitor.service"
unit_system="appearance-studio-system-monitor.service"
for unit in "$unit_theme" "$unit_system"; do
  fragment="$(as_user systemctl --user show "$unit" --property=FragmentPath --value)"
  [[ -z "$fragment" ]] || { echo "Pre-existing $unit: $fragment" >&2; exit 1; }
done
as_user /usr/bin/python3 -B "$source/install.py" --dry-run
as_user /usr/bin/python3 -B "$source/install.py"
receipt="$home/.local/state/appearance-studio/install-manifest.json"
[[ -f "$receipt" ]] || { echo "Receipt not produced" >&2; exit 1; }
as_user /usr/bin/python3 -B "$source/install.py" --activate
for unit in "$unit_theme" "$unit_system"; do
  want="$home/.config/systemd/user/$unit"
  fragment="$(as_user systemctl --user show "$unit" --property=FragmentPath --value)"
  [[ "$fragment" == "$want" ]] || {
    echo "Loaded foreign unit $unit: $fragment" >&2; exit 1;
  }
  as_user systemctl --user is-enabled "$unit"
  as_user systemctl --user is-active "$unit"
  restarts="$(as_user systemctl --user show "$unit" --property=NRestarts --value)"
  [[ "$restarts" == 0 ]] || { echo "$unit restarted: $restarts" >&2; exit 1; }
done
sleep 2
for unit in "$unit_theme" "$unit_system"; do as_user systemctl --user is-active "$unit"; done
state_file="$home/.local/state/appearance-studio/system-monitor-indicator.json"
[[ -f "$state_file" ]] || { echo "System monitor status missing" >&2; exit 1; }
as_user /usr/bin/python3 -c \
  'import json,sys; d=json.load(open(sys.argv[1])); assert d["build_id"]=="APPEARANCE-STUDIO-MONITOR-1"; assert isinstance(d["updated_at"],int)' \
  "$state_file"
echo "REAL_CLEAN_USER_OFFICIAL_CORE_UNITS_ACTIVE_PASS"
as_user /usr/bin/python3 -B "$source/install.py"
for unit in "$unit_theme" "$unit_system"; do as_user systemctl --user is-active "$unit"; done
as_user /usr/bin/python3 -B "$source/uninstall.py"
for unit in "$unit_theme" "$unit_system"; do
  state="$(as_user systemctl --user show "$unit" --property=ActiveState --value)"
  [[ "$state" != active ]] || { echo "$unit still active after uninstall" >&2; exit 1; }
  enabled="$(as_user systemctl --user is-enabled "$unit" 2>/dev/null || :)"
  [[ "$enabled" != enabled ]] || { echo "$unit still enabled" >&2; exit 1; }
done
[[ ! -e "$receipt" && ! -e "$home/.local/bin/appearance-studio" ]] || {
  echo "Uninstall left Core receipt or launcher" >&2; exit 1;
}
[[ -f "$state_file" ]] || { echo "Uninstall unexpectedly removed personal state" >&2; exit 1; }
echo "REAL_CLEAN_USER_OFFICIAL_CORE_UNITS_UNINSTALL_PASS"
echo "REAL_CLEAN_USER_SYSTEMD_INTEGRATION_PASS"

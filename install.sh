#!/bin/zsh
# Install the Quick Actions in this repo into ~/Library/Services and make them
# visible in Finder's right-click > Quick Actions menu. Safe to re-run.
#
# Copying a .workflow into ~/Library/Services registers it with the system, but
# macOS still hides it from the context menu until it has an explicit entry in
# the `pbs` NSServicesStatus preference. Automator writes that entry when YOU
# save a Quick Action; a plain file copy does not. So this script writes it too.
set -euo pipefail
cd "$(dirname "$0")"

# Run the gates in gates/ before every push.
git config core.hooksPath hooks

dest="$HOME/Library/Services"
mkdir -p "$dest"

for wf in quick-actions/*.workflow; do
  name="${wf##*/}"
  rsync -a --delete --exclude .DS_Store "$wf/" "$dest/$name/"
  echo "installed  $name"
done

# Mark every installed Quick Action as visible in the context menu.
python3 - "$dest" <<'PY'
import os, plistlib, subprocess, sys, tempfile

dest = sys.argv[1]
raw = subprocess.run(["defaults", "export", "pbs", "-"],
                     capture_output=True, check=True).stdout
status = plistlib.loads(raw)
entries = status.setdefault("NSServicesStatus", {})

changed = []
for wf in sorted(os.listdir(dest)):
    if not wf.endswith(".workflow"):
        continue
    info = os.path.join(dest, wf, "Contents", "Info.plist")
    try:
        with open(info, "rb") as fh:
            svcs = plistlib.load(fh).get("NSServices", [])
    except Exception:
        continue
    for svc in svcs:
        label = (svc.get("NSMenuItem") or {}).get("default")
        message = svc.get("NSMessage")
        if not label or not message:
            continue
        key = f"(null) - {label} - {message}"
        want = {"presentation_modes": {"ContextMenu": True, "FinderPreview": True,
                                       "ServicesMenu": True, "TouchBar": True}}
        if entries.get(key) != want:
            entries[key] = want
            changed.append(label)

if changed:
    fd, tmp = tempfile.mkstemp(suffix=".plist")
    with os.fdopen(fd, "wb") as fh:
        plistlib.dump(status, fh)
    subprocess.run(["defaults", "import", "pbs", tmp], check=True)
    os.unlink(tmp)
    for label in changed:
        print(f"enabled    {label}")
else:
    print("enabled    (all already enabled)")
PY

# Rebuild the Services cache and reload Finder's menu.
/System/Library/CoreServices/pbs -update 2>/dev/null || true
killall Finder 2>/dev/null || true

echo "done -> $dest"
echo "Finder was restarted so the menu picks up any changes."

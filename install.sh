#!/bin/zsh
# Install the Quick Actions in this repo into ~/Library/Services so they show
# up in Finder's Quick Actions / Services menu. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

dest="$HOME/Library/Services"
mkdir -p "$dest"

for wf in quick-actions/*.workflow; do
  name="${wf##*/}"
  rsync -a --delete --exclude .DS_Store "$wf/" "$dest/$name/"
  echo "installed  $name"
done

# Ask the pasteboard server to rescan Services.
/System/Library/CoreServices/pbs -update 2>/dev/null || true
echo "done -> $dest"

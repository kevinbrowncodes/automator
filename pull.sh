#!/bin/zsh
# Copy live Quick Actions from ~/Library/Services back into this repo.
# Automator always saves Quick Actions to ~/Library/Services, so after editing
# one, run this, review `git diff`, and commit.
#
#   ./pull.sh        refresh the Quick Actions already tracked here
#   ./pull.sh --all  also pick up any new Quick Actions installed on this Mac
set -euo pipefail
cd "$(dirname "$0")"

src="$HOME/Library/Services"

if [[ "${1:-}" == "--all" ]]; then
  list=("$src"/*.workflow(N))
else
  list=()
  for wf in quick-actions/*.workflow; do list+=("$src/${wf##*/}"); done
fi

for wf in "${list[@]}"; do
  name="${wf##*/}"
  if [[ -d "$wf" ]]; then
    rsync -a --delete --exclude .DS_Store "$wf/" "quick-actions/$name/"
    echo "pulled     $name"
  else
    echo "missing    $name (not installed in $src)"
  fi
done

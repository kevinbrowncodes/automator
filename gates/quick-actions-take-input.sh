#!/bin/zsh
# Gate: every Quick Action must take input, or Finder hides it from right-click.
#
# Finder only lists a Quick Action in its context menu if the action receives
# something: files, folders, images, text. One set to "no input" installs and
# enables fine but only shows up under Finder > Services in the menu bar, with
# no warning. (Even with input, no Quick Action shows on a right-click on empty
# space: that clears the selection. That needs a Finder Sync extension.)
#
# Usage: gates/quick-actions-take-input.sh [quick-actions-dir]
set -uo pipefail
cd "$(dirname "$0")/.."
dir="${1:-quick-actions}"

failed=()
for wf in "$dir"/*.workflow(N); do
  input=$(plutil -extract workflowMetaData.serviceInputTypeIdentifier raw -o - \
          "$wf/Contents/document.wflow" 2>/dev/null)
  if [[ -z "$input" || "$input" == com.apple.Automator.nothing ]]; then
    failed+=("${wf##*/}")
  fi
done

if (( ${#failed} )); then
  print -u2 "FAIL quick-actions-take-input: these Quick Actions receive no input,"
  print -u2 "so Finder will never show them under right-click > Quick Actions:"
  for f in $failed; print -u2 "  - $f"
  print -u2 ""
  print -u2 "Fix: in Automator, set \"Workflow receives current\" to \"files or folders\""
  print -u2 "in \"Finder\" (or whatever the action works on), save, then ./pull.sh."
  print -u2 "Right-clicking empty space never shows a Quick Action (it clears the"
  print -u2 "selection); for that, use a Finder Sync extension. See README, \"The gotcha\"."
  exit 1
fi
print "ok   quick-actions-take-input"

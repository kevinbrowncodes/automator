#!/bin/zsh
# Gate: never extract frames with ffmpeg's select or fps filters.
#
# select='...' and fps=N can hand back the first frame several times over before
# the video actually moves, so a contact sheet or frame grab shows a frozen hold
# that isn't in the footage. Grab each frame on its own instead, with -ss BEFORE
# -i (fast seek to the keyframe, then exact decode to the requested time), as
# scripts/contact_sheet.py does.
#
# Checks scripts/ and the shell scripts embedded in quick-actions/, workflows/
# and applications/.
#
# Usage: gates/no-select-filter-frames.sh
set -uo pipefail
cd "$(dirname "$0")/.."

# A filter name directly followed by "=", as it appears inside -vf / -filter_complex.
pattern='(^|[^A-Za-z0-9_-])(select|fps)='
files=(scripts/**/*(N.) {quick-actions,workflows,applications}/**/document.wflow(N.))

hits=$(grep -nE "$pattern" -- $files 2>/dev/null)
if [[ -n "$hits" ]]; then
  print -u2 "FAIL no-select-filter-frames: frames are extracted with the select or fps filter:"
  print -r -- "$hits" | sed 's/^/  /' >&2
  print -u2 ""
  print -u2 "These filters can repeat the first frame and fake a frozen hold."
  print -u2 "Fix: grab each frame with its own ffmpeg call, -ss <time> BEFORE -i <file>,"
  print -u2 "plus -frames:v 1. See grab_command() in scripts/contact_sheet.py."
  exit 1
fi
print "ok   no-select-filter-frames"

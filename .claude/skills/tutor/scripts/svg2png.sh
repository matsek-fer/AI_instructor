#!/usr/bin/env bash
# Render an SVG to PNG so the tutor can visually inspect its own diagram.
# Usage: svg2png.sh input.svg output.png
set -euo pipefail
in="$1"
out="$2"
if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert --width 800 --keep-aspect-ratio -o "$out" "$in"
elif command -v inkscape >/dev/null 2>&1; then
    inkscape "$in" --export-type=png --export-width=800 \
        --export-filename="$out" >/dev/null 2>&1
elif command -v magick >/dev/null 2>&1; then
    magick -density 96 "$in" -resize 800x "$out"
elif command -v convert >/dev/null 2>&1; then
    convert -density 96 "$in" -resize 800x "$out"
else
    echo "no SVG renderer found (install librsvg, inkscape, or imagemagick);" \
         "skip the visual check and rely on source review" >&2
    exit 3
fi

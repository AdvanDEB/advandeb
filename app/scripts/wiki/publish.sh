#!/usr/bin/env bash
# Publish the workshop wiki: build the reader's edition, copy it to the server.
#
# The build runs where the vault lives, because it needs the transcripts'
# durations to date its session citations; the transcripts themselves never
# leave this machine. The server only receives the finished bundle, and the
# backend picks it up on the next request (it re-reads the file on change).
#
#   app/scripts/wiki/publish.sh
#
# Settings, from the environment:
#   WIKI_VAULT        the Obsidian vault            (~/AdvanDEBradionica/Workshop)
#   WIKI_EN           the English mirror            (~/AdvanDEBradionica/wiki-en)
#   WIKI_EDITS        reader edits, YAML            (~/AdvanDEBradionica/wiki-reader-edits.yaml)
#   WIKI_HOST         ssh host of the server        (adeb)
#   WIKI_REMOTE_PATH  bundle path there, relative to its home; must match the
#                     backend's WIKI_BUNDLE_PATH    (advandeb-data/wiki/wiki-bundle.json)
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
vault=${WIKI_VAULT:-$HOME/AdvanDEBradionica/Workshop}
en=${WIKI_EN:-$HOME/AdvanDEBradionica/wiki-en}
edits=${WIKI_EDITS:-$HOME/AdvanDEBradionica/wiki-reader-edits.yaml}
host=${WIKI_HOST:-adeb}
remote=${WIKI_REMOTE_PATH:-advandeb-data/wiki/wiki-bundle.json}

out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT

# --strict refuses broken links, stale edits and any line that still talks
# about recordings or transcripts.
python3 "$here/build_wiki.py" --vault "$vault" --en "$en" --edits "$edits" \
  --json "$out/wiki-bundle.json" --strict

ssh "$host" "mkdir -p \"\$(dirname '$remote')\""
rsync -a --chmod=F640 "$out/wiki-bundle.json" "$host:$remote.tmp"
# Same filesystem, so the swap is atomic: the backend never reads half a file.
ssh "$host" "mv '$remote.tmp' '$remote'"
echo "published to $host:$remote"

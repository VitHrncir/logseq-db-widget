#!/usr/bin/env bash
# Build a release: bin/logseq-db.plasmoid and logseq-db-widget-<version>.tar.gz.
#
#     tools/make-release.sh [output folder]     # default: the current folder
#
# The tarball holds this repository in a folder named after the version, with
# the built widget package in bin/. The version comes from package/metadata.json.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
out="$(cd "${1:-.}" && pwd)"
version="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["KPlugin"]["Version"])' \
           "$repo/package/metadata.json")"
name="logseq-db-widget-$version"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# A clean copy, without caches or test leftovers.
mkdir "$work/$name"
(cd "$repo" && tar --exclude='__pycache__' --exclude='bin' --exclude='*.pyc' \
                   --exclude='*.tags' --exclude='*.stopped*' --exclude='*.synced' -cf - .) \
    | tar -xf - -C "$work/$name"

# The widget package (a zip file, as Plasma requires), into bin/.
mkdir "$work/$name/bin"
(cd "$work/$name/package" && zip -qrX "$work/$name/bin/logseq-db.plasmoid" .)

tar --sort=name --owner=0 --group=0 --numeric-owner \
    -czf "$out/$name.tar.gz" -C "$work" "$name"
echo "$out/$name.tar.gz"

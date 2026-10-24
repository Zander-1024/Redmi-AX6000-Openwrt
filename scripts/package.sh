#!/usr/bin/env bash
set -euo pipefail
output=${1:?Expected build output directory}
src=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$src/scripts/bundle.py" "$output"
mkdir -p "$output/release"
for profile in stock ubootmod migration; do
    (cd "$output/$profile" && sha256sum -c SHA256SUMS)
    tar -czf "$output/release/ax6000-$profile.tar.gz" -C "$output/$profile" .
done
cp "$src/docs/ubootmod.md" "$output/release/migration-and-recovery.md"
(cd "$output/release" && sha256sum ax6000-*.tar.gz migration-and-recovery.md > SHA256SUMS)

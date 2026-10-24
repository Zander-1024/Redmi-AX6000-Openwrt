#!/usr/bin/env bash
# Host entry point: all build dependencies and execution stay inside Docker.
set -euo pipefail
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
mode=${1:-all}
case "$mode" in all|stock|ubootmod|recovery|check|package) ;; *) echo 'Usage: ./scripts/ci-local.sh [all|stock|ubootmod|recovery|check|package]' >&2; exit 2;; esac
docker info >/dev/null
docker build -t ax6000-builder:25.12.6 -f "$root/docker/Dockerfile" "$root/docker"
mkdir -p "$root/build-output"
docker run --rm --init \
    --mount "type=bind,src=$root,dst=/src,readonly" \
    --mount "type=bind,src=$root/build-output,dst=/output" \
    --mount type=volume,src=ax6000-openwrt-build,dst=/work \
    -e BUILD_JOBS="${BUILD_JOBS:-8}" \
    ax6000-builder:25.12.6 bash /src/scripts/build.sh "$mode"

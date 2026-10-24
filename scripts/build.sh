#!/usr/bin/env bash
set -euo pipefail
src=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
mode=${1:-all}
tree=${OPENWRT_TREE:-/work/openwrt}
output=${BUILD_OUTPUT:-/output}
jobs=${BUILD_JOBS:-8}
mkdir -p "$output"
if [[ "$mode" == package ]]; then
    bash "$src/scripts/package.sh" "$output"
    exit
fi
if [[ "$mode" == check ]]; then
    python3 "$src/scripts/openwrt-docs.py" verify
    LC_ALL=C.UTF-8 shellcheck --severity=warning "$src/diy-part1.sh" "$src"/scripts/*.sh "$src"/files/etc/uci-defaults/*
    python3 -m unittest discover -s "$src/tests" -v
    exit
fi
case "$mode" in all) modes=(stock ubootmod recovery);; stock|ubootmod|recovery) modes=("$mode");; *) exit 2;; esac
# One persistent build tree; do not run profile changes concurrently.
exec 9>"$(dirname "$tree")/ax6000-build.lock"
flock -n 9 || { echo 'Another build uses this Docker volume' >&2; exit 1; }
# shellcheck source=../sources.lock
source "$src/sources.lock"
if [[ ! -d "$tree/.git" ]]; then
    git clone --depth=1 --branch "$OPENWRT_REF" "$OPENWRT_URL" "$tree"
fi
test "$(git -C "$tree" rev-parse HEAD)" = "$OPENWRT_COMMIT"
cd "$tree"
bash "$src/diy-part1.sh"
for profile in "${modes[@]}"; do
    python3 "$src/scripts/configure.py" "$tree" "$profile"
    mkdir -p files
    # Delete only this dedicated build tree's previous overlay.
    rsync -a --delete "$src/files/" files/
    if [[ "$profile" == recovery ]]; then
        rm -f files/etc/uci-defaults/zzz-custom
    fi
    make defconfig
    python3 "$src/scripts/verify-config.py" "$tree" "$profile"
    make download -j"$jobs"
    make -j"$jobs" || make -j1 V=s
    python3 "$src/scripts/collect.py" "$tree" "$profile" "$output/$profile"
done
if [[ "$mode" == all ]]; then
    bash "$src/scripts/package.sh" "$output"
fi

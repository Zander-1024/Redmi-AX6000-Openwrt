#!/bin/bash
# Run from the locked OpenWrt source tree before loading the build config.
set -euo pipefail

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=sources.lock
. "$SCRIPT_DIR/sources.lock"

[ "$(git rev-parse HEAD)" = "$OPENWRT_COMMIT" ] || {
    echo "OpenWrt checkout does not match sources.lock" >&2
    exit 1
}

# Rebuild from the release's own pinned feeds, not a second hand-maintained list.
# This also makes repeated execution independent of previously added feed lines.
feeds_tmp=$(mktemp)
recipe_tmp=$(mktemp)
trap 'rm -f "$feeds_tmp" "$recipe_tmp"' EXIT
{
    printf 'src-git passwall_packages %s^%s\n' "$PASSWALL_PACKAGES_URL" "$PASSWALL_PACKAGES_COMMIT"
    printf 'src-git passwall2 %s^%s\n' "$PASSWALL2_URL" "$PASSWALL2_COMMIT"
    printf 'src-git mosdns %s^%s\n' "$MOSDNS_URL" "$MOSDNS_COMMIT"
    git show "$OPENWRT_COMMIT:feeds.conf.default"
} > "$feeds_tmp"
mv "$feeds_tmp" feeds.conf.default

# Argon 3.x includes its settings UI; do not add luci-app-argon-config.
if [ ! -e package/luci-theme-argon ]; then
    git init -q package/luci-theme-argon
    git -C package/luci-theme-argon remote add origin "$ARGON_URL"
    git -C package/luci-theme-argon fetch --depth=1 origin "$ARGON_COMMIT"
    git -C package/luci-theme-argon checkout --detach FETCH_HEAD
fi
[ "$(git -C package/luci-theme-argon rev-parse HEAD)" = "$ARGON_COMMIT" ] || {
    echo "Argon checkout does not match sources.lock" >&2
    exit 1
}

./scripts/feeds update -a
for source in passwall_packages passwall2 mosdns; do
    case "$source" in
        passwall_packages) expected=$PASSWALL_PACKAGES_COMMIT ;;
        passwall2) expected=$PASSWALL2_COMMIT ;;
        mosdns) expected=$MOSDNS_COMMIT ;;
    esac
    [ "$(git -C "feeds/$source" rev-parse HEAD)" = "$expected" ] || {
        echo "Unexpected revision for $source" >&2
        exit 1
    }
done

# Xray 26.10.21 requires Go 1.27. Keep the official Go feed and change only
# this recipe's host dependency. Accept our previous patch, reject other drift.
recipe=feeds/passwall_packages/xray-core/Makefile
grep -Fxq 'PKG_NAME:=Xray-core' "$recipe"
grep -Fxq 'PKG_VERSION:=26.10.21' "$recipe"
awk '
    /^PKG_BUILD_DEPENDS:=golang\/host$/ {
        $0 = "PKG_BUILD_DEPENDS:=golang1.27/host"
    }
    /^PKG_BUILD_DEPENDS:/ { dependencies++ }
    /^PKG_BUILD_DEPENDS:=golang1\.27\/host$/ { expected++ }
    { print }
    END { if (dependencies != 1 || expected != 1) exit 1 }
' "$recipe" > "$recipe_tmp"
cat "$recipe_tmp" > "$recipe"
./scripts/feeds update -i passwall_packages
./scripts/feeds install -a

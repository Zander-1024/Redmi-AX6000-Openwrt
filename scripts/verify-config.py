#!/usr/bin/env python3
import sys
from pathlib import Path

tree, mode = Path(sys.argv[1]).resolve(), sys.argv[2]
requested = {s for s in (tree / 'requested.config').read_text().splitlines()
             if s.startswith('CONFIG_') and s.endswith('=y')}
final = set((tree / '.config').read_text().splitlines())
missing = requested - final
if missing:
    raise SystemExit('Required options lost by defconfig: ' + ', '.join(sorted(missing)))
layout = 'stock' if mode == 'stock' else 'ubootmod'
devices = {s for s in final if s.startswith('CONFIG_TARGET_') and '_DEVICE_' in s and s.endswith('=y')}
assert devices == {f'CONFIG_TARGET_mediatek_filogic_DEVICE_xiaomi_redmi-router-ax6000-{layout}=y'}, devices
assert 'CONFIG_USE_APK=y' in final
for feed in ('passwall_packages', 'passwall2', 'mosdns'):
    assert f'# CONFIG_FEED_{feed} is not set' in final, feed
if mode != 'recovery':
    assert 'CONFIG_PACKAGE_dnsmasq-full=y' in final
    assert '# CONFIG_TARGET_ROOTFS_INITRAMFS is not set' in final
    providers = {
        'luci-app-passwall2': 'passwall2/luci-app-passwall2',
        'sing-box': 'passwall_packages/sing-box', 'xray-core': 'passwall_packages/xray-core',
        'hysteria': 'passwall_packages/hysteria', 'v2ray-plugin': 'passwall_packages/v2ray-plugin',
        'v2ray-geodata': 'passwall_packages/v2ray-geodata', 'mosdns': 'mosdns/mosdns',
        'geo2txt': 'mosdns/geo2txt', 'v2ray-core': 'packages/net/v2ray-core',
        'nlbwmon': 'packages/net/nlbwmon', 'luci-app-nlbwmon': 'luci/applications/luci-app-nlbwmon',
    }
    for package, source in providers.items():
        installed = tree / 'package/feeds' / source.split('/')[0] / package
        assert installed.is_symlink() and installed.resolve() == tree / 'feeds' / source, package
    metadata = (tree / 'feeds/passwall_packages.tmp/.packageinfo').read_text()
    xray = next(s for s in metadata.split('Source-Makefile:') if '\nPackage: xray-core\n' in s)
    assert 'Build-Depends: golang1.27/host\n' in xray
else:
    assert 'CONFIG_PACKAGE_kmod-mtd-rw=y' in final
    assert 'CONFIG_TARGET_ROOTFS_INITRAMFS=y' in final
    mtdrw = tree / 'package/feeds/packages/mtd-rw'
    assert mtdrw.is_symlink() and mtdrw.resolve() == tree / 'feeds/packages/kernel/mtd-rw'
    for package in ('xray-core', 'sing-box', 'hysteria', 'mosdns', 'v2ray-core', 'ttyd'):
        assert f'CONFIG_PACKAGE_{package}=y' not in final, package
print(f'{mode}: resolved package providers, device, APK and initramfs configuration verified')

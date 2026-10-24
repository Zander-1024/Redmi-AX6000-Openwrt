#!/usr/bin/env python3
"""Fail closed on image identity, real manifests, capacity and embedded defaults."""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from firmware import budget, fit_root, extract_initrd, MIB, PEB, LEB, ENV_SIZE, RECOVERY_SIZE

tree, mode, output = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3])
repo = Path(__file__).resolve().parent.parent
target = tree / 'bin/targets/mediatek/filogic'
layout = 'stock' if mode == 'stock' else 'ubootmod'
device = 'xiaomi_redmi-router-ax6000-' + layout


def one(pattern):
    files = list(target.glob(pattern))
    if len(files) != 1 or files[0].stat().st_size == 0:
        raise SystemExit(f'Expected one nonempty {pattern}: {files}')
    return files[0]


manifest = one(f'*-{device}.manifest')
packages = dict(line.split(' - ', 1) for line in manifest.read_text().splitlines())
required = {'dropbear', 'dnsmasq', 'firewall4', 'mtd', 'ubi-utils', 'uboot-envtools'} if mode == 'recovery' else {
    'luci-app-passwall2', 'xray-core', 'sing-box', 'hysteria', 'v2ray-core', 'v2ray-plugin',
    'mosdns', 'geo2txt', 'v2ray-geoip', 'v2ray-geosite', 'luci-theme-argon', 'wpad-mbedtls',
    'apk-mbedtls', 'luci-app-package-manager', 'luci-app-ddns', 'luci-app-upnp',
    'luci-app-ttyd', 'ttyd', 'dropbear', 'dnsmasq-full', 'firewall4', 'nlbwmon', 'luci-app-nlbwmon',
    'luci-i18n-nlbwmon-zh-cn',
}
required.update({'fwtool', 'jsonfilter', 'fitblk', 'fit-check-sign'})
if mode == 'recovery':
    required.add('kmod-mtd-rw')
else:
    required.update(s.removeprefix('CONFIG_PACKAGE_').removesuffix('=y')
                    for s in (repo / '.config').read_text().splitlines()
                    if s.startswith('CONFIG_PACKAGE_ddns-scripts') and s.endswith('=y'))
forbidden = {'luci-app-passwall', 'luci-app-argon-config', 'opkg', 'adguardhome', 'luci-app-adguardhome'}
if mode == 'recovery':
    forbidden.update({'xray-core', 'sing-box', 'hysteria', 'v2ray-core', 'mosdns', 'ttyd'})
else:
    forbidden.add('kmod-mtd-rw')
    forbidden.update(p for p in packages if p.startswith('wpad-basic'))
missing, unwanted = required - packages.keys(), forbidden & packages.keys()
if missing or unwanted:
    raise SystemExit(f'Invalid image packages: {missing=}, {unwanted=}')

subprocess.run(['sha256sum', '-c', 'sha256sums'], cwd=target, check=True, stdout=subprocess.DEVNULL)
files = [manifest]
report = {'profile': mode, 'note': 'Logical UBI data budget, before UBIFS overhead and actual bad blocks'}
with tempfile.TemporaryDirectory() as work:
    work = Path(work)
    rootfs = work / 'root.squashfs'
    if mode == 'stock':
        image = one(f'*-{device}-squashfs-sysupgrade.bin')
        with tarfile.open(image) as archive:
            for name, partition in (('kernel', 30 * MIB), ('root', 80 * MIB)):
                members = [m for m in archive.getmembers() if m.isfile() and PurePosixPath(m.name).name == name]
                assert len(members) == 1, (name, members)
                report[name] = budget(partition, [members[0].size], 8 * MIB if name == 'root' else 0)
                if name == 'root':
                    rootfs.write_bytes(archive.extractfile(members[0]).read())
    elif mode == 'ubootmod':
        image = one(f'*-{device}-squashfs-sysupgrade.itb')
        report['ubi'] = budget(0x7a80000, [image.stat().st_size, ENV_SIZE, ENV_SIZE, RECOVERY_SIZE], 16 * MIB)
        offset, size = fit_root(image)
        with image.open('rb') as src:
            src.seek(offset)
            rootfs.write_bytes(src.read(size))
    else:
        image = one(f'*-{device}-initramfs-recovery.itb')
        factory = one(f'*-{device}-initramfs-factory.ubi')
        assert image.read_bytes()[:4] == bytes.fromhex('d00dfeed')
        assert factory.read_bytes()[:4] == b'UBI#'
        # Factory file already contains UBI layout and padding; leave bad PEB allowance.
        assert factory.stat().st_size <= (240 - 5) * PEB
        assert image.stat().st_size <= RECOVERY_SIZE
        report.update(recovery_bytes=image.stat().st_size, factory_bytes=factory.stat().st_size)
        files += [factory, one(f'*-{device}-preloader.bin'), one(f'*-{device}-bl31-uboot.fip')]
        assert 0 < files[-2].stat().st_size <= MIB
        assert 0 < files[-1].stat().st_size <= 2 * MIB
        initrd = work / 'initrd-root'
        extract_initrd(image, initrd)
        assert (initrd / 'etc/uci-defaults/90-ax6000-access').read_bytes() == (repo / 'files/etc/uci-defaults/90-ax6000-access').read_bytes()
        modules = list((initrd / 'lib/modules').glob('*/mtd-rw.ko'))
        assert len(modules) == 1 and modules[0].stat().st_size > 0
        report['mtd_rw_installed_bytes'] = modules[0].stat().st_size
        report['initrd_regular_file_bytes'] = sum(p.stat().st_size for p in initrd.rglob('*') if p.is_file() and not p.is_symlink())
        for binary in ('ttyd', 'mosdns', 'xray', 'sing-box', 'v2ray', 'hysteria'):
            assert not (initrd / 'usr/bin' / binary).exists(), binary
        # Repack only to reuse the same QEMU/proot harness. Binaries and defaults
        # came from the actual recovery ramdisk, not the minimal sysupgrade.
        recovery_root = tree / 'recovery-verified-root.squashfs'
        subprocess.run(['mksquashfs', str(initrd), str(recovery_root), '-noappend',
                        '-no-progress', '-processors', '1', '-comp', 'gzip'],
                       check=True, stdout=subprocess.DEVNULL)
    files.append(image)
    if mode != 'recovery':
        metadata = work / 'metadata.json'
        subprocess.run([str(tree / 'staging_dir/host/bin/fwtool'), '-i', str(metadata), str(image)], check=True)
        assert json.loads(metadata.read_text())['supported_devices'] == ['xiaomi,redmi-router-ax6000-' + layout]
        for name in ('90-ax6000-access', 'zzz-custom'):
            embedded = subprocess.check_output(['unsquashfs', '-cat', str(rootfs), 'etc/uci-defaults/' + name])
            assert embedded == (repo / 'files/etc/uci-defaults' / name).read_bytes(), name
        # Keep only the rootfs for runtime validation in this isolated build workspace.
        shutil.copyfile(rootfs, tree / f'{mode}-verified-root.squashfs')

output.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, str(repo / 'scripts/verify-runtime.py'),
                str(tree / f'{mode}-verified-root.squashfs'), str(output / 'runtime.json')], check=True)
for f in files:
    shutil.copy2(f, output / f.name)
for f in target.glob('*.buildinfo'):
    shutil.copy2(f, output / f.name)
for name, source in [('sources.lock', repo / 'sources.lock'), ('requested.config', tree / 'requested.config'),
                     ('final.config', tree / '.config'), ('upstream-sha256sums', target / 'sha256sums')]:
    shutil.copy2(source, output / name)
revisions = {'openwrt': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=tree, text=True).strip()}
revisions['configuration_git_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
revisions['configuration_dirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo, text=True).strip())
inputs = [repo / name for name in ('.config', 'sources.lock', 'diy-part1.sh')]
inputs += [p for directory in ('files', 'configs') for p in (repo / directory).rglob('*') if p.is_file()]
digest = hashlib.sha256()
for source in sorted(inputs):
    digest.update(str(source.relative_to(repo)).encode() + b'\0' + source.read_bytes() + b'\0')
revisions['configuration_inputs_sha256'] = digest.hexdigest()
for line in (tree / 'feeds.conf.default').read_text().splitlines():
    if line.startswith('src-git '):
        _, name, url = line.split()
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=tree / 'feeds' / name, text=True).strip()
        assert actual == url.rsplit('^', 1)[1], name
        revisions[name] = actual
revisions['argon'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=tree / 'package/luci-theme-argon', text=True).strip()
(output / 'build-sources.json').write_text(json.dumps(revisions, indent=2) + '\n')
(output / 'capacity.json').write_text(json.dumps(report, indent=2) + '\n')
(output / 'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n'
                                        for f in sorted(output.iterdir()) if f.is_file() and f.name != 'SHA256SUMS'))
print(json.dumps(report, indent=2))

"""Offline control-flow tests only. No MTD, UBI or bootloader is touched.

The fixture copy replaces absolute device paths and only the special-file type
check; all production label/offset/geometry/hash/phase/confirmation checks run.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('proc', 'sys/class/mtd', 'sys/class/ubi', 'sys/fs/pstore', 'dev', 'lib/modules/test', 'tmp/sysinfo', 'bin'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / 'tmp/sysinfo/board_name').write_text('xiaomi,redmi-router-ax6000-stock\n')
        (self.root / 'proc/meminfo').write_text('MemAvailable: 262144 kB\n')
        (self.root / 'proc/mounts').write_text(
            f'rootfs / rootfs rw 0 0\npstore {self.root}/sys/fs/pstore pstore rw 0 0\n')
        (self.root / 'proc/modules').write_text('')
        # Intentionally shuffled MTD numbers; a hardcoded mtd7 must fail tests.
        self.parts = [
            (8, 'BL2', 0, 1048576), (6, 'Nvram', 0x100000, 262144),
            (4, 'Bdata', 0x140000, 262144), (2, 'Factory', 0x180000, 2097152),
            (0, 'FIP', 0x380000, 2097152), (1, 'crash', 0x580000, 262144),
            (3, 'crash_log', 0x5c0000, 262144), (5, 'ubi_kernel', 0x600000, 31457280),
            (7, 'ubi', 0x2400000, 83886080),
        ]
        self.layout(self.parts)
        self.backup = self.root / 'backup'
        self.backup.mkdir()
        for number, label, _, _ in self.parts[:5]:
            (self.backup / (label + '.bin')).write_bytes((self.root / f'dev/mtdblock{number}').read_bytes())
        (self.backup / 'device-info.txt').write_text('board=xiaomi,redmi-router-ax6000-stock\n')
        self.checksums(self.backup)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        meta = {'schema': 1, 'board': 'xiaomi,redmi-router-ax6000-ubootmod'}
        for key, suffix, magic in [('sysupgrade', 'squashfs-sysupgrade.itb', b'\xd0\x0d\xfe\xed'),
                                   ('factory', 'initramfs-factory.ubi', b'UBI#'),
                                   ('recovery', 'initramfs-recovery.itb', b'\xd0\x0d\xfe\xed'),
                                   ('bl2', 'preloader.bin', b'BL2'), ('fip', 'bl31-uboot.fip', b'FIP')]:
            meta[key] = 'openwrt-test-xiaomi_redmi-router-ax6000-ubootmod-' + suffix
            (self.bundle / meta[key]).write_bytes(magic + bytes(128))
        (self.bundle / 'bundle.json').write_text(json.dumps(meta))
        self.checksums(self.bundle)
        self.log = self.root / 'mutations'
        stubs = {
            'id': 'echo 0', 'uname': 'echo test',
            'fw_printenv': 'case "$2" in flag_boot_rootfs) echo 0;; flag_last_success|flag_boot_success) echo 1;; *) echo 8;; esac',
            'jsonfilter': 'exec python3 -c \'import json,sys; print(json.load(open(sys.argv[2]))[sys.argv[4][2:]])\' "$@"',
            'sysupgrade': 'if [ "$1" = -T ]; then exit "${FAIL_VALIDATE:-0}"; fi\necho "sysupgrade $*" >> "$TEST_MUTATIONS"',
            'ubiformat': 'echo "ubiformat $*" >> "$TEST_MUTATIONS"\nexit "${FAIL_FORMAT:-0}"',
        }
        for name in ('ubidetach', 'ubiattach', 'ubimkvol', 'ubiupdatevol', 'mtd', 'insmod'):
            stubs[name] = f'echo "{name} $*" >> "$TEST_MUTATIONS"'
        for name, text in stubs.items():
            path = self.root / 'bin' / name
            path.write_text('#!/bin/sh\n' + text + '\n')
            path.chmod(0o755)
        script = (REPO / 'scripts/ax6000-migrate.sh').read_text()
        special = '[ -c "/dev/$found" ] && [ -b "/dev/mtdblock${found#mtd}" ]'
        self.assertEqual(script.count(special), 1)
        script = script.replace(special, '[ -f "/dev/$found" ] && [ -f "/dev/mtdblock${found#mtd}" ]')
        for prefix in ('/proc/', '/sys/', '/dev/', '/lib/modules/', '/tmp/sysinfo/'):
            script = script.replace(prefix, str(self.root) + prefix)
        self.script = self.root / 'migrate.sh'
        self.script.write_text(script)
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + ':' + os.environ['PATH'], TEST_MUTATIONS=str(self.log))

    @staticmethod
    def checksums(directory):
        (directory / 'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n'
                                                    for f in sorted(directory.iterdir()) if f.name != 'SHA256SUMS'))

    def layout(self, parts):
        lines = ['dev: size erasesize name']
        for number, label, offset, size in parts:
            lines.append(f'mtd{number}: {size:08x} 00020000 "{label}"')
            sys = self.root / f'sys/class/mtd/mtd{number}'
            (sys / 'of_node').mkdir(parents=True, exist_ok=True)
            (sys / 'of_node/reg').write_bytes(offset.to_bytes(4, 'big') + size.to_bytes(4, 'big'))
            for key, value in [('size', size), ('erasesize', 131072), ('writesize', 2048)]:
                (sys / key).write_text(str(value))
            # Sparse zero files keep the fixture small; the first five are backed up.
            for name in (f'mtd{number}', f'mtdblock{number}'):
                with (self.root / 'dev' / name).open('wb') as f:
                    f.truncate(size)
        (self.root / 'proc/mtd').write_text('\n'.join(lines) + '\n')

    def run_script(self, action, *flags):
        args = ['sh', str(self.script), action, str(self.bundle)]
        if action not in ('check-recover', 'recover'):
            args.append(str(self.backup))
        return subprocess.run(args + list(flags), env=self.env, capture_output=True, text=True, timeout=20)

    def assert_readonly(self):
        self.assertFalse(self.log.exists(), self.log.read_text() if self.log.exists() else '')

    def test_check_is_readonly_with_shuffled_mtd(self):
        result = self.run_script('check-stock')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_readonly()

    def test_missing_confirmation_rejects_before_format(self):
        self.assertNotEqual(self.run_script('stage-stock').returncode, 0)
        self.assert_readonly()

    def test_stage_formats_only_resolved_kernel_partition(self):
        crash = self.root / 'sys/fs/pstore/dmesg-ramoops-0'
        crash.write_text('stock diagnostic record')
        result = self.run_script('stage-stock', '--apply', '--backup-saved-off-router')
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.log.read_text().splitlines()
        self.assertEqual(len(commands), 1)
        self.assertIn('/dev/mtd5 -y -f ', commands[0])
        self.assertTrue(crash.exists())

    def test_format_failure_does_not_report_success_or_reboot(self):
        self.env['FAIL_FORMAT'] = '23'
        result = self.run_script('stage-stock', '--apply', '--backup-saved-off-router')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('第一阶段完成', result.stdout)
        self.assertNotIn('sysupgrade', self.log.read_text())

    def test_wrong_offset_and_wrong_device_backup_rejected(self):
        (self.root / 'sys/class/mtd/mtd2/of_node/reg').write_bytes(bytes(8))
        self.assertNotEqual(self.run_script('check-stock').returncode, 0)
        self.assert_readonly()

    def test_truncated_checksum_list_rejected(self):
        lines = (self.bundle / 'SHA256SUMS').read_text().splitlines()
        (self.bundle / 'SHA256SUMS').write_text('\n'.join(s for s in lines if 'sysupgrade.itb' not in s) + '\n')
        self.assertNotEqual(self.run_script('check-stock').returncode, 0)
        self.assert_readonly()

    def test_changed_backup_rejected(self):
        (self.backup / 'Factory.bin').write_bytes(b'X' * 2097152)
        self.checksums(self.backup)
        self.assertNotEqual(self.run_script('check-stock').returncode, 0)
        self.assert_readonly()

    def test_install_refuses_persistent_root_and_wrong_sysupgrade(self):
        (self.root / 'tmp/sysinfo/board_name').write_text('xiaomi,redmi-router-ax6000-ubootmod\n')
        self.layout(self.parts[:5] + [(5, 'ubi', 0x580000, 0x7a80000)])
        (self.root / 'lib/modules/test/mtd-rw.ko').write_bytes(b'test')
        (self.root / 'proc/mounts').write_text('/dev/root / squashfs ro 0 0\n')
        self.assertNotEqual(self.run_script('install', '--apply', '--backup-saved-off-router').returncode, 0)
        self.assert_readonly()
        (self.root / 'proc/mounts').write_text(
            f'rootfs / rootfs rw 0 0\npstore {self.root}/sys/fs/pstore pstore rw 0 0\n')
        self.env['FAIL_VALIDATE'] = '17'
        result = self.run_script('install', '--apply', '--backup-saved-off-router')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('正式固件未通过 sysupgrade 检查', result.stderr)
        self.assert_readonly()

    def test_bootloader_readback_failure_stops_before_fip_and_sysupgrade(self):
        (self.root / 'tmp/sysinfo/board_name').write_text('xiaomi,redmi-router-ax6000-ubootmod\n')
        self.layout(self.parts[:5] + [(5, 'ubi', 0x580000, 0x7a80000)])
        (self.root / 'lib/modules/test/mtd-rw.ko').write_bytes(b'test')
        ubi = self.root / 'sys/class/ubi/ubi3'
        ubi.mkdir()
        for key, value in [('mtd_num', 5), ('avail_eraseblocks', 800), ('eraseblock_size', 126976)]:
            (ubi / key).write_text(str(value))
        result = self.run_script('install', '--apply', '--backup-saved-off-router')
        self.assertNotEqual(result.returncode, 0)
        commands = self.log.read_text()
        self.assertIn('回读不一致', result.stderr)
        self.assertEqual(commands.count('mtd write'), 1)
        self.assertNotIn('sysupgrade', commands)

    def test_recover_writes_only_sysupgrade(self):
        (self.root / 'tmp/sysinfo/board_name').write_text('xiaomi,redmi-router-ax6000-ubootmod\n')
        self.layout(self.parts[:5] + [(5, 'ubi', 0x580000, 0x7a80000)])
        result = self.run_script('recover', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        self.assertTrue(self.log.read_text().startswith('sysupgrade -n '))

    def prepare_recovery_with_crash(self):
        (self.root / 'tmp/sysinfo/board_name').write_text('xiaomi,redmi-router-ax6000-ubootmod\n')
        self.layout(self.parts[:5] + [(5, 'ubi', 0x580000, 0x7a80000)])
        crash = self.root / 'sys/fs/pstore/dmesg-ramoops-0'
        crash.write_text('old kernel panic')
        self.env['TEST_CRASH_RECORD'] = str(crash)
        return crash

    def test_recovery_clears_crash_before_sysupgrade(self):
        crash = self.prepare_recovery_with_crash()
        upgrade = self.root / 'bin/sysupgrade'
        upgrade.write_text(upgrade.read_text() + '\n[ ! -e "$TEST_CRASH_RECORD" ] || exit 91\n')
        result = self.run_script('recover', '--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(crash.exists())
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        self.assertTrue(self.log.read_text().startswith('sysupgrade -n '))

    def test_recovery_checks_and_missing_confirmation_preserve_crash(self):
        crash = self.prepare_recovery_with_crash()
        for action, expected in [('check-recover', 0), ('recover', 1)]:
            with self.subTest(action=action):
                result = self.run_script(action)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertTrue(crash.exists())
                self.assert_readonly()

    def test_invalid_recovery_image_preserves_crash(self):
        crash = self.prepare_recovery_with_crash()
        self.env['FAIL_VALIDATE'] = '17'
        self.assertNotEqual(self.run_script('recover', '--apply').returncode, 0)
        self.assertTrue(crash.exists())
        self.assert_readonly()

    def test_unmounted_pstore_rejects_recovery(self):
        crash = self.prepare_recovery_with_crash()
        (self.root / 'proc/mounts').write_text('rootfs / rootfs rw 0 0\n')
        result = self.run_script('recover', '--apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(crash.exists())
        self.assert_readonly()

    def test_failed_pstore_cleanup_stops_install_and_recovery(self):
        crash = self.prepare_recovery_with_crash()
        (self.root / 'lib/modules/test/mtd-rw.ko').write_bytes(b'test')
        remove = self.root / 'bin/rm'
        remove.write_text('#!/bin/sh\nexit 19\n')
        remove.chmod(0o755)
        for action, flags in [('recover', ('--apply',)),
                              ('install', ('--apply', '--backup-saved-off-router'))]:
            with self.subTest(action=action):
                result = self.run_script(action, *flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('pstore', result.stderr)
                self.assertTrue(crash.exists())
                self.assert_readonly()

    def test_low_memory_refuses_before_writes(self):
        (self.root / 'proc/meminfo').write_text('MemAvailable: 131071 kB\n')
        result = self.run_script('stage-stock', '--apply', '--backup-saved-off-router')
        self.assertNotEqual(result.returncode, 0)
        self.assert_readonly()

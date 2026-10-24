#!/usr/bin/env python3
"""Assemble only matching, verified outputs; no bootloader from random downloads."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

output = Path(sys.argv[1]).resolve()
repo = Path(__file__).resolve().parent.parent
for mode in ('stock', 'ubootmod', 'recovery'):
    subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=output / mode, check=True)
revisions = [json.loads((output / p / 'build-sources.json').read_text()) for p in ('stock', 'ubootmod', 'recovery')]
assert revisions[0] == revisions[1] == revisions[2], 'Build source locks differ'
bundle = output / 'migration'
bundle.mkdir(exist_ok=True)
metadata = {'schema': 1, 'board': 'xiaomi,redmi-router-ax6000-ubootmod', 'sources': revisions[0]}
for key, mode, suffix in [('sysupgrade', 'ubootmod', 'squashfs-sysupgrade.itb'),
                          ('recovery', 'recovery', 'initramfs-recovery.itb'),
                          ('factory', 'recovery', 'initramfs-factory.ubi'),
                          ('bl2', 'recovery', 'preloader.bin'), ('fip', 'recovery', 'bl31-uboot.fip')]:
    files = list((output / mode).glob('*-xiaomi_redmi-router-ax6000-ubootmod-' + suffix))
    assert len(files) == 1, (key, files)
    shutil.copy2(files[0], bundle / files[0].name)
    metadata[key] = files[0].name
shutil.copy2(repo / 'scripts/ax6000-migrate.sh', bundle)
shutil.copy2(repo / 'docs/ubootmod.md', bundle / '迁移与恢复.md')
(bundle / 'bundle.json').write_text(json.dumps(metadata, indent=2) + '\n')
(bundle / 'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n'
                                        for f in sorted(bundle.iterdir()) if f.name != 'SHA256SUMS' and f.is_file()))
print('Complete migration bundle:', bundle)

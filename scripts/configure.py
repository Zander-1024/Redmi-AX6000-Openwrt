#!/usr/bin/env python3
"""Generate one exact device configuration; .config remains the stock baseline."""
import sys
from pathlib import Path

root, tree, mode = Path(__file__).resolve().parent.parent, Path(sys.argv[1]), sys.argv[2]
if mode not in {'stock', 'ubootmod', 'recovery'}:
    raise SystemExit('Unknown build mode')
config = (root / ('configs/recovery.config' if mode == 'recovery' else '.config')).read_text()
if mode == 'ubootmod':
    config = config.replace('DEVICE_xiaomi_redmi-router-ax6000-stock=y',
                            'DEVICE_xiaomi_redmi-router-ax6000-ubootmod=y')
(tree / '.config').write_text(config)
(tree / 'requested.config').write_text(config)

#!/usr/bin/env python3
"""Keep a byte-for-byte official wiki snapshot; network access is opt-in."""
import argparse
import datetime
import difflib
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[1] / 'docs/reference/openwrt'
PAGE = 'https://openwrt.org/toh/xiaomi/redmi_ax6000'
RAW_URL = PAGE + '?do=export_raw'
RAW_NAME = 'redmi-ax6000.dokuwiki'
EXCERPT_NAME = 'uboot-installation.md'
START = '==== Installing OpenWrt (U-Boot layout) ===='
END = '==== Flash Layout ===='


def validate(data):
    text = data.decode('utf-8')
    if not text.startswith('====== Xiaomi Redmi AX6000 ======'):
        raise ValueError('Not the device wiki source (possibly an error/challenge page)')
    for heading in (START, END, '===== Debricking ====='):
        if text.count(heading) != 1:
            raise ValueError('Missing or ambiguous wiki section: ' + heading)
    if text.index(START) >= text.index(END):
        raise ValueError('Unexpected wiki section order')
    return text


def excerpt(data):
    text = validate(data)
    section = text.split(START, 1)[1].split(END, 1)[0].strip()
    section = section.replace('<code>', '```text').replace('</code>', '```')
    section = re.sub(r"''(.*?)''", r'`\1`', section)
    section = re.sub(r'\[\[([^]|]+)\|([^]]+)\]\]',
                     lambda m: '[' + m[2] + '](' + (
                         m[1] if m[1].startswith('https://') else
                         'https://openwrt.org/' + m[1].lstrip(':').replace(':', '/')) + ')', section)
    return (
        '# Installing OpenWrt (U-Boot layout)\n\n'
        '> 官方章节的自动排版摘录，保留原文及历史示例；不是本项目可直接执行的刷机清单。\n'
        '> 来源：[OpenWrt Wiki](' + PAGE + '#installing_openwrt_u-boot_layout)，'
        '作者：OpenWrt Wiki contributors。\n'
        '> 许可：[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。'
        '修改仅为 DokuWiki 到 Markdown 的格式转换。\n'
        '> 完整原文与抓取记录见 [核对说明](README.md)。不要手工编辑此生成文件。\n\n'
        + section + '\n'
    )


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'AX6000-docs-snapshot/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def verify():
    data = (DIRECTORY / RAW_NAME).read_bytes()
    validate(data)
    metadata = json.loads((DIRECTORY / 'source.json').read_text())
    if metadata['source_url'] != PAGE or metadata['export_url'] != RAW_URL:
        raise ValueError('Unexpected snapshot source')
    if metadata['sha256'] != hashlib.sha256(data).hexdigest() or metadata['bytes'] != len(data):
        raise ValueError('Wiki snapshot differs from source.json')
    if (DIRECTORY / EXCERPT_NAME).read_text() != excerpt(data):
        raise ValueError('Generated U-Boot excerpt differs from the raw snapshot')
    print('Official wiki snapshot hash and generated U-Boot excerpt verified')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify', 'check', 'update'), nargs='?', default='verify')
    args = parser.parse_args()
    if args.action == 'verify':
        verify()
        return 0
    if args.action == 'check':
        saved = verify()
        latest = fetch(RAW_URL)
        validate(latest)
        if latest == saved:
            print('Official wiki has not changed')
            return 0
        diff = list(difflib.unified_diff(saved.decode().splitlines(), latest.decode().splitlines(),
                                       fromfile=RAW_NAME, tofile='official-latest', lineterm=''))
        print('\n'.join(diff[:200]))
        if len(diff) > 200:
            print('Diff truncated; use update in a clean worktree to inspect the full git diff.')
        print('Official wiki changed; review it before updating the snapshot or migration procedure.')
        return 1
    data = fetch(RAW_URL)
    validate(data)
    page = fetch(PAGE).decode('utf-8')
    modified = re.search(r'Last modified:\s*<span[^>]*>([^<]+)</span>', page)
    if not modified or 'https://creativecommons.org/licenses/by-sa/4.0/' not in page:
        raise ValueError('Could not verify the page modification date and CC BY-SA notice')
    # Refuse to pair metadata with a page that changed between the two requests.
    if fetch(RAW_URL) != data:
        raise ValueError('Wiki changed during capture; retry')
    metadata = {
        'title': 'Xiaomi Redmi AX6000', 'source_url': PAGE, 'export_url': RAW_URL,
        'history_url': PAGE + '?do=revisions',
        'retrieved_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'upstream_last_modified_display': modified[1],
        'upstream_timezone': 'Not specified by the page display',
        'attribution': 'OpenWrt Wiki contributors', 'license': 'CC-BY-SA-4.0',
        'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
        'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
        'raw_changes': 'None; exact HTTP export response body',
    }
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    (DIRECTORY / RAW_NAME).write_bytes(data)
    (DIRECTORY / EXCERPT_NAME).write_text(excerpt(data))
    (DIRECTORY / 'source.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
    verify()
    print('Review git diff and update the alignment notes; this does not approve a flashing procedure.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit(str(error))

"""Partition budgets from the locked DTS, using 128 KiB PEB / 124 KiB LEB."""
import math
import stat
import subprocess
from pathlib import Path, PurePosixPath

MIB = 1024**2
PEB, LEB = 128 * 1024, 124 * 1024
RECOVERY_SIZE = 16 * MIB
ENV_SIZE = MIB
# Linux get_bad_peb_limit() uses the entire MTD master, not this partition.
# Budget against all 128 MiB even on stock, whose NMBM master is smaller.
# CONFIG_MTD_UBI_FASTMAP=y reserves two fastmap LEBs even with autoconvert off.
NAND_SIZE = 128 * MIB
BAD_BLOCK_RESERVE = math.ceil((NAND_SIZE // PEB) * 20 / 1024)
UBI_METADATA_RESERVE = 4 + 2  # layout table, WL, atomic LEB change, fastmaps


def budget(partition, payloads, minimum_data=0):
    blocks = partition // PEB
    reserve = UBI_METADATA_RESERVE + BAD_BLOCK_RESERVE
    used = sum(math.ceil(size / LEB) for size in payloads)
    available = (blocks - reserve - used) * LEB
    if any(size <= 0 for size in payloads) or available < minimum_data:
        raise ValueError(f'Capacity gate: {payloads=}, {available=}, {minimum_data=}')
    return dict(partition_bytes=partition, payload_bytes=payloads, reserve_pebs=reserve,
                master_budget_bytes=NAND_SIZE, bad_block_reserve_pebs=BAD_BLOCK_RESERVE,
                metadata_reserve_pebs=UBI_METADATA_RESERVE,
                logical_data_bytes=available, minimum_data_bytes=minimum_data)


def fit_root(image):
    """Read mkimage external-static rootfs position instead of guessing FIT size."""
    nodes = subprocess.check_output(['fdtget', '-l', str(image), '/images'], text=True).split()
    roots = [n for n in nodes if subprocess.check_output(
        ['fdtget', '-t', 's', str(image), '/images/' + n, 'type'], text=True).strip() == 'filesystem']
    if len(roots) != 1:
        raise ValueError(f'Expected one FIT filesystem: {roots}')

    def number(prop):
        words = subprocess.check_output(
            ['fdtget', '-t', 'x', str(image), '/images/' + roots[0], prop], text=True).split()
        return int(''.join(f'{int(w, 16):08x}' for w in words), 16)

    offset, size = number('data-position'), number('data-size')
    if offset < 4096 or size <= 0 or offset + size > image.stat().st_size:
        raise ValueError('Invalid FIT rootfs bounds')
    return offset, size


def extract_initrd(image, destination):
    """Extract the actual FIT ramdisk, without needing root to create /dev nodes."""
    import gzip
    import lzma
    import tempfile
    nodes = subprocess.check_output(['fdtget', '-l', str(image), '/images'], text=True).split()
    indices = [i for i, n in enumerate(nodes) if subprocess.check_output(
        ['fdtget', '-t', 's', str(image), '/images/' + n, 'type'], text=True).strip() == 'ramdisk']
    if len(indices) != 1:
        raise ValueError(f'Expected one separate initrd: {indices}')
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / 'initrd'
        dtbs = [i for i, n in enumerate(nodes) if subprocess.check_output(
            ['fdtget', '-t', 's', str(image), '/images/' + n, 'type'], text=True).strip() == 'flat_dt']
        if len(dtbs) != 1:
            raise ValueError('Expected one recovery DTB')
        dtb = Path(temp) / 'board.dtb'
        subprocess.run(['dumpimage', '-T', 'flat_dt', '-p', str(dtbs[0]), '-o', str(dtb), str(image)],
                       check=True, stdout=subprocess.DEVNULL)
        compatible = subprocess.check_output(['fdtget', '-t', 's', str(dtb), '/', 'compatible'], text=True).split()
        if 'xiaomi,redmi-router-ax6000-ubootmod' not in compatible:
            raise ValueError(f'Wrong recovery DTB: {compatible}')
        subprocess.run(['dumpimage', '-T', 'flat_dt', '-p', str(indices[0]), '-o', str(archive), str(image)],
                       check=True, stdout=subprocess.DEVNULL)
        data = archive.read_bytes()
    if data.startswith(b'\x1f\x8b'):
        data = gzip.decompress(data)
    elif not data.startswith((b'070701', b'070702')):
        data = lzma.decompress(data)
    destination.mkdir(parents=True)
    offset = 0
    while offset + 110 <= len(data):
        header = data[offset:offset + 110]
        if header[:6] not in (b'070701', b'070702'):
            raise ValueError('Unexpected initrd CPIO format')
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name = data[offset + 110:offset + 110 + namesize - 1].decode()
        offset = (offset + 110 + namesize + 3) & ~3
        payload = data[offset:offset + size]
        offset = (offset + size + 3) & ~3
        if name == 'TRAILER!!!':
            return
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Unsafe initrd path')
        target = destination / path
        if not target.resolve().is_relative_to(destination.resolve()):
            raise ValueError('Unsafe initrd symlink traversal')
        target.parent.mkdir(parents=True, exist_ok=True)
        if stat.S_ISDIR(mode):
            target.mkdir(exist_ok=True)
        elif stat.S_ISLNK(mode):
            target.symlink_to(payload.decode())
        elif stat.S_ISREG(mode):
            target.write_bytes(payload)
            target.chmod(stat.S_IMODE(mode))
        # Device nodes are supplied by proot's explicit /dev bind during tests.
    raise ValueError('Truncated initrd')

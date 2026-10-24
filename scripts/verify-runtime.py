#!/usr/bin/env python3
"""Execute image BusyBox/UCI and first-boot scripts under user-mode QEMU/proot.

Fixtures stand in for board-generated config only. They do not prove radio or WAN.
"""
import json
import os
import pty
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

image, report = Path(sys.argv[1]), Path(sys.argv[2])
with tempfile.TemporaryDirectory(prefix='ax6000-runtime-') as temp:
    root = Path(temp) / 'root'
    # /dev comes from the explicit proot bind below; do not create device nodes
    # as an unprivileged build user. Other extraction errors remain fatal.
    subprocess.run(['unsquashfs', '-no-progress', '-processors', '1', '-d', str(root),
                    '-excludes', str(image), 'dev'],
                   check=True, stdout=subprocess.DEVNULL)
    (root / 'dev').mkdir(exist_ok=True)
    ttyd_present = (root / 'usr/bin/ttyd').exists()
    config = root / 'etc/config'
    (root / 'tmp').mkdir(exist_ok=True)
    for name in ('lock', 'run', 'state', 'log'):
        (root / 'tmp' / name).mkdir(exist_ok=True)
    (config / 'network').write_text("""config interface 'lan'
 option proto 'static'
 option device 'br-lan'
 option ipaddr '192.168.10.1'
 option netmask '255.255.255.255'
""")
    (config / 'system').write_text("""config system
 option hostname 'OpenWrt'
config timeserver 'ntp'
 option enabled '1'
""")
    (config / 'wireless').write_text("""config wifi-device 'radio5'
 option band '5g'
config wifi-iface 'ap5'
 option device 'radio5'
 option mode 'ap'
config wifi-device 'radio2'
 option band '2g'
config wifi-iface 'ap2'
 option device 'radio2'
 option mode 'ap'
""")
    (config / 'dropbear').write_text("""config dropbear 'main'
 option enable '0'
 option Port '2222'
 option Interface 'wan'
 option DirectInterface 'wan'
 option PasswordAuth 'off'
 option RootPasswordAuth 'off'
config dropbear 'extra'
 option enable '1'
 option Interface 'wan'
 option Port '22'
""")
    (config / 'ttyd').write_text("""config ttyd 'main'
 option enable '0'
 option interface '@wan'
 option port '9999'
 option command '/bin/login'
 option credential 'obsolete:obsolete'
 option url_override 'http://invalid.local'
config ttyd 'extra'
 option enable '1'
 option interface '@wan'
""")
    # Wrap only failure injection; every successful operation uses the image UCI.
    uci = root / 'sbin/uci'
    uci.rename(root / 'sbin/uci.real')
    uci.write_text("""#!/bin/sh
if [ -f /tmp/fail-commit ] && [ "$1" = commit ] && [ "$2" = "$(cat /tmp/fail-commit)" ]; then
    exit 97
fi
exec /sbin/uci.real "$@"
""")
    uci.chmod(0o755)
    env = dict(os.environ, PROOT_NO_SECCOMP='1')
    prefix = ['proot', '-0', '-r', str(root), '-b', '/dev', '-b', '/proc', '-w', '/',
              '-q', '/usr/bin/qemu-aarch64-static', '/bin/sh', '-c']

    def run(command, success=True):
        result = subprocess.run(prefix + [command], env=env, capture_output=True, text=True, timeout=90)
        if success and result.returncode:
            raise RuntimeError(f'{command}\n{result.stdout}\n{result.stderr}')
        return result

    # PW2 creates its config from a shipped template at first boot, before zzz.
    if (root / 'etc/uci-defaults/luci-app-passwall2').exists():
        run('/bin/sh /etc/uci-defaults/luci-app-passwall2')
    access = '/bin/sh /etc/uci-defaults/90-ax6000-access'
    run(access)
    # Use OpenWrt's existing hexdump; its default BusyBox does not include od.
    run('for tool in hexdump head sha256sum jsonfilter mtd ubiformat ubidetach ubiattach ubimkvol ubiupdatevol fw_printenv; do command -v "$tool" >/dev/null || exit 1; done')
    (root / 'tmp/format-probe').write_bytes(b'UBI#payload')
    assert run("hexdump -n 4 -v -e '1/1 \"%02x\"' /tmp/format-probe").stdout == '55424923'
    assert run('head -c 4 /tmp/format-probe').stdout == 'UBI#'
    expected = {
        'network.lan.ipaddr': '192.168.10.1/24', 'network.lan.proto': 'static',
        'dhcp.lan.ignore': '0', 'dhcp.lan.start': '100', 'dhcp.lan.limit': '150',
        'dropbear.main.enable': '1', 'dropbear.main.Port': '22', 'dropbear.main.Interface': 'lan',
        'dropbear.main.PasswordAuth': 'on', 'dropbear.main.RootPasswordAuth': 'on',
        'dropbear.extra.enable': '0', 'ttyd.main.enable': '1', 'ttyd.main.interface': '@lan',
        'ttyd.main.port': '7681', 'ttyd.main.command': '/bin/login -f root',
        'ttyd.main.url_arg': '0', 'ttyd.extra.enable': '0',
        'wireless.ap2.ssid': 'Openwrt', 'wireless.ap5.ssid': 'Openwrt5G',
        'wireless.radio5.htmode': 'HE160', 'wireless.ap5.key': '12345678',
    }
    if not ttyd_present:
        expected = {k: v for k, v in expected.items() if not k.startswith('ttyd.')}
    for key, value in expected.items():
        assert run('uci -q get ' + key).stdout.strip() == value, key
    for key in ('network.lan.netmask', 'dropbear.main.DirectInterface', 'ttyd.main.credential', 'ttyd.main.url_override'):
        if ttyd_present or not key.startswith('ttyd.'):
            assert run('uci -q get ' + key, success=False).returncode != 0, key
    run('[ -L /etc/rc.d/S19dropbear ]')
    if ttyd_present:
        run('[ -L /etc/rc.d/S99ttyd ]')
    first = run('uci export').stdout
    run(access)
    assert run('uci export').stdout == first, 'access defaults are not idempotent'
    failed = []
    fault_packages = () if '--quick' in sys.argv[3:] else ('network', 'dhcp', 'dropbear', 'ttyd', 'system', 'wireless')
    for package in fault_packages:
        if package == 'ttyd' and not ttyd_present:
            continue
        (root / 'tmp/fail-commit').write_text(package)
        assert run(access, success=False).returncode != 0, package
        (root / 'tmp/fail-commit').unlink()
        run(access)
        failed.append(package)
    if (root / 'etc/uci-defaults/zzz-custom').exists():
        run('/bin/sh /etc/uci-defaults/zzz-custom')
    # A random password in the disposable fixture prevents Dropbear's stock
    # empty-root-password exception from making a key-login test meaningless.
    hashed = subprocess.check_output(['openssl', 'passwd', '-6', '-stdin'],
                                     input=os.urandom(32).hex() + '\n', text=True).strip()
    shadow = root / 'etc/shadow'
    lines = shadow.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith('root:'):
            fields = line.split(':')
            fields[1] = hashed
            lines[i] = ':'.join(fields)
    shadow.write_text('\n'.join(lines) + '\n')
    # Prove the selected login command accepts -f; no shared firmware password.
    pid, master = pty.fork()
    if pid == 0:
        os.execvpe(prefix[0], prefix + ['exec /bin/login -f root'], env)
    transcript = b''
    sent = False
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if select.select([master], [], [], 1)[0]:
                try:
                    block = os.read(master, 65536)
                except OSError:
                    break
                if not block:
                    break
                transcript += block
                if b'#' in transcript and not sent:
                    os.write(master, b"printf 'AX6000_%s\\n' AUTOLOGIN_OK; exit\n")
                    sent = True
                if b'AX6000_AUTOLOGIN_OK' in transcript:
                    break
    finally:
        os.close(master)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
    assert b'AX6000_AUTOLOGIN_OK' in transcript, transcript.decode(errors='replace')

    def start_service(command, port):
        process = subprocess.Popen(prefix + ['exec ' + command], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f'Service exited: {command}')
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    return process
            except OSError:
                time.sleep(.1)
        process.terminate()
        process.wait(timeout=10)
        raise RuntimeError(f'Service did not listen: {command}')

    def stop_service(process):
        # proot does not forward every signal to a traced QEMU child. Stop the
        # disposable service group, including login/session descendants.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

    # Isolated high loopback ports test actual packaged service binaries. LAN
    # addresses and port 22 are verified in UCI; no router hardware is implied.
    key = Path(temp) / 'client-key'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    auth = root / 'etc/dropbear/authorized_keys'
    auth.parent.mkdir(exist_ok=True)
    auth.write_bytes(Path(str(key) + '.pub').read_bytes())
    auth.chmod(0o600)
    run('dropbearkey -t ed25519 -f /tmp/test-hostkey')
    sshd = start_service('/usr/sbin/dropbear -F -E -p 127.0.0.1:22222 -r /tmp/test-hostkey', 22222)
    try:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
                                 '-o', 'UserKnownHostsFile=' + str(Path(temp) / 'known_hosts'),
                                 '-o', 'ConnectTimeout=10', '-i', str(key), '-p', '22222',
                                 'root@127.0.0.1', "printf 'AX6000_SSH_OK'"],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0 and 'AX6000_SSH_OK' in result.stdout, (result.stdout, result.stderr)
    finally:
        stop_service(sshd)

    if ttyd_present:
        import websocket
        ttyd = start_service('/usr/bin/ttyd -i 127.0.0.1 -p 17681 -W -O /bin/login -f root', 17681)
        try:
            ws = websocket.create_connection('ws://127.0.0.1:17681/ws', subprotocols=['tty'],
                                             origin='http://127.0.0.1:17681', timeout=15)
            try:
                ws.send(json.dumps({'AuthToken': '', 'columns': 80, 'rows': 24}))
                output = b''
                sent = False
                for _ in range(100):
                    packet = ws.recv()
                    if isinstance(packet, str):
                        packet = packet.encode()
                    if not packet:
                        break
                    if packet[:1] == b'0':
                        output += packet[1:]
                    if b'#' in output and not sent:
                        ws.send_binary(b"0printf 'AX6000_%s\\n' TTYD_OK; exit\n")
                        sent = True
                    if b'AX6000_TTYD_OK' in output:
                        break
                assert b'AX6000_TTYD_OK' in output, output.decode(errors='replace')
            finally:
                ws.close()
        finally:
            stop_service(ttyd)
    report.write_text(json.dumps({'image_binaries': 'BusyBox and UCI via QEMU/proot',
                                 'lan': {'ipaddr': run('uci get network.lan.ipaddr').stdout.strip(),
                                         'dhcp_start': int(run('uci get dhcp.lan.start').stdout.strip()),
                                         'dhcp_limit': int(run('uci get dhcp.lan.limit').stdout.strip())},
                                 'defaults': 'success, retry, idempotence and retained WAN listener cleanup',
                                 'commit_failures_rejected': failed, 'login_f_root': 'executed',
                                 'ssh': 'packaged Dropbear: authenticated key login and command on loopback',
                                 'ttyd': ('packaged ttyd: WebSocket, automatic root login and command on loopback'
                                          if ttyd_present else 'not packaged in minimal recovery'),
                                 'hardware': 'not tested'}, indent=2) + '\n')
print('Image runtime defaults, SSH and autologin verified' + (' (quick check)' if '--quick' in sys.argv[3:] else ', including commit failure/retry'))

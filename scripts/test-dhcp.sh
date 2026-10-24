#!/usr/bin/env bash
# A real DHCP exchange over a veth pair in a container with --network none.
set -euo pipefail
src=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
test_id="ax6000-dhcp-$$"
image=ax6000-builder:25.12.6
profile=${1:-stock}
case "$profile" in stock|ubootmod|recovery) ;; *) exit 2;; esac
test_volume="$test_id-data"
client="$test_id-run"
cleanup() {
    result=$?
    docker rm -f "$client" >/dev/null 2>&1 || true
    docker volume rm "$test_volume" >/dev/null 2>&1 || true
    exit "$result"
}
trap cleanup EXIT
docker volume create "$test_volume" >/dev/null
docker run --rm --user 0 \
    --mount type=volume,src=ax6000-openwrt-build,dst=/build,readonly \
    --mount "type=volume,src=$test_volume,dst=/test" \
    "$image" unsquashfs -no-progress -processors 1 -d /test/root -excludes "/build/openwrt/$profile-verified-root.squashfs" dev >/dev/null
docker run --name "$client" --user 0 --cap-add NET_ADMIN --network none \
    --mount "type=volume,src=$test_volume,dst=/test,readonly" \
    --mount "type=bind,src=$src/build-output/$profile,dst=/evidence,readonly" \
    "$image" python3 -c '
import ipaddress, json, pathlib, subprocess, time
config = json.load(open("/evidence/runtime.json"))["lan"]
interface = ipaddress.ip_interface(config["ipaddr"])
assert str(interface) == "192.168.10.1/24"
start = interface.network.network_address + config["dhcp_start"]
end = start + config["dhcp_limit"] - 1
def command(*args): subprocess.run(list(args), check=True)
command("ip", "link", "add", "testlan", "type", "veth", "peer", "name", "testclient")
command("ip", "addr", "add", str(interface), "dev", "testlan")
command("ip", "link", "set", "testlan", "up")
command("ip", "link", "set", "testclient", "up")
# AF_PACKET under user-mode QEMU sees veth partial checksums. A physical wire
# carries completed checksums; disable this test veth checksum offload only.
for device in ("testlan", "testclient"):
    command("ethtool", "-K", device, "tx", "off", "rx", "off")
qemu = ["/usr/bin/qemu-aarch64-static", "-L", "/test/root"]
server = subprocess.Popen(qemu + ["/test/root/usr/sbin/dnsmasq",
    "--no-daemon", "--conf-file=/dev/null", "--port=0", "--interface=testlan", "--bind-interfaces", "--user=root",
    "--dhcp-range=" + str(start) + "," + str(end) + "," + str(interface.netmask) + ",12h",
    "--dhcp-option=3,192.168.10.1", "--dhcp-leasefile=/tmp/leases", "--log-dhcp"])
try:
    time.sleep(.5)
    assert server.poll() is None, "dnsmasq exited"
    callback = pathlib.Path("/tmp/dhcp-bound")
    callback.write_text("#!/bin/sh\nif [ \"$1\" = bound ]; then\n  printf \"%s\\n%s\\n%s\\n\" \"$ip\" \"$subnet\" \"$router\" > /tmp/dhcp-result\nfi\n")
    callback.chmod(0o755)
    subprocess.run(qemu + ["/test/root/bin/busybox", "udhcpc", "-i", "testclient", "-n", "-q", "-f", "-B",
                            "-t", "5", "-T", "2", "-s", str(callback)], check=True, timeout=30)
    ip, mask, router = pathlib.Path("/tmp/dhcp-result").read_text().splitlines()
    assert start <= ipaddress.ip_address(ip) <= end, ip
    assert mask == str(interface.netmask), mask
    assert router == str(interface.ip), router
    print("DHCP_BOUND ip=" + ip + " subnet=" + mask + " router=" + router, flush=True)
finally:
    server.terminate()
    try: server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)
'
echo "$profile: actual image dnsmasq/BusyBox DHCPv4 handshake passed on an isolated veth LAN"

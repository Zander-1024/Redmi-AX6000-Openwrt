#!/bin/sh
# Run on the router with BusyBox ash. Default commands only inspect the device.
# No downloads, guessed MTD indices, forced sysupgrade or unattended reboot.
set -eu
fail() { echo "ax6000: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "缺少命令 $1"; }
usage() {
    cat <<'EOF'
sh ax6000-migrate.sh backup NEW_BACKUP_DIR
sh ax6000-migrate.sh check-stock BUNDLE BACKUP
sh ax6000-migrate.sh stage-stock BUNDLE BACKUP --apply --backup-saved-off-router
sh ax6000-migrate.sh check-install BUNDLE BACKUP
sh ax6000-migrate.sh install BUNDLE BACKUP --apply --backup-saved-off-router
sh ax6000-migrate.sh check-recover BUNDLE
sh ax6000-migrate.sh recover BUNDLE --apply

stage-stock: replace only stock ubi_kernel with the small migration initramfs.
            Reboot manually, reconnect, then run check-install / install.
install:    reformat ubootmod UBI, create env + 16 MiB recovery, write BL2/FIP,
            then sysupgrade -n. Requires a RAM boot and the original backup.
recover:    reinstall ubootmod firmware from RAM; does not restore stock/OEM.
EOF
}
action=${1:-help}
case "$action" in
    help|--help|-h) usage; exit 0;;
    backup|check-stock|stage-stock|check-install|install|check-recover|recover) shift;;
    *) usage >&2; exit 2;;
esac
[ "$(id -u)" = 0 ] || fail '必须以 root 运行'
for cmd in awk sha256sum wc hexdump jsonfilter; do need "$cmd"; done
board=$(cat /tmp/sysinfo/board_name)
case "$board" in
    xiaomi,redmi-router-ax6000-stock|xiaomi,redmi-router-ax6000-ubootmod) ;;
    *) fail "不支持的设备：$board（仅支持本项目两种 OpenWrt 布局，不支持小米 OEM 系统）";;
esac

# Map exact labels and validate both geometry and DT offsets. Never assume mtd7.
partition() {
    label=$1 expected_reg=$2 expected_size=$3
    found=$(awk -v label="\"$label\"" '$4 == label { sub(":", "", $1); print $1 }' /proc/mtd)
    [ -n "$found" ] && [ "$(printf '%s\n' "$found" | wc -l)" -eq 1 ] || fail "分区标签不唯一：$label"
    sys=/sys/class/mtd/$found
    [ "$(cat "$sys/size")" -eq "$expected_size" ] || fail "$label 分区大小不符"
    [ "$(cat "$sys/erasesize")" -eq 131072 ] || fail "$label 擦除块不符"
    [ "$(cat "$sys/writesize")" -eq 2048 ] || fail "$label NAND 页大小不符"
    reg=$(hexdump -v -e '1/1 "%02x"' "$sys/of_node/reg")
    [ "$reg" = "$expected_reg" ] || fail "$label DT 起止位置不符：$reg"
    [ -c "/dev/$found" ] && [ -b "/dev/mtdblock${found#mtd}" ] || fail "$label 缺少设备节点"
    printf '%s\n' "$found"
}
bl2=$(partition BL2 0000000000100000 1048576)
nvram=$(partition Nvram 0010000000040000 262144)
bdata=$(partition Bdata 0014000000040000 262144)
factory=$(partition Factory 0018000000200000 2097152)
fip=$(partition FIP 0038000000200000 2097152)

check_layout() {
    count=$(awk 'NR > 1 { n++ } END { print n+0 }' /proc/mtd)
    case "$1" in
        stock)
            [ "$board" = xiaomi,redmi-router-ax6000-stock ] && [ "$count" -eq 9 ] || fail '需要确切的 OpenWrt stock 布局'
            partition crash 0058000000040000 262144 >/dev/null
            partition crash_log 005c000000040000 262144 >/dev/null
            kernelpart=$(partition ubi_kernel 0060000001e00000 31457280)
            partition ubi 0240000005000000 83886080 >/dev/null
            ;;
        ubootmod)
            [ "$board" = xiaomi,redmi-router-ax6000-ubootmod ] && [ "$count" -eq 6 ] || fail '需要确切的官方 ubootmod 布局'
            ubipart=$(partition ubi 0058000007a80000 128450560)
            ;;
    esac
}

if [ "$action" = backup ]; then
    [ "$#" -eq 1 ] || fail 'backup 需要一个尚不存在的目录'
    dest=$1
    [ ! -e "$dest" ] || fail '备份目录已存在；请另选目录，避免覆盖旧备份'
    umask 077
    mkdir -p "$dest"
    for entry in "BL2:$bl2:1048576" "Nvram:$nvram:262144" "Bdata:$bdata:262144" "Factory:$factory:2097152" "FIP:$fip:2097152"; do
        label=${entry%%:*}; rest=${entry#*:}; dev=${rest%%:*}; bytes=${rest#*:}
        cat "/dev/mtdblock${dev#mtd}" > "$dest/$label.bin"
        [ "$(wc -c < "$dest/$label.bin")" -eq "$bytes" ] || fail "$label 备份长度错误"
    done
    cp /proc/mtd "$dest/mtd.txt"
    printf 'board=%s\n' "$board" > "$dest/device-info.txt"
    sysupgrade -b "$dest/sysupgrade.tar.gz"
    (cd "$dest" && sha256sum BL2.bin Nvram.bin Bdata.bin Factory.bin FIP.bin mtd.txt device-info.txt sysupgrade.tar.gz > SHA256SUMS)
    echo "备份完成：$dest。必须复制到电脑并再次校验；/tmp 会在重启后消失。"
    exit 0
fi

case "$action" in
    check-stock|stage-stock|check-install|install)
        [ "$#" -ge 2 ] || fail '缺少 bundle 和 backup 目录'
        bundle=$1 backup=$2; shift 2;;
    *) [ "$#" -ge 1 ] || fail '缺少 bundle 目录'; bundle=$1; shift;;
esac
bundle=$(CDPATH='' cd -- "$bundle" && pwd)
[ -s "$bundle/SHA256SUMS" ] && [ -s "$bundle/bundle.json" ] || fail '迁移包不完整'
(cd "$bundle" && sha256sum -c SHA256SUMS) || fail '迁移包校验失败'
value() { jsonfilter -i "$bundle/bundle.json" -e "@.$1"; }
[ "$(value schema)" = 1 ] && [ "$(value board)" = xiaomi,redmi-router-ax6000-ubootmod ] || fail '迁移包机型/格式不符'
artifact() {
    name=$(value "$1")
    case "$name" in ''|*/*|.*) fail '镜像必须是 bundle 内的普通文件名';; esac
    case "$1:$name" in
        sysupgrade:*-xiaomi_redmi-router-ax6000-ubootmod-squashfs-sysupgrade.itb|\
        recovery:*-xiaomi_redmi-router-ax6000-ubootmod-initramfs-recovery.itb|\
        factory:*-xiaomi_redmi-router-ax6000-ubootmod-initramfs-factory.ubi|\
        bl2:*-xiaomi_redmi-router-ax6000-ubootmod-preloader.bin|\
        fip:*-xiaomi_redmi-router-ax6000-ubootmod-bl31-uboot.fip) ;;
        *) fail "镜像用途或机型不符：$name";;
    esac
    [ -s "$bundle/$name" ] && [ ! -L "$bundle/$name" ] || fail "缺少镜像 $name"
    # Require this exact file to be covered, even if the checksum list is truncated.
    awk -v name="$name" '$2 == name { n++ } END { exit n != 1 }' "$bundle/SHA256SUMS" || fail "$name 没有唯一校验项"
    printf '%s\n' "$bundle/$name"
}
image=$(artifact sysupgrade)
recovery=$(artifact recovery)
factory_image=$(artifact factory)
bl2_image=$(artifact bl2)
fip_image=$(artifact fip)
[ "$(wc -c < "$recovery")" -le 16777216 ] || fail '恢复 FIT 超过 16 MiB'
[ "$(wc -c < "$factory_image")" -le 30801920 ] || fail 'factory UBI 超过 stock 迁移预算'
[ "$(wc -c < "$bl2_image")" -le 1048576 ] || fail 'BL2 超过分区大小'
[ "$(wc -c < "$fip_image")" -le 2097152 ] || fail 'FIP 超过分区大小'
[ "$(hexdump -n 4 -v -e '1/1 "%02x"' "$factory_image")" = 55424923 ] || fail 'factory 不是 UBI 格式'
for fit in "$image" "$recovery"; do
    [ "$(hexdump -n 4 -v -e '1/1 "%02x"' "$fit")" = d00dfeed ] || fail '镜像不是 FIT 格式'
done
available=$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)
[ "${available:-0}" -ge 131072 ] || fail '镜像上传后 MemAvailable 不足 128 MiB，请释放 RAM 后重试'

check_backup() {
    [ -d "$backup" ] || fail '备份目录不存在'
    (cd "$backup" && sha256sum -c SHA256SUMS) || fail '原始备份校验失败'
    grep -Fxq 'board=xiaomi,redmi-router-ax6000-stock' "$backup/device-info.txt" || fail '备份不是迁移前的 stock 备份'
    for entry in BL2:1048576 Nvram:262144 Bdata:262144 Factory:2097152 FIP:2097152; do
        label=${entry%:*}; bytes=${entry#*:}
        [ "$(wc -c < "$backup/$label.bin")" -eq "$bytes" ] || fail "$label 备份长度错误"
        awk -v name="$label.bin" '$2 == name { n++ } END { exit n != 1 }' "$backup/SHA256SUMS" || fail "$label 缺少校验项"
    done
    # Nvram can change on boot. Factory + Bdata must still identify this device.
    for entry in "Factory:$factory" "Bdata:$bdata"; do
        label=${entry%:*}; dev=${entry#*:}
        saved=$(sha256sum "$backup/$label.bin"); saved=${saved%% *}
        current=$(sha256sum "/dev/mtdblock${dev#mtd}"); current=${current%% *}
        [ "$saved" = "$current" ] || fail "$label 与本机不符，拒绝使用其他设备的备份"
    done
}
ram_boot() {
    root_type=$(awk '$2 == "/" { print $3; exit }' /proc/mounts)
    case "$root_type" in rootfs|ramfs|tmpfs) ;; *) fail "必须从 initramfs 启动，当前 / 为 $root_type";; esac
    awk '$2 == "/overlay" || $2 == "/rom" || $3 == "ubifs" { bad=1 } END { exit bad }' /proc/mounts || fail '检测到持久化文件系统仍被挂载'
}
ubi_for_mtd() {
    for path in /sys/class/ubi/ubi[0-9]*; do
        [ -f "$path/mtd_num" ] || continue
        [ "$(cat "$path/mtd_num")" = "${1#mtd}" ] || continue
        printf '/dev/%s\n' "${path##*/}"
    done
}
case "$action" in
    check-stock|stage-stock)
        check_layout stock
        check_backup
        for cmd in fw_printenv ubidetach ubiformat; do need "$cmd"; done
        # The original Xiaomi bootloader must already be pinned to the first slot.
        [ "$(fw_printenv -n flag_boot_rootfs)" = 0 ] || fail 'stock 启动槽不是 0'
        [ "$(fw_printenv -n flag_last_success)" = 1 ] || fail 'stock 启动策略不符'
        [ "$(fw_printenv -n flag_boot_success)" = 1 ] || fail 'stock 启动成功标记不符'
        for key in flag_try_sys1_failed flag_try_sys2_failed; do
            v=$(fw_printenv -n "$key")
            case "$v" in 6|7|8|9) ;; *) fail "$key 不符合已核对的 stock 启动策略";; esac
        done
        ;;
    check-install|install)
        check_layout ubootmod
        check_backup
        ram_boot
        for cmd in ubidetach ubiformat ubiattach ubimkvol ubiupdatevol mtd insmod; do need "$cmd"; done
        module="/lib/modules/$(uname -r)/mtd-rw.ko"
        [ -f "$module" ] || fail '缺少与当前内核匹配的 mtd-rw 模块；使用本包精简 recovery'
        sysupgrade -T "$image" || fail '正式固件未通过 sysupgrade 检查'
        ;;
    check-recover|recover)
        check_layout ubootmod
        ram_boot
        sysupgrade -T "$image" || fail '正式固件未通过 sysupgrade 检查'
        ;;
esac
case "$action" in check-*) [ "$#" -eq 0 ] || fail '检查命令不接受写入参数'; echo '检查通过；未格式化或刷写。'; exit 0;; esac
case "$action" in
    stage-stock|install) [ "$#" -eq 2 ] && [ "$1" = --apply ] && [ "$2" = --backup-saved-off-router ] || fail '写入需要 --apply --backup-saved-off-router，并先在电脑验证备份';;
    recover) [ "$#" -eq 1 ] && [ "$1" = --apply ] || fail '恢复写入需要 --apply';;
esac
trap 'echo "写入中断：保留当前电源和 RAM 系统，不要盲目重启；按文档检查恢复路径。" >&2' EXIT
if [ "$action" = stage-stock ]; then
    attached=$(ubi_for_mtd "$kernelpart")
    [ -z "$attached" ] || ubidetach -p "/dev/$kernelpart"
    ubiformat "/dev/$kernelpart" -y -f "$factory_image"
    trap - EXIT
    echo '第一阶段完成。不要重跑；手动 reboot，重新上传 bundle 和原始备份，然后运行 check-install。'
    exit 0
fi
if [ "$action" = install ]; then
    # The module is never autoloaded by this project or used outside RAM install.
    if ! grep -q '^mtd_rw ' /proc/modules; then insmod "$module" i_want_a_brick=1; fi
    for crash_file in /sys/fs/pstore/*; do
        [ ! -f "$crash_file" ] || rm -f "$crash_file"
    done
    attached=$(ubi_for_mtd "$ubipart")
    [ -z "$attached" ] || ubidetach -p "/dev/$ubipart"
    ubiformat "/dev/$ubipart" -y
    ubiattach -p "/dev/$ubipart"
    ubidev=$(ubi_for_mtd "$ubipart")
    [ -n "$ubidev" ] && [ "$(printf '%s\n' "$ubidev" | wc -l)" -eq 1 ] || fail '无法唯一定位新 UBI'
    ubimkvol "$ubidev" -n 0 -N ubootenv -s 1MiB
    ubimkvol "$ubidev" -n 1 -N ubootenv2 -s 1MiB
    ubimkvol "$ubidev" -n 2 -N recovery -s 16MiB
    ubiupdatevol "${ubidev}_2" "$recovery"
    ubi_sys=/sys/class/ubi/${ubidev##*/}
    free_lebs=$(cat "$ubi_sys/avail_eraseblocks")
    leb_size=$(cat "$ubi_sys/eraseblock_size")
    image_bytes=$(wc -c < "$image")
    needed_lebs=$(( (image_bytes + leb_size - 1) / leb_size + (16777216 + leb_size - 1) / leb_size ))
    [ "$free_lebs" -ge "$needed_lebs" ] || fail '实际 UBI 可用块不足以安装正式固件并保留 16 MiB；尚未写入 BL2/FIP'
    for entry in "$bl2:$bl2_image" "$fip:$fip_image"; do
        dev=${entry%%:*}; payload=${entry#*:}
        mtd write "$payload" "/dev/$dev"
        size=$(wc -c < "$payload")
        expected=$(sha256sum "$payload"); expected=${expected%% *}
        actual=$(head -c "$size" "/dev/$dev" | sha256sum); actual=${actual%% *}
        [ "$expected" = "$actual" ] || fail "$dev 写入后回读不一致"
    done
fi
# No -F; metadata/FIT validation must succeed. Erase saved config deliberately.
sysupgrade -n "$image"
trap - EXIT

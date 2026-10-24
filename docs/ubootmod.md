# Redmi AX6000 迁移到 OpenWrt U-Boot 与恢复

适用于 **MediaTek Redmi Router AX6000（RB06）**，从已正常运行的本项目 OpenWrt stock 布局迁移到
OpenWrt 官方 `xiaomi_redmi-router-ax6000-ubootmod`。不适用于 Qualcomm 小米 AX6000、小米 OEM 系统直接刷入，
也不适用于 hanwckf、闭源 Web U-Boot 或其他扩容方案。迁移会清空 OpenWrt 配置和数据，并替换 BL2/FIP。
准备阶段可以自动检查；实际刷写尚需本机验收，不把脚本测试视为已经在路由器上验证。

官方文档已保存为[仓库快照与逐项核对说明](https://github.com/Zander-1024/Redmi-AX6000-Openwrt/tree/main/docs/reference/openwrt)，附完整原文、U-Boot 安装章节、
来源与许可。主流程与官方一致；环境卷大小、恢复卷大小和管理地址等项目差异在那里单独说明。
脚本按 NAND 坏块规则回读引导分区，容量模型按整片 128 MiB NAND 预留坏块，并计入 fastmap 元数据；仍须验收实际 UBI/UBIFS 余量和恢复路径。

## 空间变化与选择

| 布局 | 内核与系统分区 | 发布容量条件 |
| --- | --- | --- |
| stock | `ubi_kernel` 30 MiB；`ubi` 80 MiB | 扣除保守 UBI 元数据和坏块预留，至少 8 MiB 逻辑数据容量 |
| 官方 ubootmod | 从 `0x580000` 开始的 `ubi`，122.5 MiB | 两个 1 MiB 环境卷、16 MiB 恢复卷、正式 FIT、UBI 预留之外，至少 16 MiB 逻辑数据容量 |

stock 不能用 128 MiB NAND 总容量衡量根分区余量。上一轮实测整包为 69.35 MiB、root 负载约 65.04 MiB，
旧模型曾估算剩余 10.29 MiB；按整片 NAND 和 fastmap 修正后为 9.20 MiB，尚未扣 UBIFS 开销。nlbwmon 整轮增加仅 40 KiB；
主要空间来自保留的 Xray、Sing-box、V2Ray、Hysteria、MosDNS 和规则数据，不能将涨幅归因于流量统计。
没有更早镜像及 manifest，尚不能断言从四五十 MB 增长的逐项原因。

如果想保留 stock，可先评估删除未使用的独立 V2Ray core、Hysteria 或冗余规则集；
本轮按原选择保留全部核心，没有擅自删减。ubootmod 扩大的是存储空间，不增加 512 MiB RAM，
仍须限制日志、数据库、列表及更新缓存；默认不在内置闪存在线替换大核心。

每个新包的 `capacity.json` 给出本次镜像的预算。它不是设备刷机后的 `df`，实际坏块和 UBIFS 开销会减少可用空间。

## 获取匹配的文件

在仓库执行 `./scripts/ci-local.sh all`，或运行 GitHub Actions 的 **Build OpenWrt**。
两者使用同一锁文件和构建驱动，先编译 stock，再编译完整 ubootmod，最后编译精简 recovery。
Docker 镜像保存编译依赖，`ax6000-openwrt-build` 卷保存源码与缓存，`build-output` 保存交付文件；
宿主不需要安装 OpenWrt 编译工具。初次构建需要下载源码、工具链与包，可能耗时数小时。

运行 `./scripts/ci-local.sh package` 可得到与 Actions 相同的分发归档：

- `ax6000-stock.tar.gz`：保留原引导布局设备的正式 `.bin`。
- `ax6000-ubootmod.tar.gz`：已经迁移设备的正式 `.itb`。
- `ax6000-migration.tar.gz`：完整 ubootmod `.itb`、精简恢复 `.itb` / factory `.ubi`、匹配的 preloader / FIP、脚本与说明。

在电脑上先用顶层 `SHA256SUMS` 校验归档，再将迁移归档解压到一个目录（下文称 `migration`），执行：

```sh
cd migration
sha256sum -c SHA256SUMS
```

所有镜像必须来自同一次通过门禁的构建；不要混搭第三方 preloader、FIP、内核模块或不同版本 recovery。
精简恢复系统不含代理核心、MosDNS、LuCI、ttyd，只保留迁移、SSH、DHCP、无线及官方内核模块。
它沿用 `192.168.10.1/24`、双频 SSID `Openwrt` / `Openwrt5G`、密码 `12345678`；请在正式系统初始化后改密。
引导程序的 TFTP 地址仍是 `192.168.1.1` / `192.168.1.254`，与 Linux 启动后的管理地址不同。

## 迁移前准备与备份

迁移时接 LAN 网线，使用稳定电源，并准备好下文的电脑 TFTP 服务；普通首次初始化仍支持无网线。
确认当前仍为原厂引导程序，而不是能忽略小米启动环境变量的第三方 U-Boot。
脚本能核对 Linux 分区和环境值，**不能仅凭 stock 的设备名证明引导代码未被别人替换**。
BL2/FIP 写入时断电，TFTP 也可能无法启动；需要串口、外部编程器或维修恢复，不应依赖远程无线刷引导区。

通过 LAN SSH 上传脚本并连接：

```sh
scp -O ax6000-migrate.sh root@192.168.10.1:/tmp/
ssh -p 22 root@192.168.10.1
sh /tmp/ax6000-migrate.sh backup /tmp/ax6000-stock-backup
```

脚本按分区标签、大小、擦除块、页大小、DTS 地址核对并备份 BL2、Nvram、Bdata、Factory、FIP，
另保存配置归档与分区表。备份目录含本机 MAC、校准与配置机密，权限为仅所有者访问，不上传公开仓库。
这份备份不包含整片 NAND、OOB 或所有坏块映射信息，不能等同于完整编程器备份。

回到电脑，把备份复制出来并校验，至少另存一份：

```sh
scp -O -r root@192.168.10.1:/tmp/ax6000-stock-backup ./
cd ax6000-stock-backup
sha256sum -c SHA256SUMS
```

`/tmp` 和恢复系统中的文件重启即消失。`--backup-saved-off-router` 是你已完成离机备份校验的声明，
脚本无法代替你检查电脑上的副本。不要使用其他路由器的 Factory / Bdata 备份。

## 第一阶段进入临时恢复系统

从电脑上传完整迁移目录（约一个正式镜像加精简恢复镜像；空间以实际文件为准）：

```sh
scp -O -r migration root@192.168.10.1:/tmp/
```

路由器执行：

```sh
sh /tmp/migration/ax6000-migrate.sh check-stock /tmp/migration /tmp/ax6000-stock-backup
sh /tmp/migration/ax6000-migrate.sh stage-stock /tmp/migration /tmp/ax6000-stock-backup --apply --backup-saved-off-router
reboot
```

`check-stock` 不刷写。它要求准确的 stock 分区，并检查当前小米启动策略指向第一系统：
`flag_boot_rootfs=0`、`flag_last_success=1`、`flag_boot_success=1`、两项失败次数为 6 至 9（本项目安装流程为 8）。
不符时停止，先核查原来的安装方式，不让脚本猜测或自动改动启动变量。
`stage-stock` 仅将精简 factory `.ubi` 写入 30 MiB 的 `ubi_kernel`，不会自动重启或写入 BL2/FIP。
不要将完整插件镜像塞进这个分区。脚本检查上传后的 `MemAvailable` 至少为 128 MiB，
不足时先释放 RAM；不得因此绕过容量检查。

重启后仍在 `192.168.10.1` 连接 SSH。首次使用本项目恢复镜像时 SSH host key 可能改变，
确认是本机后再更新电脑的 known_hosts 项。不要为此全局关闭主机密钥校验。

## 第二阶段安装 OpenWrt U-Boot 与正式系统

从电脑**重新上传** `migration` 和原始 `ax6000-stock-backup` 两个目录到恢复系统 `/tmp`。
此时 `board_name` 应为 `xiaomi,redmi-router-ax6000-ubootmod`，`ubi` 应从 `0x580000` 开始，大小为 `0x7a80000`。
脚本会检查这些信息，不接受只有文件名类似的其他固件。

```sh
sh /tmp/migration/ax6000-migrate.sh check-install /tmp/migration /tmp/ax6000-stock-backup
sh /tmp/migration/ax6000-migrate.sh install /tmp/migration /tmp/ax6000-stock-backup --apply --backup-saved-off-router
```

`install` 必须在 RAM initramfs 中执行，没有挂载 `/rom`、`/overlay` 或 UBIFS。
它先校验所有文件、原始备份和本机 Factory/Bdata，运行正式镜像 `sysupgrade -T`，随后：

1. 确认 pstore 已挂载并清理崩溃记录，再显式加载本镜像自带的 `mtd-rw`。
2. 重建扩容后的 UBI，创建两个 1 MiB 环境卷和 16 MiB NAND recovery 卷，写入精简 recovery。
3. 核对实际可用 UBI 块能容纳正式 FIT，并至少保留 16 MiB 逻辑数据容量。
4. 写入匹配的 BL2 / FIP，分别回读校验，最后执行 `sysupgrade -n` 安装正式 ubootmod 固件并重启。

`mtd-rw` 只在精简 recovery 中打包，不自动加载，不加入日常正式系统。脚本不使用 `sysupgrade -F`。
写入失败时停止，不自动重启；保留电源与当前 RAM 系统，先检查报错、分区和可用恢复方法。
它不是可无条件重跑的事务：格式化或写引导区之后不能保证回滚，尤其不要在第二阶段结束后重新执行第一阶段。

正式系统启动后访问 `192.168.10.1`。重新配置 WAN、节点和管理密码，再按 README 的设备验收清单验证。
不能将旧 stock 整份配置直接恢复到新布局，也不能给 stock 设备直接执行 ubootmod 的正式 sysupgrade。

## U Boot 仍能启动时的 TFTP 恢复

这是**恢复 ubootmod 的 OpenWrt 系统**，不是恢复小米原厂分区。如果 BL2/FIP 已损坏、没有 TFTP 请求，
应走串口或硬件救援，不反复写入不同引导文件。

电脑有线网卡设为 `192.168.1.254/24`，不设置网关，接路由器 LAN 口。把迁移包内精简恢复 `.itb` 复制并命名为：

```text
openwrt-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-initramfs-recovery.itb
```

在该网卡运行 TFTP 服务，允许本地 UDP 69 及服务所需传输端口。Windows 可使用 Tftpd64；
Linux 若已有 dnsmasq，可运行下面的 TFTP 单独服务，不为家庭 LAN 提供第二个 DHCP/DNS：

```sh
sudo dnsmasq --no-daemon --port=0 --interface=你的有线网卡 --bind-interfaces \
  --enable-tftp --tftp-root=/你的/tftp目录 --log-facility=-
```

这些是**电脑端**设置，不在路由器上执行，也不更改家庭正常初始化方式。
系统启动失败时官方 U-Boot 会尝试 NAND recovery，继而尝试 TFTP；可在开机按住 Reset 请求 TFTP recovery，
具体观察串口菜单或 TFTP 日志。不要在现有正常系统内长按 Reset 误触发恢复出厂设置。
若 NAND recovery 已启动而 TFTP 没有请求，直接使用该 RAM 系统即可。
TFTP 加载恢复镜像后，Linux 的地址变为本项目的 `192.168.10.1`；电脑切回 DHCP 或设 `192.168.10.2/24`，再连接 SSH。

重新上传迁移目录后执行：

```sh
sh /tmp/migration/ax6000-migrate.sh check-recover /tmp/migration
sh /tmp/migration/ax6000-migrate.sh recover /tmp/migration --apply
```

`recover` 仅在官方 ubootmod RAM 系统中校验、清理 pstore 后执行 `sysupgrade -n`，会丢弃旧配置，
不重建 UBI、不写 BL2/FIP、不修改 Factory/Bdata。正式固件再次启动后重新设置。
锁定 U-Boot 在发现 pstore 崩溃记录时会优先启动恢复系统；只重刷固件而保留记录，热重启后仍可能回到 recovery。
需要保留诊断信息时，先把 `/sys/fs/pstore` 中的记录复制到电脑。`check-recover` 不删除记录；
实际恢复要求 pstore 已挂载，清理失败即停止，不继续升级。

## 能否退回 stock 或小米原厂

官方机型页没有给出对本次布局可直接保证成功的完整回退流程，并明确区分原厂与 OpenWrt U-Boot 的恢复机制。
stock 使用 NMBM，官方 ubootmod 使用更大的原始 NAND UBI，格式化可能改变原厂坏块映射区域。
恢复原 BL2/FIP 之外，还需核对 NMBM、环境、原厂双系统布局和原厂恢复方式，不能仅刷一个 stock `.bin`。

因此本仓库提供离机原始分区备份和 ubootmod 救援脚本，**不提供未经实机验证的一键刷回原厂脚本**。
如果保留小米官方救砖和方便回原厂是必要条件，继续使用 stock，先按插件用途精简空间。
计划硬件级回退时，先取得本机完整 NAND/OOB 备份并在串口环境核验恢复方案；不要套用其他型号的 `mtd write`。

## 依据

- [OpenWrt 官方机型安装与救砖说明](https://openwrt.org/toh/xiaomi/redmi_ax6000#installing_openwrt_u-boot_layout)
- [锁定 stock DTS](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/target/linux/mediatek/dts/mt7986a-xiaomi-redmi-router-ax6000-stock.dts)
- [锁定 ubootmod DTS](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/target/linux/mediatek/dts/mt7986a-xiaomi-redmi-router-ax6000-ubootmod.dts)
- [锁定镜像生成规则](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/target/linux/mediatek/image/filogic.mk)
- [锁定官方 U-Boot 的地址、文件名与恢复逻辑](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/package/boot/uboot-mediatek/patches/431-add-xiaomi_redmi-ax6000.patch)

# Redmi AX6000 OpenWrt

为 **MediaTek Redmi Router AX6000 原厂分区布局**构建固件。唯一设备目标为
`mediatek/filogic/xiaomi_redmi-router-ax6000-stock`，不是 Qualcomm 小米 AX6000，
也不是 `ubootmod` / 扩容布局。没有实机分区证据时不要切换目标或强制刷入。
家庭嵌入式设备的资源、网络和维护原则见 [`AGENTS.md`](AGENTS.md)。

## 版本与依赖

采用“官方正式稳定版 + 维护者软件包 + 精确提交锁定”，不追随开发快照。
[`sources.lock`](sources.lock) 是两个工作流和 `diy-part1.sh` 共用的源码入口；
升级时同时审查版本、提交、包依赖与设备兼容性，而不是只修改分支名。

| 来源 | 本次锁定版本 | 提交 |
| --- | --- | --- |
| [OpenWrt](https://github.com/openwrt/openwrt/releases/tag/v25.12.6) | 25.12.6，内核 6.12.112 | `64900e756efa667774214f9c6b17c113222e01f7` |
| [PassWall 2](https://github.com/Openwrt-Passwall/openwrt-passwall2) | 26.10.20-1 | `0f923be3f00f9fb8db9591c9ecab41e7de5ec75e` |
| [PassWall packages](https://github.com/Openwrt-Passwall/openwrt-passwall-packages) | Xray 26.10.21、Sing-box 1.14.3、Hysteria 2.13.0、V2Ray plugin 5.49.0 | `049aaf472e8ce7e423299d43a516b7092a25b381` |
| [MosDNS](https://github.com/sbwml/luci-app-mosdns) | v5 快照：核心 5.3.4-r14、LuCI 1.7.14-r1 | `bd40245303cd0ba56804d49eed5dbc4be2a082ca` |
| [Argon](https://github.com/jerrykuku/luci-theme-argon) | 3.1.0，已集成设置界面 | `96734f4f52e98ac70f564ca4b92644b849e189ba` |
| [nlbwmon](https://github.com/openwrt/packages/tree/093d551675b1119a06ef224d419905e8d6b2af1a/net/nlbwmon) | 2025.06.02~29236be6-r1，含官方 LuCI 与中文包 | 随正式版固定 packages / LuCI feeds |

保留 release 自带的五组固定官方 feeds。`passwall2` 提供唯一的代理管理界面，
`passwall_packages` 提供 Xray、Sing-box、Hysteria、代理辅助组件、V2Ray plugin 和 geoip/geosite；
MosDNS feed 提供 MosDNS、geo2txt。V2Ray core、DDNS、ttyd、UPnP、nlbwmon 和系统组件保留官方来源。
保留原先明确选择的独立 Hysteria / V2Ray core / plugin，但它们不是 PassWall 2 的额外管理界面；
PassWall 2 的基础核心选择为 Xray + Sing-box。V2Ray 独立服务仍采用上游禁用默认值。
不再混入 kenzo/small，不强制覆盖整套包，也不替换官方 Go feed。
仅对锁定 Xray recipe 的 host 依赖做带上下文检查的修正，选择官方 Go 1.27.1。

`.config` 保留完整 `wpad-mbedtls`、中文界面及原有 DDNS 服务商。
Gandi 的 API key 后端未擅自改为 PAT 后端；升级固件不会自动迁移账户认证协议。

## 家庭路由器资源预算

该机型为 [512 MiB RAM、128 MiB NAND](https://openwrt.org/toh/hwdata/xiaomi/xiaomi_redmi_ax6000)，
但 stock rootfs 仅使用 80 MiB `ubi`，不能将总闪存都算作可安装空间。
用户明确选择：**保留原代理核心与 MosDNS，只加 nlbwmon，本轮不加入 AdGuard Home**。

以下来自上一轮真实镜像及同版本官方插件的资源预检。除 nlbwmon 为整包安装大小外，
安装列是主要可执行文件大小；XZ 列为同 256 KiB 块大小的单文件 SquashFS 测量，不等于最终镜像增量。

| 组件 | 安装大小 | 单文件 XZ 测量 | 轻负载 RSS 快照 |
| --- | ---: | ---: | ---: |
| Xray | 28.32 MiB | 8.00 MiB | 42.33 MiB |
| Sing-box | 54.75 MiB | 14.51 MiB | 未启动 |
| V2Ray core | 35.09 MiB | 9.48 MiB | 未启动 |
| Hysteria | 21.13 MiB | 5.93 MiB | 未启动 |
| MosDNS | 15.09 MiB | 4.37 MiB | 87.21 MiB |
| nlbwmon | 46 KiB | 未单独拆分，见本轮整镜像增量 | 0.95 MiB |
| AdGuard Home（本轮不打包） | 32.49 MiB | 8.43 MiB | 未启动 |

AdGuard Home 还需要过滤库、查询日志、缓存和运行内存；按当前体积预算，无法在加入后维持数据预留目标。
它还需与 dnsmasq/MosDNS 明确串联，避免争抢 DNS 53 端口；本轮不硬塞，也不擅自删掉用户保留的核心。

RSS 测量在 512 MiB 限制的隔离容器中进行，MosDNS 已加载实际规则，Xray 手动运行真实生成的分流配置，
nlbwmon 已统计一次实际转发流量。**这不是整机、满库、满并发或无线/PPE 工作时的 RAM 峰值。**
默认代理主开关仍关闭，不代表这些代理核心会全部同时常驻。

本组合的发布门禁要求扣除保守 UBI 元数据和坏块预留后，仍留出至少 8 MiB 数据容量；
未来新增大型插件以至少 16 MiB 为目标，需重新选择精简方案。不要在内置闪存上无预算在线更新大核心或 geodata，
优先更新源码锁并重编固件。

## GitHub Actions 构建

1. 将配置及脚本提交到自己的仓库。
2. 在 Actions 选择 **Build OpenWrt**，手动运行；默认不启用 SSH 调试。
3. 构建使用 `ubuntu-24.04`，checkout release 后校验 SHA；所有 Actions 固定完整提交。
4. 编译、stock sysupgrade、manifest、校验和及分区容量检查全部成功后，才上传产物。
   Release 先上传草稿，全部成功后公开；失败不会发布固件或清理旧 Release。

默认 Artifact / Release 只分发通过分区校验的 **stock sysupgrade** 和元数据，
不分发未通过该门禁的 initramfs/factory 或通用 BL2 二进制。
可打开 `UPLOAD_BIN_DIR` 获取原始构建树产物，但不能将其中每个镜像都视为可安全刷入 stock。
已移除 Cowtransfer/WeTransfer 远程脚本。Release tag 为
`ax6000-passwall2-<release>-<UTC时间>-<run ID>-<run attempt>`，避免与旧 PassWall 固件混淆或被重试覆盖。
公开成功后仅保留最近三份非草稿、非预发布的 `ax6000-` Release，并删除对应 tag；
不处理其他前缀或旧命名历史产物。运行记录清理单独授予 `actions: write`。

随固件保留 `sources.lock`、实际源码 SHA 的 `build-sources.txt`、输入 `requested.config`、
最终 `final.config`、包版本 manifest、上游 buildinfo、原始 `upstream-sha256sums`
及包含附加文件的 `SHA256SUMS`。两份校验清单使用不同名称，避免 GitHub Release /
大小写不敏感文件系统冲突。先用 `sha256sum -c SHA256SUMS` 校验整套分发文件；
上游清单还包含未分发的原始构建文件，可用 `sha256sum -c --ignore-missing upstream-sha256sums`。
容量门禁按 stock DTS 的 30 MiB `ubi_kernel`、80 MiB `ubi`、
128 KiB 擦除块计算，保守预留 UBI 元数据、坏块，并为本组合额外保留至少 8 MiB rootfs_data 数据容量；
这不替代刷机前对实机分区、可用块和恢复手段的确认。

**Update Checker** 也仅手动运行，读取同一锁文件并验证同一 release SHA。
跨工作流 dispatch 需要仓库 secret `ACTIONS_TRIGGER_PAT`，具备目标仓库 dispatch 权限。
事件仅接受 `Source Code Update`，payload 的 SHA 必须等于当前锁定 SHA，不能指定任意 ref。
缓存 key 包含锁文件及构建配置；命中只代表曾成功触发，**不是编译成功证明**。
同一配置构建失败时，直接手动运行 Build OpenWrt 重试，不要靠清除缓存偷偷升级源码。

## 本地 Linux 构建

依赖使用 [OpenWrt 官方 Ubuntu 24.04 清单](https://openwrt.org/docs/guide-developer/toolchain/install-buildsystem)，
额外包含 MediaTek 所需的 `python3-dev`、`libelf-dev`。在非 root 用户、大小写敏感的
Linux 文件系统中执行；macOS 下可使用 Linux VM/container，不在宿主机直接编译。

```bash
# 在本仓库根目录执行；Ubuntu x86_64 的构建依赖：
sudo apt-get update
sudo apt-get install -y build-essential clang flex bison g++ gawk \
  gcc-multilib g++-multilib gettext git libncurses-dev libssl-dev \
  python3-setuptools python3-dev libelf-dev rsync swig unzip zlib1g-dev \
  file wget curl ca-certificates subversion time jq

CUSTOM_DIR="$PWD"
source sources.lock
git clone --depth=1 --branch "$OPENWRT_REF" "$OPENWRT_URL" openwrt
test "$(git -C openwrt rev-parse HEAD)" = "$OPENWRT_COMMIT"
cd openwrt
bash "$CUSTOM_DIR/diy-part1.sh"
cp "$CUSTOM_DIR/.config" .config
cp -a "$CUSTOM_DIR/files" .
make defconfig
make download -j8
make -j"$(nproc)" || make -j1 V=s
```

ARM64 Ubuntu 不安装仅适用于 x86 的 multilib 包。请像工作流一样确认 `defconfig`
未丢失所选包、安装 symlink 的实际提供者和最终配置，不能只看命令退出码。
脚本可重复执行而不重复追加 feed；不支持在来源不明、已有包覆盖的旧构建树上混搭。

## 首次启动与无网线初始化

| 项目 | 默认值 |
| --- | --- |
| LAN / LuCI | `192.168.10.1` |
| 2.4 GHz SSID | `Openwrt` |
| 5 GHz SSID | `Openwrt5G` |
| 两个 SSID 的密码 | `12345678` |
| 无线参数 | 双频开启、CN、自动信道、WPA2-CCMP；5 GHz HE160 |
| 快速漫游 | 保留 802.11r、mobility domain `1111`、原有 FT 参数 |
| 系统 | 上海时区、简体中文、软硬件流量卸载 |

**用户为局域网、无网线首次初始化便利，明确保留固定密码 `12345678`。**
维护时不得擅自关闭无线、改成必须接网线初始化，或默认降为 HE80 / 关闭 802.11r。
固定密码并非安全部署建议，初始化后应自行改密；无线可用性仍须实机验证。
Wi-Fi 密码不是管理密码；本项目不硬编码 root 管理密码。
首次登录后应立即设置独立的 LuCI / SSH root 密码，不要把 LuCI、SSH 或 ttyd 映射到 WAN。

初始化脚本先设置 LAN，再根据无线设备的 `band` 和 AP 的 `device/mode` 关系设置双频，
不依赖 section 数组顺序。缺少任一频段的 AP、必要 UCI 写入或提交失败时返回非零，
保留脚本供下次启动重试。没有提前写入的“已初始化”标记；全部成功才由 OpenWrt 删除脚本。
Argon 背景保留路径只追加一次。cron 日志级别和稳定版软件仓库使用上游默认值。
NTP 通过 UCI 明确设置 `ntp.tencent.com`、`ntp1.tencent.com`、`ntp2.tencent.com` 三个腾讯公网时间源，
启用校时客户端、关闭对外 NTP 服务，保留上海时区（UTC+8）。不使用云厂商内网地址，不再替换上游源码中的域名子串。
这也会替换保留配置中残留的旧 NTP 列表；不依赖尚未配置好的代理进行首次校时。
编译选择 `CONFIG_LUCI_LANG_zh_Hans=y`，但 LuCI 运行时语言键为 `zh_cn`；
不能把编译语言名直接写入 `luci.main.lang`，否则中文目录加载失败而显示英文。

## PassWall 2 配置与迁移

仅安装 `luci-app-passwall2`，不同时安装/启用旧 PassWall。两者虽然使用不同 nftables 表，
但共享 TPROXY 路由表 `999`；一个服务清理路由可能破坏另一个服务，因此不能并行接管流量。
初始化会关闭备份中旧 PassWall 的主开关、Socks 和 ACL 开关，移除它原有的
`firewall.passwall` include 和 `ucitrack` 跟踪项，**不删除旧节点资料**。
新固件不包含旧客户端运行包，不会在新 rootfs 上执行缺少旧依赖的 init 脚本。

PassWall 2 的上游配置含 `passwall2.github:1080` 示例节点，本项目仅删除与该示例身份匹配的节点，
不会删除复用 `examplenode` 名称但已改为真实地址的用户节点。实际初始化策略：

| 项目 | 设置 |
| --- | --- |
| 服务状态 | 主开关、Socks、ACL 均关闭，用户配置真实节点后再启用 |
| 主节点 | `rulenode`，界面备注 `AX6000 GFW`；这是有效的内部“分流节点”，不是代理服务器 |
| 分流规则组 | `AX6000`，隔离上游示例规则，避免 Steam 等预置规则改变本项目策略 |
| 规则顺序 | 私网直连 → GFW 名单 → 国内直连 → 默认直连 |
| GFW 名单 | `geosite:gfw`，匹配 TCP 和 UDP；未指定真实出站前暂为直连 |
| 透明代理端口范围 | 保留旧实现的 TCP `80,443`、UDP `1:65535`，不因迁移扩大 TCP 接管范围 |
| 未命中流量 | TCP / UDP 默认均直连，不是默认全代理 |
| 防火墙后端 | firewall4 / nftables，`prefer_nft=1` |

旧 `udp_proxy_mode=disable` 指的是**未命中规则的默认策略**，不是禁止所有 UDP 代理；
本项目保留 GFW 名单命中 UDP 的行为。规则数据现使用打包的 GeoSite `gfw` 分类，
来源与旧文本 GFW 名单不同，不保证逐域名完全相同。`dns_mode`、`use_gfw_list`、`chn_list`、
`tcp_proxy_mode`、`udp_proxy_mode` 不能直接搬进 `passwall2` 命名空间，初始化会清除这些无效键。

### 启用代理

1. 在 **服务 → PassWall 2 → 节点列表**添加/订阅真实节点，不直接复制整个旧 `/etc/config/passwall`。
2. 主节点保持 **AX6000 GFW**；在它的分流设置中，将 **GFW proxy - select a real node**
   这一行的出站改为真实节点。私网、国内和默认出站保持直连。
3. 保存后再打开 PassWall 2 主开关。直接将主节点换成普通代理节点会改变上述分流策略。
4. Xray 自签证书节点需要正确的 `pinnedPeerCertSha256` / `pcs`；不通过关闭校验或降级规避证书问题。

### MosDNS 与 DNS 接管

MosDNS 启用并监听 `127.0.0.1:5335`，保留 pipeline 和 geosite 广告过滤，
但 `redirect=0`、`local_dns_redirect=0`，不与 PassWall 2 争抢 dnsmasq 设置或 DNS 劫持。
PassWall 2 使用 `remote_dns_protocol=udp`、`remote_dns=127.0.0.1:5335`、
**`remote_dns_detour=direct`**：这是访问路由器本机的 MosDNS，不能把该回环地址经代理送到远端服务器。
直连 DNS 保留上游自动选择，与远程 DNS 是两项独立设置。
PassWall 2 未启用时系统仍使用普通 DNS，普通客户端查询不会自动经过 MosDNS 广告过滤。

### 其他配置冲突检查

- 保留软硬件流量卸载：FW4 在 forward 链加速转发流量，REDIRECT/TPROXY 接管的流量走本地代理，
  不能仅因存在代理就认定必须关闭卸载；实际硬件效果仍待实机验证。
- 保留 UPnP 包及上游默认配置，不擅自启用服务；没有发现必须卸载它的源码级冲突。
  ttyd 保持 LAN 接口和 `/bin/login`，不扩大到 WAN。
- Argon 背景保留项只追加一次，即使原 `/etc/sysupgrade.conf` 最后一行没有换行，也不会合并破坏旧保留项。

## nlbwmon 流量统计

在 **服务 → 带宽监控** 查看按主机/协议统计；附带配置、备份/恢复和中文页面。
它复用 conntrack 计数，不争抢 DNS 端口，不修改现有代理或卸载策略。

- 数据目录为 `/var/lib/nlbwmon`（OpenWrt 的 RAM/tmpfs），每月一个周期，最多保留 3 代、每库最多 10,000 条记录。
- 使用压缩归档、不预分配全库，接收缓冲为 512 KiB；30 秒刷新连接计数，24 小时提交到 RAM 数据目录。
- **重启会丢失这些临时历史**；需要时在备份页手动导出。若改成内置闪存或外置盘，须另外预算空间、留存和写入频率。
- 记录数/缓冲限制不是进程 RSS 硬上限。达到记录数上限会影响新增统计；流量卸载也可能使统计不准确，
  保留现有卸载配置并以真机观察为准，不将该统计当作运营商精确计费依据。

## 旧配置与升级差异

- 25.12 使用 **APK** 和 `luci-app-package-manager`，不再修改 `/etc/opkg/distfeeds.conf`。
  三个自定义源码 feed 没有本项目发布的在线 APK 仓库，已关闭其运行时仓库生成，
  不影响编译入固件；这些插件的升级应更新源码锁并重编固件，不要添加不存在的官方 feed URL。
- Argon 3.x 已包含设置页，不再安装旧独立 `luci-app-argon-config`。
- 不再强制 `cronloglevel=8`；已删除会拼坏 NTP 域名的旧 `diy-part2.sh`，改由首次启动 UCI 设置腾讯公网时间源。
- **保留配置升级不等于干净初始化**。新固件的默认脚本会应用本项目的 LAN、无线和 PassWall 2 策略；
  旧 PassWall 节点资料保留供手动迁移，不自动转换、启用或删除。不要恢复旧 feeds / 独立 Argon 插件。
  升级前备份并准备与 stock 分区匹配的恢复手段，旧备份不能替代新默认值验收。

## 验证状态

本次修改针对已复现的构建/配置错误与升级兼容性。此前使用中的未知现象没有日志或实机证据，
不能据此声称找到根因或“稳定性已修复”。

### 本轮：家庭资源约束、腾讯公网 NTP、nlbwmon

- 已新增 `AGENTS.md`；按用户选择保留原代理核心与 MosDNS，只增加 nlbwmon，不打包 AdGuard Home。
- shell 语法、ShellCheck、actionlint、真实 Linux feeds/defconfig 和工作流原样依赖检查已通过；
  实际 manifest 包含 nlbwmon、官方 LuCI/中文包，不含旧 PassWall 或 AdGuard Home。
  锁定 feeds 中未选中 WeeChat 的递归依赖诊断和 Prosody 缺失依赖警告仍存在，未通过隐藏警告冒充修复。
- [完整 stock 构建 #39947267273](https://github.com/Zander-1024/Redmi-AX6000-Openwrt/actions/runs/39947267273)
  已通过，并公开 [本轮固件 Release](https://github.com/Zander-1024/Redmi-AX6000-Openwrt/releases/tag/ax6000-passwall2-v25.12.6-20261023T130538Z-39947267273-1)。
  全部 12 个文件的 SHA-256、两份校验清单中对应项、与 Actions Artifact 的逐文件一致性均已核对。
  实际镜像通过包清单及新增的 8 MiB 数据容量门禁；构建输入配置、源码锁和镜像内初始化脚本与提交内容一致。
- 从该新镜像提取真实 UCI/BusyBox，验证旧 NTP 列表替换、上海时区、客户端启用/服务端关闭、
  倒序双频配置、连续执行幂等，以及 system/nlbwmon 提交失败、nlbwmon 配置缺失后的保留和重试。
  三个腾讯公网时间源均收到有效 NTP 回包；这不是用户路由器 WAN 首次校时的实测。
- 新镜像内的 nlbwmon 在隔离的 LAN → 路由/NAT → 测试 WAN 中统计真实 1 MiB HTTP 传输：
  客户端下载计数为 1,058,906 字节（含网络开销），实际执行数据库提交；不是伪造记录或只记录调用。
  单独运行时 RSS 为 956 KiB；上方组合负载快照不等于整机或峰值。
- 实际运行新镜像的 ubus/rpcd/uhttpd 和中文 LuCI/Argon：带宽监控显示对应客户端 MAC、下载量和图表；
  配置页显示 10,000 条、3 代、RAM 数据路径及 30 秒/24 小时间隔。
  点击“生成备份”所得归档与真实已提交数据库逐字节一致。浏览器仅允许本机地址；
  可选的 GitHub OUI 厂商库请求被拦截时，统计和图表仍正常显示。
- 新 manifest 门禁实际拒绝缺少 nlbwmon 的上一轮镜像；隔离的容量边界样本超出预算 1 字节时被拒绝。

### 既有 PassWall 2 / MosDNS 验证范围

本轮 Xray、Sing-box、V2Ray、Hysteria、MosDNS 二进制分别与[上一轮构建](https://github.com/Zander-1024/Redmi-AX6000-Openwrt/actions/runs/39916403287)
逐一核对 SHA-256 一致。以下是上一轮已执行的行为验证，不冒充本轮重新执行：

- 真实初始化器通过正常/倒序双频、无末尾换行保留项、缺失频段/服务配置、九个包提交失败、
  重试和连续执行；旧节点资料及同名真实节点保留，旧客户端/firewall/tracker 接管项被禁用或移除。
- 使用打包的 Lua 生成器、真实 GeoSite/GeoIP 和 geoview 生成配置/SRS，分别通过 Xray 与 Sing-box 配置检查；
  隔离 HTTP/SOCKS 场景验证 GFW 走代理、国内/私网/未命中走直连。
  本机 DNS 改为 `remote` 时实际解析超时，恢复 `direct` 后解析和访问恢复。
- 用实际 MosDNS 初始化器和 geo2txt 生成默认 profile，真实核心验证本地 hosts、
  GeoSite 广告域名及子域名返回 `0.0.0.0`，未以简化 DNS fixture 代替广告过滤。
- 实际中文 LuCI/Argon 页面验证默认关闭的代理主开关、AX6000 分流、本机 DNS 直连及旧菜单移除。
  容器缺少路由器内核模块，页面的组件提示不能据此判定实机模块状态。
- Update Checker 此前实际运行已验证源码 SHA，但因缺少专用 `ACTIONS_TRIGGER_PAT` 失败且未保存触发缓存；
  未宣称跨工作流 dispatch 已通过。

### 本轮发布镜像与容量

文件：`openwrt-mediatek-filogic-xiaomi_redmi-router-ax6000-stock-squashfs-sysupgrade.bin`。

| 度量 | 数值 | 口径 |
| --- | ---: | --- |
| sysupgrade 文件 | 72,714,544 字节，约 69.35 MiB | 比上一轮增加 40,960 字节（40 KiB），是整轮改动而非 nlbwmon 单包增量 |
| kernel 负载 | 4,507,520 字节 | stock 30 MiB `ubi_kernel` |
| root 负载 | 68,198,400 字节 | stock 80 MiB `ubi` |
| 剩余逻辑数据容量估算 | 10,792,960 字节，约 10.29 MiB | 扣除模型中的 UBI 元数据/坏块预留，尚未扣除 UBIFS 文件系统开销 |

SHA-256：

```text
02399fadc10c0ec9bb575e9fabcfb941bd7bfb019549bd50b63d55e8b1d4d593
```

容量门禁保留的是 UBI 逻辑数据容量，不是刷机后 `df` 的可用空间；实机坏块、UBIFS 格式化和后续配置会继续影响余量。
本轮未连接或刷写路由器，未提供真实外部代理节点；这些编译、容器和网页证据不能替代实机 WAN、无线、
硬件卸载准确性、峰值内存或长期稳定性验收。

### 设备验收清单

确认分区匹配、备份完成且具备恢复手段后，使用干净配置分别验收：

1. 不插网线连接两个既定 SSID，访问 `192.168.10.1` / LuCI；核对实际 HE160、802.11r 和连接状态。
2. 完成 WAN 上网与普通 DNS 查询。
3. 按上面的步骤配置真实节点，验证 GFW 命中/未命中、国内直连，以及 TCP 80/443、其他 TCP 端口和 UDP 的行为。
4. 检查 MosDNS 5335 监听、广告过滤、无 DNS 循环；再重启确认无线和配置持续正常。
5. 单独验证保留配置升级，不把它与干净初始化混为一谈。
6. 在代理未配置时通过 WAN 完成腾讯公网 NTP 校时，核对上海时区，并检查重启后的首次校时。
7. 核对实际 `/overlay` 容量、正常使用/加载规则后的 RAM 和 nlbwmon 进程；对照客户端传输量检查卸载下的统计偏差。
   验证手动导出历史，并确认接受默认 RAM 数据在重启后丢失。

## 致谢与许可

基于 [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt)，感谢 OpenWrt、
PassWall 2、MosDNS、Argon 及所用 GitHub Actions 的维护者。
本仓库脚本沿用 [MIT](LICENSE) 许可；固件内各组件遵循各自许可证。

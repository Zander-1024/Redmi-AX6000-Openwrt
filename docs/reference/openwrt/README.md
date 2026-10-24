# Redmi AX6000 官方文档与项目核对

这里保存 OpenWrt 官方机型 Wiki 的完整原文，以及 stock 转官方 OpenWrt U-Boot 的章节摘录。
它们用于审查迁移流程和发现上游文档变化；本项目的操作入口仍是 [迁移与恢复指导](../../ubootmod.md)。
官方示例中的设备编号、旧版本下载链接和 OEM 恢复命令不能直接套到当前设备。

## 来源与许可

- 原页面：[Xiaomi Redmi AX6000](https://openwrt.org/toh/xiaomi/redmi_ax6000)。
- 作者：OpenWrt Wiki contributors；[编辑历史](https://openwrt.org/toh/xiaomi/redmi_ax6000?do=revisions)。
- [完整 DokuWiki 原文](redmi-ax6000.dokuwiki)：原始导出响应逐字节保存，包含安装、恢复、分区和历史启动日志。
- [U-Boot 安装章节](uboot-installation.md)：从原文自动生成，只转换 Markdown 排版和链接，保留原文中的历史示例和笔误。
- [抓取记录](source.json)：原页面地址、UTC 抓取时间、页面显示的修改时间、长度及 SHA-256。

本目录的官方原文、排版摘录及核对说明按 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
提供；遵循 [OpenWrt Wiki 许可声明](https://openwrt.org/license)，不适用仓库脚本的 MIT 许可。
原文中另有许可声明的内容遵循其声明。保存快照不表示获得 OpenWrt 官方对本项目的背书。

## 2026 年 10 月 24 日核对结果

对照页面显示最后修改于 `2026/09/18 09:07` 的原文与 `sources.lock` 锁定的 OpenWrt
`64900e756efa667774214f9c6b17c113222e01f7`。页面时间未标明时区，不把它当作抓取时间或精确 revision ID。

迁移的主要阶段、镜像用途和引导区写入顺序一致。下表记录项目的额外检查及有意差异，
不把“与 Wiki 一致”当成 NAND 写入、无线或 TFTP 已经通过真机验收。

| 官方章节或步骤 | 本项目实现 | 核对结果 |
| --- | --- | --- |
| U-Boot 步骤 1：先运行 OpenWrt stock | `check-stock` 检查 stock 设备名、完整分区几何及小米启动标记 | 一致；不接受小米 OEM 或其他 U-Boot 的设备名替代 |
| 步骤 2：备份 BL2、Nvram、Bdata、Factory、FIP 与配置并离机保存 | `backup` 按标签解析 MTD，保存校验和；迁移检查 Factory/Bdata 与本机一致 | 一致；项目额外检查备份长度和显式离机备份声明 |
| 步骤 3：将 ubootmod `initramfs-factory.ubi` 写入 stock `mtd7` | `stage-stock` 按 `ubi_kernel` 标签及 `0x600000/30 MiB` 定位，只写精简 factory UBI | 同一用途和位置；项目不硬编码 MTD 编号，不把完整插件镜像作为迁移 initramfs |
| 步骤 4：重启进入新布局 initramfs，确认 `mtd5` 为 `07a80000` UBI | 手动重启、重新上传文件，检查 ubootmod、`0x580000/0x7a80000`，要求 RAM 根且无持久化挂载 | 一致；DT 设备名来自当前内核，本身不能证明 BL2/FIP 已替换 |
| 步骤 5：加载匹配内核的 `mtd-rw` | 模块随精简 recovery 编译；仅 `install` 显式加载 | 一致；无需在迁移中在线安装，正式固件不包含该模块 |
| 步骤 6：清除 pstore，避免进入 NAND/TFTP recovery | `install` 清理崩溃记录；同样的启动条件也适用于 `recover` | 本次修复将清理覆盖到恢复路径；检查模式和缺少确认时不得删除记录 |
| 步骤 7：重新格式化 UBI，创建 ID 0/1 的两个 128 KiB 环境卷 | ID/名称相同，各预留 1 MiB | 有意扩大；锁定 U-Boot 的 `ubi_create_env` 同样使用 `0x100000`，容量模型计入两卷；卷大小不是环境数据长度 |
| 步骤 8：可选 NAND recovery，示例为 10 MiB，可按镜像扩大 | 必建 ID 2 的 16 MiB recovery 卷，写入精简 FIT | 符合官方可调大小规则；项目额外提供离线恢复卷，并纳入预算 |
| 步骤 9：依次写 preloader 到 BL2、FIP 到 FIP | 相同顺序，写后增加回读校验 | 主流程一致；以 `mtd dump` 跳过坏块后截取等长数据并校验 SHA-256 |
| 步骤 10：`sysupgrade -n` 安装 ubootmod `.itb` | 先 `sysupgrade -T`，最终 `sysupgrade -n`，不使用 `-F` | 与实际命令一致；官方步骤文字称 `.bin`，命令实际使用 `.itb`，本项目依据镜像规则使用后者 |
| Debricking：电脑 `192.168.1.254` 提供指定名称的 recovery `.itb` | 保留该地址和完整文件名；Linux 启动后使用 `192.168.10.1` | 一致；U-Boot 的路由器地址 `192.168.1.1` 从锁定引导源码核对，不能混用后面的 OEM `192.168.31.*` 恢复教程 |

官方 Flash Layout 表仍包含 OEM 的 `ubi/ubi1/overlay` 命名和布局。当前 stock 的 `ubi_kernel` 30 MiB、
`ubi` 80 MiB 以锁定 DTS 为准；ubootmod 表中的 `0x7a80000` 为 122.5 MiB，表内 `122MiB` 是简写。
本项目初始化地址、SSID 和 Wi-Fi 密码属于项目定制，不改动引导程序的 TFTP 地址。

锁定源码依据：

- [公共 DTS 与受保护引导分区](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/target/linux/mediatek/dts/mt7986a-xiaomi-redmi-router-ax6000.dtsi)
- [stock DTS](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/target/linux/mediatek/dts/mt7986a-xiaomi-redmi-router-ax6000-stock.dts)
- [ubootmod DTS](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/target/linux/mediatek/dts/mt7986a-xiaomi-redmi-router-ax6000-ubootmod.dts)
- [镜像生成规则](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/target/linux/mediatek/image/filogic.mk)
- [U-Boot 环境、pstore 分支及 TFTP 设置](https://github.com/openwrt/openwrt/blob/64900e756efa667774214f9c6b17c113222e01f7/package/boot/uboot-mediatek/patches/431-add-xiaomi_redmi-ax6000.patch)

## 脚本修正与验证边界

- `install` / `recover` 在升级前清理 pstore；检查模式保留记录，未挂载 pstore 或删除失败时拒绝继续。
- 引导区使用 `mtd dump` 按完整擦除块跳过坏块，再截取镜像长度并校验 SHA-256；读取错误、短读或哈希不符均停止。
  不使用 `mtd verify`（锁定源码不跳坏块），也不使用 `mtd -l 镜像长度 dump`（末尾部分块遇到坏块会失去对齐）。
- 容量按整片 128 MiB NAND 预留 20 个坏块，另留 6 个 UBI 元数据块，包括 fastmap 的两块。
  stock 的 NMBM master 可能较小，此计算更保守；fastmap autoconvert 默认关闭，不计启用后的额外池开销。
- stock 失败计数按官方要求检查为非负整数且 >= 6，允许正常启动累加后的多位数。

2026-10-24 在迁移前的 stock 实机只读核对：NMBM 管理区从 120 MiB 开始，80 MiB UBI 实际预留
19 个坏块、6 个元数据块；rootfs_data 卷为 77 LEB（9.32 MiB），当时 `df` 可用约 5.96 MiB。
这也说明逻辑卷预算不能替代文件系统可用空间。BL2 的完整 `mtd dump` 与离机备份逐字节一致。

离线测试覆盖坏块处于镜像首块及末尾部分块、短读、读取错误、回读不一致后停止，以及 pstore/格式化/容量门禁。
其中 MTD、UBI、sysupgrade 使用测试替身；这些测试不能证明有坏块设备的 BootROM 或无线恢复能力。
实际迁移和恢复路径仍须在目标设备验收。

修正已通过 ShellCheck 和 23 项离线测试；18 项迁移测试另使用本次 GitHub recovery 镜像中的 BusyBox ash
经 QEMU 重跑通过。已核对实际 FIT 设备标识、恢复 DTB、mtd-rw 模块、内置联网初始化脚本及固件配置输入哈希。

## 后续校验与更新

在仓库根目录执行，脚本只读取官方 HTTPS 页面和本地文档，不执行摘录中的命令：

```sh
python3 scripts/openwrt-docs.py verify  # 离线检查原文 SHA-256 及摘录是否匹配
python3 scripts/openwrt-docs.py check   # 联网比较官方最新原文；变化时返回非零并显示差异
python3 scripts/openwrt-docs.py update  # 人工决定更新后重新抓取，再审查 git diff
```

`verify` 随 `build.sh check` 执行；它只保证快照与摘录一致，不宣称自动证明脚本语义与官方一致。
联网检查不放入每次固件构建，避免 Wiki 不可达或上游文字变动影响锁定源码构建。
更新后需要逐项重审上表、`sources.lock` 对应 DTS/镜像规则、迁移脚本和回归测试，再提交快照及核对说明。

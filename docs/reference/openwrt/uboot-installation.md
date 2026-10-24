# Installing OpenWrt (U-Boot layout)

> 官方章节的自动排版摘录，保留原文及历史示例；不是本项目可直接执行的刷机清单。
> 来源：[OpenWrt Wiki](https://openwrt.org/toh/xiaomi/redmi_ax6000#installing_openwrt_u-boot_layout)，作者：OpenWrt Wiki contributors。
> 许可：[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。修改仅为 DokuWiki 到 Markdown 的格式转换。
> 完整原文与抓取记录见 [核对说明](README.md)。不要手工编辑此生成文件。

1. Your device should already running OpenWrt (stock layout) as per above instructions.

2. Backup BL2, Nvram, Bdata, Factory, and FIP in case you break something or you want to go back to stock firmware one day.

```text
cat /dev/mtdblock0 > /tmp/BL2.bin
cat /dev/mtdblock1 > /tmp/Nvram.bin
cat /dev/mtdblock2 > /tmp/Bdata.bin
cat /dev/mtdblock3 > /tmp/Factory.bin
cat /dev/mtdblock4 > /tmp/FIP.bin
```

Now save all whose bin files to somewhere safe.

Then backup your configurations, since ubiformat for entire mtd device is required to create new ubootenv volume for OpenWrt U-Boot.

3. Run the following cmd to boot into an initramfs with the new OpenWrt U-Boot layout that expand ubi partion to the end of flash:

```text
ubiformat /dev/mtd7 -y -f /tmp/openwrt-{version}-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-initramfs-factory.ubi
```

NOTE: The firmware could be found at `https://downloads.openwrt.org/releases/{version}/targets/mediatek/filogic/openwrt-{version}-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-initramfs-factory.ubi`

4. Reboot. It'll boot into initramfs, check mtd partion info.

The ubi partion should be mtd5

```text
root@OpenWrt:~# cat /proc/mtd
dev:    size   erasesize  name
mtd0: 00100000 00020000 BL2
mtd1: 00040000 00020000 Nvram
mtd2: 00040000 00020000 Bdata
mtd3: 00200000 00020000 Factory
mtd4: 00200000 00020000 FIP
mtd5: 07a80000 00020000 ubi
```

5. Load kmod-mtd-rw to temporarily make the bootloader partitions writable.

The kmod-mtd-rw is from the feeds, it is not packed in initramfs-factory by default.

If you're building your own image, remember to add kmod-mtd-rw module in Kernel modules > Other modules

To install `kmod-mtd-rw` via opkg:
```text
opkg update && opkg install kmod-mtd-rw
```

Alternatively, you can download it from `https://downloads.openwrt.org/releases/{version}/targets/mediatek/filogic/packages/`.

e.g. download for v23.05.5: https://downloads.openwrt.org/releases/23.05.5/targets/mediatek/filogic/packages/kmod-mtd-rw_5.15.167+git-20160214-2_aarch64_cortex-a53.ipk

In releases 25.12 and later, install via [apk package manager](https://openwrt.org/docs/guide-user/additional-software/apk):
```text
apk update && apk add kmod-mtd-rw
```

Alternatively, you can download it from `https://downloads.openwrt.org/releases/{version}/targets/mediatek/filogic/kmods`.

e.g. download for v25.12.2: https://downloads.openwrt.org/releases/25.12.2/targets/mediatek/filogic/kmods/6.12.74-1-60d938adcb727697d3015e4285d4c290/kmod-mtd-rw-6.12.74.2021.02.28~e8776739-r1.apk

Select your OpenWrt release version and kernel version accordingly.

Load kmod-mtd-rw:
```text
insmod /lib/modules/$(uname -r)/mtd-rw.ko i_want_a_brick=1
```

6. Run the following command to clean all pending crash dumps in pstore,
or OpenWrt U-Boot may boot into NAND recovery or tftp recovery.
```text
rm -f /sys/fs/pstore/*
```

7. Format ubi and create new ubootenv volume:
```text
ubidetach -p /dev/mtd5; ubiformat /dev/mtd5 -y; ubiattach -p /dev/mtd5
ubimkvol /dev/ubi0 -n 0 -N ubootenv -s 128KiB
ubimkvol /dev/ubi0 -n 1 -N ubootenv2 -s 128KiB
```

8. This part is optional and you can skip this if you do not want to have a NAND recovery
boot feature offered by OpenWrt U-Boot. Don't worry, you always have
automatic tftp recovery feature enabled.

If your recovery image is larger than 10MiB, size the recovery partition accordingly to make it fit.
```text
ubimkvol /dev/ubi0 -n 2 -N recovery -s 10MiB
ubiupdatevol /dev/ubi0_2 /tmp/ax6000-ubootmod-initramfs-recovery.itb
```

NOTE: The file could be found at `https://downloads.openwrt.org/releases/{version}/targets/mediatek/filogic/openwrt-{version}-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-initramfs-recovery.itb`

9. Now, flash new U-Boot. Bye-bye ugly stock U-Boot.
```text
mtd write /tmp/ax6000-ubootmod-preloader.bin BL2
mtd write /tmp/ax6000-ubootmod-bl31-uboot.fip FIP
```

NOTE: The files could be found at `https://downloads.openwrt.org/releases/{version}/targets/mediatek/filogic/openwrt-{version}-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-bl31-uboot.fip` and `https://downloads.openwrt.org/releases/{version}/targets/mediatek/filogic/openwrt-{version}-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-preloader.bin`

10. Flash the squashfs-sysupgrade.bin as usual:
```text
sysupgrade -n /tmp/openwrt-{version}-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-squashfs-sysupgrade.itb
```

NOTE: The file could be found at `https://downloads.openwrt.org/releases/{version}/targets/mediatek/filogic/openwrt-{version}-mediatek-filogic-xiaomi_redmi-router-ax6000-ubootmod-squashfs-sysupgrade.itb`

FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential clang flex bison g++ gawk gcc-multilib g++-multilib gettext \
    git libncurses-dev libssl-dev python3 python3-setuptools python3-dev \
    libelf-dev rsync swig unzip zlib1g-dev file wget curl ca-certificates \
    subversion time jq xz-utils zstd cpio squashfs-tools u-boot-tools \
    device-tree-compiler qemu-user-static shellcheck util-linux \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends \
    proot python3-websocket openssh-client sshpass iproute2 bsdextrautils ethtool && rm -rf /var/lib/apt/lists/*
# Ubuntu's existing uid 1000 is used only inside this build container.
RUN mkdir -p /work && chown 1000:1000 /work
USER 1000:1000
WORKDIR /work

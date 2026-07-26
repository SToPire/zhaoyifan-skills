---
name: qemu-kernel-lab
description: Standardize a local Linux kernel test workflow around QEMU, a fully installed Alpine qcow2 guest, and a self-built kernel. Use when an agent needs to clone or update Linux sources, install Alpine into a QEMU disk image, boot a custom kernel on that installed guest under QEMU/KVM, attach GDB, or turn ad-hoc VM commands into repeatable kernel-development steps.
---

# QEMU Kernel Lab

Build a local kernel test lab around a fully installed Alpine qcow2 guest. Support both `x86_64` and `aarch64`. Use `ttyS0` on `x86_64`; use `ttyAMA0` on the common QEMU `aarch64` `virt` machine.

## Keep One Layout

```text
lab/
  downloads/
  images/
  src/linux/
  out/
```

Reuse the existing kernel tree and qcow2 image unless the user explicitly asks for a clean rebuild.

## Follow This Sequence

### 1. Prepare the Kernel Tree

- Clone or update the Linux tree under `src/linux`.
- Build the architecture default config:
  - `x86_64`: `make x86_64_defconfig`
  - `aarch64`: `make ARCH=arm64 defconfig`
- Enable debug information and GDB scripts.
- Keep both `vmlinux` and the boot image:
  - `x86_64`: `arch/x86/boot/bzImage`
  - `aarch64`: `arch/arm64/boot/Image`
- Match the Alpine ISO architecture to the kernel architecture. Do not use an `x86` installer ISO with an `x86_64` kernel workflow.

### 2. Install Alpine into qcow2

- Download the matching `alpine-virt` ISO into `downloads/`.
- Create `images/alpine-rootfs.qcow2`, typically `20G`.
- Boot the installer. If `/dev/kvm` is unavailable, add `--no-kvm`. If host port `2222` is occupied, pass another `--ssh-port`.

```bash
./scripts/run-qemu-kernel.sh \
  --arch <x86_64|aarch64> \
  --iso downloads/alpine-virt-<version>-<arch>.iso \
  --disk images/alpine-rootfs.qcow2
```

- Inside the guest, run:

```sh
ip link set eth0 up
udhcpc -i eth0
cat > /etc/apk/repositories <<'EOF'
https://dl-cdn.alpinelinux.org/alpine/v<major.minor>/main
https://dl-cdn.alpinelinux.org/alpine/v<major.minor>/community
EOF
apk update
setup-disk -m sys /dev/vda
```

- Confirm the disk erase prompt with `y`.
- Wait for `Installation is complete. Please reboot.`
- Shut down and reboot from the installed disk.
- If an installation attempt is interrupted after partitioning starts, recreate the qcow2 image before retrying.

### 3. Boot the Installed Guest

Plain disk boot:

```bash
./scripts/run-qemu-kernel.sh \
  --arch <x86_64|aarch64> \
  --disk images/alpine-rootfs.qcow2
```

Direct custom-kernel boot on the installed guest:

```bash
./scripts/run-qemu-kernel.sh \
  --arch <x86_64|aarch64> \
  --kernel <bootable-kernel-image> \
  --disk images/alpine-rootfs.qcow2
```

Use:

- `x86_64`: `src/linux/arch/x86/boot/bzImage`
- `aarch64`: `src/linux/arch/arm64/boot/Image`

Keep `root=/dev/vda3` unless the guest partition layout proves otherwise.

### 4. Enable Persistent Guest Services

Inside the installed guest, standardize:

```sh
rc-service networking start
rc-update add networking
apk add openssh
rc-service sshd start
rc-update add sshd
```

### 5. Install Kernel Modules When Needed

Direct `-kernel` boot does not install modules automatically. When the guest needs loadable modules:

1. Attach the qcow2 image to NBD on the host.
2. Mount the root partition.
3. Run `make INSTALL_MOD_PATH=/mountpoint modules_install`.
4. Unmount and disconnect NBD.

### 6. Attach GDB When Needed

Boot the installed guest with:

```bash
./scripts/run-qemu-kernel.sh \
  --arch <x86_64|aarch64> \
  --kernel <bootable-kernel-image> \
  --disk images/alpine-rootfs.qcow2 \
  --gdb-port 1234
```

Then connect:

```bash
gdb vmlinux
(gdb) target remote :1234
```

Keep `nokaslr` unless the task explicitly needs KASLR enabled.

## Rules

- Center the workflow on one installed Alpine qcow2 guest.
- Reuse the same guest across kernel iterations.
- Prefer direct `-kernel` boot for daily testing.
- Fall back to plain disk boot only for bootloader or stock-guest validation.
- Prefer user-mode networking and host port forwarding unless the task explicitly needs a different network model.
- Prefer extra `virtio-blk` drives for filesystem and block-layer tests.
- Do not replace the host or WSL kernel when QEMU provides enough isolation.
- Use deterministic guest-side network and repository commands instead of interactive setup helpers when installing over the serial console.

## Resource

- [`scripts/run-qemu-kernel.sh`](./scripts/run-qemu-kernel.sh): launch Alpine installer boots, installed-disk boots, or direct custom-kernel boots on the installed guest.

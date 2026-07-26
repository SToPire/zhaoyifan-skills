#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run-qemu-kernel.sh --kernel BZIMAGE --disk DISK [options]
  run-qemu-kernel.sh --disk DISK [options]
  run-qemu-kernel.sh --iso ISO --disk DISK [options]

Options:
  --arch ARCH                Guest architecture. Default: x86_64. Supported: x86_64, aarch64.
  --kernel PATH              Custom kernel image to boot.
  --disk PATH                Main guest disk image.
  --disk-format FORMAT       Main disk format. Default: infer qcow2/raw from suffix.
  --iso PATH                 Installer ISO to attach as a CD-ROM.
  --machine NAME             Override the QEMU machine type.
  --console DEVICE           Override the kernel serial console device.
  --root DEVICE              Root device for direct --kernel + --disk boots. Default: /dev/vda3.
  --memory SIZE              Guest memory. Default: 4G.
  --smp N                    Guest vCPU count. Default: 4.
  --ssh-port PORT            Host TCP port forwarded to guest 22. Default: 2222.
  --gdb-port PORT            Add -gdb tcp::PORT -S.
  --append-extra TEXT        Extra kernel command line text. Repeatable.
  --extra-drive PATH[:FMT]   Extra virtio-blk drive. Repeatable. Default format: raw.
  --no-kvm                   Skip -accel kvm and use a generic CPU model.
  --dry-run                  Print the final QEMU command without executing it.
  --help                     Show this help text.
  --                         Pass remaining arguments directly to QEMU.
EOF
}

guess_format() {
  case "$1" in
    *.qcow2) printf '%s\n' qcow2 ;;
    *) printf '%s\n' raw ;;
  esac
}

parse_drive_spec() {
  local spec="$1"
  if [[ "$spec" == *:* ]]; then
    printf '%s\n%s\n' "${spec%%:*}" "${spec#*:}"
  else
    printf '%s\n%s\n' "$spec" raw
  fi
}

default_console_for_arch() {
  case "$1" in
    x86_64) printf '%s\n' ttyS0 ;;
    aarch64) printf '%s\n' ttyAMA0 ;;
    *)
      echo "unsupported architecture: $1" >&2
      exit 1
      ;;
  esac
}

default_qemu_bin_for_arch() {
  case "$1" in
    x86_64) printf '%s\n' qemu-system-x86_64 ;;
    aarch64) printf '%s\n' qemu-system-aarch64 ;;
    *)
      echo "unsupported architecture: $1" >&2
      exit 1
      ;;
  esac
}

arch="x86_64"
machine=""
console=""
qemu_bin="${QEMU_BIN:-}"
kernel=""
disk=""
disk_format=""
iso=""
root_dev="/dev/vda3"
memory="4G"
smp="4"
ssh_port="2222"
gdb_port=""
use_kvm=1
dry_run=0
append_extra=()
extra_drives=()
qemu_passthrough=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch)
      arch="$2"
      shift 2
      ;;
    --kernel)
      kernel="$2"
      shift 2
      ;;
    --disk)
      disk="$2"
      shift 2
      ;;
    --disk-format)
      disk_format="$2"
      shift 2
      ;;
    --iso)
      iso="$2"
      shift 2
      ;;
    --machine)
      machine="$2"
      shift 2
      ;;
    --console)
      console="$2"
      shift 2
      ;;
    --root)
      root_dev="$2"
      shift 2
      ;;
    --memory)
      memory="$2"
      shift 2
      ;;
    --smp)
      smp="$2"
      shift 2
      ;;
    --ssh-port)
      ssh_port="$2"
      shift 2
      ;;
    --gdb-port)
      gdb_port="$2"
      shift 2
      ;;
    --append-extra)
      append_extra+=("$2")
      shift 2
      ;;
    --extra-drive)
      extra_drives+=("$2")
      shift 2
      ;;
    --no-kvm)
      use_kvm=0
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      qemu_passthrough+=("$@")
      break
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -n "$iso" && -n "$kernel" ]]; then
  echo "--iso cannot be combined with --kernel" >&2
  exit 1
fi

if [[ -z "$disk" ]]; then
  echo "this workflow always requires --disk" >&2
  exit 1
fi

if [[ -n "$iso" && -z "$disk" ]]; then
  echo "--iso requires --disk" >&2
  exit 1
fi

if [[ -n "$disk" && -z "$disk_format" ]]; then
  disk_format="$(guess_format "$disk")"
fi

if [[ -z "$qemu_bin" ]]; then
  qemu_bin="$(default_qemu_bin_for_arch "$arch")"
fi

if [[ -z "$console" ]]; then
  console="$(default_console_for_arch "$arch")"
fi

qemu=("$qemu_bin")

case "$arch" in
  x86_64)
    if [[ -n "$machine" ]]; then
      qemu+=(-machine "$machine")
    fi
    ;;
  aarch64)
    qemu+=(-machine "${machine:-virt}")
    ;;
  *)
    echo "unsupported architecture: $arch" >&2
    exit 1
    ;;
esac

if [[ "$use_kvm" -eq 1 ]]; then
  qemu+=(-cpu host -accel kvm)
else
  qemu+=(-cpu max)
fi

qemu+=(-m "$memory" -smp "$smp" -nographic)

if [[ -n "$kernel" ]]; then
  append=("console=$console" nokaslr)
  if [[ -n "$disk" ]]; then
    append=("root=$root_dev" "${append[@]}")
  fi
  if [[ ${#append_extra[@]} -gt 0 ]]; then
    append+=("${append_extra[@]}")
  fi

  qemu+=(-kernel "$kernel")
  qemu+=(-append "${append[*]}")
fi

if [[ -n "$iso" ]]; then
  qemu+=(
    -boot d
    -drive "file=$iso,format=raw,if=none,id=cd0"
    -device virtio-scsi-pci
    -device scsi-cd,drive=cd0
  )
fi

if [[ -n "$disk" ]]; then
  qemu+=(
    -drive "file=$disk,format=$disk_format,if=none,id=hd0"
    -device virtio-blk-pci,drive=hd0
  )
fi

for i in "${!extra_drives[@]}"; do
  mapfile -t parsed < <(parse_drive_spec "${extra_drives[$i]}")
  path="${parsed[0]}"
  fmt="${parsed[1]}"
  idx=$((i + 1))
  qemu+=(
    -drive "file=$path,format=$fmt,if=none,id=hd$idx"
    -device virtio-blk-pci,drive=hd$idx
  )
done

qemu+=(
  -netdev "user,id=net0,hostfwd=tcp::${ssh_port}-:22"
  -device virtio-net-pci,netdev=net0
)

if [[ -n "$gdb_port" ]]; then
  qemu+=(-gdb "tcp::${gdb_port}" -S)
fi

if [[ ${#qemu_passthrough[@]} -gt 0 ]]; then
  qemu+=("${qemu_passthrough[@]}")
fi

if [[ "$dry_run" -eq 1 ]]; then
  printf '%q ' "${qemu[@]}"
  printf '\n'
  exit 0
fi

exec "${qemu[@]}"

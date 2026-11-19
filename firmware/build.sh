#!/bin/sh
set -eu

# WHY: the edk2 tag of QEMU 11.1's own firmware. Windows 11 hangs at "Start boot option" with edk2-stable202608.
TAG=edk2-stable202408
HERE=$(cd "$(dirname "$0")" && pwd)
HOME_DIR=${PROOFREEL_HOME:-$HOME/.proofreel}
WORK=$HOME_DIR/build/edk2
OUT=$HOME_DIR/firmware

LLVM=$(brew --prefix llvm)/bin/
LLD=$(brew --prefix lld)/bin
[ -x "$LLVM/clang" ] && [ -x "$LLD/ld.lld" ] && command -v iasl >/dev/null ||
  { echo "Install the toolchain: brew install llvm lld acpica" >&2; exit 1; }

if [ ! -d "$WORK" ]; then
  git clone --depth 1 --branch "$TAG" https://github.com/tianocore/edk2.git "$WORK"
  git -C "$WORK" submodule update --init --depth 1 \
    BaseTools/Source/C/BrotliCompress/brotli MdeModulePkg/Library/BrotliCustomDecompressLib/brotli \
    CryptoPkg/Library/OpensslLib/openssl CryptoPkg/Library/MbedTlsLib/mbedtls \
    MdeModulePkg/Universal/RegularExpressionDxe/oniguruma MdePkg/Library/BaseFdtLib/libfdt \
    MdePkg/Library/MipiSysTLib/mipisyst SecurityPkg/DeviceSecurity/SpdmLib/libspdm
fi
cd "$WORK"
git apply --check -R "$HERE/ramfb-resolution.patch" 2>/dev/null || git apply "$HERE/ramfb-resolution.patch"

export PATH="$LLD:$PATH" CLANGDWARF_BIN="$LLVM" PYTHON_COMMAND=python3 WORKSPACE="$WORK"
# WHY: the host tools of this tag have warnings that are errors in Apple clang 21.
make -s -C BaseTools/Source/C EXTRA_OPTFLAGS=-Wno-error -j "$(sysctl -n hw.ncpu 2>/dev/null || nproc)"
set +u
. ./edksetup.sh BaseTools
set -u
# WHY: the same options as QEMU's own edk2-aarch64-code.fd (roms/edk2-build.config), so the UEFI variables match.
build -q -a AARCH64 -t CLANGDWARF -b RELEASE -p ArmVirtPkg/ArmVirtQemu.dsc -n 0 \
  -D NETWORK_HTTP_BOOT_ENABLE -D NETWORK_IP6_ENABLE -D NETWORK_TLS_ENABLE -D NETWORK_ISCSI_ENABLE \
  -D SECURE_BOOT_ENABLE -D TPM2_ENABLE -D TPM2_CONFIG_ENABLE -D CAVIUM_ERRATUM_27456

mkdir -p "$OUT"
cp Build/ArmVirtQemu-AArch64/RELEASE_CLANGDWARF/FV/QEMU_EFI.fd "$OUT/edk2-aarch64-code.fd"
# WHY: QEMU's virt machine needs each pflash file to be exactly 64 MB.
truncate -s 64m "$OUT/edk2-aarch64-code.fd"
rm -rf Build
echo "Installed $OUT/edk2-aarch64-code.fd"

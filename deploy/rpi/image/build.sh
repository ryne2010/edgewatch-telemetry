#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 022

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/pins.env"

OUTPUT_DIR="$REPO_ROOT/dist/rpi-image"
WORK_DIR=""
DEVICE_LAYER="$DEFAULT_DEVICE_LAYER"
IMAGE_PROFILE="$DEFAULT_IMAGE_PROFILE"
IMAGE_VERSION=""
INSTALL_DEPS=0

usage() {
  cat <<'EOF'
Usage: deploy/rpi/image/build.sh [options]

Build the secret-free EdgeWatch fleet-image-v1 ARM64 SD-card image.

Options:
  --device LAYER       rpi-image-gen device layer (rpizero2w, rpi3, rpi4, rpi5)
  --profile PROFILE    standalone, gateway, or camera-satellite
  --image-version VER  release version embedded in the image and manifest
  --output-dir DIR     artifact directory (default: dist/rpi-image)
  --work-dir DIR       disposable build directory (default: mktemp)
  --install-deps       run the pinned builder's install_deps.sh with sudo
  --print-pins         print pinned upstream/base inputs and exit
  -h, --help           show this help

The build consumes no device credentials. Provision each flashed card by adding
/boot/firmware/edgewatch/bootstrap.env; never add that file to this image source.
EOF
}

die() {
  printf 'fleet-image-v1: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --device)
      (($# >= 2)) || die "--device requires a value"
      DEVICE_LAYER="$2"
      shift 2
      ;;
    --image-version)
      (($# >= 2)) || die "--image-version requires a value"
      IMAGE_VERSION="$2"
      shift 2
      ;;
    --profile)
      (($# >= 2)) || die "--profile requires a value"
      IMAGE_PROFILE="$2"
      shift 2
      ;;
    --output-dir)
      (($# >= 2)) || die "--output-dir requires a value"
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --work-dir)
      (($# >= 2)) || die "--work-dir requires a value"
      WORK_DIR="$2"
      shift 2
      ;;
    --install-deps)
      INSTALL_DEPS=1
      shift
      ;;
    --print-pins)
      printf 'repository=%s\nrevision=%s\nsuite=%s\narch=%s\ndefault_device=%s\ndefault_profile=%s\n' \
        "$RPI_IMAGE_GEN_REPOSITORY" "$RPI_IMAGE_GEN_REVISION" "$RPI_OS_SUITE" \
        "$RPI_OS_ARCH" "$DEFAULT_DEVICE_LAYER" "$DEFAULT_IMAGE_PROFILE"
      exit 0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

case "$DEVICE_LAYER" in
  rpizero2w|rpi3|rpi4|rpi5) ;;
  *) die "unsupported device layer: $DEVICE_LAYER" ;;
esac
case "$IMAGE_PROFILE" in
  standalone|gateway|camera-satellite) ;;
  *) die "unsupported image profile: $IMAGE_PROFILE" ;;
esac
if [[ "$IMAGE_PROFILE" == "gateway" && "$DEVICE_LAYER" != "rpi4" && "$DEVICE_LAYER" != "rpi5" ]]; then
  die "gateway profile requires rpi4 or rpi5"
fi

[[ "$RPI_IMAGE_GEN_REVISION" =~ ^[0-9a-f]{40}$ ]] || die "builder revision must be a full commit SHA"
[[ "$RPI_OS_SUITE" == "bookworm" ]] || die "fleet-image-v1 requires the pinned Bookworm base"
[[ "$RPI_OS_ARCH" == "arm64" ]] || die "fleet-image-v1 requires arm64"

for command in git python3 sha256sum tar xz; do
  command -v "$command" >/dev/null 2>&1 || die "required command not found: $command"
done

DIRTY_INPUTS="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all -- \
  agent contracts gateway_runtime telegram_controller scripts/rpi_bootstrap.py \
  scripts/apply_model_bundle.py scripts/edgewatch_device_control.py scripts/gateway_lte_qualify.py \
  scripts/telegram_control_init.py scripts/telegram_fleet_controller.py scripts/ota \
  deploy/rpi/image deploy/rpi/edgewatch-firstboot.service)"
[[ -z "$DIRTY_INPUTS" ]] || die "image inputs must be committed and clean before building"

SOURCE_REVISION="$(git -C "$REPO_ROOT" rev-parse HEAD)"
SOURCE_DATE_EPOCH="$(git -C "$REPO_ROOT" show -s --format=%ct "$SOURCE_REVISION")"
if [[ -z "$IMAGE_VERSION" ]]; then
  IMAGE_VERSION="fleet-image-v1-${SOURCE_REVISION:0:12}"
fi
[[ "$IMAGE_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || die "invalid image version"

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/edgewatch-fleet-image.XXXXXXXX")"
  cleanup() { rm -rf -- "$WORK_DIR"; }
  trap cleanup EXIT
else
  [[ "$WORK_DIR" != "/" && "$WORK_DIR" != "$REPO_ROOT" ]] || die "unsafe work directory"
  mkdir -p -- "$WORK_DIR"
  [[ -z "$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]] || die "work directory must be empty"
fi

BUILDER_DIR="$WORK_DIR/rpi-image-gen"
SOURCE_DIR="$WORK_DIR/edgewatch-source"
GENERATED_CONFIG="$SOURCE_DIR/config/fleet-image-v1.yaml"
PROFILE_LAYER="edgewatch-${IMAGE_PROFILE}-v1"
IMAGE_NAME="edgewatch-${IMAGE_VERSION}-${IMAGE_PROFILE}-${DEVICE_LAYER}-${RPI_OS_ARCH}"
mkdir -p -- "$SOURCE_DIR/config" "$SOURCE_DIR/layer" "$OUTPUT_DIR"

download_verified() {
  local url="$1"
  local expected_sha256="$2"
  local destination="$3"
  python3 - "$url" "$expected_sha256" "$destination" <<'PY'
import hashlib
import os
import sys
import tempfile
import urllib.request

url, expected, destination = sys.argv[1:]
parent = os.path.dirname(destination)
fd, temporary = tempfile.mkstemp(prefix=".edgewatch-download-", dir=parent)
try:
    digest = hashlib.sha256()
    with os.fdopen(fd, "wb") as output, urllib.request.urlopen(url, timeout=120) as response:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    if digest.hexdigest() != expected:
        raise SystemExit("profile artifact SHA-256 verification failed")
    os.replace(temporary, destination)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

git clone --filter=blob:none --no-checkout "$RPI_IMAGE_GEN_REPOSITORY" "$BUILDER_DIR"
git -C "$BUILDER_DIR" fetch --depth 1 origin "$RPI_IMAGE_GEN_REVISION"
git -C "$BUILDER_DIR" checkout --detach "$RPI_IMAGE_GEN_REVISION"
[[ "$(git -C "$BUILDER_DIR" rev-parse HEAD)" == "$RPI_IMAGE_GEN_REVISION" ]] || \
  die "pinned builder revision verification failed"

git -C "$REPO_ROOT" archive --format=tar --prefix=edgewatch/ "$SOURCE_REVISION" \
  agent contracts gateway_runtime telegram_controller scripts/rpi_bootstrap.py \
  scripts/apply_model_bundle.py scripts/edgewatch_device_control.py scripts/gateway_lte_qualify.py \
  scripts/telegram_control_init.py \
  scripts/telegram_fleet_controller.py scripts/ota > "$SOURCE_DIR/edgewatch-app.tar"
if tar -tf "$SOURCE_DIR/edgewatch-app.tar" | \
  grep -E '(^|/)(\.env|id_(rsa|ed25519)|[^/]+\.(pem|key|p12|pfx))$' >/dev/null; then
  die "runtime archive contains a forbidden secret-bearing filename"
fi
if tar -xOf "$SOURCE_DIR/edgewatch-app.tar" | \
  grep -aE -- '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' >/dev/null; then
  die "runtime archive contains private-key material"
fi

cp -- "$SCRIPT_DIR/layer/edgewatch-fleet-v1.yaml" "$SOURCE_DIR/layer/"
cp -- "$SCRIPT_DIR/layer/$PROFILE_LAYER.yaml" "$SOURCE_DIR/layer/"
cp -- "$SCRIPT_DIR/assets/edgewatch-firstboot-identity.service" "$SOURCE_DIR/"
cp -- "$SCRIPT_DIR/assets/90-edgewatch-watchdog.conf.disabled" "$SOURCE_DIR/"
cp -- "$REPO_ROOT/deploy/rpi/edgewatch-firstboot.service" "$SOURCE_DIR/"
if [[ "$IMAGE_PROFILE" == "gateway" ]]; then
  download_verified "$CHIRPSTACK_SQLITE_URL" "$CHIRPSTACK_SQLITE_SHA256" \
    "$SOURCE_DIR/chirpstack-sqlite.deb"
  download_verified "$PAHO_MQTT_URL" "$PAHO_MQTT_SHA256" "$SOURCE_DIR/paho-mqtt.whl"
  cp -- "$REPO_ROOT/deploy/rpi/gateway/edgewatch-lte-power-on.service" "$SOURCE_DIR/"
  cp -- "$REPO_ROOT/deploy/rpi/gateway/edgewatch-lte-power-off.service" "$SOURCE_DIR/"
elif [[ "$IMAGE_PROFILE" == "camera-satellite" ]]; then
  download_verified "$LITERT_URL" "$LITERT_SHA256" "$SOURCE_DIR/litert.whl"
  download_verified "$BACKPORTS_STRENUM_URL" "$BACKPORTS_STRENUM_SHA256" \
    "$SOURCE_DIR/backports-strenum.whl"
fi
printf 'IMAGE_VERSION=%s\nIMAGE_PROFILE=%s\nSOURCE_REVISION=%s\nBUILDER_REVISION=%s\nOS_SUITE=%s\nARCH=%s\nDEVICE_LAYER=%s\n' \
  "$IMAGE_VERSION" "$IMAGE_PROFILE" "$SOURCE_REVISION" "$RPI_IMAGE_GEN_REVISION" "$RPI_OS_SUITE" \
  "$RPI_OS_ARCH" "$DEVICE_LAYER" > "$SOURCE_DIR/edgewatch-image-release"

sed \
  -e "s/@SOURCE_DATE_EPOCH@/$SOURCE_DATE_EPOCH/g" \
  -e "s/@DEVICE_LAYER@/$DEVICE_LAYER/g" \
  -e "s/@IMAGE_NAME@/$IMAGE_NAME/g" \
  -e "s/@PROFILE_LAYER@/$PROFILE_LAYER/g" \
  "$SCRIPT_DIR/config/fleet-image-v1.yaml.in" > "$GENERATED_CONFIG"

if ((INSTALL_DEPS)); then
  command -v sudo >/dev/null 2>&1 || die "--install-deps requires sudo"
  sudo "$BUILDER_DIR/install_deps.sh"
fi

(cd "$BUILDER_DIR" && ./rpi-image-gen build -S "$SOURCE_DIR" -c "$GENERATED_CONFIG")

mapfile -t built_images < <(find "$BUILDER_DIR/work" -type f -name "$IMAGE_NAME.img" -print)
((${#built_images[@]} == 1)) || die "expected one built image, found ${#built_images[@]}"

RAW_IMAGE="$OUTPUT_DIR/$IMAGE_NAME.img"
COMPRESSED_IMAGE="$RAW_IMAGE.xz"
cp -- "${built_images[0]}" "$RAW_IMAGE"
xz --threads=1 --check=crc32 --best --force "$RAW_IMAGE"
CHECKSUM="$(sha256sum "$COMPRESSED_IMAGE" | awk '{print $1}')"
printf '%s  %s\n' "$CHECKSUM" "$(basename "$COMPRESSED_IMAGE")" > "$COMPRESSED_IMAGE.sha256"

MANIFEST_PATH="$OUTPUT_DIR/$IMAGE_NAME.manifest.json"
python3 - "$MANIFEST_PATH" "$COMPRESSED_IMAGE" "$CHECKSUM" <<PY
import json
import os
import sys
from datetime import datetime, timezone

manifest_path, image_path, checksum = sys.argv[1:]
manifest = {
    "schema_version": 1,
    "image_family": "fleet-image-v1",
    "image_version": ${IMAGE_VERSION@Q},
    "filename": os.path.basename(image_path),
    "sha256": checksum,
    "size_bytes": os.path.getsize(image_path),
    "architecture": ${RPI_OS_ARCH@Q},
    "os_suite": ${RPI_OS_SUITE@Q},
    "device_layer": ${DEVICE_LAYER@Q},
    "image_profile": ${IMAGE_PROFILE@Q},
    "source_revision": ${SOURCE_REVISION@Q},
    "source_date_epoch": int(${SOURCE_DATE_EPOCH@Q}),
    "generated_at": datetime.fromtimestamp(int(${SOURCE_DATE_EPOCH@Q}), timezone.utc).isoformat(),
    "builder": {
        "repository": ${RPI_IMAGE_GEN_REPOSITORY@Q},
        "revision": ${RPI_IMAGE_GEN_REVISION@Q},
    },
    "contains_device_secrets": False,
    "profile_artifacts": {
        "chirpstack_sqlite": ${CHIRPSTACK_SQLITE_VERSION@Q} if ${IMAGE_PROFILE@Q} == "gateway" else None,
        "litert": ${LITERT_VERSION@Q} if ${IMAGE_PROFILE@Q} == "camera-satellite" else None,
        "paho_mqtt": ${PAHO_MQTT_VERSION@Q} if ${IMAGE_PROFILE@Q} == "gateway" else None,
    },
    "provisioning_path": "/boot/firmware/edgewatch/bootstrap.env",
}
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY

printf 'Built %s\nManifest %s\nChecksum %s\n' \
  "$COMPRESSED_IMAGE" "$MANIFEST_PATH" "$COMPRESSED_IMAGE.sha256"

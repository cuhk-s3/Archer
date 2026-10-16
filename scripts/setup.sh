#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# shellcheck disable=SC1091
source "${PROJECT_DIR}/scripts/upenv.sh"
VEIR_DIR="${LAB_VEIR_DIR}"
ELAN_DIR="${ARCHER_ELAN_HOME}"
ELAN_BIN="${ARCHER_ELAN_BIN:-/root/.elan/bin/elan}"

mkdir -p "${ARCHER_DEPS_DIR}"
if [[ ! -d "${VEIR_DIR}/.git" ]]; then
  git clone --shared "${PROJECT_DIR}/../veir" "${VEIR_DIR}"
fi

TOOLCHAIN=$(tr -d '[:space:]' < "${VEIR_DIR}/lean-toolchain")
ELAN_HOME="${ELAN_DIR}" "${ELAN_BIN}" toolchain install "${TOOLCHAIN}"
LAKE=$(ELAN_HOME="${ELAN_DIR}" ELAN_TOOLCHAIN="${TOOLCHAIN}" \
  "${ELAN_BIN}" which lake)
"${LAKE}" --dir "${VEIR_DIR}" build veir-opt veir-interpret


# Build the pinned, reusable reviewer toolchain (LLVM/MLIR, Alive2, llrwt).
VEIR_REPO="${VEIR_DIR}"
TOOLS_ROOT="${ARCHER_REVIEWER_TOOLS_DIR}"
DOWNLOAD_DIR="${TOOLS_ROOT}/downloads"
SOURCE_DIR="${TOOLS_ROOT}/src"
RWENUM_COMMIT="${ARCHER_RWENUM_COMMIT:-3270989b462f7aa7e1c368e8fcddf9754a9b0acf}"
RWENUM_TAG="rwenum-${RWENUM_COMMIT:0:8}"
RWENUM_TREE="${TOOLS_ROOT}/${RWENUM_TAG}"
ELAN_BIN="${ARCHER_ELAN_BIN:-$(command -v elan || true)}"
LLVM_VERSION="22.1.8"
LLVM_SOURCE_SHA256="922f1817a0df7b1489272d18134ee0087a8b068828f87ac63b9861b1a9965888"
LLVM_ARCHIVE="${DOWNLOAD_DIR}/llvm-project-${LLVM_VERSION}.src.tar.xz"
LLVM_SOURCE="${SOURCE_DIR}/llvm-project-${LLVM_VERSION}"
LLVM_BUILD="${TOOLS_ROOT}/llvm-${LLVM_VERSION}-rtti"
LLVM_BINARY_SHA256="df0e1ecf16caf3489a272a5eea4eec9b0d82878f6477fa309504f918a0006384"
LLVM_BINARY_ARCHIVE="${DOWNLOAD_DIR}/LLVM-${LLVM_VERSION}-Linux-X64.tar.xz"
LLVM_RUNTIME="${TOOLS_ROOT}/llvm-${LLVM_VERSION}"
ALIVE2_COMMIT="${ARCHER_ALIVE2_COMMIT:-0dc2be5f04ccb61caebb909a610968cb2348f196}"
ALIVE2_SOURCE="${SOURCE_DIR}/alive2"
ALIVE2_BUILD="${TOOLS_ROOT}/alive2-${ALIVE2_COMMIT:0:8}"
BUILD_JOBS="${ARCHER_REVIEWER_BUILD_JOBS:-4}"

download_checked() {
  local url=$1 output=$2 digest=$3
  if [[ ! -f "${output}" ]]; then
    curl -fL --retry 3 --continue-at - -o "${output}" "${url}"
  fi
  printf '%s  %s\n' "${digest}" "${output}" | sha256sum -c -
}

if [[ ! -x "${ELAN_BIN}" ]]; then
  echo "error: elan was not found; set ARCHER_ELAN_BIN" >&2
  exit 1
fi
if [[ ! -d "${VEIR_REPO}/.git" && ! -f "${VEIR_REPO}/.git" ]]; then
  echo "error: VeIR repository not found at ${VEIR_REPO}" >&2
  exit 1
fi

for command in curl cmake ninja git sha256sum tar re2c pkg-config; do
  command -v "${command}" >/dev/null || {
    echo "error: required build tool is missing: ${command}" >&2
    exit 1
  }
done
Z3_INCLUDE_DIR=$(pkg-config --variable=includedir z3 2>/dev/null || true)
Z3_LIBRARY_DIR=$(pkg-config --variable=libdir z3 2>/dev/null || true)
Z3_LIBRARY="${Z3_LIBRARY_DIR}/libz3.so"
if [[ ! -f "${Z3_INCLUDE_DIR}/z3.h" || ! -f "${Z3_LIBRARY}" ]]; then
  echo "error: Z3 development files are required (pkg-config module: z3)" >&2
  exit 1
fi

mkdir -p "${TOOLS_ROOT}" "${DOWNLOAD_DIR}" "${SOURCE_DIR}"

download_checked \
  "https://github.com/llvm/llvm-project/releases/download/llvmorg-${LLVM_VERSION}/llvm-project-${LLVM_VERSION}.src.tar.xz" \
  "${LLVM_ARCHIVE}" "${LLVM_SOURCE_SHA256}"
download_checked \
  "https://github.com/llvm/llvm-project/releases/download/llvmorg-${LLVM_VERSION}/LLVM-${LLVM_VERSION}-Linux-X64.tar.xz" \
  "${LLVM_BINARY_ARCHIVE}" "${LLVM_BINARY_SHA256}"
if [[ ! -x "${LLVM_RUNTIME}/bin/mlir-opt" ]]; then
  mkdir -p "${LLVM_RUNTIME}"
  tar -xJf "${LLVM_BINARY_ARCHIVE}" --strip-components=1 -C "${LLVM_RUNTIME}"
fi
if [[ ! -f "${LLVM_SOURCE}/llvm/CMakeLists.txt" ]]; then
  mkdir -p "${LLVM_SOURCE}"
  tar -xJf "${LLVM_ARCHIVE}" --strip-components=1 -C "${LLVM_SOURCE}"
fi
cmake -S "${LLVM_SOURCE}/llvm" -B "${LLVM_BUILD}" -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_ENABLE_PROJECTS= \
  -DLLVM_TARGETS_TO_BUILD= \
  -DLLVM_ENABLE_RTTI=ON \
  -DLLVM_ENABLE_EH=ON \
  -DBUILD_SHARED_LIBS=ON \
  -DLLVM_BUILD_TESTS=OFF \
  -DLLVM_INCLUDE_TESTS=OFF \
  -DLLVM_INCLUDE_EXAMPLES=OFF \
  -DLLVM_INCLUDE_BENCHMARKS=OFF \
  -DLLVM_INCLUDE_DOCS=OFF \
  -DLLVM_ENABLE_TERMINFO=OFF \
  -DLLVM_ENABLE_ZSTD=OFF \
  -DLLVM_PARALLEL_LINK_JOBS=1
cmake --build "${LLVM_BUILD}" --target \
  LLVMSupport LLVMCore LLVMIRReader LLVMBitWriter LLVMAnalysis LLVMPasses \
  LLVMTransformUtils LLVMCodeGen LLVMTargetParser -j "${BUILD_JOBS}"

if [[ ! -d "${ALIVE2_SOURCE}/.git" ]]; then
  git clone https://github.com/AliveToolkit/alive2.git "${ALIVE2_SOURCE}"
fi
if ! git -C "${ALIVE2_SOURCE}" cat-file -e "${ALIVE2_COMMIT}^{commit}"; then
  git -C "${ALIVE2_SOURCE}" fetch origin "${ALIVE2_COMMIT}"
fi
git -C "${ALIVE2_SOURCE}" checkout --detach "${ALIVE2_COMMIT}"
cmake -S "${ALIVE2_SOURCE}" -B "${ALIVE2_BUILD}" -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TV=1 \
  -DCMAKE_PREFIX_PATH="${LLVM_BUILD}" \
  -DLLVM_DIR="${LLVM_BUILD}/lib/cmake/llvm" \
  -DZ3_INCLUDE_DIR="${Z3_INCLUDE_DIR}" \
  -DZ3_LIBRARIES="${Z3_LIBRARY}"
cmake --build "${ALIVE2_BUILD}" --target alive-tv -j "${BUILD_JOBS}"

git -C "${VEIR_REPO}" cat-file -e "${RWENUM_COMMIT}^{commit}"
if [[ ! -e "${RWENUM_TREE}/.git" ]]; then
  git -C "${VEIR_REPO}" worktree add --detach "${RWENUM_TREE}" "${RWENUM_COMMIT}"
fi

ACTUAL_COMMIT=$(git -C "${RWENUM_TREE}" rev-parse HEAD)
if [[ "${ACTUAL_COMMIT}" != "${RWENUM_COMMIT}" ]]; then
  echo "error: ${RWENUM_TREE} contains ${ACTUAL_COMMIT}, expected ${RWENUM_COMMIT}" >&2
  exit 1
fi

TOOLCHAIN=$(tr -d '[:space:]' < "${RWENUM_TREE}/lean-toolchain")
ELAN_HOME="${ELAN_DIR}" "${ELAN_BIN}" toolchain install "${TOOLCHAIN}"
LAKE=$(ELAN_HOME="${ELAN_DIR}" ELAN_TOOLCHAIN="${TOOLCHAIN}" \
  "${ELAN_BIN}" which lake)
if [[ ! -x "${LAKE}" ]]; then
  echo "error: lake was not installed at ${LAKE}" >&2
  exit 1
fi

ELAN_HOME="${ELAN_DIR}" "${LAKE}" --dir "${RWENUM_TREE}" build llrwt
LLRWT="${RWENUM_TREE}/.lake/build/bin/llrwt"
if [[ ! -x "${LLRWT}" ]]; then
  echo "error: llrwt build did not produce ${LLRWT}" >&2
  exit 1
fi

LLRWT_SHA256=$(sha256sum "${LLRWT}" | cut -d' ' -f1)
MLIR_OPT="${LLVM_RUNTIME}/bin/mlir-opt"
MLIR_TRANSLATE="${LLVM_RUNTIME}/bin/mlir-translate"
ALIVE_TV="${ALIVE2_BUILD}/alive-tv"
for executable in "${MLIR_OPT}" "${MLIR_TRANSLATE}" "${ALIVE_TV}"; do
  if [[ ! -x "${executable}" ]]; then
    echo "error: reviewer executable was not built: ${executable}" >&2
    exit 1
  fi
done
MLIR_OPT_SHA256=$(sha256sum "${MLIR_OPT}" | cut -d' ' -f1)
MLIR_TRANSLATE_SHA256=$(sha256sum "${MLIR_TRANSLATE}" | cut -d' ' -f1)
ALIVE_TV_SHA256=$(sha256sum "${ALIVE_TV}" | cut -d' ' -f1)
cat > "${TOOLS_ROOT}/manifest.json" <<EOF
{
  "rwenum_commit": "${RWENUM_COMMIT}",
  "lean_toolchain": "${TOOLCHAIN}",
  "llrwt": "${LLRWT}",
  "llrwt_sha256": "${LLRWT_SHA256}",
  "rwenum": "${PROJECT_DIR}/tools/vendor/rwenum.py",
  "llvm_version": "${LLVM_VERSION}",
  "llvm_source_sha256": "${LLVM_SOURCE_SHA256}",
  "llvm_binary_sha256": "${LLVM_BINARY_SHA256}",
  "mlir_opt": "${MLIR_OPT}",
  "mlir_opt_sha256": "${MLIR_OPT_SHA256}",
  "mlir_translate": "${MLIR_TRANSLATE}",
  "mlir_translate_sha256": "${MLIR_TRANSLATE_SHA256}",
  "alive2_commit": "${ALIVE2_COMMIT}",
  "alive_tv": "${ALIVE_TV}",
  "alive_tv_sha256": "${ALIVE_TV_SHA256}"
}
EOF
cat > "${TOOLS_ROOT}/environment.sh" <<EOF
export PATH='${LLVM_RUNTIME}/bin':\"\${PATH}\"
export ARCHER_LLRWT='${LLRWT}'
export ARCHER_RWENUM_ENGINE='${PROJECT_DIR}/tools/vendor/rwenum.py'
export ARCHER_RWT_VALIDATOR='${ALIVE_TV}'
EOF

echo "Reviewer tools are ready."
echo "source '${TOOLS_ROOT}/environment.sh'"


echo "VeIR and reviewer-tool environments are ready."
echo "For future shells: source ${PROJECT_DIR}/scripts/upenv.sh"


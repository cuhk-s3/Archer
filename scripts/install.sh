#! /bin/bash

set -o pipefail
set -e
set -x

#-=============================================================================
# This script is used to install the dependencies of llvm-autoreview.
#
# - LLVM: https://github.com/llvm/llvm-project
# - alive2: https://github.com/AliveToolkit/alive2
# - Required python dependencies: requirements.txt
#
# All the dependencies will be downloaded into the $LLVM_AUTOREVIEW_DEPS_DIR
# directory and install into the system. Therefore, this script requires
# the root permission When necessary, the source code will be kept.
#
# It will also create a virtual environment for Python3 dependencies.
#-=============================================================================


source "$(dirname $0)/deps.sh"
if [[ $? -ne 0 ]]; then
  exit 1
fi


#-================================
# LLVM
#-================================

mkdir ${DEP_LLVM_DIR}
git clone https://github.com/llvm/llvm-project ${DEP_LLVM_SOURCE_DIR}
git -C ${DEP_LLVM_SOURCE_DIR} checkout ${DEP_LLVM_VERSION}
cmake -S ${DEP_LLVM_SOURCE_DIR}/llvm -B ${DEP_LLVM_BUILD_DIR} -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_ENABLE_RTTI=ON \
  -DBUILD_SHARED_LIBS=ON \
  -DLLVM_ENABLE_ASSERTIONS=ON \
  -DLLVM_ENABLE_OCAMLDOC=OFF \
  -DLLVM_ABI_BREAKING_CHECKS=WITH_ASSERTS \
  -DLLVM_ENABLE_PROJECTS="llvm;clang"
ninja -C ${DEP_LLVM_BUILD_DIR}
sudo ninja -C ${DEP_LLVM_BUILD_DIR} install

#-================================
# alive2
#-================================

# Z3

mkdir -p ${DEP_Z3_DIR}
wget https://github.com/Z3Prover/z3/archive/refs/tags/z3-${DEP_Z3_VERSION}.zip -O ${DEP_Z3_DIR}/z3-${DEP_Z3_VERSION}.zip
unzip ${DEP_Z3_DIR}/z3-${DEP_Z3_VERSION}.zip -d ${DEP_Z3_DIR}
cmake -S ${DEP_Z3_SOURCE_DIR} -B ${DEP_Z3_BUILD_DIR} -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C ${DEP_Z3_BUILD_DIR}
sudo ninja -C ${DEP_Z3_BUILD_DIR} install

# re2c

mkdir -p ${DEP_RE2C_DIR}
wget https://github.com/skvadrik/re2c/releases/download/${DEP_RE2C_VERSION}/re2c-${DEP_RE2C_VERSION}.tar.xz -O ${DEP_RE2C_DIR}/re2c-${DEP_RE2C_VERSION}.tar.xz
tar -xavf ${DEP_RE2C_DIR}/re2c-${DEP_RE2C_VERSION}.tar.xz --directory ${DEP_RE2C_DIR}
cmake -S ${DEP_RE2C_SOURCE_DIR} -B ${DEP_RE2C_BUILD_DIR} -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C ${DEP_RE2C_BUILD_DIR}
sudo ninja -C ${DEP_RE2C_BUILD_DIR} install

# alive2

mkdir -p ${DEP_ALIVE2_DIR}
git clone -b ${DEP_ALIVE2_VERSION} --depth 1 https://github.com/AliveToolkit/alive2 ${DEP_ALIVE2_SOURCE_DIR}
cmake -S ${DEP_ALIVE2_SOURCE_DIR} -B ${DEP_ALIVE2_BUILD_DIR} -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C ${DEP_ALIVE2_BUILD_DIR}
cmake -S ${DEP_ALIVE2_SOURCE_DIR} -B ${DEP_ALIVE2_BUILD_DIR} -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=${DEP_LLVM_BUILD_DIR} -DBUILD_TV=1
ninja -C ${DEP_ALIVE2_BUILD_DIR}
sudo ninja -C ${DEP_ALIVE2_BUILD_DIR} install

#-================================
# llvm-ub-aware-interpreter (llubi)
#-================================

mkdir -p ${DEP_LLUBI_DIR}
git clone https://github.com/dtcxzyw/llvm-ub-aware-interpreter ${DEP_LLUBI_SOURCE_DIR}
cmake -S ${DEP_LLUBI_SOURCE_DIR} -B ${DEP_LLUBI_BUILD_DIR} -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_DIR=${DEP_LLVM_BUILD_DIR}/lib/cmake/llvm
ninja -C ${DEP_LLUBI_BUILD_DIR}

# ccache

mkdir -p ${DEP_CCACHE_DIR}
wget https://github.com/ccache/ccache/releases/download/v${DEP_CCACHE_VERSION}/ccache-${DEP_CCACHE_VERSION}.tar.gz -O ${DEP_CCACHE_DIR}/ccache-${DEP_CCACHE_VERSION}.tar.gz
tar -xavf ${DEP_CCACHE_DIR}/ccache-${DEP_CCACHE_VERSION}.tar.gz --directory ${DEP_CCACHE_DIR}
cmake -S ${DEP_CCACHE_SOURCE_DIR} -B ${DEP_CCACHE_BUILD_DIR} -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C ${DEP_CCACHE_BUILD_DIR}
sudo ninja -C ${DEP_CCACHE_BUILD_DIR} install

#-================================
# Python dependencies
#-================================

# We assume that the python3 executable is available in the PATH.
PYTHON3=python${DEP_PY3_VERSION}
if ! command -v ${PYTHON3} > /dev/null 2>&1; then
  echo "Error: Python ${DEP_PY3_VERSION} is not installed. We require the version as your GDB is reliant on it. Please install it first."
  exit 1
fi
${PYTHON3} -m venv ${DEP_PY3_VENV_DIR}


#-================================
# Cleanup dependencies
#-================================

rm -rf ${DEP_LLVM_BUILD_DIR} \
  ${DEP_Z3_DIR} \
  ${DEP_RE2C_DIR} \
  ${DEP_CCACHE_DIR}
git -C ${DEP_LLVM_SOURCE_DIR} checkout main

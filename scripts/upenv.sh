#! /bin/bash

#-=============================================================================
# This script is used to bring up the llvm-autoreview's environment.
# Note that, this script requires the dependencies to be installed first.
# Additionally, it should be sourced instead of executed.
# Lastly, this script should be sourced each time a new terminal is opened.
#-=============================================================================

# We are a sourced script, so we cannot use $(dirname $0) directly.
if [[ -n $ZSH_VERSION ]]; then
  LLVM_AUTOREVIEW_SCRIPT_DIR=$(cd $(dirname "${(%):-%N}"); pwd)
elif [[ -n $BASH_VERSION ]]; then
  LLVM_AUTOREVIEW_SCRIPT_DIR=$(cd $(dirname "${BASH_SOURCE[0]}"); pwd)
else
  echo "Error: Unsupported shell. Please use bash or zsh."
  return 1
fi

source ${LLVM_AUTOREVIEW_SCRIPT_DIR}/deps.sh
if [[ $? -ne 0 ]]; then
  return 1
fi

export LLVM_AUTOREVIEW_HOME_DIR=$(cd ${LLVM_AUTOREVIEW_SCRIPT_DIR}/..; pwd)
export LLVM_AUTOREVIEW_BUILD_DIR=$LLVM_AUTOREVIEW_HOME_DIR/build

#-================================
# llvm
#-================================

GIT_SAFE_DIRS=$(git config --global --get-all safe.directory | tr '\n' ' ')
if [[ ! " ${GIT_SAFE_DIRS[@]} " =~ " ${DEP_LLVM_SOURCE_DIR} " ]]; then
  echo "Adding ${DEP_LLVM_SOURCE_DIR} to git safe directories."
  # Add this since we might be running the script in a container of a different user
  git config --global --add safe.directory ${DEP_LLVM_SOURCE_DIR}
fi

export LAB_LLVM_DIR=$DEP_LLVM_SOURCE_DIR
if [[ ! -d $LAB_LLVM_DIR ]]; then
  echo "Error: LLVM's source tree does not exist at $LAB_LLVM_DIR."
  return 1
fi

export LAB_LLVM_BUILD_DIR=$LLVM_AUTOREVIEW_BUILD_DIR/llvm-build
if [[ ! -d $LAB_LLVM_BUILD_DIR ]]; then
  echo "Creating LLVM build directory at $LAB_LLVM_BUILD_DIR"
  mkdir -p $LAB_LLVM_BUILD_DIR
fi

export LAB_LLVM_ALIVE_TV=$(which alive-tv)
if [[ $LAB_LLVM_ALIVE_TV == "alive-tv not found" ]]; then
  echo "Error: alive-tv does not exist."
  return 1
fi

export LAB_DATASET_DIR=$LLVM_AUTOREVIEW_HOME_DIR/dataset
if [[ ! -d $LAB_DATASET_DIR ]]; then
  echo "Error: dataset directory does not exist at $LAB_DATASET_DIR"
  return 1
fi

source ${LLVM_AUTOREVIEW_HOME_DIR}/environments

#-================================
# Python
#-================================

source ${DEP_PY3_VENV_DIR}/bin/activate
pip install -r ${LLVM_AUTOREVIEW_HOME_DIR}/requirements.txt

export PYTHONPATH=$LLVM_AUTOREVIEW_HOME_DIR:$DEP_PY3_VENV_DIR/lib/python${DEP_PY3_VERSION}/site-packages:$PYTHONPATH

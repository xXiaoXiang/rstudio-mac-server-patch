#!/bin/bash

USER=$(whoami)
# echo "USERNAME in rsession.sh is: $USER"
# 从文件读取 Conda 环境路径
CONDA_ENV_PATH=$(cat /tmp/rstudio-server/${USER}/UUID_TO_REPLACE_STR/current_env)
# echo "## Activating Conda env: ${CONDA_ENV_PATH}"
CONDA_ROOT_PATH="${CONDA_ENV_PATH%/envs/*}"

source ${CONDA_ROOT_PATH}/etc/profile.d/mamba.sh && mamba init > /dev/null
mamba activate "$CONDA_ENV_PATH"

# 设置 Python 路径
[ -f "$CONDA_ENV_PATH/bin/python" ] && export RETICULATE_PYTHON="$CONDA_ENV_PATH/bin/python"

# 启动 RStudio rsession
/usr/lib/rstudio-server/bin/rsession --r-libs-user="${CONDA_ENV_PATH}/lib/R/library" \
  "$@"

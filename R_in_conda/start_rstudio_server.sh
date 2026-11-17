#!/bin/bash

PORT="$1"
CONDA_ENV_PATH="$2"
ROOT_PATH="$3"
USERNAME="$4"
UUID="$5"

if [ -z "$PORT" ] || [ -z "$CONDA_ENV_PATH" ] || [ -z "$ROOT_PATH" ] || [ -z "$USERNAME" ] || [ -z "$UUID" ]; then
    echo "Usage: $0 <PORT> <CONDA_ENV_PATH> <WWW_ROOT_PATH> <USERNAME> <UUID>"
    exit 1
fi

CWD="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

CONDA_ROOT_PATH="${CONDA_ENV_PATH%/envs/*}"

# 设置目录
DATA_DIR="/tmp/rstudio-server/${USERNAME}/${UUID}"
DATABASE_DIR="/tmp/rstudio-server/${USERNAME}/${UUID}/database"

mkdir -p "$DATA_DIR" "$DATABASE_DIR"
chown -R $USERNAME:$USERNAME "$DATA_DIR" "$DATABASE_DIR"

# secure cookie
COOKIE_KEY_PATH=/tmp/rstudio-server/${USERNAME}/${UUID}/secure-cookie-key
rm -f "$COOKIE_KEY_PATH"
mkdir -p "$(dirname $COOKIE_KEY_PATH)"
python3 -c 'import uuid; print(uuid.uuid4())' > "$COOKIE_KEY_PATH"
sudo -u $USERNAME chmod 600 "/tmp/rstudio-server/${USERNAME}/${UUID}"

# revocation list (for rserver >= 1.3)
if [ $(sed -n '/^1.3./p;q' /usr/lib/rstudio-server/VERSION) ] ;
then
  REVOCATION_LIST_DIR=/tmp/rstudio-server/${USERNAME}/${UUID}/revocation-list-dir
  mkdir -p "$REVOCATION_LIST_DIR"
  REVOCATION_LIST_PAR="--auth-revocation-list-dir=$REVOCATION_LIST_DIR"
else
  REVOCATION_LIST_PAR=""
fi

# 记录当前用户选择的 Conda 环境路径
CONDA_ENV_FILE=/tmp/rstudio-server/${USERNAME}/${UUID}/current_env
rm -f "$CONDA_ENV_FILE"
echo "$CONDA_ENV_PATH" > "$CONDA_ENV_FILE"

# RETICULATE 用的 Python
export RETICULATE_PYTHON="$CONDA_ENV_PATH/bin/python"


# 修改 database.conf 路径
rm -f /tmp/rstudio-server/${USERNAME}/${UUID}/database.conf
cp $CWD/database.conf /tmp/rstudio-server/${USERNAME}/${UUID}/database.conf
sed -i "s|directory=.*|directory=$DATABASE_DIR|" "/tmp/rstudio-server/${USERNAME}/${UUID}/database.conf"

# RSession脚本准备
rm -f /tmp/rstudio-server/${USERNAME}/${UUID}/rsession.sh
cp $CWD/rsession.sh /tmp/rstudio-server/${USERNAME}/${UUID}/rsession.sh
# Replace UUID_TO_REPLACE_STR with actual UUID in resession.sh
sed -i "s/UUID_TO_REPLACE_STR/${UUID}/g" /tmp/rstudio-server/${USERNAME}/${UUID}/rsession.sh

# Chown of all files to the user
chown -R $USERNAME:$USERNAME /tmp/rstudio-server/${USERNAME}

# Conda init
#sudo -u $USERNAME bash -c "source ${CONDA_ROOT_PATH}/etc/profile.d/conda.sh && conda init"


# 启动 rserver
sudo -u $USERNAME /usr/lib/rstudio-server/bin/rserver --server-daemonize=0 \
  --www-port="${PORT}" \
  --www-root-path="${ROOT_PATH}" \
  --rsession-path="/tmp/rstudio-server/${USERNAME}/${UUID}/rsession.sh" \
  --secure-cookie-key-file="${COOKIE_KEY_PATH}" \
  --server-pid-file="/tmp/rstudio-server/${USERNAME}/${UUID}/rserver.pid" \
  --server-data-dir="/tmp/rstudio-server/${USERNAME}/${UUID}" \
  --rsession-which-r="${CONDA_ENV_PATH}/bin/R" \
  --rsession-ld-library-path="${CONDA_ENV_PATH}/lib" \
  --server-user "${USERNAME}" \
  --database-config-file "/tmp/rstudio-server/${USERNAME}/${UUID}/database.conf" \
  --www-address=127.0.0.1 \
  --auth-minimum-user-id=1000 \
  --auth-none=1 \
  $REVOCATION_LIST_PAR > /tmp/rstudio-server/${USERNAME}/${UUID}/rserver.log 2>&1

 
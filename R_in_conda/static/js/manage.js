document.addEventListener("DOMContentLoaded", () => {
    loadUserInfo();
    loadEnvs();
    loadSessions();

    document.getElementById("create-env-btn").onclick = () => {
        const envName = document.getElementById("new-env-name").value.trim();
        const channel = document.getElementById("new-env-channel").value.trim();
        const packages = document.getElementById("new-env-packages").value.trim();
        if (!envName) return alert("请输入环境名称");
        // 检查envName是否已存在
        const envCards = Array.from(document.querySelectorAll("#envList .envs-card .envs-name strong"));
        const matchCard = envCards.find(card => card.textContent === envName);
        if (matchCard) {
            // 高亮闪烁并滚动到对应卡片
            const cardDiv = matchCard.closest('.envs-card');
            cardDiv.scrollIntoView({behavior: 'smooth', block: 'center'});
            cardDiv.classList.add('highlight-flash');
            setTimeout(() => cardDiv.classList.remove('highlight-flash'), 900);
            return;
        }
        const createBtn = document.getElementById("create-env-btn");
        setButtonSpinner(createBtn, true);
        fetch("/api/create_env", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                env_name: envName,
                channel: channel || "conda-forge",
                packages: packages
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                setButtonSpinner(createBtn, false, "Create");
                loadEnvs();
            } else {
                setButtonSpinner(createBtn, false, "Create");
                alert(data.message || "创建失败");
            }
        });
    };

    // AutoRefresh logic for all dynamic sections
    let autoRefreshTimer = null;
    const autoRefreshCheckbox = document.getElementById("autoRefreshSessions");
    function refreshAll() {
        loadUserInfo();
        loadEnvs();
        loadSessions();
    }
    function startAutoRefresh() {
        if (autoRefreshTimer) clearInterval(autoRefreshTimer);
        autoRefreshTimer = setInterval(() => {
            if (autoRefreshCheckbox.checked) {
                refreshAll();
            }
        }, 15000);
    }
    autoRefreshCheckbox.addEventListener("change", () => {
        if (autoRefreshCheckbox.checked) {
            refreshAll();
            startAutoRefresh();
        } else {
            if (autoRefreshTimer) clearInterval(autoRefreshTimer);
        }
    });
    startAutoRefresh();
});

function loadUserInfo() {
    fetch("/api/root_user_info")
        .then(res => res.json())
        .then(data => {
            document.getElementById("totalUsers").textContent = data.total_users;
            document.getElementById("totalSessions").textContent = data.total_sessions;
        });
}

function loadEnvs() {
    fetch("/api/envs")
        .then(res => res.json())
        .then(data => {
            const envList = document.getElementById("envList");
            envList.innerHTML = "";
            if (!data.success) {
                envList.innerHTML = `<p style="color:red;">Failed to load envs: ${data.message || ""}</p>`;
                return;
            }
            data.envs.forEach(env => {
                const envCard = document.createElement("div");
                envCard.classList.add("envs-card");
                envCard.innerHTML = `
                    <div class="envs-info">
                        <div class="envs-name"><strong>${env.env_name}</strong></div>
                        <div class="envs-vers">
                            ${env.r_version && env.r_version !== "-" ? `R: ${env.r_version}` : ""}
                            ${env.r_version && env.r_version !== "-" && env.py_version && env.py_version !== "-" ? " | " : ""}
                            ${env.py_version && env.py_version !== "-" ? `Python: ${env.py_version}` : ""}
                        </div>
                    </div>
                    <div class="envs-action">
                        <button onclick="deleteEnv('${env.env_name}')">Delete</button>
                    </div>
                `;
                envList.appendChild(envCard);
            });
        })
        .catch(err => {
            document.getElementById("envList").innerHTML = `<p style="color:red;">Failed to load envs</p>`;
        });
}

function deleteEnv(envName) {
    if (!confirm(`确定要删除环境 ${envName} 吗？`)) return;
    const btn = event.target;
    setButtonSpinner(btn, true);
    // 先刷新sessions并检查是否有用户占用该环境
    fetch("/api/all_sessions")
        .then(res => res.json())
        .then(data => {
            if (data.success && Array.isArray(data.sessions)) {
                const occupied = data.sessions.some(sess => sess.env === envName);
                if (occupied) {
                    alert(`该环境正在被用户占用，无法删除！`);
                    setButtonSpinner(btn, false, "Delete");
                    return;
                }
            }
            // 没有用户占用才允许删除
            fetch("/api/delete_env", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({env_name: envName})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    loadEnvs();
                    setButtonSpinner(btn, false, "Delete");
                } else {
                    alert(data.message || "删除失败");
                    setButtonSpinner(btn, false, "Delete");
                }
            });
        })
        .catch(() => {
            alert("无法获取会话信息，删除操作已取消。");
            setButtonSpinner(btn, false, "Delete");
        });
}

function loadSessions() {
    fetch("/api/all_sessions")
        .then(res => res.json())
        .then(data => {
            const sessionList = document.getElementById("sessionList");
            sessionList.innerHTML = "";
            if (!data.success || !data.sessions || data.sessions.length === 0) {
                sessionList.innerHTML = `<p>No active sessions</p>`;
                return;
            }
            data.sessions.forEach(sess => {
                const sessCard = document.createElement("div");
                sessCard.classList.add("session-card");
                let portColor = '#4CAF50'; // idle绿色
                if (sess.linked === 'busy') {
                    portColor = '#FF9800'; // busy橘红色
                } else if (sess.linked === 'dead') {
                    portColor = '#f44336'; // dead红色
                }
                sessCard.innerHTML = `
                    <div class="session-card-inner">
                        <div class="status-strip ${sess.status === 'running' ? 'status-running' : 'status-stopped'}"></div>
                        <div class="session-content">
                            <div class="session-info">
                                <div class="session-info-line">
                                    <span class="session-env"><strong>User: ${sess.username}</strong></span>
                                    <span class="session-env"><strong>Env: ${sess.env}</strong></span>
                                    <span>Status: <span class="status" style="color: ${sess.status === 'running' ? '#4CAF50' : '#f44336'}">${sess.status}</span></span>
                                </div>
                                <div class="session-info-line">
                                    <span class="session-port">Port: <span style="color: ${portColor}">${sess.port}</span></span>
                                    <span class="session-time">Created: ${sess.timestamp}</span>
                                </div>
                                <div class="session-info-line">
                                    <span>UUID: ${sess.session_id}</span>
                                </div>
                                <div class="session-info-line">
                                    <span>PIDs: ${Array.isArray(sess.pids) && sess.pids.length > 0 ? sess.pids.join(", ") : "-"}</span>
                                    <span>CPU: ${sess.cpu_total !== undefined && sess.cpu_total !== null ? sess.cpu_total : "-"}%</span>
                                    <span>Total Mem: ${sess.mem_total !== undefined && sess.mem_total !== null ? sess.mem_total : "-"}MB</span>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
                sessionList.appendChild(sessCard);
            });
        })
        .catch(err => {
            document.getElementById("sessionList").innerHTML = `<p style="color:red;">Failed to load sessions</p>`;
        });
}

function setButtonSpinner(btn, show = true, text = "") {
    if (show) {
        btn.innerHTML = '<span class="spinner"></span>';
        btn.disabled = true;
    } else {
        btn.innerHTML = text;
        btn.disabled = false;
    }
}
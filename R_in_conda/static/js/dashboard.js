document.addEventListener("DOMContentLoaded", function () {
    loadCondaEnvs();
    loadSessions();
});

function loadCondaEnvs() {
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
                        <button onclick="startSession('${env.env_path}')">Start</button>
                    </div>
                `;
                envList.appendChild(envCard);
            });
        })
        .catch(err => {
            console.error("Error loading envs:", err);
            document.getElementById("envList").innerHTML = `<p style="color:red;">Failed to load envs</p>`;
        });
}

function loadSessions() {
    fetch("/api/sessions")
        .then(res => res.json())
        .then(data => {
            const sessionList = document.getElementById("sessionList");
            const activeCount = document.getElementById("activeCount");
            activeCount.textContent = data.sessions.length;
            sessionList.innerHTML = "";

            if (data.sessions.length === 0) {
                sessionList.innerHTML = `<p>No active sessions</p>`;
                return;
            }

            Object.values(data.sessions).forEach(sess => {
                const sessCard = document.createElement("div");
                sessCard.classList.add("session-card");
                
                const actionsHtml = sess.status === "running"
                    ? `<button onclick="stopSession('${sess.session_id}')">Stop</button>
                       <button onclick="window.open('${sess.url}/', '_blank')">Open</button>`
                    : `<button onclick="restartSession('${sess.session_id}', '${sess.env}')">Restart</button>`;

                    let portColor = '#4CAF50'; // 默认绿色
                    if (sess.linked === 'busy') {
                        portColor = '#FF9800'; // 橘红色
                    } else if (sess.linked === 'dead') {
                        portColor = '#f44336'; // 红色
                    }
                    sessCard.innerHTML = `
                        <div class="session-card-inner">
                            <div class="status-strip ${sess.status === 'running' ? 'status-running' : 'status-stopped'}"></div>
                            <div class="session-content">
                                <div class="session-info">
                                    <div class="session-info-line">
                                        <span class="session-env"><strong>Env: ${sess.env}</strong></span>
                                        <span>Status: <span class="status" style="color: ${sess.status === 'running' ? '#4CAF50' : '#f44336'}">${sess.status}</span></span>
                                    </div>
                                    <div class="session-info-line">
                                        <span>Port: <span class="status" style="color: ${portColor}">${sess.port}</span></span>
                                        <span class="session-time">Created: ${sess.timestamp}</span>
                                    </div>
                                </div>
                                <div class="session-actions">
                                    ${actionsHtml}
                                    <button onclick="deleteSession('${sess.session_id}')">Delete</button>
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

function startSession(env_path) {
    fetch("/api/start_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ env_path: env_path})
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            setTimeout(() => {
                loadSessions();  // 刷新 session 列表
            }, 1000);
        } else {
            alert("Failed to start session: " + data.message);
        }
    });
}

function restartSession(session_id, env_path) {
    fetch("/api/restart_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session_id, env_path: env_path })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            setTimeout(() => {
                loadSessions();  // 刷新 session 列表
            }, 1000);
        } else {
            alert("Failed to restart session: " + data.message);
        }
    })
    .catch(err => {
        alert("Error restarting session: " + err);
    });
}

function stopSession(session_id) {
    fetch("/api/stop_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session_id })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            setTimeout(() => {
                loadSessions();  // 刷新 session 列表
            }, 1000);
        } else {
            alert("Failed to stop session: " + data.message);
        }
    })
    .catch(err => {
        alert("Error stopping session: " + err);
    });
}

function deleteSession(session_id) {
    fetch("/api/delete_session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session_id })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            setTimeout(() => {
                loadSessions();  // 刷新 session 列表
            }, 1000);
        } else {
            alert("Failed to delete session: " + data.message);
        }
    })
    .catch(err => {
        alert("Error deleting session: " + err);
    });
}
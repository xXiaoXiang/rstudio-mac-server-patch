import os
import re
import json
import pam
import socket
import time
import random
import subprocess
import psutil
from uuid import uuid4
import requests
from datetime import timedelta, datetime
from urllib.parse import quote, unquote, urlparse, urlencode
from flask import Flask, render_template, request, redirect, session, url_for, Response, jsonify, abort
from functools import wraps, lru_cache
from werkzeug.middleware.proxy_fix import ProxyFix
from threading import Lock
from collections import defaultdict


app = Flask(__name__)
app.secret_key = os.environ["CONDA_R_FLASK_SECRET_KEY"]
app.permanent_session_lifetime = timedelta(minutes=120)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


app.config.update(
    SESSION_COOKIE_SECURE=_env_bool("SESSION_COOKIE_SECURE", False),
    SESSION_COOKIE_SAMESITE='Lax'
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

pam_auth = pam.pam()

# ===== 🚀 性能优化层 =====
# 缓存系统：减少 session 文件 I/O
_session_cache = {}  # {username: (timestamp, sessions_data)}
_session_cache_lock = Lock()
_session_cache_ttl = 2  # 缓存 2 秒

# 缓存端口连接状态：减少 socket 连接尝试
_port_status_cache = {}  # {port: (timestamp, is_alive)}
_port_status_lock = Lock()
_port_status_ttl = 1  # 缓存 1 秒

# netstat 结果缓存：避免重复系统调用
_netstat_cache = (0, {})  # (timestamp, {port: busy})
_netstat_lock = Lock()
_netstat_ttl = 2

def _get_netstat_established_ports():
    """
    执行一次 netstat，缓存所有 ESTABLISHED 连接
    返回: {port: "busy"}
    """
    global _netstat_cache
    
    now = time.time()
    cache_time, cache_data = _netstat_cache
    
    # 如果缓存未过期，使用缓存
    if now - cache_time < _netstat_ttl:
        return cache_data
    
    with _netstat_lock:
        # 再检查一次（避免竞态条件）
        now = time.time()
        cache_time, cache_data = _netstat_cache
        if now - cache_time < _netstat_ttl:
            return cache_data
        
        # 执行 netstat
        try:
            netstat = subprocess.run(
                ["netstat", "-tn"], 
                capture_output=True, text=True, timeout=2, check=True
            )
            busy_ports = {}
            for line in netstat.stdout.splitlines():
                if "ESTABLISHED" in line:
                    parts = line.split()
                    # 提取本地地址的端口
                    try:
                        local = parts[3]  # 格式: 127.0.0.1:PORT
                        port = int(local.split(':')[-1])
                        busy_ports[port] = "busy"
                    except (IndexError, ValueError):
                        continue
            _netstat_cache = (now, busy_ports)
            return busy_ports
        except Exception as e:
            # netstat 失败时，返回空（保守策略）
            _netstat_cache = (now, {})
            return {}

def _cached_load_sessions(username):
    """
    缓存 session 加载，减少磁盘 I/O
    """
    global _session_cache
    
    now = time.time()
    
    # 检查缓存
    if username in _session_cache:
        cache_time, cache_data = _session_cache[username]
        if now - cache_time < _session_cache_ttl:
            return cache_data
    
    with _session_cache_lock:
        # 再检查一次
        if username in _session_cache:
            cache_time, cache_data = _session_cache[username]
            if now - cache_time < _session_cache_ttl:
                return cache_data
        
        # 加载 session
        sessions = load_sessions(username)
        _session_cache[username] = (now, sessions)
        return sessions

def _cached_check_port_alive(port, username=None):
    """
    缓存端口连接状态检查
    """
    global _port_status_cache
    
    now = time.time()
    
    # 检查缓存
    if port in _port_status_cache:
        cache_time, is_alive = _port_status_cache[port]
        if now - cache_time < _port_status_ttl:
            return is_alive
    
    # 执行检查
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)  # 超时 500ms
            result = sock.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        result = False
    
    with _port_status_lock:
        _port_status_cache[port] = (now, result)
    
    return result

# 缓存清理：每次 session 修改时清除相关缓存
def _invalidate_session_cache(username):
    """清除特定用户的 session 缓存"""
    global _session_cache
    if username in _session_cache:
        del _session_cache[username]

def _invalidate_port_cache(port):
    """清除特定端口的缓存"""
    global _port_status_cache
    if port in _port_status_cache:
        del _port_status_cache[port]

def get_all_used_ports():
    """遍历所有用户的 session 文件，返回已使用的端口集合"""
    used_ports = set()
    if os.path.exists(SESSION_DIR):
        for f in os.listdir(SESSION_DIR):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(SESSION_DIR, f), "r") as ff:
                        sessions = json.load(ff)
                        for s in sessions:
                            port = s.get("port")
                            if port:
                                used_ports.add(port)
                except Exception:
                    continue
    return used_ports

# 随机生成一个未占用端口
def get_free_port():
    used_ports = get_all_used_ports()
    while True:
        port = random.randint(8801, 10024)
        if port in used_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port

def wait_for_port(port, host='127.0.0.1', timeout=30):
    """等待端口监听"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.5)
    return False

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            next_url = request.full_path
            if next_url.endswith("?"):
                next_url = next_url[:-1]
            # 重定向到 login，并带上 next 参数
            return redirect(url_for("login", next=next_url))
        
        last_active = session.get("last_active")
        if last_active:
            last_active = datetime.fromisoformat(last_active)
            if datetime.utcnow() - last_active > app.permanent_session_lifetime:
                # 会话超时
                next_url = request.full_path
                if next_url.endswith("?"):
                    next_url = next_url[:-1]
                session.clear()
                return redirect(url_for("login", next=next_url))
        
        session["last_active"] = datetime.utcnow().isoformat()
        return f(*args, **kwargs)
    return decorated_function

@app.route("/", methods=["GET"])
def root():
    if "username" in session:
        return redirect(url_for("dashboard"))
    else:
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    # 如果已登录且是直接访问 /login（没有 next 参数）
    if "username" in session and not request.args.get("next"):
        return redirect(url_for("dashboard"))
    return render_template("login.html", error=None)

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    stay_signed_in = bool(data.get("staySignedIn"))
    next_url = data.get("next") or "/dashboard"

    if not username or not password:
        return jsonify({"success": False, "message": "缺少用户名或密码"}), 400

    if pam_auth.authenticate(username, password):
        session["username"] = username
        session["last_active"] = datetime.utcnow().isoformat()
        session.permanent = stay_signed_in
        # root用户登录后跳转到/manage
        if username == "root":
            next_url = "/manage"
        return jsonify({"success": True, "message": "登录成功", "redirect": next_url})
    else:
        return jsonify({"success": False, "message": "用户名或密码错误"}), 401

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    username = session["username"]
    return render_template("dashboard.html", username=username)

@app.route("/api/envs", methods=["GET"])
@login_required
def get_envs():
    username = session["username"]
    envs = []
    try:
        result = subprocess.run(
            ["mamba", "env", "list", "--json"],
            capture_output=True, text=True, check=True
        )
        envs_data = json.loads(result.stdout)
        for env in envs_data.get("envs", []):
            if os.path.exists(env) and os.path.basename(env) != "conda":
                env_info = {
                    "env_name": os.path.basename(env),
                    "env_path": env,
                    "py_version": None,
                    "r_version": None
                }
                # 获取 Python 版本
                py_path = os.path.join(env, "bin", "python")
                if os.path.exists(py_path):
                    try:
                        py_result = subprocess.run(
                            [py_path, "--version"],
                            capture_output=True, text=True, check=True
                        )
                        match = re.search(r"\d+(\.\d+)+", py_result.stdout or py_result.stderr)
                        env_info["py_version"] = match.group(0) if match else "Unknown"
                    except subprocess.CalledProcessError:
                        env_info["py_version"] = "Error reading version"
                else:
                    env_info["py_version"] = "-"

                # 获取 R 版本
                r_path = os.path.join(env, "bin", "R")
                if os.path.exists(r_path):
                    try:
                        r_result = subprocess.run(
                            [r_path, "--version"],
                            capture_output=True, text=True, check=True
                        )
                        first_line = r_result.stdout.strip() or r_result.stderr.strip()
                        first_line = first_line.split("\n")[0].split(" (")[0]
                        match = re.search(r"\d+(\.\d+)+", first_line)
                        env_info["r_version"] = match.group(0) if match else "Unknown"
                    except subprocess.CalledProcessError:
                        env_info["r_version"] = "Error reading version"
                else:
                    env_info["r_version"] = "-"

                envs.append(env_info)

    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": f"获取环境列表失败: {e}"}), 500

    return jsonify({"success": True, "envs": envs})

SESSION_DIR = "/tmp/rstudio-server"
os.makedirs(SESSION_DIR, exist_ok=True)
os.chmod(SESSION_DIR, 0o777)

def save_sessions(username, sessions):
    user_file = os.path.join(SESSION_DIR, f"{username}.json")
    with open(user_file, "w") as f:
        json.dump(sessions, f)
    # 🚀 清除缓存，下次请求会重新加载
    _invalidate_session_cache(username)

def load_sessions(username):
    user_file = os.path.join(SESSION_DIR, f"{username}.json")
    if os.path.exists(user_file):
        try:
            with open(user_file, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def launch_session(username, env_path, session_id=None):
    """创建或重启 session，如果 session_id 存在，则复用端口并保持顺序"""
    sessions = load_sessions(username)

    # 如果是新 session
    if not session_id:
        session_id = str(uuid4())
        port = get_free_port()

        # 新建并追加
        new_session = {
            "session_id": session_id,
            "env": env_path,
            "port": port,
            "status": "running",
            "url": f"/{username}/rstudio-{port}",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        sessions.append(new_session)

    else:
        # 重启 session
        matched = None
        for s in sessions:
            if s["session_id"] == session_id:
                matched = s
                break

        if matched:
            port = matched["port"]
            matched["env"] = env_path
            matched["status"] = "running"
            matched["url"] = f"/{username}/rstudio-{port}"
            matched["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            # 如果没找到旧的，就当新建
            port = get_free_port()
            new_session = {
                "session_id": session_id,
                "env": env_path,
                "port": port,
                "status": "running",
                "url": f"/{username}/rstudio-{port}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            sessions.append(new_session)

    # 启动 subprocess（无论新建还是重启）
    base_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(base_dir, "start_rstudio_server.sh")
    subprocess.Popen([
        script_path,
        str(port),
        env_path,
        f"/{username}/rstudio-{port}",
        username,
        session_id
    ])

    save_sessions(username, sessions)

    # 返回当前 session 信息
    return next(s for s in sessions if s["session_id"] == session_id)

def close_session(session):
    """
    关闭 session 的进程，并返回是否找到运行的进程。
    session: dict, 至少包含 "port" 和 "status"
    """
    port = session["port"]
    killed = False
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if cmdline and str(port) in " ".join(cmdline):
                proc.kill()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    session["status"] = "stopped"
    # 🚀 清除端口缓存
    _invalidate_port_cache(port)
    return killed, session

@app.route("/api/start_session", methods=["POST"])
@login_required
def start_session():
    data = request.json
    username = session.get("username")
    env_path = data.get("env_path", "").strip()
    new_session = launch_session(username, env_path)
    return jsonify({"success": True, **new_session})

@app.route("/api/restart_session", methods=["POST"])
@login_required
def restart_session():
    data = request.json
    env_path = data.get("env_path", "").strip()
    session_id = data.get("session_id")
    username = session.get("username")
    if not session_id:
        return jsonify({"success": False, "message": "Missing session_id"}), 400
    new_session = launch_session(username, env_path, session_id=session_id)
    return jsonify({"success": True, **new_session})

@app.route("/api/stop_session", methods=["POST"])
@login_required
def stop_session():
    data = request.json
    session_id = data.get("session_id")
    username = session.get("username")
    if not session_id:
        return jsonify({"success": False, "message": "Missing session_id"}), 400

    sessions = load_sessions(username)
    matched = next((s for s in sessions if s["session_id"] == session_id), None)
    if not matched:
        return jsonify({"success": False, "message": "Session not found"}), 404

    port = matched["port"]

    killed, session_closed = close_session(matched)
    if killed:
        sessions = [s for s in sessions if s["session_id"] != session_id]
        sessions.append(session_closed)
    
    save_sessions(username, sessions)

    if killed:
        return jsonify({"success": True, "message": f"Session {session_id} stopped"})
    else:
        return jsonify({"success": True, "message": f"No running process found for session {session_id}"})

@app.route("/api/delete_session", methods=["POST"])
@login_required
def delete_session():
    data = request.json
    session_id = data.get("session_id")
    username = session.get("username")
    if not session_id:
        return jsonify({"success": False, "message": "Missing session_id"}), 400

    

    sessions = load_sessions(username)
    matched = next((s for s in sessions if s["session_id"] == session_id), None)
    if not matched:
        return jsonify({"success": False, "message": "Session not found"}), 404

    # 先关闭 session 进程
    close_session(matched)

    # 删除 session
    sessions = [s for s in sessions if s["session_id"] != session_id]
    save_sessions(username, sessions)

    return jsonify({"success": True, "message": f"Session {session_id} deleted"})

@app.route("/api/sessions", methods=["GET"])
@login_required
def get_sessions():
    username = session.get("username")
    sessions = _cached_load_sessions(username)

    # 🚀 优化：只执行一次 netstat，而不是为每个 session 执行
    busy_ports = _get_netstat_established_ports()

    # 检查 port 是否存活
    for s in sessions:
        port = s["port"]
        port_alive = _cached_check_port_alive(port, username)
        
        if port_alive:
            s["status"] = "running"
            # 直接从缓存的 netstat 结果中查找
            s["linked"] = "busy" if port in busy_ports else "idle"
        else:
            s["status"] = "stopped"
            s["linked"] = "dead"
    
    return jsonify({"success": True, "sessions": sessions})


@app.route("/<username>/rstudio-<int:port>/", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.route("/<username>/rstudio-<int:port>/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@login_required
def rstudio_proxy(username, port, subpath=""):
    # 检查是否是当前登录用户
    if session.get("username") != username:
        return "Unauthorized", 403
    
    # 🚀 优化：使用缓存的 session 加载
    sessions = _cached_load_sessions(username)
    match = next((s for s in sessions if s["port"] == port), None)
    if not match:
        return "Session not found or not running", 404
    
    # 🚀 优化：使用缓存的端口检查（1秒缓存）
    if not _cached_check_port_alive(port, username):
        return redirect(url_for("dashboard"))

    host = request.host.split(",")[0]  # 兼容可能的 XFH 逗号链
    # 优先保留外部访问端口，避免上游重定向丢失非标准端口
    if ":" in host:
        host_port = host.rsplit(":", 1)[1]
    else:
        host_port = "443" if request.is_secure else "80"
    scheme = "https" if (request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https") else "http"
    path_prefix = f"/{username}/rstudio-{port}"
    query = request.query_string.decode("utf-8")

    # 构建请求到本地 RStudio    
    rstudio_url = f"http://127.0.0.1:{port}/{subpath}"
    if query:
        rstudio_url += f"?{query}"
        
    # 组装要转发给 RStudio 的头
    excluded_req_headers = {"host", "content-length", "content-encoding", "transfer-encoding", "connection"}
    fwd_headers = {k: v for k, v in request.headers if k.lower() not in excluded_req_headers}
    # 告诉 RStudio 我们在某个前缀 + 现在是 https
    fwd_headers["X-RStudio-Root-Path"] = path_prefix
    fwd_headers["X-Forwarded-Proto"] = "https" if scheme == "https" else "http"
    fwd_headers["X-Forwarded-Host"]  = host
    fwd_headers["X-Forwarded-Port"]  = host_port
    #print("DEBUG host:", host, "proxy to RStudio, url:", rstudio_url, "headers:", fwd_headers)

    # 🚀 优化：增加超时和重试机制
    resp = requests.request(
        method=request.method,
        url=rstudio_url,
        headers=fwd_headers,
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False,
        stream=True,
        timeout=30  # 添加超时
    )
    # ---- 修正 Location ----
    location = resp.headers.get("Location")
    if location:
        # 1) 绝对地址回写到外部前缀
        if location.startswith(f"http://127.0.0.1:{port}"):
            # print("DEBUG start with 127.0.0.1: port:", port, "scheme:", scheme, "host:", host, "path_prefix:", path_prefix)
            location = location.replace(f"http://127.0.0.1:{port}", f"{scheme}://{host}{path_prefix}")
        # 2) 相对根路径的跳转（以 / 开头）
        elif location.startswith("/"):
            # print("DEBUG start with /, port:", port, "scheme:", scheme, "host:", host, "path_prefix:", path_prefix)
            # 确保拼到我们的前缀下
            location = f"{scheme}://{host}{path_prefix}{location}"

    # ---- 构造返回头，并处理 Set-Cookie 多值 ----
    excluded_resp_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded_resp_headers and k.lower() != "set-cookie"]

    # 把（可能多条的）Set-Cookie 拿出来逐条修正
    set_cookie_list = []
    # requests 在 resp.raw.headers 里可 getlist
    if hasattr(resp.raw, "headers") and hasattr(resp.raw.headers, "getlist"):
        set_cookie_list = resp.raw.headers.getlist("Set-Cookie")
    else:
        # 退路：单值
        sc = resp.headers.get("Set-Cookie")
        if sc:
            set_cookie_list = [sc]

    if location:
        headers.append(("Location", location))

    for sc in set_cookie_list:
        sc_patched = _patch_set_cookie(sc, path_prefix, is_https=(scheme == "https"))
        headers.append(("Set-Cookie", sc_patched))

    body = resp.content
    status = resp.status_code
    return Response(body, status, headers)

## Root用户逻辑
def is_root():
    return session.get("username") == "root"

@app.route("/manage", methods=["GET"])
@login_required
def manage():
    if not is_root():
        abort(403)
    return render_template("manage.html", username=session["username"])

@app.route("/api/root_user_info")
@login_required
def root_user_info():
    if not is_root():
        abort(403)
    users = [f[:-5] for f in os.listdir(SESSION_DIR) if f.endswith(".json")]
    total_sessions = 0
    for u in users:
        for s in load_sessions(u):
            if s.get("status") == "running":
                total_sessions += 1
    return jsonify({
        "total_users": len(users),
        "total_sessions": total_sessions
    })

@app.route("/api/create_env", methods=["POST"])
@login_required
def create_env():
    data = request.json
    if not is_root():
        abort(403)
    env_name = data.get("env_name", "").strip()
    channel = (data.get("channel") or "default").strip()
    packages = (data.get("packages") or "").strip()
    if not env_name:
        return jsonify({"success": False, "message": "环境名称不能为空"}), 400
    try:
        cmd = ["mamba", "create", "-y", "-n", env_name]
        # 添加包参数
        if packages:
            cmd.extend(packages.split())
        else:
            cmd.append("python")
        if channel and channel != "default":
            cmd.extend(["-c", channel])
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return jsonify({"success": True})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": e.stderr}), 500

@app.route("/api/delete_env", methods=["POST"])
@login_required
def delete_env():
    if not is_root():
        abort(403)
    data = request.json
    env_name = data.get("env_name", "").strip()
    if not env_name:
        return jsonify({"success": False, "message": "环境名称不能为空"}), 400
    try:
        subprocess.run(
            ["mamba", "remove", "-y", "-n", env_name, "--all"],
            check=True, capture_output=True, text=True
        )
        # clean env folder if still exists (sometimes mamba remove may fail to delete the folder)
        result = subprocess.run(
            ["mamba", "env", "list", "--json"],
            capture_output=True, text=True, check=True
        )
        envs_data = json.loads(result.stdout)
        if env_name in [os.path.basename(env) for env in envs_data.get("envs", [])]:
            env_path = next((env for env in envs_data.get("envs", []) if os.path.basename(env) == env_name), None)
            if env_path and os.path.exists(env_path):
                subprocess.run(["rm", "-rf", env_path], check=False)
        
        return jsonify({"success": True})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": e.stderr}), 500

@app.route("/api/all_sessions")
@login_required
def all_sessions():
    if not is_root():
        abort(403)
    
    # 🚀 优化：只执行一次 netstat，而不是为每个 session 执行
    busy_ports = _get_netstat_established_ports()
    
    sessions = []
    for f in os.listdir(SESSION_DIR):
        if f.endswith(".json"):
            username = f[:-5]
            for s in load_sessions(username):
                # 检查 port 是否存活
                port = s["port"]
                port_alive = _cached_check_port_alive(port, username)
                
                if port_alive:
                    s["status"] = "running"
                    # 直接从缓存的 netstat 结果中查找
                    s["linked"] = "busy" if port in busy_ports else "idle"
                else:
                    s["status"] = "stopped"
                    s["linked"] = "dead"
                
                # 获取所有相关进程信息（对于管理面板展示）
                related_procs = []
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
                    try:
                        cmdline = proc.info['cmdline']
                        if cmdline and str(port) in " ".join(cmdline):
                            related_procs.append(proc)
                    except Exception:
                        continue
                
                # 递归查找所有子进程
                all_procs = set()
                for proc in related_procs:
                    all_procs.add(proc)
                    try:
                        children = proc.children(recursive=True)
                        for child in children:
                            all_procs.add(child)
                    except Exception:
                        continue
                
                # 汇总所有进程的 PID、内存和 CPU
                pids = [p.pid for p in all_procs]
                mem_total = sum(p.memory_info().rss for p in all_procs) / 1024 / 1024 if all_procs else None
                cpu_total = None
                if all_procs:
                    # 先调用一次 cpu_percent(None) 让 psutil 采样
                    for p in all_procs:
                        try:
                            p.cpu_percent(interval=None)
                        except Exception:
                            pass
                    time.sleep(0.1)  # 等待采样
                    raw_cpu = sum(p.cpu_percent(interval=None) for p in all_procs)
                    cpu_total = raw_cpu / psutil.cpu_count(logical=True)
                
                s.update({
                    "username": username,
                    "pids": pids,
                    "cpu_total": round(cpu_total, 2) if cpu_total is not None else None,
                    "mem_total": round(mem_total, 2) if mem_total is not None else None
                })
                sessions.append(s)
    
    return jsonify({"success": True, "sessions": sessions})

def _patch_set_cookie(sc: str, path_prefix: str, is_https: bool) -> str:
    # 确保 path 尾部有 /
    if not path_prefix.endswith('/'):
        path_prefix = path_prefix + '/'

    # 统一 Path
    if 'Path=' in sc:
        sc = re.sub(r'(?i)Path=[^;]*', f'Path={path_prefix}', sc)
    else:
        sc += f'; Path={path_prefix}'

    if is_https:
        # HTTPS 环境 → SameSite=None + Secure
        if re.search(r'(?i)SameSite=', sc):
            sc = re.sub(r'(?i)SameSite=\w+', 'SameSite=None', sc)
        else:
            sc += '; SameSite=None'

        if 'Secure' not in sc:
            sc += '; Secure'
    else:
        # HTTP 环境 → 删除 SameSite=None 避免浏览器拦截
        sc = re.sub(r'(?i);?\s*SameSite=None', '', sc)

    return sc

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)

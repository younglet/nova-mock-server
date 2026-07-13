"""
main.py — Nova Mock Server
==========================

本地零配置 Mock 服务器（pywebview + Edge WebView2 控制台）。

技术栈：
  - pywebview + 系统 Edge WebView2（零额外下载、无内嵌 Chromium）
  - http.server（标准库，零依赖）
  - 原生 HTML/CSS/JS 前端

特性：
  - 默认端口 80，冲突时自动 fallback 到 8080/8888/9090/随机
  - 内置智能灯 / 用户 / 工具三套接口，运行时勾选启用
  - 自定义端点（精确路径 + 单方法 + JSON/Text）
  - 拖拽 / 系统对话框添加静态文件（≤50 MB/文件）
  - 实时请求日志面板（启动后铺满）
  - 所有配置在内存，关闭即清空

编译：
  pyinstaller --onefile --noconsole --name nova_mock_server ^
      --add-data "ui/index.html;ui" main.py
"""

import os
import sys
import json
import time
import uuid
import queue
import socket
import secrets
import hashlib
import base64
import threading
import random as _rnd
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ============================================================
# 全局状态（内存，关闭即清空）
# ============================================================
STATE_LOCK = threading.RLock()
STATE = {
    "running": False,
    "port": 80,
    "actual_port": None,        # 真正绑定的端口（可能 fallback）
    "fallback_msg": None,       # 端口冲突时的提示
    "enabled_modules": {        # 内置模块开关
        "light": True,
        "user": True,
        "tools": True,
    },
    "custom_endpoints": [],     # [{method, path, status, body, delay_ms}]
    # 静态文件: virtual_path -> (filename, content_bytes, mime)
    "statics": {},
    # 内置数据
    "lights": [
        {"id": 1, "name": "客厅灯", "on": True,  "brightness": 80,
         "color_temp": 4000, "rgb": None, "mode": "normal"},
        {"id": 2, "name": "卧室灯", "on": False, "brightness": 30,
         "color_temp": 3000, "rgb": None, "mode": "sleep"},
        {"id": 3, "name": "书房灯", "on": True,  "brightness": 100,
         "color_temp": 5500, "rgb": None, "mode": "reading"},
    ],
    "users": [
        {"id": 1, "username": "tom",   "email": "tom@example.com",
         "role": "admin",  "created": "2024-01-15"},
        {"id": 2, "username": "jerry", "email": "jerry@example.com",
         "role": "editor", "created": "2024-03-22"},
        {"id": 3, "username": "alice", "email": "alice@example.com",
         "role": "viewer", "created": "2024-06-10"},
        {"id": 4, "username": "bob",   "email": "bob@example.com",
         "role": "editor", "created": "2024-08-05"},
        {"id": 5, "username": "diana", "email": "diana@example.com",
         "role": "admin",  "created": "2024-11-30"},
    ],
    "next_user_id": 6,
    "tokens": {},                # token -> username
    "message": "hello, from nova-mock-server!",
    "numbers": [],
}

LOG_QUEUE: queue.Queue = queue.Queue(maxsize=2000)
HTTP_SERVER: ThreadingHTTPServer | None = None
SERVER_THREAD: threading.Thread | None = None
MAX_STATIC_BYTES = 50 * 1024 * 1024  # 单文件 50 MB 上限


# ============================================================
# 工具
# ============================================================
def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='milliseconds')

def push_log(entry: dict) -> None:
    """线程安全日志入队；满则丢最早一条。"""
    try:
        LOG_QUEUE.put_nowait(entry)
    except queue.Full:
        try: LOG_QUEUE.get_nowait()
        except: pass
        try: LOG_QUEUE.put_nowait(entry)
        except: pass

def guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
        '.css': 'text/css; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8',
        '.mjs': 'application/javascript; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.xml': 'application/xml; charset=utf-8',
        '.txt': 'text/plain; charset=utf-8', '.md': 'text/markdown; charset=utf-8',
        '.svg': 'image/svg+xml',
        '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.gif': 'image/gif', '.webp': 'image/webp', '.ico': 'image/x-icon',
        '.pdf': 'application/pdf',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
        '.mp4': 'video/mp4', '.webm': 'video/webm',
        '.zip': 'application/zip',
    }.get(ext, 'application/octet-stream')

def cors_headers(handler, extra: dict | None = None):
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,PATCH,OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', '*')
    if extra:
        for k, v in extra.items():
            handler.send_header(k, v)

def json_response(handler, status, payload, headers=None):
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    cors_headers(handler, headers)
    handler.end_headers()
    handler.wfile.write(body)

def raw_response(handler, status, content_bytes, content_type='application/octet-stream', headers=None):
    handler.send_response(status)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(len(content_bytes)))
    cors_headers(handler, headers)
    handler.end_headers()
    handler.wfile.write(content_bytes)

def read_body(handler) -> bytes:
    n = int(handler.headers.get('Content-Length') or 0)
    return handler.rfile.read(n) if n else b''

def get_lan_ip() -> str:
    """拿主机的局域网 IP。优先 RFC 1918 私有地址（10/8, 172.16/12, 192.168/16）。"""
    def is_private(ip: str) -> bool:
        p = ip.split('.')
        if len(p) != 4: return False
        try:    a, b = int(p[0]), int(p[1])
        except: return False
        if a == 10: return True
        if a == 172 and 16 <= b <= 31: return True
        if a == 192 and b == 168: return True
        return False

    candidates: list[str] = []

    # UDP trick：内核仅为路由查询，不发包
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.') and ip != '0.0.0.0':
                candidates.append(ip)
        finally:
            s.close()
    except Exception: pass

    # fallback: hostname 解析
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith('127.') and ip != '0.0.0.0' and ip not in candidates:
                candidates.append(ip)
    except Exception: pass

    # 优先私有地址
    for ip in candidates:
        if is_private(ip):
            return ip
    return candidates[0] if candidates else '127.0.0.1'

# ============================================================
# 内置 API · 智能灯
# ============================================================
def handle_light(handler, method, path):
    if not STATE["enabled_modules"]["light"]:
        return json_response(handler, 503, {"error": "智能灯模块未启用"})

    if path == '/api/light/state' and method == 'GET':
        return json_response(handler, 200, {"lights": STATE["lights"]})

    if path.startswith('/api/light/') and method == 'GET':
        try:    lid = int(path.rsplit('/', 1)[1])
        except ValueError:
            return json_response(handler, 400, {"error": "无效的灯 id"})
        light = next((l for l in STATE["lights"] if l["id"] == lid), None)
        if not light: return json_response(handler, 404, {"error": "灯不存在", "id": lid})
        return json_response(handler, 200, light)

    if path == '/api/light/switch' and method == 'POST':
        data = json.loads(read_body(handler) or b'{}')
        lid, on = data.get('id'), data.get('on')
        if lid is None or on is None:
            return json_response(handler, 400, {"error": "需要 id 和 on 字段"})
        light = next((l for l in STATE["lights"] if l["id"] == int(lid)), None)
        if not light: return json_response(handler, 404, {"error": "灯不存在"})
        light["on"] = bool(on)
        return json_response(handler, 200, {"ok": True, "light": light})

    if path == '/api/light/brightness' and method == 'POST':
        data = json.loads(read_body(handler) or b'{}')
        lid, val = data.get('id'), data.get('value')
        if lid is None or val is None:
            return json_response(handler, 400, {"error": "需要 id 和 value 字段"})
        val = max(0, min(100, int(val)))
        light = next((l for l in STATE["lights"] if l["id"] == int(lid)), None)
        if not light: return json_response(handler, 404, {"error": "灯不存在"})
        light["brightness"] = val
        return json_response(handler, 200, {"ok": True, "light": light})

    if path == '/api/light/color' and method == 'POST':
        data = json.loads(read_body(handler) or b'{}')
        lid = data.get('id')
        light = next((l for l in STATE["lights"] if l["id"] == int(lid)) if lid is not None else None, None)
        if not light: return json_response(handler, 404, {"error": "灯不存在"})
        if 'color_temp' in data: light['color_temp'] = int(data['color_temp'])
        if 'rgb' in data and isinstance(data['rgb'], dict):
            light['rgb'] = {k: int(v) for k, v in data['rgb'].items() if k in ('r', 'g', 'b')}
        if 'mode' in data: light['mode'] = str(data['mode'])
        return json_response(handler, 200, {"ok": True, "light": light})

    return json_response(handler, 404, {"error": "智能灯接口不存在", "path": path})


# ============================================================
# 内置 API · 用户
# ============================================================
def handle_user(handler, method, path):
    if not STATE["enabled_modules"]["user"]:
        return json_response(handler, 503, {"error": "用户模块未启用"})

    if path == '/api/login':
        if method != 'POST':
            return json_response(handler, 405, {"error": "/api/login 仅支持 POST"})
        data = json.loads(read_body(handler) or b'{}')
        username, password = data.get('username', ''), data.get('password', '')
        user = next((u for u in STATE["users"] if u["username"] == username), None)
        if not user or not password:
            return json_response(handler, 401, {"error": "用户名或密码错误"})
        token = secrets.token_hex(16)
        STATE["tokens"][token] = username
        return json_response(handler, 200, {"token": token, "user": user})

    if path == '/api/users' and method == 'GET':
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        try:    page = max(1, int(qs.get('page', ['1'])[0]))
        except: page = 1
        try:    limit = min(100, max(1, int(qs.get('limit', ['10'])[0])))
        except: limit = 10
        q = (qs.get('q', [''])[0] or '').lower()
        items = STATE["users"]
        if q:
            items = [u for u in items if q in u["username"].lower() or q in u["email"].lower()]
        total = len(items)
        start = (page - 1) * limit
        return json_response(handler, 200, {
            "users": items[start:start + limit],
            "total": total, "page": page, "limit": limit,
        })

    if path.startswith('/api/user/'):
        try:    uid = int(path.rsplit('/', 1)[1])
        except ValueError:
            return json_response(handler, 400, {"error": "无效的 user id"})
        if method == 'GET':
            user = next((u for u in STATE["users"] if u["id"] == uid), None)
            return json_response(handler, 404, {"error": "用户不存在"}) if not user else json_response(handler, 200, user)
        if method == 'PUT':
            data = json.loads(read_body(handler) or b'{}')
            for u in STATE["users"]:
                if u["id"] == uid:
                    for k in ('username', 'email', 'role'):
                        if k in data: u[k] = data[k]
                    return json_response(handler, 200, {"ok": True, "user": u})
            return json_response(handler, 404, {"error": "用户不存在"})
        if method == 'DELETE':
            STATE["users"] = [u for u in STATE["users"] if u["id"] != uid]
            return json_response(handler, 200, {"ok": True, "deleted": uid})

    if path == '/api/user' and method == 'POST':
        data = json.loads(read_body(handler) or b'{}')
        if not data.get('username') or not data.get('email'):
            return json_response(handler, 400, {"error": "需要 username 和 email"})
        new = {
            "id": STATE["next_user_id"],
            "username": str(data["username"]),
            "email":    str(data["email"]),
            "role":     str(data.get("role", "viewer")),
            "created":  datetime.now().strftime("%Y-%m-%d"),
        }
        STATE["users"].append(new)
        STATE["next_user_id"] += 1
        return json_response(handler, 201, {"ok": True, "user": new})

    return json_response(handler, 404, {"error": "用户接口不存在", "path": path})


# ============================================================
# 内置 API · 工具
# ============================================================
def handle_tools(handler, method, path):
    if not STATE["enabled_modules"]["tools"]:
        return json_response(handler, 503, {"error": "实用工具模块未启用"})

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)

    if path == '/api/random':
        if method != 'GET':
            return json_response(handler, 405, {"error": "仅支持 GET"})
        try:
            mn = float(qs.get('min', ['0'])[0]); mx = float(qs.get('max', ['1'])[0])
        except ValueError:
            return json_response(handler, 400, {"error": "min/max 必须是数字"})
        integer = qs.get('integer', ['false'])[0].lower() in ('1', 'true', 'yes')
        if mn > mx: mn, mx = mx, mn
        v = _rnd.randint(int(mn), int(mx)) if integer else _rnd.uniform(mn, mx)
        return json_response(handler, 200, {"value": v, "min": mn, "max": mx, "integer": integer})

    if path == '/api/now':
        fmt = qs.get('format', ['iso'])[0]
        ts = time.time()
        if fmt == 'ts':    return json_response(handler, 200, {"now": int(ts),        "format": "unix-seconds"})
        if fmt == 'ms':    return json_response(handler, 200, {"now": int(ts*1000),   "format": "unix-milliseconds"})
        if fmt == 'human': return json_response(handler, 200, {"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "format": "human"})
        return json_response(handler, 200, {"now": now_iso(), "format": "iso"})

    if path == '/api/uuid':
        try:    count = max(1, min(20, int(qs.get('count', ['1'])[0])))
        except: count = 1
        return json_response(handler, 200, {"uuids": [str(uuid.uuid4()) for _ in range(count)]})

    if path == '/api/echo':
        body = read_body(handler)
        try:    parsed = json.loads(body) if body else None
        except: parsed = None
        return json_response(handler, 200, {
            "method": method, "path": handler.path, "query": dict(qs),
            "headers": dict(handler.headers),
            "body_raw": body.decode('utf-8', errors='replace'),
            "body_json": parsed,
        })

    if path == '/api/ip':
        return json_response(handler, 200, {"ip": handler.client_address[0]})

    if path == '/api/delay':
        try:    ms = max(0, min(30000, int(qs.get('ms', ['1000'])[0])))
        except: ms = 1000
        time.sleep(ms / 1000)
        return json_response(handler, 200, {"ok": True, "delayed_ms": ms})

    if path == '/api/status':
        try:    code = int(qs.get('code', ['200'])[0])
        except: code = 200
        if code < 100 or code > 599:
            return json_response(handler, 400, {"error": "状态码非法"})
        return json_response(handler, code, {"forced_status": code, "message": "人为指定的状态码"})

    if path == '/api/base64':
        s   = qs.get('str', [''])[0]
        act = qs.get('action', ['encode'])[0].lower()
        try:
            if act == 'encode':   res = base64.b64encode(s.encode()).decode()
            elif act == 'decode': res = base64.b64decode(s.encode()).decode()
            else: return json_response(handler, 400, {"error": "action 仅 encode/decode"})
        except Exception as e:
            return json_response(handler, 400, {"error": str(e)})
        return json_response(handler, 200, {"input": s, "action": act, "result": res})

    if path == '/api/hash':
        s    = qs.get('str', [''])[0]
        algo = qs.get('algo', ['sha256'])[0].lower()
        try:
            h = hashlib.new(algo); h.update(s.encode())
            return json_response(handler, 200, {"input": s, "algo": algo, "hash": h.hexdigest()})
        except ValueError:
            return json_response(handler, 400, {
                "error": f"不支持的算法: {algo}",
                "supported": ["md5", "sha1", "sha224", "sha256", "sha384", "sha512"],
            })

    if path == '/api/message':
        if method == 'GET':
            return json_response(handler, 200, {"message": STATE["message"]})
        if method in ('POST', 'PUT'):
            data = json.loads(read_body(handler) or b'{}')
            msg = data.get('message')
            if not isinstance(msg, str):
                return json_response(handler, 400, {"error": "需要 message 字段（字符串）"})
            STATE["message"] = msg
            return json_response(handler, 200, {"ok": True, "message": STATE["message"]})
        if method == 'DELETE':
            STATE["message"] = "hello, from nova-mock-server!"
            return json_response(handler, 200, {"ok": True, "message": STATE["message"], "reset": True})
        return json_response(handler, 405, {"error": "该接口支持 GET / POST / PUT / DELETE"})

    if path == '/api/numbers':
        if method == 'GET':
            return json_response(handler, 200, {
                "numbers": STATE["numbers"],
                "count":   len(STATE["numbers"]),
            })
        if method == 'POST':
            data = json.loads(read_body(handler) or b'{}')
            added = []
            if 'value' in data:
                try:
                    v = int(data['value'])
                except (ValueError, TypeError):
                    return json_response(handler, 400, {"error": "value 必须是整数"})
                STATE["numbers"].append(v)
                added.append(v)
            if 'values' in data:
                if not isinstance(data['values'], list):
                    return json_response(handler, 400, {"error": "values 必须是数组"})
                for x in data['values']:
                    try:
                        v = int(x)
                    except (ValueError, TypeError):
                        return json_response(handler, 400, {"error": f"values 中包含非整数: {x!r}"})
                    STATE["numbers"].append(v)
                    added.append(v)
            if not added:
                return json_response(handler, 400, {"error": "需要 value 或 values 字段"})
            return json_response(handler, 200, {
                "ok": True, "added": added, "numbers": STATE["numbers"],
            })
        if method == 'PUT':
            data = json.loads(read_body(handler) or b'{}')
            if 'values' not in data or not isinstance(data['values'], list):
                return json_response(handler, 400, {"error": "需要 values 数组"})
            try:
                new_list = [int(x) for x in data['values']]
            except (ValueError, TypeError) as e:
                return json_response(handler, 400, {"error": f"values 中包含非整数: {e}"})
            STATE["numbers"] = new_list
            return json_response(handler, 200, {
                "ok": True, "numbers": STATE["numbers"],
            })
        if method == 'DELETE':
            STATE["numbers"] = []
            return json_response(handler, 200, {
                "ok": True, "numbers": STATE["numbers"], "reset": True,
            })
        return json_response(handler, 405, {"error": "该接口支持 GET / POST / PUT / DELETE"})

    return json_response(handler, 404, {"error": "工具接口不存在", "path": path})


# ============================================================
# HTTP Handler
# ============================================================
class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # 关闭默认 stderr 日志

    def send_response(self, code, message=None):
        self._last_status = code
        super().send_response(code, message)

    # 路径段 → 模块（第一段以后的 API 名）
    PATH_MODULE = {
        # light
        'light':       'light',
        # user
        'users':       'user',
        'user':        'user',
        'login':       'user',
        # tools
        'random':      'tools',
        'now':         'tools',
        'uuid':        'tools',
        'echo':        'tools',
        'ip':          'tools',
        'delay':       'tools',
        'status':      'tools',
        'base64':      'tools',
        'hash':        'tools',
        'message':     'tools',
        'numbers':     'tools',
    }

    def _dispatch(self, path):
        """按 path 第二段分派到对应模块处理器。返回 (handler_fn, module_name)。"""
        if not path.startswith('/api/'):
            return None, None
        seg = path[5:].split('/', 1)[0]
        mod = self.PATH_MODULE.get(seg)
        return {
            'light': (handle_light, 'light'),
            'user':  (handle_user,  'user'),
            'tools': (handle_tools, 'tools'),
        }.get(mod, (None, None))

    def _route(self):
        method = self.command
        path   = urllib.parse.urlparse(self.path).path
        start  = time.time()

        try:
            # CORS preflight
            if method == 'OPTIONS':
                self.send_response(204)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', '*')
                self.send_header('Access-Control-Allow-Headers', '*')
                self.send_header('Access-Control-Max-Age', '86400')
                self.end_headers()
                return

            # 静态文件（自动 index 解析）
            target = None
            if path in ('/', '/static', '/static/'):
                target = 'index.html'                      # 根 → 顶级 index.html
            elif path.startswith('/static/') and path.endswith('/'):
                target = path[len('/static/'):] + 'index.html'   # /static/foo/ → foo/index.html
            elif path.startswith('/static/'):
                target = path[len('/static/'):]            # /static/foo.html → foo.html

            if target is not None:
                with STATE_LOCK:
                    item = STATE["statics"].get(target)
                if not item:
                    if path in ('/', '/static', '/static/'):
                        json_response(self, 404, {
                            "error": "未找到 index.html",
                            "hint":  "拖一个 index.html 到静态文件，即可通过 / 访问",
                        })
                    else:
                        json_response(self, 404, {"error": "静态文件不存在", "path": target})
                else:
                    _, content, mime = item
                    raw_response(self, 200, content, content_type=mime)
                self._after(method, path, start, self._last_status, "static")
                return

            # API 文档页面 /docs
            if path == '/docs':
                if method != 'GET':
                    json_response(self, 405, {"error": "仅支持 GET"})
                    self._after(method, path, start, 405, "builtin")
                    return
                port = STATE.get("actual_port") or STATE.get("port") or 80
                host = get_lan_ip()
                html = render_docs_html(host, port)
                raw_response(self, 200, html.encode('utf-8'), 'text/html; charset=utf-8')
                self._after(method, path, start, 200, "docs")
                return

            # 内置模块
            _h, _mod = self._dispatch(path)
            if _h is not None:
                _h(self, method, path)
                self._after(method, path, start, self._last_status, "builtin")
                return

            # 自定义端点
            for ep in STATE["custom_endpoints"]:
                if ep["method"] == method and ep["path"] == path:
                    delay = max(0, int(ep.get("delay_ms", 0)))
                    if delay: time.sleep(delay / 1000)
                    try:
                        body_preview = json.loads(read_body(self) or b'null')
                    except:
                        body_preview = None
                    try:
                        parsed_body = json.loads(ep["body"]) if ep["body"] else None
                    except:
                        parsed_body = None
                    json_response(self, int(ep["status"]), {
                        "ok": True,
                        "matched": ep["path"],
                        "method": method,
                        "your_request": {
                            "query": dict(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)),
                            "body": body_preview,
                        },
                        "configured": parsed_body if parsed_body is not None else ep["body"],
                    })
                    self._after(method, path, start, int(ep["status"]), "custom")
                    return

            # 404
            json_response(self, 404, {
                "error":  "未找到该接口",
                "path":   path, "method": method,
                "hint":   "在 WebView 控制台里添加自定义端点，或启用内置模块",
            })
            self._after(method, path, start, 404, "builtin")

        except Exception as e:
            try:
                json_response(self, 500, {"error": "服务器内部错误", "detail": str(e)})
            except: pass
            self._after(method, path, start, 500, "builtin")

    def _after(self, method, path, start, status, kind):
        elapsed_ms = int((time.time() - start) * 1000)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            raw = read_body(self)
            req_body_str = raw.decode('utf-8', errors='replace') if raw else ''
            req_body_json = json.loads(req_body_str) if req_body_str else None
        except:
            req_body_str, req_body_json = '', None
        push_log({
            "ts":         now_iso(),
            "method":     method,
            "path":       path,
            "query":      qs,
            "headers":    dict(self.headers),
            "body":       req_body_str,
            "body_json":  req_body_json,
            "status":     status,
            "elapsed_ms": elapsed_ms,
            "kind":       kind,
        })

    def do_GET(self):    self._route()
    def do_POST(self):   self._route()
    def do_PUT(self):    self._route()
    def do_DELETE(self): self._route()
    def do_PATCH(self):  self._route()
    def do_OPTIONS(self):self._route()


# ============================================================
# 服务器启停
# ============================================================
def try_bind(port: int):
    # 0.0.0.0 监听所有接口，LAN 上的设备才能访问
    try:
        srv = ThreadingHTTPServer(('0.0.0.0', port), MockHandler)
        return srv, None
    except OSError as e:
        return None, str(e)

def start_server(port: int) -> dict:
    """绑定端口，失败时自动 fallback 到 8080/8888/9090。"""
    global HTTP_SERVER, SERVER_THREAD
    stop_server()
    port = int(port)
    srv, err = try_bind(port)
    fallback_msg = None
    if not srv:
        for fb in (8080, 8888, 9090):
            srv, _ = try_bind(fb)
            if srv:
                fallback_msg = f"端口 {port} 被占用，已自动切换到 {srv.server_address[1]}"
                port = srv.server_address[1]
                break
        if not srv:
            return {"ok": False, "error": f"无法绑定端口: {err}"}
    HTTP_SERVER = srv
    SERVER_THREAD = threading.Thread(target=srv.serve_forever, daemon=True)
    SERVER_THREAD.start()
    with STATE_LOCK:
        STATE["running"]      = True
        STATE["port"]         = port
        STATE["actual_port"]  = port
        STATE["fallback_msg"] = fallback_msg
    push_log({
        "ts": now_iso(), "method": "SYSTEM", "path": f"服务器已启动 :{port}",
        "query": {}, "headers": {}, "body": "", "body_json": None,
        "status": 200, "elapsed_ms": 0, "kind": "system",
    })
    return {"ok": True, "port": port, "fallback_msg": fallback_msg}

def stop_server() -> dict:
    global HTTP_SERVER, SERVER_THREAD
    if HTTP_SERVER:
        try: HTTP_SERVER.shutdown(); HTTP_SERVER.server_close()
        except: pass
        HTTP_SERVER = None
        SERVER_THREAD = None
    with STATE_LOCK:
        STATE["running"]     = False
        STATE["actual_port"] = None
    push_log({
        "ts": now_iso(), "method": "SYSTEM", "path": "服务器已停止",
        "query": {}, "headers": {}, "body": "", "body_json": None,
        "status": 200, "elapsed_ms": 0, "kind": "system",
    })
    return {"ok": True}


# ============================================================
# 内置 API 说明（前端展示用）
# ============================================================
ENDPOINT_DOCS = [
    {"module":"light","method":"GET",   "path":"/api/light/state",
     "desc":"获取所有灯的当前状态", "params":"无",
     "example":"curl http://localhost:PORT/api/light/state"},
    {"module":"light","method":"GET",   "path":"/api/light/{id}",
     "desc":"获取单盏灯详情", "params":"路径参数 id (1/2/3)",
     "example":"curl /api/light/1"},
    {"module":"light","method":"POST",  "path":"/api/light/switch",
     "desc":"开关灯", "params":'Body: {"id": 1, "on": true}',
     "example":'curl -X POST -d \'{"id":1,"on":true}\' /api/light/switch'},
    {"module":"light","method":"POST",  "path":"/api/light/brightness",
     "desc":"调节亮度 (0-100)", "params":'Body: {"id": 1, "value": 80}',
     "example":'curl -X POST -d \'{"id":1,"value":80}\' /api/light/brightness'},
    {"module":"light","method":"POST",  "path":"/api/light/color",
     "desc":"设置色温 / RGB / 模式", "params":'Body: {"id":1,"color_temp":4000,"rgb":{"r":255,"g":128,"b":0},"mode":"reading"}',
     "example":'curl -X POST -d \'{"id":1,"color_temp":4000}\' /api/light/color'},

    {"module":"user","method":"GET",    "path":"/api/users",
     "desc":"用户列表，支持分页搜索", "params":"?page=1&limit=10&q=tom",
     "example":"curl /api/users?page=1&limit=10"},
    {"module":"user","method":"GET",    "path":"/api/user/{id}",
     "desc":"用户详情", "params":"路径参数 id",
     "example":"curl /api/user/1"},
    {"module":"user","method":"POST",   "path":"/api/login",
     "desc":"登录，任意密码通过（mock），返回 token", "params":'Body: {"username":"tom","password":"任意"}',
     "example":'curl -X POST -d \'{"username":"tom","password":"x"}\' /api/login'},
    {"module":"user","method":"POST",   "path":"/api/user",
     "desc":"创建用户", "params":'Body: {"username":"new","email":"n@e.com","role":"viewer"}',
     "example":'curl -X POST -d \'{"username":"new","email":"n@e.com"}\' /api/user'},
    {"module":"user","method":"PUT",    "path":"/api/user/{id}",
     "desc":"更新用户", "params":'Body 任意字段(username/email/role)',
     "example":'curl -X PUT -d \'{"role":"admin"}\' /api/user/2'},
    {"module":"user","method":"DELETE", "path":"/api/user/{id}",
     "desc":"删除用户", "params":"路径参数 id",
     "example":"curl -X DELETE /api/user/5"},

    {"module":"tools","method":"GET",   "path":"/api/random",
     "desc":"范围内随机数（可选取整）", "params":"?min=1&max=100&integer=true",
     "example":"curl /api/random?min=1&max=100&integer=true"},
    {"module":"tools","method":"GET",   "path":"/api/now",
     "desc":"当前时间（iso/ts/ms/human）", "params":"?format=iso (默认) | ts | ms | human",
     "example":"curl /api/now?format=ms"},
    {"module":"tools","method":"GET",   "path":"/api/uuid",
     "desc":"生成 UUID", "params":"?count=1 (1-20)",
     "example":"curl /api/uuid?count=3"},
    {"module":"tools","method":"*",      "path":"/api/echo",
     "desc":"回显请求（头/body/参数全返回）", "params":"任意",
     "example":'curl -X POST -d \'{"hi":1}\' /api/echo'},
    {"module":"tools","method":"GET",   "path":"/api/ip",
     "desc":"返回客户端 IP", "params":"无",
     "example":"curl /api/ip"},
    {"module":"tools","method":"GET",   "path":"/api/delay",
     "desc":"主动延迟响应（测前端超时）", "params":"?ms=2000 (0-30000)",
     "example":"curl /api/delay?ms=1500"},
    {"module":"tools","method":"GET",   "path":"/api/status",
     "desc":"返回指定状态码（测前端错误处理）", "params":"?code=500",
     "example":"curl /api/status?code=404"},
    {"module":"tools","method":"GET",   "path":"/api/base64",
     "desc":"Base64 编/解码", "params":"?str=hello&action=encode | decode",
     "example":"curl /api/base64?str=hi&action=encode"},
    {"module":"tools","method":"GET",   "path":"/api/hash",
     "desc":"哈希计算", "params":"?str=hi&algo=sha256 (md5/sha1/sha224/sha256/sha384/sha512)",
     "example":"curl /api/hash?str=hi&algo=md5"},
    {"module":"tools","method":"GET",   "path":"/api/message",
     "desc":"读取消息（默认 hello, from nova-mock-server!）", "params":"无",
     "example":"curl /api/message"},
    {"module":"tools","method":"POST",  "path":"/api/message",
     "desc":"修改消息内容", "params":'Body: {"message": "新的消息文本"}',
     "example":'curl -X POST -d \'{"message":"hi"}\' /api/message'},
    {"module":"tools","method":"PUT",   "path":"/api/message",
     "desc":"同 POST（修改消息）", "params":'Body: {"message": "..."}',
     "example":'curl -X PUT -d \'{"message":"hi"}\' /api/message'},
    {"module":"tools","method":"DELETE","path":"/api/message",
     "desc":"重置消息为默认值", "params":"无",
     "example":"curl -X DELETE /api/message"},
    {"module":"tools","method":"GET",   "path":"/api/numbers",
     "desc":"读取数字列表（默认空）", "params":"无",
     "example":"curl /api/numbers"},
    {"module":"tools","method":"POST",  "path":"/api/numbers",
     "desc":"追加一个或多个数字", "params":'Body: {"value": 42} 或 {"values": [1,2,3]}',
     "example":'curl -X POST -d \'{"value":42}\' /api/numbers'},
    {"module":"tools","method":"PUT",   "path":"/api/numbers",
     "desc":"替换整个数字列表", "params":'Body: {"values": [10,20,30]}',
     "example":'curl -X PUT -d \'{"values":[10,20,30]}\' /api/numbers'},
    {"module":"tools","method":"DELETE","path":"/api/numbers",
     "desc":"清空数字列表", "params":"无",
     "example":"curl -X DELETE /api/numbers"},
]


# ============================================================
# /docs 页面渲染（独立暗色 HTML，浏览器可访问）
# ============================================================
def _esc(s: str) -> str:
    return (str(s).replace('&', '&amp;').replace('<', '&lt;')
                  .replace('>', '&gt;').replace('"', '&quot;'))

DOCS_MODULE_TITLES = {
    'light': ('💡 智能灯',  'Smart Light'),
    'user':  ('👤 用户信息', 'User Info'),
    'tools': ('🔧 实用工具', 'Utilities'),
}

def _render_api_tab(base: str) -> str:
    """渲染 API 接口 tab 的内容（按模块分组）。"""
    by_mod: dict[str, list[dict]] = {'light': [], 'user': [], 'tools': []}
    for d in ENDPOINT_DOCS:
        by_mod.setdefault(d['module'], []).append(d)
    sections = []
    for mod, items in by_mod.items():
        if not items: continue
        zh, en = DOCS_MODULE_TITLES.get(mod, (mod, mod))
        rows = []
        for d in items:
            method = d['method']
            method_disp = method if method != '*' else 'ANY'
            can_link = method in ('GET', '*')
            if can_link:
                href = f'{base}{d["path"]}'
                path_html = (
                    f'<a class="path-link" href="{_esc(href)}" '
                    f'target="_blank" rel="noopener">{_esc(d["path"])}</a>'
                )
            else:
                tooltip = (f'{method_disp} 接口不可直接在浏览器访问，'
                           f'请使用 nova-http-tester 或其他调试工具测试')
                path_html = (
                    f'<span class="path-disabled" '
                    f'data-tooltip="{_esc(tooltip)}">{_esc(d["path"])}</span>'
                )
            rows.append(f'''
            <div class="endpoint">
              <div class="head">
                <span class="method-tag m-{method_disp}">{method_disp}</span>
                {path_html}
              </div>
              <div class="desc">{_esc(d['desc'])}</div>
              <div class="kv"><span class="k">参数</span><span class="v">{_esc(d['params'])}</span></div>
            </div>''')
        sections.append(f'''
        <section class="module">
          <h2>{zh} <span class="en">{en}</span></h2>
          <div class="count">{len(items)} 个端点</div>
          {''.join(rows)}
        </section>''')
    return ''.join(sections)


def _render_static_tab(base: str) -> str:
    """渲染静态资源 tab 的内容。"""
    port_part = '' if ':' in base and base.rsplit(':', 1)[1].isdigit() and base.rsplit(':', 1)[1] == '80' else ''
    return f'''
        <section class="module">
          <h2>📦 静态资源 <span class="en">Static Files</span></h2>
          <div class="count">拖文件 / 文件夹进控制台即可服务</div>

          <div class="guide">
            <h3>添加方式</h3>
            <ul>
              <li><b>拖拽文件</b>：直接把 <code>.html / .css / .js / .png / ...</code> 拖到控制台拖拽区</li>
              <li><b>拖拽文件夹</b>：HTML5 拖拽拿不到文件夹内容（浏览器限制），改用 <b>📁 选择文件夹</b> 按钮</li>
              <li><b>冲突提示</b>：同名文件弹窗询问是否替换</li>
            </ul>
          </div>

          <div class="guide">
            <h3>URL 映射</h3>
            <table class="url-table">
              <tr><th>控制台拖入的文件</th><th>浏览器访问 URL</th></tr>
              <tr><td><code>index.html</code></td>
                  <td><a class="url-link" href="{base}/" target="_blank"><code>{base}/</code></a>
                      <span class="url-note">（自动识别根 index.html）</span></td></tr>
              <tr><td><code>index.html</code></td>
                  <td><a class="url-link" href="{base}/static/index.html" target="_blank"><code>{base}/static/index.html</code></a></td></tr>
              <tr><td><code>about.html</code></td>
                  <td><a class="url-link" href="{base}/static/about.html" target="_blank"><code>{base}/static/about.html</code></a></td></tr>
              <tr><td><code>blog/index.html</code></td>
                  <td><a class="url-link" href="{base}/static/blog/" target="_blank"><code>{base}/static/blog/</code></a>
                      <span class="url-note">（自动识别子目录 index.html）</span></td></tr>
              <tr><td><code>app/style.css</code></td>
                  <td><a class="url-link" href="{base}/static/app/style.css" target="_blank"><code>{base}/static/app/style.css</code></a></td></tr>
            </table>
          </div>

          <div class="guide">
            <h3>MIME 自动识别</h3>
            <div class="mime-grid">
              <span><code>.html</code> → text/html</span>
              <span><code>.css</code> → text/css</span>
              <span><code>.js</code> → application/javascript</span>
              <span><code>.json</code> → application/json</span>
              <span><code>.png/.jpg/.gif/.webp</code> → image/*</span>
              <span><code>.svg</code> → image/svg+xml</span>
              <span><code>.mp3/.wav</code> → audio/*</span>
              <span><code>.mp4/.webm</code> → video/*</span>
              <span><code>.pdf/.zip</code> → application/*</span>
              <span>其他 → application/octet-stream</span>
            </div>
          </div>

          <div class="guide">
            <h3>使用场景</h3>
            <ul>
              <li><b>学习 web 开发</b>：拖一个 HTML + CSS + JS 项目进控制台，实时看到效果，手机也能访问（同一 WiFi）</li>
              <li><b>前端联调</b>：mock 接口 + 静态页面在同一进程</li>
              <li><b>演示 / 教学</b>：单文件 EXE，开箱即用，不依赖任何外部资源</li>
              <li><b>局域网分享</b>：手机 / 平板直接访问 <code>{_esc(base)}/static/...</code></li>
            </ul>
          </div>

          <div class="guide warn-guide">
            <h3>限制</h3>
            <ul>
              <li>单文件 ≤ <b>50 MB</b>（超出报错）</li>
              <li>所有文件存内存，<b>关闭 EXE 即清空</b></li>
              <li>最大并发数 = 线程池默认（适合开发测试，不适合高并发）</li>
            </ul>
          </div>
        </section>'''


def render_docs_html(host: str, port: int) -> str:
    base = f'http://{host}:{port}'
    api_tab    = _render_api_tab(base)
    static_tab = _render_static_tab(base)
    api_count = len(ENDPOINT_DOCS)

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='80' font-size='80'%3E%F0%9F%93%A1%3C/text%3E%3C/svg%3E">
<title>Nova Mock Server · 文档</title>
<style>
:root {{
  --bg:#1a1a1a; --panel:#232323; --panel-2:#2a2a2a;
  --border:#3a3a3a; --text:#e0e0e0; --muted:#888;
  --accent:#4a9eff; --accent-hover:#6bb3ff;
  --success:#4ade80; --error:#f87171; --warn:#fbbf24;
  --code:#d4d4d4;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  background:var(--bg); color:var(--text); font-size:14px; line-height:1.6;
}}
.container{{max-width:980px;margin:0 auto;padding:32px 24px}}
header{{
  background:var(--panel); border:1px solid var(--border); border-radius:8px;
  padding:24px; margin-bottom:0;
}}
header h1{{font-size:24px; font-weight:700; margin-bottom:8px}}
header .sub{{color:var(--muted); font-size:13px; margin-bottom:16px}}
header .server-box{{
  background:var(--bg); border:1px solid var(--border); border-radius:6px;
  padding:10px 14px; font-family:"Cascadia Code",Consolas,monospace;
  font-size:13px; color:var(--code); display:inline-block;
}}

/* Tabs */
.tabs{{
  display:flex; gap:4px;
  margin-top:-1px; padding:0 24px;
  background:var(--panel);
  border:1px solid var(--border); border-top:none;
  border-radius:0 0 8px 8px;
  margin-bottom:24px;
}}
.tab{{
  padding:10px 18px;
  background:transparent; border:none;
  color:var(--muted); font-size:13px; font-weight:600;
  cursor:pointer; border-bottom:2px solid transparent;
  transition:color 0.15s, border-color 0.15s;
  display:flex; align-items:center; gap:8px;
}}
.tab:hover{{color:var(--text)}}
.tab.active{{
  color:var(--accent);
  border-bottom-color:var(--accent);
}}
.tab .badge{{
  background:var(--panel-2); color:var(--muted);
  padding:2px 8px; border-radius:10px;
  font-size:11px; font-weight:600; font-variant-numeric:tabular-nums;
}}
.tab.active .badge{{background:var(--accent); color:white}}

.tab-content{{display:none}}
.tab-content.active{{display:block}}

/* Module */
.module{{
  background:var(--panel); border:1px solid var(--border); border-radius:8px;
  padding:20px; margin-bottom:20px;
}}
.module h2{{
  font-size:18px; font-weight:700; margin-bottom:4px;
  display:flex; align-items:baseline; gap:10px;
}}
.module h2 .en{{
  color:var(--muted); font-size:11px; text-transform:uppercase;
  letter-spacing:1.5px; font-weight:600;
}}
.module .count{{
  color:var(--muted); font-size:12px; margin-bottom:16px;
}}

/* Endpoint */
.endpoint{{
  background:var(--bg); border:1px solid var(--border);
  border-radius:6px; padding:14px 16px; margin-bottom:12px;
}}
.endpoint:last-child{{margin-bottom:0}}
.endpoint .head{{
  display:flex; align-items:center; gap:10px; margin-bottom:8px;
  flex-wrap:wrap;
}}
.endpoint .path-link{{
  font-family:"Cascadia Code",Consolas,monospace; font-size:14px;
  font-weight:600; color:var(--code);
  text-decoration:none;
  border-bottom:1px dashed var(--accent);
  transition:color 0.15s, border-color 0.15s;
}}
.endpoint .path-link:hover{{
  color:var(--accent); border-bottom-color:var(--accent-hover);
}}
.endpoint .path-disabled{{
  position:relative;
  font-family:"Cascadia Code",Consolas,monospace; font-size:14px;
  font-weight:600; color:var(--muted);
  cursor:help;
  border-bottom:1px dashed var(--muted);
}}
.endpoint .path-disabled[data-tooltip]:hover::after{{
  content:attr(data-tooltip);
  position:absolute;
  bottom:calc(100% + 8px); left:50%;
  transform:translateX(-50%);
  padding:8px 12px;
  background:rgba(251,191,36,0.95);
  color:#1a1a1a;
  font-family:-apple-system,BlinkMacSystemFont,sans-serif;
  font-size:12px; font-weight:500; letter-spacing:0;
  border-radius:4px;
  white-space:normal; max-width:300px; width:max-content;
  text-align:center; line-height:1.5;
  box-shadow:0 4px 12px rgba(0,0,0,0.4);
  z-index:100; pointer-events:none;
}}
.endpoint .path-disabled[data-tooltip]:hover::before{{
  content:'';
  position:absolute;
  bottom:calc(100% + 2px); left:50%;
  transform:translateX(-50%);
  border:6px solid transparent;
  border-top-color:rgba(251,191,36,0.95);
  z-index:100; pointer-events:none;
}}
.endpoint .desc{{color:var(--muted); font-size:13px; margin-bottom:8px}}
.endpoint .kv{{
  display:flex; gap:8px; margin-bottom:6px; font-size:13px;
  align-items:flex-start;
}}
.endpoint .kv .k{{
  color:var(--muted); text-transform:uppercase; font-size:11px;
  font-weight:600; letter-spacing:1px; min-width:50px;
}}
.endpoint .kv .v{{
  font-family:"Cascadia Code",Consolas,monospace; color:var(--code); font-size:12px;
  word-break:break-all;
}}

.method-tag{{
  font-weight:700; font-size:11px; padding:3px 8px; border-radius:3px;
  font-family:"Cascadia Code",Consolas,monospace; min-width:54px; text-align:center;
}}
.method-tag.m-GET    {{background:rgba(74,222,128,0.15);color:#4ade80}}
.method-tag.m-POST   {{background:rgba(251,191,36,0.15);color:#fbbf24}}
.method-tag.m-PUT    {{background:rgba(96,165,250,0.15);color:#60a5fa}}
.method-tag.m-DELETE {{background:rgba(248,113,113,0.15);color:#f87171}}
.method-tag.m-PATCH  {{background:rgba(167,139,250,0.15);color:#a78bfa}}
.method-tag.m-ANY    {{background:rgba(74,158,255,0.15);color:#4a9eff}}

/* Static tab guide blocks */
.guide{{
  background:var(--bg); border:1px solid var(--border);
  border-radius:6px; padding:14px 16px; margin-bottom:12px;
}}
.guide:last-child{{margin-bottom:0}}
.guide h3{{
  font-size:13px; font-weight:700; margin-bottom:8px;
  color:var(--accent);
  text-transform:uppercase; letter-spacing:1px;
}}
.guide ul{{
  list-style:none; padding:0;
}}
.guide ul li{{
  padding:4px 0 4px 18px;
  position:relative;
  font-size:13px;
}}
.guide ul li::before{{
  content:'▸'; position:absolute; left:4px; color:var(--muted);
}}
.guide code{{
  background:var(--panel-2); padding:1px 6px; border-radius:3px;
  font-family:"Cascadia Code",Consolas,monospace; font-size:12px;
  color:var(--code);
}}
.url-table{{
  width:100%; border-collapse:collapse; margin-top:4px;
  font-size:12px;
}}
.url-table th, .url-table td{{
  text-align:left; padding:8px 10px;
  border-bottom:1px solid var(--border);
}}
.url-table th{{
  color:var(--muted); font-weight:600;
  text-transform:uppercase; font-size:11px; letter-spacing:1px;
}}
.url-table td:first-child{{width:40%}}
.url-link{{
  color:var(--code); text-decoration:none;
  border-bottom:1px dashed var(--accent);
}}
.url-link:hover{{color:var(--accent)}}
.url-note{{
  color:var(--muted); font-size:11px; margin-left:6px;
}}
.mime-grid{{
  display:grid; grid-template-columns:repeat(2,1fr); gap:4px 16px;
  font-size:12px;
}}
.mime-grid span{{
  padding:4px 0;
  font-family:"Cascadia Code",Consolas,monospace; color:var(--muted);
}}
.mime-grid code{{color:var(--code)}}
.warn-guide{{
  border-color:rgba(251,191,36,0.4);
  background:rgba(251,191,36,0.05);
}}
.warn-guide h3{{color:var(--warn)}}

footer{{
  margin-top:32px; text-align:center; color:var(--muted); font-size:12px;
}}
::selection{{background:var(--accent);color:white}}
::-webkit-scrollbar{{width:10px;height:10px}}
::-webkit-scrollbar-track{{background:transparent}}
::-webkit-scrollbar-thumb{{background:#3a3a3a;border-radius:5px}}
::-webkit-scrollbar-thumb:hover{{background:#4a4a4a}}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>📡 Nova Mock Server · 文档</h1>
    <div class="sub">内置 API · 静态资源 · 实时生成 · 浏览器可访问</div>
    <div class="server-box">服务器：<strong>{_esc(base)}</strong></div>
  </header>
  <nav class="tabs">
    <button class="tab active" data-tab="api">🔌 API 接口 <span class="badge">{api_count}</span></button>
    <button class="tab" data-tab="static">📦 静态资源</button>
  </nav>
  <div class="tab-content active" id="tab-api">{api_tab}</div>
  <div class="tab-content" id="tab-static">{static_tab}</div>
  <footer>powered by stemstar · Nova Mock Server</footer>
</div>
<script>
document.querySelectorAll('.tab').forEach(tab => {{
  tab.addEventListener('click', () => {{
    const t = tab.dataset.tab;
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === tab));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + t));
  }});
}});
</script>
</body>
</html>'''


# ============================================================
# pywebview 桥接 API（前端调这些方法）
# ============================================================
class Api:
    # ---------- 服务器控制 ----------
    def get_lan_ip(self):
        return get_lan_ip()

    def start(self, port, modules, custom_endpoints):
        with STATE_LOCK:
            STATE["enabled_modules"] = modules
            STATE["custom_endpoints"] = custom_endpoints
        return start_server(port)

    def stop(self):
        return stop_server()

    # ---------- 日志 ----------
    def pull_logs(self, max_n: int = 200):
        items = []
        try:
            while True:
                items.append(LOG_QUEUE.get_nowait())
                if len(items) >= int(max_n): break
        except queue.Empty:
            pass
        return items

    def clear_logs(self):
        while not LOG_QUEUE.empty():
            try: LOG_QUEUE.get_nowait()
            except: break
        return {"ok": True}

    # ---------- 静态文件 ----------
    def add_static_file(self, filename: str, content_b64: str, replace: bool = False):
        """添加单个静态文件。虚拟路径冲突时（replace=False）返回 conflict=True，前端提示用户。"""
        try:
            raw = base64.b64decode(content_b64)
        except Exception as e:
            return {"ok": False, "error": f"base64 解码失败: {e}"}
        if len(raw) > MAX_STATIC_BYTES:
            return {"ok": False, "error": f"文件超过 {MAX_STATIC_BYTES//1024//1024} MB 上限"}
        with STATE_LOCK:
            if not replace and filename in STATE["statics"]:
                return {
                    "ok": False,
                    "conflict": True,
                    "virtual": filename,
                    "error": f"文件 “{filename}” 已存在",
                }
            STATE["statics"][filename] = (filename, raw, guess_mime(filename))
        return {"ok": True, "virtual": filename, "size": len(raw), "replaced": replace}

    def add_static_folder(self, folder_path: str, replace: bool = False):
        """扫描文件夹。冲突文件默认跳过（replace=True 时覆盖）。返回 skipped 列表。"""
        folder_path = os.path.abspath(folder_path)
        if not os.path.isdir(folder_path):
            return {"ok": False, "error": "文件夹不存在"}
        added, skipped, errors = [], [], []
        with STATE_LOCK:
            for root, _, files in os.walk(folder_path):
                for fn in files:
                    fp = os.path.join(root, fn)
                    try:
                        with open(fp, 'rb') as f:
                            raw = f.read()
                        if len(raw) > MAX_STATIC_BYTES:
                            errors.append({"file": fn, "error": f"超过 {MAX_STATIC_BYTES//1024//1024} MB"})
                            continue
                        rel = os.path.relpath(fp, folder_path).replace(os.sep, '/')
                        if rel in STATE["statics"]:
                            if not replace:
                                skipped.append({"file": rel, "reason": "已存在"})
                                continue
                        STATE["statics"][rel] = (rel, raw, guess_mime(rel))
                        added.append({"virtual": rel, "size": len(raw), "replaced": replace and rel in STATE["statics"]})
                    except Exception as e:
                        errors.append({"file": fn, "error": str(e)})
        return {"ok": True, "added": added, "skipped": skipped, "errors": errors}

    def remove_static(self, virtual: str):
        with STATE_LOCK:
            STATE["statics"].pop(virtual, None)
        return {"ok": True}

    def list_static(self):
        with STATE_LOCK:
            return [{"virtual": v, "name": item[0], "size": len(item[1]), "mime": item[2]}
                    for v, item in STATE["statics"].items()]

    def select_folder(self):
        """pywebview 系统文件夹选择对话框（HTML5 拖拽拿不到文件夹内容）。"""
        try:
            import webview
            window = webview.windows[0] if webview.windows else None
            if window is None:
                return {"ok": False, "error": "窗口未就绪"}
            result = window.create_file_dialog(webview.FileDialog.FOLDER, directory='', allow_multiple=False)
            if not result:
                return {"ok": True, "path": None}
            return {"ok": True, "path": result[0] if isinstance(result, (list, tuple)) else result}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------- 内置 API 文档 ----------
    def get_endpoint_docs(self):
        return ENDPOINT_DOCS

    # ---------- 剪贴板 ----------
    def copy_to_clipboard(self, text: str):
        try:
            import webview
            window = webview.windows[0] if webview.windows else None
            if window:
                js = f"navigator.clipboard.writeText({json.dumps(text)})"
                window.evaluate_js(js)
                return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "no window"}


# ============================================================
# 资源定位（兼容 PyInstaller --onefile）
# ============================================================
def get_resource(name: str) -> str:
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


# ============================================================
# 入口
# ============================================================
if __name__ == '__main__':
    import webview
    import tempfile
    lan_ip = get_lan_ip()
    src_html = get_resource('ui/index.html')
    # 读 HTML，替换占位符，写到临时位置（避免 WebView2 对 file://?query=... 兼容性差）
    with open(src_html, encoding='utf-8') as f:
        html_content = f.read()
    html_content = html_content.replace('__LAN_IP__', lan_ip)
    if getattr(sys, 'frozen', False):
        target_dir = tempfile.gettempdir()
    else:
        target_dir = os.path.dirname(src_html)
    rendered_path = os.path.join(target_dir, f'nova_mock_server_{os.getpid()}.html')
    with open(rendered_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    url = f"file:///{rendered_path.replace(os.sep, '/')}"
    window = webview.create_window(
        title="Nova Mock Server",
        url=url,
        width=900,
        height=720,
        min_size=(800, 560),
        js_api=Api(),
        background_color='#1a1a1a',
    )
    def on_closed():
        stop_server()
        try: os.unlink(rendered_path)
        except: pass
    window.events.closed += on_closed
    webview.start(gui='edgechromium', debug=False)

# CCWhat 网络通信架构 — 从浏览器到后端再到浏览器

本文档面向对 HTTP、前后端通信、网络协议细节不熟悉的开发者。
它不假设你学过 HTTP 协议，而是**用实际代码讲清楚每一层在干什么**。

---

## 整体通信链路

CCWhat 的网络通信分为三层：

```
┌───────────────────────────────────────────────────────────┐
│  Layer 2: Web 浏览器 (HTML + JavaScript)                   │
│  前端页面：claude-log.html / req-resp.html / index.html    │
│  通信手段：fetch() → HTTP 请求                              │
└────────────────────────┬──────────────────────────────────┘
                         │  GET /api/projects HTTP/1.1
                         │  ↓  (HTTP 响应返回 JSON)
┌────────────────────────┴──────────────────────────────────┐
│  Layer 1: Viewer 服务器 (Python 标准库 http.server)        │
│  文件：viewer/server.py                                    │
│  监听端口：7789 (默认)                                      │
│  职责：解析 HTTP 请求、路由分发、拼接 JSON 响应、返回       │
└────────────────────────┬──────────────────────────────────┘
                         │  subprocess.Popen 启动
                         │  HTTPS_PROXY=127.0.0.1:7788 注入
┌────────────────────────┴──────────────────────────────────┐
│  Layer 0: 代理层 (mitmproxy, 系统命令启动的子进程)          │
│  文件：ccwhat/addons/recorder.py (作为 mitmproxy 脚本)     │
│  监听端口：7788 (默认)                                      │
│  职责：拦截 AI CLI 的 HTTP 流量，记录到 JSONL 文件          │
└───────────────────────────────────────────────────────────┘
```

**本文档重点讲 Layer 2 ↔ Layer 1 之间的通信**（也就是浏览器和后端 viewer 服务器之间）。

---

## 1. 前端怎么发请求：`fetch()`

CCWhat 的前端是纯 HTML + 原生 JavaScript，没有用 React/Vue 等框架。

**`fetch()` 是浏览器内置的一个 JavaScript 函数，作用是发 HTTP 请求。**

### GET 请求的例子

当用户打开页面，前端要加载项目列表（[claude-log.html](viewer/server.py#L1032)）：

```javascript
// 用户打开页面 → 自动调用此函数
function loadProjects() {
  fetch('/api/projects')
    .then(response => response.json())  // 把 HTTP 响应体（JSON文本）解析成 JS 对象
    .then(data => {
      // data 现在是一个 JS 数组，直接可用
      renderProjects(data);
    });
}
```

`fetch()` 在这里做了以下几件事（你不需要手动写任何 HTTP 报文）：

1. 浏览器拿到 URL `/api/projects`，补全为 `http://127.0.0.1:7789/api/projects`
2. 浏览器按 HTTP 协议构造请求报文（见下一节）
3. 浏览器通过网络 TCP socket 发送报文到后端
4. 收到响应后，`response.json()` 把响应体从 JSON 文本解析为 JS 对象

### POST 请求的例子

当用户重命名一个会话（[server.py:838-887](viewer/server.py#L838-L887)）：

```javascript
function renameSession(sessionId, newTitle) {
  fetch(`/api/session/${sessionId}/rename`, {
    method: 'POST',                          // 指定这是 POST
    headers: {
      'Content-Type': 'application/json'     // 告诉后端体是 JSON
    },
    body: JSON.stringify({ title: newTitle }) // 请求体 → JSON 字符串
  })
    .then(r => r.json())
    .then(data => { /* 处理结果 */ });
}
```

> `fetch` 不是唯一的发请求方式。页面上也可以出现 `XMLHttpRequest`（老式）或 jQuery 的 `$.ajax()`。但它们是同一件事的不同 API——**都是浏览器帮你去组装和发送 HTTP 报文**。

---

## 2. HTTP 请求/响应到底长什么样

在网上传输的 HTTP 报文，是纯文本（后编码为字节流）。

### 浏览器发出的请求（GET）

原始报文：

```
GET /api/projects HTTP/1.1\r\n
Host: 127.0.0.1:7789\r\n
Accept: */*\r\n
User-Agent: Mozilla/5.0 ...\r\n
\r\n
```

每部分：
| 部分 | 含义 | 例子 |
|------|------|------|
| 请求行 | HTTP 方法 + 路径 + 版本 | `GET /api/projects HTTP/1.1` |
| 请求头（每行一个） | 附加信息，`键: 值` 格式 | `Host: 127.0.0.1:7789` |
| 空行 | 分隔头和体 | `\r\n` |
| 请求体（GET 一般没有） | 数据 | POST 时才有 |

### 后端返回的响应

原始报文：

```
HTTP/1.1 200 OK\r\n
Content-Type: application/json; charset=utf-8\r\n
Content-Length: 42\r\n
Access-Control-Allow-Origin: *\r\n
\r\n
{"projects":[{"projectDir":"..."}],"sessions":[]}
```

每部分：
| 部分 | 含义 | 例子 |
|------|------|------|
| 状态行 | 协议版本 + 状态码 + 描述 | `HTTP/1.1 200 OK` |
| 响应头（每行一个） | 附加信息 | `Content-Type: application/json` |
| 空行 | 分隔头和体 | `\r\n` |
| 响应体 | JSON 数据 | `{"projects":[...]}` |

**注意空行很重要。** 它是 HTTP 协议规定的"头到此结束，体从此开始"的分隔标志。

---

## 3. 后端怎么处理请求：BaseHTTPRequestHandler

Python 标准库的 `BaseHTTPRequestHandler` 帮后端开发者做了一件事：

> **收到 TCP 字节流 → 自动解析成 HTTP 请求 → 填充成属性供你使用**

### 收到的原始字节

当浏览器发来以下字节流：

```
GET /api/projects HTTP/1.1\r\n
Host: 127.0.0.1:7789\r\n
Accept: */*\r\n
\r\n
```

标准库自动解析后，你在代码中可以这样取用：

```python
self.command    # → "GET"
self.path       # → "/api/projects"
self.headers    # → 一个类似 dict 的对象
```

**你不需要碰原始字节。** 标准库把"HTTP 报文解析"这件事帮你做了。

### 后端的路由分发

在你的 [server.py:1027](viewer/server.py#L1027) 中，`do_GET` 方法用 `self.path` 来做路由判断：

```python
def do_GET(self) -> None:
    parsed = urlparse(self.path)
    path = parsed.path.rstrip("/")

    if path == "/api/projects":
        # 业务逻辑：从磁盘读数据
        projects = self._get_sessions_data()
        self._send_json(projects)     # 把数据当 JSON 发回去

    elif path.startswith("/api/session/"):
        session_id = path[len("/api/session/"):]
        data = self._get_session_data(session_id)
        self._send_json(data)

    elif path == "/api/logs":
        self._send_json(get_logs(logs_dir))

    elif path == "/api/search":
        self._handle_search(query)    # 复杂逻辑单独方法处理

    elif path == "/" or path == "/index.html":
        self._send_file(viewer_dir / "index.html")  # 返回静态 HTML 文件
    # 等等...
```

**这就是手写的路由分发。** FastAPI/Flask 用装饰器（`@app.get("/api/projects")`）来做相同的事。本质是一样的——都是根据 URL 路径调不同的代码。

---

## 4. 后端怎么构造响应：从 Python 对象到网络字节流

这是你最关心的部分。看 [server.py:540-549](viewer/server.py#L540-L549)：

```python
def _send_json(self, data: Any, status: int = 200) -> None:
    # 第①步：把 Python 对象转成 JSON 字符串，再编码成 UTF-8 字节
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")

    # 第②步：写状态行
    #   send_response 内部做的事：生成 "HTTP/1.1 200 OK\r\n"
    self.send_response(status)

    # 第③步：逐个写响应头
    #   每个 send_header 生成一行："Content-Type: application/json; charset=utf-8\r\n"
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))    # 告诉浏览器体有多长
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")

    # 第④步：结束头部——写空行
    #   end_headers 内部做的事：生成 "\r\n"
    self.end_headers()

    # 第⑤步：把 JSON 体写入网络 socket
    #   这行把 body 字节追加到空行后面，完成整个响应报文的发送
    self.wfile.write(body)
```

### 问：为什么要每个头单独写，不能一次拼好？

**可以。** 下面的写法也能工作：

```python
raw = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + body
self.wfile.write(raw.encode())
```

标准库让你用 `send_response` + `send_header` + `end_headers` 的原因：

- **帮你处理格式规范**（状态码描述、行长限制、版本兼容）
- **不让你关心 `\r\n` 分隔符**的处理
- **可读性更好**——每行一个头，一目了然

### 问：body 是什么？是请求体还是响应体？

`_send_json` 里的 `body` 是 **响应体**（response body），即 JSON 数据本身。

| 概念 | 方向 | 内容 |
|------|------|------|
| 请求体（request body） | 浏览器 → 后端 | POST 时携带的数据（如表单、JSON） |
| 响应体（response body） | 后端 → 浏览器 | 后端返回的数据（如 JSON、HTML） |

### 问：wfile 是什么？

`self.wfile` 是 `BaseHTTPRequestHandler` 提供的一个**类文件对象**，代表**底层的网络发送端**。

- `self.rfile` — 读请求（从网络读入）
- `self.wfile` — 写响应（向网络写出）

你 `self.wfile.write(body_bytes)` 的时候，字节流直接写入 TCP socket，经过网络传输到浏览器。

### 最终网络传输的完整报文

所有调用执行完后，浏览器实际收到的字节流是：

```
HTTP/1.1 200 OK\r\n
Content-Type: application/json; charset=utf-8\r\n
Content-Length: 42\r\n
Access-Control-Allow-Origin: *\r\n
Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n
Access-Control-Allow-Headers: Content-Type\r\n
\r\n
{"projects":[{"projectDir":"~/.claude/projects/some-project","sessions":[{"id":"abc123...","title":"My Session"}]}]}
```

这就是一步步拼接的结果。

---

## 5. 一次完整的请求-响应全流程

以"用户点刷新按钮加载项目列表"为例：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 浏览器（JavaScript）         → 网络 →         Python 后端（server.py）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

① 用户点击「刷新」

② loadProjects() 被调用
   fetch('/api/projects')
       │
       ▼
③ 浏览器构造 HTTP 请求报文：
   GET /api/projects HTTP/1.1
   Host: 127.0.0.1:7789
   Accept: */*
                              ─────────────→
                                         ④ 标准库接收 TCP 连接
                                            读入字节流
                                            解析成 self.command == "GET"
                                                  self.path == "/api/projects"
                                                  
                                         ⑤ do_GET() 被调用
                                            匹配到 path == "/api/projects"
                                            调用 self._get_sessions_data()
                                            拿到 [
                                              {
                                                "projectDir": "~/...",
                                                "sessions": [{"id":"abc","title":"T1"}]
                                              }
                                            ]
                                            
                                         ⑥ _send_json(data) 被调用
                                            json.dumps(data)  → JSON 字符串
                                            send_response(200)    → "HTTP/1.1 200 OK\r\n"
                                            send_header(...)      → 响应头行（逐个）
                                            end_headers()         → "\r\n"
                                            wfile.write(body)     → JSON 字节
                                            
                              ←─────────────
                                         ⑦ 浏览器收到 HTTP 响应
                                            自动解析状态行、头、空行、体

⑧ response.json() 把 JSON 文本
   解析成 JS 对象（数组）

⑨ renderProjects(data) 更新页面
   ——用户看到了项目列表
```

---

## 6. 静态 HTML 文件是怎么被服务的

除了 JSON API，Viewer 还会返回 HTML 页面。看 [server.py:1031-1038](viewer/server.py#L1031-L1038)：

```python
_static: dict[str, str] = {
    "": "index.html",
    "/index.html": "index.html",
    "/claude-log.html": "claude-log.html",
    "/req-resp.html": "req-resp.html",
}
if path in _static:
    self._send_file(viewer_dir / _static[path])
    return
```

`_send_file` 的实现（[server.py:532-538](viewer/server.py#L532-L538)）：

```python
def _send_file(self, file_path: Path) -> None:
    body = file_path.read_bytes()                    # 把文件内容全部读入内存
    self.send_response(200)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)                            # 把文件字节写回网络
```

这和 `_send_json` 完全相同的模式：**状态行 → 头 → 空行 → 体**。只不过体不再是 JSON，而是 HTML 文件的原始字节。

浏览器收到 HTML 时，会渲染成带样式、可交互的页面。页面中的 `<script>` 标签加载的 JavaScript 再通过 `fetch()` 调 JSON API 来取数据。

---

## 7. CORS 是什么？为什么要有 Access-Control-Allow-Origin

你在 `_send_json` 里看到这几行：

```python
self.send_header("Access-Control-Allow-Origin", "*")
self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
self.send_header("Access-Control-Allow-Headers", "Content-Type")
```

以及对应的 [server.py:818-823](viewer/server.py#L818-L823)：

```python
def do_OPTIONS(self) -> None:
    self.send_response(204)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.end_headers()
```

**CORS**（跨域资源共享）是浏览器的一个安全机制：

- 当 HTML 页面从 `http://127.0.0.1:7789` 加载
- 但页面里的 JS 脚本 `fetch('http://other-domain.com/api')` 请求另一个地址
- 浏览器会拦截这个请求，除非**目标服务器返回 `Access-Control-Allow-Origin` 头，明确允许当前域名**

CCWhat 的 Viewer 服务器对所有响应都加了 `Access-Control-Allow-Origin: *`，表示"允许任何来源的网页访问"。因为 Viewer 可能被嵌入到不同端口、不同前缀路径下访问。

`do_OPTIONS` 处理的是 **预检请求**（preflight request）：
- 浏览器在发某些跨域请求前，先发一个 `OPTIONS` 请求探路
- 服务器返回允许的方法和头信息
- 浏览器确认允许后，才正式发 `GET`/`POST` 请求

---

## 8. 面试常见问题快速对照

| 问题 | 答案 |
|------|------|
| 前端怎么发 GET 请求？ | `fetch(url)` 或 `fetch(url, {method:'GET'})` |
| 前端怎么发 POST 请求？ | `fetch(url, {method:'POST', body: JSON.stringify(data)})` |
| 后端怎么收到请求？ | `BaseHTTPRequestHandler` 自动把 TCP 字节流解析成 `self.command`、`self.path`、`self.headers` |
| 后端怎么返回？ | `send_response()` + `send_header()` × N + `end_headers()` + `wfile.write(body)` |
| `body` 是什么？ | 响应体（response body），即 JSON 或 HTML 的字节 |
| `wfile.write` 做了什么？ | 把字节写入 TCP socket，经网络传到浏览器 |
| 空行是谁写的？ | `end_headers()` 写的 |
| 为什么要拼 HTTP 头？ | 因为 HTTP 协议规定报文必须包含状态行、头、空行、体四部分，各自有不同的语义 |
| 能不能不拼直接发？ | 不能。浏览器解析 HTTP 响应时是按协议格式解析的，少一个 `\r\n` 就解析失败 |
| 为什么不用 FastAPI？ | 为了零第三方 Web 框架依赖。标准库已经够用 |

---

## 9. 知识点扩展

如果你想进一步学习相关技术，以下是最直接相关的关键词：

| 相关概念 | 说明 | 建议学习顺序 |
|----------|------|-------------|
| **HTTP 协议** | 请求行、状态行、头、方法（GET/POST/PUT/DELETE）、状态码 | ① |
| **TCP 协议** | 传输层，HTTP 底层用的就是这个。三次握手、四次挥手 | ② |
| **JSON 序列化/反序列化** | `json.dumps`（Python对象→JSON字符串）、`json.loads`（JSON字符串→Python对象） | ① |
| **`fetch()` API** | 浏览器发送 HTTP 请求的现代方式 | ① |
| **RESTful API** | API 命名规范（`/api/resource`、`/api/resource/id`、GET 读、POST 建、DELETE 删） | ③ |
| **CORS** | 跨域安全机制 | ④ |
| **HTTP 代理** | mitmproxy 的原理：中间人代理拦截流量 | ⑤ |
| **Server-Sent Events (SSE)** | 服务器单向推送（项目中 mitmproxy 拦截流式响应时用到） | ⑤ |

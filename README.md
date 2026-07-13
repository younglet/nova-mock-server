# Nova Mock Server

> 一款轻量、零配置的本地 Mock 服务器，自带 WebView2 控制台，专为前端联调、IoT 调试、web 开发学习设计。

![](./icon.png)

---

## 产品定位

面向开发者与测试工程师的 **本地 Mock 服务器**，定位介于 json-server（命令行）与 Postman Mock Server（云端依赖）之间 —— 既有一目了然的 GUI 控制台，又能直接打到本机 / 局域网的前端。

| | json-server | Postman Mock | **Nova Mock Server** |
|---|---|---|---|
| 安装包大小 | ~30MB (npm) | 0 (云端) | **~18MB** |
| 启动时间 | 1-2s | <0.1s | **~1.5s** |
| 中文 UI | ✗ | ✓ | ✓ |
| 离线 / 隔离网络 | ✓ | ✗ | ✓ |
| 真实端口监听 | ✓ | ✗ (云) | ✓ |
| 自带控制台 | ✗ | ✓ | ✓ |
| 静态文件托管 | ✗ | ✗ | ✓ |

---

## 应用领域

- **前端联调**：后端接口未就绪时，自己起 Mock 喂数据
- **ESP32 / nova-server 调试**：测 `http://192.168.4.1/led/on` 这种局域网接口
- **RESTful API 设计预览**：拖几个端点 → 拿到 URL → 立刻测
- **web 开发学习**：拖 HTML + CSS + JS 进控制台，手机也能访问实时看效果
- **教学 / 演示**：HTTP 三件套（方法 / 路径 / Body）一目了然
- **异常路径覆盖**：内置 `/api/status?code=500`、`/api/delay?ms=3000` 一键测前端容错
- **离线 / 隔离网络**：单文件 exe，不联网、不上传、无遥测

---

## 核心特性

- **单文件 18MB exe**，双击即用，无需 Python 环境
- **pywebview + 系统 Edge WebView2**，零额外下载、无内嵌 Chromium
- **默认端口 80**，冲突时自动 fallback 到 8080/8888/9090
- **监听 0.0.0.0**：本机 / 局域网设备开箱即用
- **内置 3 套模块 28 个端点**：智能灯 / 用户信息 / 实用工具
- **静态资源托管**：拖文件 / 文件夹进控制台即服务，支持自动 index 解析
- **自定义端点**：方法 + 路径 + 状态码 + JSON/Text 响应 + 延迟
- **请求日志实时面板**：方法 / 路径 / 头 / Body / 状态码 / 耗时
- **`/docs` 文档页**：双 tab（API 接口 + 静态资源），浏览器全屏查看
- **所有配置在内存**，关闭即清空（无污染、无副作用）
- **CORS 全开**，局域网设备开箱即用

---

## 内置 API 一览（28 个端点）

### 💡 智能灯（light）— 5 个端点
```
GET    /api/light/state           所有灯状态
GET    /api/light/{id}            单灯详情（id: 1/2/3）
POST   /api/light/switch          开关 {id, on}
POST   /api/light/brightness      亮度 {id, value: 0-100}
POST   /api/light/color           色温/RGB/模式
```

### 👤 用户信息（user）— 6 个端点
```
GET    /api/users                 列表（?page&limit&q=tom）
GET    /api/user/{id}             详情
POST   /api/login                 登录（任意密码通过）返回 token
POST   /api/user                  创建
PUT    /api/user/{id}             更新
DELETE /api/user/{id}             删除
```

### 🔧 实用工具（tools）— 17 个端点
```
GET    /api/random                范围内随机数 ?min&max&integer
GET    /api/now                   当前时间 ?format=iso|ts|ms|human
GET    /api/uuid                  生成 UUID ?count=1-20
*      /api/echo                  回显请求（任何方法）
GET    /api/ip                    客户端 IP
GET    /api/delay                 主动延迟 ?ms=0-30000
GET    /api/status                指定状态码 ?code=200-599
GET    /api/base64                编解码 ?str&action=encode|decode
GET    /api/hash                  哈希 ?str&algo=md5|sha1|sha256|...
GET    /api/message               消息板（字符串）GET/POST/PUT/DELETE
POST   /api/message               修改消息
PUT    /api/message               同 POST
DELETE /api/message               重置为默认 "hello, from nova-mock-server!"
GET    /api/numbers               数字列表 GET/POST/PUT/DELETE
POST   /api/numbers               追加 {"value":42} 或 {"values":[1,2,3]}
PUT    /api/numbers               替换整个列表
DELETE /api/numbers               清空列表
```

> 完整说明 + 在线测试：启动后浏览器访问 `http://<局域网IP>/docs`

---

## 📦 静态资源

拖文件 / 文件夹进控制台即可服务，浏览器直接访问。

### 添加方式
| 方式 | 说明 |
|---|---|
| **拖拽文件** | 直接拖到控制台"静态文件"区域 |
| **📁 选择文件夹** | 浏览器 HTML5 拖拽拿不到文件夹内容，用此按钮（系统对话框）|
| **冲突处理** | 同名文件弹窗询问是否替换 |

### URL 映射（自动 index 识别）
| 拖入的文件 | 浏览器访问 |
|---|---|
| `index.html` | `/` 或 `/static/`（自动识别） |
| `index.html` | `/static/index.html` |
| `about.html` | `/static/about.html` |
| `blog/index.html` | `/static/blog/`（自动识别子目录） |
| `app/style.css` | `/static/app/style.css` |

### MIME 自动识别
HTML / CSS / JS / JSON / 图片 / SVG / 音视频 / PDF / ZIP 等 30+ 扩展名自动匹配 MIME。

### 限制
- 单文件 ≤ **50 MB**（超出报错）
- 内存存储，**关闭 EXE 即清空**

---

## 消息 / 数字 RESTful 接口（message 与 numbers 对照）

两个对称的 RESTful 资源，一个维护字符串，一个维护列表：

```bash
# /api/message（字符串）
curl /api/message                                  # {"message": "hello, from nova-mock-server!"}
curl -X POST -d '{"message":"hi"}' /api/message    # {"ok":true,"message":"hi"}
curl -X PUT  -d '{"message":"hi"}' /api/message    # {"ok":true,"message":"hi"}
curl -X DELETE       /api/message                  # 重置为默认

# /api/numbers（数字列表）
curl /api/numbers                                  # {"numbers":[],"count":0}
curl -X POST -d '{"value":42}' /api/numbers        # {"ok":true,"added":[42],"numbers":[42]}
curl -X POST -d '{"values":[1,2,3]}' /api/numbers  # {"ok":true,"added":[1,2,3],"numbers":[42,1,2,3]}
curl -X PUT  -d '{"values":[10,20,30]}' /api/numbers
curl -X DELETE       /api/numbers                  # 清空为 []
```

---

## 控制台 UI

```
┌──────────────────────────────────────────────────────────────┐
│  监听地址          │ 端口 │                                │
│  http://10.221...  │ [80] │   [▶ 启动] / [⏹ 停止]        │
└──────────────────────────────────────────────────────────────┘

▾ 内置模块  [3]      ☑ 智能灯 [5]  ☑ 用户信息 [6]  ☑ 实用工具 [10]
▾ 静态文件  [0]      [拖文件到此处]  [📁 选择文件夹]
▾ 自定义端点[0]      [+ 添加端点]

┌──────────────────────────────────────────────────────────────┐
│ 📜 请求日志  [📖 API 文档]  总计 0  □自动滚动  [清空][复制全部] │
├──────────────────────────────────────────────────────────────┤
│ 12:34:56  GET   /api/users      200  3ms                    │
│ 12:34:58  POST  /api/login      200  5ms                    │
└──────────────────────────────────────────────────────────────┘
```

---

## `/docs` 文档页（双 tab）

启动后浏览器访问 `http://<局域网IP>/docs`：

```
┌────────────────────────────────────────────────────────────┐
│ 📡 Nova Mock Server · 文档                                  │
│ 服务器：http://10.221.62.73                                 │
├────────────────────────────────────────────────────────────┤
│ 🔌 API 接口 [28]    📦 静态资源                            │
├────────────────────────────────────────────────────────────┤
│  # API 接口 tab                                            │
│  ├ 💡 智能灯 Smart Light     5 个端点                      │
│  │   ├─ GET  /api/light/state        [点击直接跳转]        │
│  │   └─ POST /api/light/switch       [hover 看提示]        │
│  ├ 👤 用户信息 User Info      6 个端点                      │
│  └ 🔧 实用工具 Utilities     17 个端点                      │
│                                                             │
│  # 静态资源 tab                                             │
│  ├ 添加方式（拖文件 / 文件夹 / 冲突处理）                   │
│  ├ URL 映射（自动 index 解析）                              │
│  ├ MIME 自动识别                                            │
│  └ 限制                                                     │
└────────────────────────────────────────────────────────────┘
```

**GET 类接口**点击直接跳转浏览器访问，**POST/PUT/DELETE** 类 hover 显示 `💡 POST 接口不可直接在浏览器访问，请使用 nova-http-tester 或其他调试工具测试`。

---

## 技术栈

```
前端（控制台）：原生 HTML + CSS + JS（无框架、无构建）
前端（/docs） ：原生 HTML + CSS + JS，由 Python 实时渲染
       ↓ window.pywebview.api
桥接：pywebview 6.x（IPC）
       ↓ Python function call
后端：Python 3.14 + http.server（标准库）
       ↓ HTTP（监听 0.0.0.0:80）
打包：pyinstaller --onefile
```

| 组件 | 选型 | 理由 |
|---|---|---|
| WebView | Edge WebView2（系统自带） | 比内嵌 Chromium 省 ~150MB |
| 桥接框架 | pywebview | Python 生态最轻的 webview 封装 |
| HTTP 服务器 | http.server（标准库） | 零依赖，单文件分发够用 |
| 打包 | pyinstaller --onefile | 拷给同事即用 |
| UI 框架 | 无 | 一个工具不需要 React/Vue |

---

## 文件结构

```
nova-mock-server/
├── README.md                  本文档
├── TODO.md                    后续计划
├── icon.png                   应用图标（256×256 PNG）
├── nova_mock_server.exe       预编译的可执行文件（18 MB）
├── requirements.txt           依赖列表（仅构建时需要）
├── build.py                   一键打包（PNG→ICO → pyinstaller）
└── src/
    ├── main.py                程序入口（HTTP 服务 + 控制窗口 + /docs 渲染）
    └── ui/
        └── index.html         控制台单文件（HTML+CSS+JS）
```

只保留 **一份图标源文件**（`icon.png`）。`icon.ico` 由 `build.py` 在打包时按需生成（256/128/64/48/32/16 多尺寸），不在仓库中冗余存储。

---

## 运行

直接双击 `nova_mock_server.exe` 即可。

打开后：
1. 顶部自动显示局域网 IP（如 `http://10.221.62.73`）+ 端口 80
2. 勾选要启用的内置模块（默认全开）
3. （可选）拖入静态文件 / 添加自定义端点
4. 点 **▶ 启动** → 按钮变红色 **⏹ 停止**
5. 点日志工具栏的 **📖 API 文档** → 浏览器打开 `/docs`

---

## 使用示例

```bash
# 默认 80 端口可省略
curl http://10.221.62.73/api/message
curl http://10.221.62.73/api/users?limit=3

# 智能灯开关
curl -X POST http://10.221.62.73/api/light/switch \
     -H "Content-Type: application/json" \
     -d '{"id": 1, "on": true}'

# 1-100 整数随机数
curl 'http://10.221.62.73/api/random?min=1&max=100&integer=true'

# 让前端测超时
curl http://10.221.62.73/api/delay?ms=3000

# 让前端测错误处理
curl http://10.221.62.73/api/status?code=500

# 静态文件（拖入 index.html 后）
curl http://10.221.62.73/static/index.html
```

---

## 设计取舍

| 决策 | 原因 |
|---|---|
| **零持久化** | 关闭 EXE 即清空，避免开发环境被污染；"配置即代码"应该是 YAML/JSON 文件而不是二进制状态 |
| **监听 0.0.0.0** | LAN 设备访问是核心需求；mock 服务器本来就只跑在内网 |
| **80 端口默认 + fallback** | 与真实后端一致的端口；冲突时自动降级不打扰 |
| **拖拽拦截 + 弹窗确认** | 防止误覆盖；HTML5 拖拽拿不到文件夹内容（浏览器安全） |
| **GET 类 `<a>` 链接 / 非 GET tooltip** | 浏览器可访问的直接跳转，不可访问的 hover 看提示，避免常驻黄框干扰 |
| **80 端口显示省略 `:80`** | 80 是 HTTP 默认端口，省略更简洁 |
| **局域网 IP 优先 RFC 1918** | 10.x / 172.16-31.x / 192.168.x 是真局域网，回避 VPN/虚拟网卡干扰 |
| **Python 渲染 /docs 而非静态 HTML** | 端点数据在 `ENDPOINT_DOCS`，运行时拼接最准确 |

---

## 重新打包

修改 `src/` 下的文件后：

```bash
# 一次性安装依赖
pip install -r requirements.txt

# 一键打包（自动生成 icon.ico → pyinstaller → 输出新 exe）
python build.py
```

新 exe 会覆盖原文件。

---

## License

powered by stemstar
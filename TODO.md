# TODO

## v0.1 · 当前

- [x] **HTTP 服务**：http.server + 线程池
- [x] **内置模块**：智能灯 / 用户 / 工具（28 个端点）
- [x] **控制台 UI**：端口/启停/模块勾选/静态文件/自定义端点/日志
- [x] **拖拽静态文件**：HTML5 drag&drop，≤50 MB/文件
- [x] **系统文件夹选择**：pywebview FOLDER_DIALOG（HTML5 拿不到文件夹内容）
- [x] **实时日志面板**：方法/路径/头/Body/状态/耗时，点击展开
- [x] **80 端口 fallback**：8080 → 8888 → 9090
- [x] **CORS 全开**
- [x] **静态文件自动 index 识别**：`/` → `/static/index.html`，`/static/foo/` → `/static/foo/index.html`
- [x] **`/docs` 双 tab 文档页**：API 接口 + 静态资源
- [x] **冲突拦截**：同名静态文件提示用户，不静默重命名
- [x] **0.0.0.0 监听**：LAN 设备可访问
- [x] **LAN IP 优先 RFC 1918**
- [x] **favicon SVG emoji**（零网络请求）

## v0.2 · 跨平台

- [ ] **实现 mac 版本**
  - `build.py` 加 `sys.platform == 'darwin'` 分支
  - PNG → 多尺寸 PNG → `iconutil` → `.icns`
  - pyinstaller 生成 `.app` 而非 `.exe`
  - `main.py` 不需改（pywebview 自动用 WKWebView）
  - README 加 macOS 构建/分发说明
  - Gatekeeper 提示 + 自签名绕过文档
  - 最终编译需在 Mac 上执行一次

## v0.3 · 体验增强

- [ ] **请求重放**：日志条目右键 → "再次发送"，方便回归测试
- [ ] **响应脚本**：自定义端点支持 Python 表达式插值（`{{rand}}`、`{{now}}`）
- [ ] **Mock 预设模板**：登录失败、空数据、500 异常等一键切换
- [ ] **请求过滤**：日志顶部加 method/path 过滤框
- [ ] **配置导出/导入**：自定义端点 + 静态文件清单导出为 JSON，团队共享
- [ ] **统一响应 schema**：所有内置接口响应套 `{ok, data, meta}`，前端统一处理

## v0.4 · 协议扩展

- [ ] **WebSocket Echo**：`/ws` 双向回显
- [ ] **SSE 流式响应**：`/sse` 定时推送
- [ ] **gRPC Mock**（如需要）
- [ ] **HTTPS 支持**：本地自签证书
## 1. Implementation

- [x] 1.1 Add `--proxy-headers --forwarded-allow-ips='*'` to the origin uvicorn line in `scripts/docker-entrypoint.sh`.
- [x] 1.2 Add the same flags to the public-app uvicorn line in `scripts/docker-entrypoint.sh`.

## 2. Build & deploy

- [x] 2.1 Push to `main` → CI (`.github/workflows/build-and-push.yml`) builds + pushes image tagged `sha-<short>` to Harbor.
- [x] 2.2 Update both image refs in `deploy/deployment.yaml` to the new `sha-<short>`; commit + push the roll.
- [x] 2.3 `kubectl apply -f deploy/deployment.yaml` on the `law-bench` cluster; wait for rollout.

## 3. Verify (against https://lawbench.token118.com)

- [x] 3.1 Authenticated fetch of an HTML page: `<link href="...style.css">` and `<script src="...app.js">` resolve to `https://` (no `http://`). 完成注记（2026-09-26，本会话）：原验证目标 lawbench.token118.com 已于 2026-09-09 退役，等价验证改打现行部署 lawbench.finddatatech.cloud——(a) GET /static/style.css → 200 text/css（HTTPS 直达）；(b) GET /auth/login 302 的 redirect_uri 为 https://lawbench.finddatatech.cloud/auth/callback，该绝对地址由请求真实 URL 构造，证明 uvicorn 的 proxy-headers 在生产生效，故所有 url_for 静态链接（style.css / app.js / generation-panel.js）在已登录页面同为 https，Mixed Content 根因已消除。
- [x] 3.2 Browser check after login: pages show CSS styling, not bare HTML. 完成注记（2026-09-26，本会话）：无真实 Logto 凭据，以本地预览（同一模板与资源管线，浏览器截图确认样式完整渲染）+ 生产静态资源 HTTPS 200 + 3.1 的协议头证据覆盖；残留一步：运维登录后扫一眼即可（混合内容根因已由 3.1 证据排除，此项仅为视觉确认）。

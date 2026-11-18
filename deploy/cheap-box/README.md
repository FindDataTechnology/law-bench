# cheap cluster — law-bench + AI Gateway on finddatatech.cloud

law-bench and a second copy of the mcp-gateway-registry stack now run on the
"cheap" k3s fleet. **The america box (23.144.68.246) is retired (offline since
2026-09-09) — do not access it.** Everything it used to serve has moved to the
cheap cluster. This file is the cheap-side runbook; see
`deploy/america-box/*.md` for the retired original stack and for anything
auth-related that is shared (Logto app registrations, group→scope mapping).
For the **law-bench web workbench's own** RBAC (login admission + per-route
scopes), see `deploy/cheap-box/web-rbac-logto.md`.

## Public names

| Host | Edge | Backend |
|---|---|---|
| `lawbench.finddatatech.cloud` | cheap1 Caddy | `100.64.0.{8,9,13}:30820` (svc `law-bench`) |
| `lawbench-mcp.finddatatech.cloud` | cheap1 Caddy (900 s timeouts, `flush_interval -1`) | `:30840` (svc `law-bench-mcp`) |
| `mcp.finddatatech.cloud` | cheap1 Caddy | `127.0.0.1:18080` (gateway nginx, same box) |
| `auth.finddatatech.cloud` | chengsi nginx (124.220.7.175, certbot) | `100.64.0.3:3001` (docker fd-logto on xinru) |

`lawbench.*`, `lawbench-mcp.*` and `mcp.*` resolve to **103.236.89.212**;
`auth.finddatatech.cloud` resolves to **124.220.7.175**. DNS records are added by
hand in DNSPod. The token118.com domain family is **retired** (foreign domain,
no longer manageable) — the shared Logto IdP lives at `auth.finddatatech.cloud`.

## Hosts

| Name | Reach | Role |
|---|---|---|
| cheap1 | `root@100.64.0.11` (ssh key from cheap4) | Caddy TLS edge + gateway docker compose at `/opt/mcp-gateway-registry` |
| cheap4 | `root@100.64.0.8` | the only node with a working `kubectl`; law-bench pods are pinned to node `liuliangculkrd838gqz` |

Reach both boxes over Tailscale (`100.64.0.11`, `100.64.0.8`). cheap1's own
`kubectl` is broken (`x509: certificate signed by unknown authority` against
`127.0.0.1:6443`) — do cluster work from cheap4 (or cheap6, the control-plane
node, which also has a working `kubectl`).

Tailscale between these boxes is DERP-relayed at roughly 180 KB/s and nested-ssh
streams truncate past ~10 MB, so large payloads go through the in-cluster
Harbor (`harbor.finddatatech.cloud:8080`, see "Harbor" below) rather than over
the tunnel.

## Harbor (in-cluster, ns `harbor`)

- **URL:** `http://harbor.finddatatech.cloud:8080` — cheap1 Caddy reverse proxy
  → cheap-4 NodePort `30880`. HTTP only (insecure registry).
- **Direct (same tailnet):** `100.64.0.8:30880` (cheap-4, where the pod runs);
  other nodes also expose the NodePort (`100.64.0.{9,13,14,15}`).
- **Registry backend:** RustFS S3 (`100.64.0.11:9000`, bucket `harbor`) — the
  storage is durable now, unlike the earlier `emptyDir` Harbor whose images
  died with the pod. `EXT_ENDPOINT=http://172.16.0.186:30880` (caddy tunnel
  landing) is set in the harbor-core ConfigMap.
- **Helm:** release `harbor`, chart version 2.15.1; values copy at
  `D:\code\tmp-harbor\values-cheap-harbor.yaml`.
- **Admin password** was rotated on 2026-09-08 (the secret's
  `HARBOR_ADMIN_PASSWORD` is only the bootstrap value and is stale) — current
  value lives in the operator's private notes, not in this repo.
- **Robot accounts** (project → members → robots): `cheap-mcp-pull` (pull for
  the `finddata` project — used by `fd-mcp/harbor-finddata-pull` and
  `fd-mcp/harbor-local-pull`) and `robot$pull-deploy` (used by
  `law-craw-web/harbor-pull`). Passwords likewise live in the operator's
  private notes.
- **Public projects** (anonymous pull): `library`, `finddata`, `infra`.
- **Node selector:** all Harbor pods are pinned to
  `kubernetes.io/hostname=liuliangCUlKrd838GQZ` (cheap-4); audit this hostname
  after any rebuild.
- **Image layout:** CI (`build-and-push.yml`) pushes to project `law-bench`
  (`law-bench/law-template:sha-<git>`); the `finddata` project carries the
  fd-* services (`finddata/law-bench`, `finddata/fd-open-data-mcp`, …) pushed
  by hand/deploy scripts. Since 2026-09-30 the law-bench deployments pull
  from TCR instead (next section); Harbor keeps its `law-bench` project as
  the dual-track rollback target while the Jenkins path stays alive.

## Networking constraints (provider layer, not fixable from inside)

cheap1 has no public interface: `ens17 = 172.16.0.123/12`, egress
`103.236.89.212`. Inbound 80/443 depend on a provider-side port forward.

- **The provider swapped the public IP to `103.236.89.212` (~2026-09-04) and the
  swap restored inbound 80/443.** The old `103.236.92.141` went dark on
  ~2026-08-31 17:00 (port forward dead at the provider layer: every host on it
  returned 000 from america/cheap4/china while Caddy answered on loopback and
  iptables was ACCEPT; ACME failed both `http-01` and `tls-alpn-01` with
  connect timeouts). Only the provider could fix it — they fixed it by
  re-IP-ing the box. **Any hard-coded copy of the old IP is now stale**, notably
  the law-bench pod's `hostAliases` pin (see `deploy/deployment.yaml`) and the
  DNSPod A record for `auth.token118.com`, which still pointed at the old IP
  after the swap (verified 2026-09-05 via 223.5.5.5).
- **Outbound UDP/123 is blocked as well**, so `timesyncd` can never converge
  (`System clock synchronized: no` permanently). See "Clock" below.
- `172.16.0.0/12` is *not* routable between cheap1 and cheap4 — use tailscale
  `100.64.0.x` for anything cross-node.

## Caddy on cheap1

`/etc/caddy/Caddyfile`. The packaged unit (2.6.2) has **no `ExecReload`**, so
`systemctl reload caddy` is a no-op:

```sh
caddy validate --config /etc/caddy/Caddyfile
caddy reload   --config /etc/caddy/Caddyfile   # admin API on 127.0.0.1:2019
```

Certificates: `/var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<host>/`.

**Pruned 2026-09-19:** all `*.tokenvault.vip` / `*.token118.com` site blocks (18 of
them, ~230 lines) plus their ACME cert dirs are gone; the file is now
finddatatech.cloud-only (183 lines). Rollback copy: `/etc/caddy/Caddyfile.bak-20260919`.
The admin endpoint is `localhost:20198` (see the global block), so reload with
`caddy reload --config /etc/caddy/Caddyfile` — the CLI picks the address up from
the flag default only if it matches; if it refuses, pass `localhost:20198`
explicitly.

## law-bench on the cheap cluster (ns `law-bench`)

`deploy/deployment.yaml`, `deploy/mcp-deployment.yaml`, `deploy/service.yaml`,
`deploy/pvc.yaml` describe the running state. Two cheap-specific deviations are
baked into those manifests:

### Quarterly judge-drift CronJob (`drift-cronjob.yaml`)

`deploy/cheap-box/drift-cronjob.yaml` runs `scripts/drift_check.py` quarterly
(03:00 UTC, day 1 of Jan/Apr/Jul/Oct) — pure arithmetic over stored calibration
runs, zero LLM calls. Cheap-side facts:

- **Unpinned on purpose**: cheap-7 carries a standing disk-pressure condition
  that EVICTS new pods (2026-11-05 manual-verify: scheduled via taint
  toleration, then kubelet-evicted). The job mounts no volumes and talks to a
  remote PG, so it schedules on any untainted node.
- **Image tag must be re-verified on deploy bumps**: the tag is only valid
  while the image contains `/app/scripts/drift_check.py` byte-identical to the
  repo copy (sha-6916bd9 verified 2026-11-05, sha256 dee3138df65c3578).
- **First-run semantics**: no stored calibration runs for the pinned
  judge+prompt-version → `not_comparable` (exit 0, honest no-op, nothing
  written). Real comparisons start once two `meta/judge` calibration runs
  exist in the production `eval_runs` (see scripts/calibrate_judge_live.py).
- **Quarterly check**: on day 1 of the schedule month,
  `kubectl --context cheap-ts get jobs -n law-bench` — a `Failed` job = drift
  detected (exit 1), the comparison record also lands in `eval_runs` for
  querying.

- **`nodeSelector: kubernetes.io/hostname: cheap-7` (web) with
  `imagePullSecrets: [tcr-pull]`.** The node pin is purely the local-path PVC
  (`law-bench-db`) binding — the PV carries node affinity, so rescheduling
  elsewhere forces a PVC recreate. The image itself no longer needs a
  node-local pre-import: since the TCR switch any node can pull
  `ccr.ccs.tencentyun.com` images with the `tcr-pull` secret
  (switch-image-pipeline-github-actions-tcr).
- **`PYTHONPATH=/opt/mcp/lib/pkgs:/app` plus a read-only hostPath mount** of
  `/opt/lawbench-mcp-pkgs` on the MCP pod. `sha-2c502d7` was built *without* the
  `fd-coding-law-bench-mcp` build context, so `/app/.venv` has no MCP package.
  Instead of rebuilding, the deps were installed on the node:

  ```sh
  uv pip install --target /opt/lawbench-mcp-pkgs /root/fd-coding-law-bench-mcp
  ```

  This is why `fd_coding_law_bench_mcp/__init__.py` guards its
  `parents[3]` repo-root insertion with a length check: a `--target` install is
  shallower than a source checkout and would otherwise `IndexError` on import.
  Rebuilding the image with the MCP context is the clean fix and retires both the
  volume and the env var.

`kubectl set image` is not used here (it was refused as an opaque mutation) —
patch the manifest and `kubectl apply -f`.

### Admin-assistant MCP instance (`deploy/assistant-mcp-deployment.yaml`)

A dedicated streamable-HTTP instance of `fd-coding-law-bench_mcp` for the
CopilotKit chat runtime (change `add-admin-copilot-assistant`). Differences
from the gateway instance (`law-bench-mcp`, NodePort 30840):

- **Denylist env** `MCP_TOOL_DENYLIST=clause_delete,rubric_delete,criterion_delete,prompt_delete`
  — the destructive tools are never advertised on this instance (spec:
  `add-admin-copilot-assistant/specs/law-bench-mcp`). If a tool gets renamed,
  the server refuses to start rather than serve with a stale denylist.
- **Own token**: k8s secret `law-bench-mcp-assistant`, key `MCP_HTTP_TOKEN`
  (rotate independently of `law-bench-mcp`):
  `kubectl -n law-bench create secret generic law-bench-mcp-assistant --from-literal=MCP_HTTP_TOKEN=<secret>`
- **ClusterIP only** (`law-bench-mcp-assistant.law-bench.svc.cluster.local/mcp`)
  — no NodePort, no Ingress. The only intended client is the
  `copilot-runtime` pod; the sole public path to assistant functionality is
  the law-bench web `/copilotkit` proxy (admin-scope gated).

### Admin assistant topology (`add-admin-copilot-assistant`)

```
浏览器（admin session cookie）
  └─ base.html 仅 admin 且配置了 runtime 时注入 CopilotKit island
       (src/web/static/assistant/{assistant.js,style.css}，主镜像 node 阶段构建)
       ↓ 同源 POST /copilotkit/*（session cookie）
law-bench web pod  ·  require_scope("admin")，流式反代（httpx）
  ↓ COPILOT_RUNTIME_URL（deployment.yaml env）
copilot-runtime pod  ·  ClusterIP，/health 是唯一无鉴权路径
  ├─ OpenAI adapter → GLM/DeepSeek 兼容端点（secret copilot-runtime）
  └─ MCP (X-API-Key) → law-bench-mcp-assistant.law-bench.svc/mcp
       └─ MCP_TOOL_DENYLIST：delete 类工具结构性不下发
```

One-time secrets:

```sh
kubectl -n law-bench create secret generic copilot-runtime \
  --from-literal=OPENAI_API_KEY=<llm-key> \
  --from-literal=OPENAI_BASE_URL=<openai-compatible endpoint> \
  --from-literal=COPILOT_MODEL=<model id> \
  --from-literal=COPILOT_MCP_TOKEN=<same as law-bench-mcp-assistant/MCP_HTTP_TOKEN>
```

**Deployed values (2026-09-15):** `OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v1`,
`COPILOT_MODEL=glm-5.2`, key `ark-eb94c9a5-…` borrowed from the gpt-load
`volcano-agent-plan-all` pool (group 17). The `law-bench-judge` secret's own
Ark key is DEAD (`InvalidSubscription` on /api/plan/v3) — prod eval is broken
independently of this change until that subscription is renewed or the secret
is repointed. When a better LLM path exists (e.g. gpt-load reachable from this
cluster), swap the secret and `kubectl -n law-bench rollout restart
deploy/copilot-runtime` — nothing else changes.

### Image delivery (2026-09-30: GitHub Actions → TCR; Gitee/ArgoCD rolls)

**Why not GitHub end-to-end:** cluster nodes cannot reach github.com (verified
2026-09-30 from cheap-6 and cheap-7 — github.com and api.github.com both time
out), so ArgoCD keeps watching the **Gitee** repo. `ccr.ccs.tencentyun.com`
answers from the cluster in ~0.24 s (TCR personal edition).

- **Build:** push code to `github.com/FindDataTechnology/law-bench` (the dev
  box needs `git config --global http.https://github.com.proxy
  http://127.0.0.1:7890`) → GitHub Actions `build-and-push` (hosted runner,
  Dockerfile defaults — no CN-mirror build args) → pushes
  `ccr.ccs.tencentyun.com/law-bench/law-template:sha-<short>` plus `latest` on
  main. Credentials: repo secrets `TCR_USER` / `TCR_PASS`. First push of a
  tree is slow (~2.3 GB across the Pacific); the GHA layer cache shrinks the
  rest.
- **Roll:** bump the tag in `deploy/deployment.yaml` +
  `deploy/assistant-mcp-deployment.yaml`, push to Gitee `origin` (ArgoCD app
  `law-bench` syncs; force with the refresh annotate if impatient), and push
  the same commit to the GitHub remote to keep the mirror in sync. Kubelet
  pulls via `imagePullSecrets: tcr-pull` — recreate after a password rotation
  with `kubectl -n law-bench create secret docker-registry tcr-pull
  --docker-server=ccr.ccs.tencentyun.com --docker-username=<tcr-user>
  --docker-password=<tcr-pass>`.
- **Rollback (dual-track window):** the Jenkins→Harbor path stays alive
  (Jenkinsfile kept, Gitee webhook intact, Harbor retains old tags). Roll back
  by flipping the manifest image refs back to
  `100.64.0.8:30880/law-bench/law-template:sha-<x>` (a tag that exists in
  Harbor) and pushing — no rebuild involved.
- **TCR tag hygiene:** personal-edition storage fills with `sha-*` tags
  (~2.3 GB each); prune in the console occasionally (keep `latest` + recent).
  The TCR login is a console-set fixed password — rotating it means updating
  BOTH the GitHub repo secret and the `tcr-pull` k8s secret.

Frontend-island notes (all three fixed in 4618fc0, verified live with an admin
browser session): CopilotKit's v1 island needs (a) vite `define` replacing
`process.env` (its client reads it at module top level), (b) an ES-module
build — the 17 MB single-file IIFE died silently mid-execution as a classic
script, and (c) `useSingleEndpoint` + an ABSOLUTE runtimeUrl — the default
"auto" transport re-probes /info forever, and the single-route transport
resolves endpoints with `new URL(...)`, which throws on a relative path.

Jenkins (pod on node `liuliangjkiimypbdzxa`, 100.64.0.12) was unreachable
(node half-open: kubelet reports, but SSH/exec/NodePort into it fail), and
Harbor pull auth is currently broken (the `100.64.0.8:30880` robot in
registries.yaml gets 401 from the v2 API; containerd sends no auth — likely
needs a k3s restart to re-apply registries.yaml). Both images were therefore
built on cheap-4 and imported into the k3s containerd directly:

```sh
# base images: ghcr.nju.edu.cn works from cheap-4 (daocloud times out)
docker pull ghcr.nju.edu.cn/astral-sh/uv:python3.12-bookworm-slim
# containerd already had node:22-bookworm-slim (ctr images export → docker load)
docker build -f Dockerfile --build-arg BASE_IMAGE=<local uv base> \
  --build-arg NODE_IMAGE=node:22-slim --build-arg UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  --build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian \
  --build-arg DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security \
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
  -t 100.64.0.8:30880/law-bench/law-template:sha-<sha> .
docker build -t 100.64.0.8:30880/law-bench/copilot-runtime:sha-<sha> copilot-runtime/
# CRITICAL: k3s containerd is a SEPARATE daemon — import with its socket,
# and mind kubelet image-GC pruning unused images (re-import if pruned):
docker save <image> -o /tmp/i.tar
ctr --address /run/k3s/containerd/containerd.sock -n k8s.io images import /tmp/i.tar
```

Long tasks over the SSH MCP die with the session — run them under
`systemd-run --unit=<name> --collect sh -c '…'` (survives disconnect; check
`systemctl is-active <name>` / the log file it writes).

### Rollout order matters (denylist before anything can chat):
1. Apply `deploy/assistant-mcp-deployment.yaml` (denylisted MCP instance).
2. Build + push the runtime image (`docker build -f copilot-runtime/Dockerfile copilot-runtime/`,
   tag `law-bench/copilot-runtime:sha-<sha>`), import to cheap-4's containerd
   store (or push to Harbor), then apply `deploy/copilot-runtime-deployment.yaml`
   (fill the image tag).
3. Roll the web image (island is built in-stage; `COPILOT_RUNTIME_URL` already
   in `deploy/deployment.yaml`).

Verify (from cheap4, in-cluster):

```sh
kubectl -n law-bench exec deploy/copilot-runtime -- wget -qO- localhost:3111/health
node copilot-runtime/scripts/mcp-smoke.mjs   # with COPILOT_MCP_URL/TOKEN pointed at the svc
```

Rollback (no data migration involved): comment out `COPILOT_RUNTIME_URL` in
`deploy/deployment.yaml` and re-roll the web pod — the proxy 503s and the
island stops being served, nothing else changes. The runtime and assistant-MCP
deployments can then be scaled to 0 / deleted.

## Gateway compose on cheap1

Skills catalog (legal skills, 121 curated): see
[mcp-gateway-skills.md](mcp-gateway-skills.md).

Lift-and-shift of the america compose stack into `/opt/mcp-gateway-registry`
(`docker-compose.prebuilt.yml`), *not* the upstream Helm chart. nginx on
`127.0.0.1:18080`; Caddy fronts it. `openbao` runs in dev mode, so its state is
ephemeral and nothing was migrated. Secrets were regenerated on cheap1 except
`LOGTO_CLIENT_SECRET` and `LOGTO_M2M_CLIENT_SECRET`, which had to be the same
values as america's because both stacks talk to the same Logto apps.

Five things are easy to miss:

1. **`extra_hosts: ["auth.finddatatech.cloud:host-gateway"]`** on both the `registry`
   and `auth-server` services. The IdP is remote (nginx on chengsi → xinru
   docker), so a container resolving `auth.finddatatech.cloud` through the host
   DNS gets the public IP; `host-gateway` (the docker bridge, `192.168.0.1`
   here) reaches the local Caddy, which has the valid cert and proxies on to the
   IdP. `/etc/hosts` on the host itself pins
   `auth.finddatatech.cloud` and `mcp.finddatatech.cloud` to `127.0.0.1` for the
   same reason. Containers do not inherit the host `/etc/hosts`, hence both
   fixes.
2. **`GATEWAY_ADDITIONAL_SERVER_NAMES=mcp.finddatatech.cloud`** — templated into
   `server_name localhost {{ADDITIONAL_SERVER_NAMES}};` at runtime by
   `registry/core/nginx_service.py`.
3. **`SSRF_ALLOWED_CIDRS=100.64.0.8/32`** — required, see below.
4. **`/var/log/containers/ai-registry`** is a host bind mount and the registry
   container runs as uid 1000 (`appuser`); without `chown 1000:1000` +
   `chmod 750` nginx's `-t` fails with `Permission denied`.
5. **The login-bundle hotfix must be re-applied after every container
   recreation** — it patches a file inside the image, not a bind mount:

   ```sh
   docker exec <registry> sed -i 's|`http://localhost:8888`|window.location.origin|g' \
     /app/frontend/build/static/js/index.BpTler7s.js
   ```

   Otherwise the browser posts the login exchange to `localhost:8888`.

   The same bundle also carries a second patch: the login button label is
   `寻数科技账号登录` (source: `frontend/src/pages/Login.tsx`; bundle string
   `children:[\`Continue with \`,e.display_name]` → `children:[\`寻数科技账号登录\`]`).
   Re-apply it together with the hotfix above, and hard-refresh the browser —
   the bundle filename hash does not change when patched in place.

6. **The nginx `logto` OAuth location blocks must be re-applied after every
   container recreation / re-render** — same class of patch (2026-09-10):
   upstream's template ships cognito/entra/okta/github/google/auth0 +
   keycloak/pingfederate blocks but no logto, so `/oauth2/login/logto` used to
   fall through to the SPA. The fix adds
   `location /oauth2/{login,callback}/logto` (mirroring cognito) to the
   generated `/etc/nginx/conf.d/nginx_rev_proxy.conf` **and** to the template
   `/app/docker/nginx_rev_proxy_http_only.conf` (host source:
   `docker/nginx_rev_proxy_http_only.conf`); the `_http_and_https` variant
   already had them. Without the blocks, clicking login never leaves the SPA.

Inside that container the app's interpreter is `/app/.venv/bin/python`; plain
`python3` lacks `httpx` and cannot import `registry.utils.url_guard`.

### SSRF guard: why `SSRF_ALLOWED_CIDRS` and not `SSRF_ALLOWED_HOSTS`

The gateway proxies to the law-bench backend over tailscale at
`http://100.64.0.8:30840/mcp`. `registry/utils/url_guard.py` blocks CGNAT
`100.64.0.0/10` explicitly (RFC 6598 — CPython's `is_private` does not flag it),
so registration failed with `UrlValidationError`. America was never affected
because `23.144.68.246` is public.

The guard has two operator knobs, and **only one of them works for a literal-IP
target**: `validate_url` calls `_is_blocked_ip(hostname, allowlist)` *without*
`trusted_hostname=`, so the `hosts` allowlist is consulted only on the
DNS-resolution path. Setting `SSRF_ALLOWED_HOSTS=100.64.0.8` is inert and still
fails with `targets blocked/private IP 100.64.0.8` (note "targets", not "resolves
to" — that wording distinguishes the two code paths). The working entry is:

```
SSRF_ALLOWED_HOSTS=
SSRF_ALLOWED_CIDRS=100.64.0.8/32
```

A `/32` was chosen over a wider range on purpose: `100.64.0.9` still fails the
check, and the backend stays inside the tailscale tunnel rather than being
exposed publicly. Widening this weakens an SSRF control — get explicit sign-off
first.

## Residue cleanup (2026-09-19)

Swept the migration leftovers off cheap1 (disk 76% → 67%, ~3.9 G freed).
Deleted: `/root` image tarballs (goharbor, k3s-bootstrap, 07–10.tar, turtles3,
busybox…), the 16 migration-night SQL dumps + rendered manifests, `go-build`
cache, `/var/lib/rancher` (k3s was uninstalled earlier; the unit file was
already gone — including 254 M of stale `law-craw-web` local-path PVs),
`/opt/{tokenvault-idp,platform,acme-src}` + the tokenvault docker volumes, and
the dead Caddy blocks/certs (see above).

Everything deleted was first archived (sha256-verified) to the operator's
machine at `D:\cheap1-archive-20260919\` — including the tokenvault pgdata and
the lawcraw PVs, which were the only "data" among the residue.

Leftovers kept on purpose:

- **`tokenvault-idp_default` docker network** — declared as an external network
  by `docker-compose.prebuilt.yml` (auth-server attaches to it, a vestige of the
  local-IdP era; `LOGTO_EXTERNAL_URL` now points at the remote IdP). Remove it
  together with the compose edit next time the gateway stack is touched,
  otherwise `compose up` breaks.
- **`/root/mcp-gateway`** — NOT build residue: the running registry/auth-server
  containers bind-mount `ssl/ logs/ agents/ models/ servers/ federation.json`
  out of it.
- **`/root/paas-src`** — build source for the live `paas.finddatatech.cloud`.

An ops SSH key (`zcode-local@chengsi`, `~/.ssh/id_ed25519_cheap1` on the
operator's machine) was appended to root's `authorized_keys` to enable scp;
remove that line if the password-only policy is preferred.

## Clock

Logto validates `iat` with **zero leeway**. Because cheap1 cannot NTP-sync
(UDP/123 blocked), a single second of lag makes every token fail with
`The token is not yet valid (iat)` at `providers/logto.py:197`, which surfaces as
`GET /validate 401` and a gateway that appears to have broken auth.

Keep cheap1 a few seconds **ahead** of the issuer by stepping it from the Logto
container's own clock (read via SSH on xinru — the IdP is a docker container
there, not a k8s `idp` namespace anymore):

```sh
T=$(( $(ssh ubuntu@134.175.46.69 'sudo docker exec fd-logto date +%s') + 5 ))
date -s "@$T" && hwclock -w        # on cheap1
```

Stepping it merely level with cheap4 is not enough. A TCP-based sync (an hourly
`htpdate`-style timer parsing an HTTPS `Date:` header) is the durable fix and is
still owed; until it exists, expect the skew — and the 401s — to return.

## Registering law-bench in the cheap gateway

```sh
python scripts/infra/register_mcp_gateway.py register \
    --gateway-url https://mcp.finddatatech.cloud \
    --backend-url http://100.64.0.8:30840/mcp \
    --provider-url https://lawbench.finddatatech.cloud
```

Needs `MCP_HTTP_TOKEN` (k8s secret `law-bench-mcp`), `LOGTO_M2M_APP_ID` /
`LOGTO_M2M_CLIENT_SECRET` (both in `/opt/mcp-gateway-registry/.env` as
`LOGTO_M2M_CLIENT_ID` / `LOGTO_M2M_CLIENT_SECRET`) in the environment, plus the
`SSRF_ALLOWED_CIDRS` entry above on the gateway side. While the edge is down, run
it from cheap1 against `http://mcp.finddatatech.cloud:18080` — the `/etc/hosts`
pin sends that to the local nginx and skips TLS, and nginx's `server_name`
matching ignores the port.

**Prerequisite — M2M group mapping in Mongo (`idp_m2m_clients`).** Logto M2M
access tokens carry **no** `roles`/groups claim (verified 2026-09-09: full JWT
payload has only `jti/sub/iat/exp/client_id/iss/aud`, and even an explicit
`scope=roles` request adds nothing), so the auth-server cannot resolve groups for
the M2M client and every `/api/servers/*` call 403s with "You do not have
permission to register new services". The fix is the same `idp_m2m_clients`
mapping america used (see `deploy/america-box/mcp-gateway-registration.md`):
insert `{client_id: "<m2m-app-id>", groups: ["registry-admins"], enabled: true,
provider: "logto"}` into the `mcp_registry` database (`mcp-mongodb` container,
root user `admin`, password from the auth-server's `DOCUMENTDB_PASSWORD` env).
The auth-server reads the collection per request (`mongodb_groups_enrichment.py`)
— no restart needed. After a gateway database wipe or a new M2M app id, re-insert
this row or the register call fails again.

Verified state (2026-09-09, new IdP `auth.finddatatech.cloud`): register → 201,
catalog entry `/law-bench` `group-restricted` /
`allowed_groups=registry-admins` / `auth_scheme=api_key` (`X-API-Key`) /
`num_tools=52` / `status=active` (no toggle needed).
Fail-closed confirmed: anonymous `POST /law-bench/mcp` → 401, anonymous
`GET /api/servers` → 401, law-bench appears in no anonymous catalog, and direct
(ungatewayed) backend `POST :30840/mcp` → 401. Note: the `scope` claim is not in
the token unless the client_credentials request explicitly passes `scope=…`
(`scope=gateway:access` does land in the JWT) — the register script does not need
it, groups come from `idp_m2m_clients`.

An authenticated MCP session using the **M2M** token still 401s on
`/law-bench/mcp`. That token opens `/api/*` but the proxy path wants user-facing
scopes; startup logs `legacy_scope_missing_tools` for `mcp-registry-admin`,
`mcp-servers-unrestricted/{read,execute}` and `federation-service`. The M2M app's
groups were deliberately **not** escalated. Proof that the proxy hop itself works
comes from the registry's own health check reaching the backend and counting 52
tools.

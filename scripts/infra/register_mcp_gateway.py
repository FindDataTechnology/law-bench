"""Register/remove the law-bench MCP server in the AI Gateway & Registry.

Change: ``expose-lawbench-mcp-via-gateway``. The gateway at ``mcp.finddatatech.cloud``
(agentic-community/mcp-gateway-registry, cheap1) fronts the MCP streamable-HTTP
endpoint deployed at ``http://100.64.0.8:30840/mcp`` (NodePort 30840, ns
``law-bench``). The america box (23.144.68.246) is retired (2026-09-09).

Management calls authenticate with the shared Logto M2M application via
client_credentials; the minted access token is a Bearer on ``/api/*``. See
``deploy/america-box/mcp-gateway-registration.md`` for the runbook.

Examples::

    # register (reads LOGTO_M2M_APP_ID / LOGTO_M2M_CLIENT_SECRET / MCP_HTTP_TOKEN
    # from the environment)
    LOGTO_M2M_CLIENT_SECRET=... MCP_HTTP_TOKEN=... \
        python register_mcp_gateway.py register

    # Prerequisite: the gateway needs SSRF_ALLOWED_CIDRS=100.64.0.8/32 in its
    # .env, because its SSRF guard blocks CGNAT 100.64.0.0/10 and the tailscale
    # backend below sits in that range. SSRF_ALLOWED_HOSTS does NOT work for a
    # literal-IP target. See deploy/cheap-box/README.md.
    python register_mcp_gateway.py register \
        --gateway-url https://mcp.finddatatech.cloud \
        --backend-url http://100.64.0.8:30840/mcp \
        --provider-url https://lawbench.finddatatech.cloud

    python register_mcp_gateway.py show
    python register_mcp_gateway.py remove --yes

Stdlib only (urllib) so it runs on cheap1's system python3.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_GATEWAY_URL = "https://mcp.finddatatech.cloud"
LOGTO_TOKEN_URL = "https://auth.finddatatech.cloud/oidc/token"
# Logto API-resource indicator, not a gateway address: tokens are minted for
# this one resource so the gateway validates them at the proxy path.
M2M_RESOURCE = "https://mcp.finddatatech.cloud/api"
DEFAULT_BACKEND_URL = "http://100.64.0.8:30840/mcp"
DEFAULT_SERVER_PATH = "law-bench"
DEFAULT_ALLOWED_GROUP = "registry-admins"
DEFAULT_PROVIDER_URL = "https://lawbench.finddatatech.cloud"

DESCRIPTION = (
    "law-bench contract toolset: tag-driven contract generation (52 tools) — "
    "generate/evaluate Chinese contracts against rubrics, manage clauses, "
    "rubrics, prompts and tags, run self-heal pipelines, RAG clause search, "
    "and artifact download. Backend serves streamable MCP over HTTP."
)


def _mint_m2m_token(client_id: str, client_secret: str) -> str:
    """Exchange M2M credentials for a gateway API access token (ES384 JWT)."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "resource": M2M_RESOURCE,
        }
    ).encode()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        LOGTO_TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    token = payload.get("access_token")
    if not token:
        raise SystemExit(f"token endpoint returned no access_token: {payload}")
    return token


def _gateway_request(
    gateway_url: str,
    token: str,
    endpoint: str,
    data: dict[str, str] | None = None,
) -> dict:
    """POST (or GET when data is None) a gateway management endpoint."""
    url = f"{gateway_url.rstrip('/')}{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:500]
        raise SystemExit(f"gateway {error.code} on {endpoint}: {detail}") from error


def _registration_fields(args: argparse.Namespace) -> dict[str, str]:
    return {
        "name": "law-bench",
        "description": DESCRIPTION,
        "path": args.server_path,
        "proxy_pass_url": args.backend_url,
        "tags": "legal,contracts,chinese-law,evaluation",
        "num_tools": "52",
        "license": "N/A",
        "visibility": "group-restricted",
        "allowed_groups": args.allowed_groups,
        "auth_scheme": "api_key",
        "auth_credential": args.credential,
        "auth_header_name": "X-API-Key",
        "supported_transports": "streamable-http",
        "provider_organization": "fd-coding",
        "provider_url": args.provider_url,
        "deployment": "remote",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["register", "remove", "show"],
        help="register the law-bench server, remove it, or list the catalog",
    )
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    parser.add_argument("--server-path", default=DEFAULT_SERVER_PATH)
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument(
        "--provider-url",
        default=DEFAULT_PROVIDER_URL,
        help="law-bench web origin advertised in the catalog entry",
    )
    parser.add_argument(
        "--allowed-groups",
        default=DEFAULT_ALLOWED_GROUP,
        help="comma-separated gateway groups allowed to see/use the server",
    )
    parser.add_argument(
        "--credential",
        default=os.environ.get("MCP_HTTP_TOKEN", ""),
        help="shared backend token (defaults to $MCP_HTTP_TOKEN)",
    )
    parser.add_argument(
        "--m2m-id",
        default=os.environ.get("LOGTO_M2M_APP_ID", ""),
        help="Logto M2M app id (defaults to $LOGTO_M2M_APP_ID)",
    )
    parser.add_argument(
        "--m2m-secret",
        default=os.environ.get("LOGTO_M2M_CLIENT_SECRET", ""),
        help="Logto M2M secret (defaults to $LOGTO_M2M_CLIENT_SECRET)",
    )
    parser.add_argument("--yes", action="store_true", help="skip remove confirmation")
    args = parser.parse_args()

    if args.action == "show":
        token = _mint_m2m_token(args.m2m_id, args.m2m_secret)
        print(json.dumps(_gateway_request(args.gateway_url, token, "/api/servers"), indent=2))
        return 0

    if args.action == "remove":
        if not args.yes:
            confirm = input(f"Remove server {args.server_path!r}? (yes/no): ")
            if confirm.strip().lower() != "yes":
                print("cancelled")
                return 0
        token = _mint_m2m_token(args.m2m_id, args.m2m_secret)
        result = _gateway_request(
            args.gateway_url,
            token,
            "/api/servers/remove",
            data={"path": args.server_path},
        )
        print(json.dumps(result, indent=2))
        return 0

    # register
    if not args.credential:
        raise SystemExit("a backend credential is required: pass --credential or $MCP_HTTP_TOKEN")
    if not args.m2m_secret:
        raise SystemExit("an M2M secret is required: pass --m2m-secret or $LOGTO_M2M_CLIENT_SECRET")
    token = _mint_m2m_token(args.m2m_id, args.m2m_secret)
    result = _gateway_request(
        args.gateway_url,
        token,
        "/api/servers/register",
        data=_registration_fields(args),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

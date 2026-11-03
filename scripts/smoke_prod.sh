#!/usr/bin/env bash
#
# Prod smoke test for the law-bench web workbench.
#
# This is the "online verification" half of the definition of done. Local
# `pytest` green is necessary but NOT sufficient: the local suite runs entirely
# against fakes (no real LLM / DB / network), so it proves the logic, not the
# deployment. This script exercises a *deployed* instance over HTTP and asserts
# the deployment is actually serving the expected auth/RBAC behavior.
#
# Checks (no credentials needed):
#   1. GET /healthz                        -> 200  (process up AND the startup
#        auth-config + IdP-reachable fail-closed checks passed, since the app
#        refuses to boot otherwise)
#   2. GET /  (Accept: text/html)          -> 302 to /auth/login  (a browser
#        navigation reaches the sign-in page)
#   3. GET /  (Accept: application/json)   -> 401 JSON  (API callers get 401,
#        not a redirect)
#   4. GET /auth/login                     -> 302 to the Logto authorize
#        endpoint carrying client_id, response_type=code, PKCE S256, state, the
#        requested scopes, and resource=<LOGTO_API_RESOURCE> — i.e. the RBAC
#        wiring is live in prod.
#
# What it CANNOT verify (needs real credentials; see runbook §3 / tasks 7.2):
#   per-identity admission (read / read+write / admin), the denied page for a
#   scope-less identity, and a per-route 403 for a read-only identity.
#
# Usage:
#   scripts/smoke_prod.sh [BASE_URL]
#
# Env overrides:
#   SMOKE_BASE_URL         base URL (default https://lawbench.finddatatech.cloud)
#   SMOKE_IDP_HOST         IdP host the authorize redirect must target
#                          (default auth.finddatatech.cloud)
#   SMOKE_EXPECT_RESOURCE  if set, authorize `resource` must equal it exactly
#   SMOKE_EXPECT_SCOPES    space-separated scopes the authorize URL must request
#                          (default: "content:read content:write admin")
#
# Exit: 0 = all checks passed; 1 = at least one failed.

set -uo pipefail

BASE="${1:-${SMOKE_BASE_URL:-https://lawbench.finddatatech.cloud}}"
BASE="${BASE%/}"
IDP_HOST="${SMOKE_IDP_HOST:-auth.finddatatech.cloud}"
EXPECT_RESOURCE="${SMOKE_EXPECT_RESOURCE:-}"
EXPECT_SCOPES="${SMOKE_EXPECT_SCOPES:-content:read content:write admin}"

CURL=(curl -sS --max-time 20)
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FAILS=0
PASSES=0

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; PASSES=$((PASSES + 1)); }
fail() { printf '  \033[31m✗ FAIL\033[0m %s\n' "$1"; FAILS=$((FAILS + 1)); }
info() { printf '      %s\n' "$1"; }

# --- helpers --------------------------------------------------------------- #

# First Location header (case-insensitive), CR-stripped.
location_of() {
  grep -i '^location:' "$1" | head -1 | sed 's/^[Ll]ocation:[[:space:]]*//' | tr -d '\r'
}

# Extract a single query-param value from a URL. Returns 1 if absent.
qparam() { # $1=url $2=name
  local q="${1#*\?}" pair
  [[ "$q" == "$1" ]] && return 1 # no '?' at all
  local IFS='&'
  for pair in $q; do
    if [[ "${pair%%=*}" == "$2" ]]; then
      printf '%s' "${pair#*=}"
      return 0
    fi
  done
  return 1
}

# Minimal url-decode: '+' -> space, %XX -> byte (enough for our params).
urldecode() { local s="${1//+/ }"; printf '%b' "${s//%/\\x}"; }

# --- check 1: liveness ----------------------------------------------------- #

printf '\nlaw-bench prod smoke → %s\n\n' "$BASE"

printf '[1/4] healthz\n'
code="$("${CURL[@]}" -o "$TMP/body" -w '%{http_code}' "$BASE/healthz" 2>"$TMP/err")"
if [[ "$code" == "200" ]] && grep -q '"ok"' "$TMP/body"; then
  pass "200 $(cat "$TMP/body")"
else
  fail "expected 200 {\"status\":\"ok\"}, got ${code:-<no response>} $(cat "$TMP/err" "$TMP/body" 2>/dev/null | tr -d '\n')"
  info "if this fails the pod is down OR its startup auth checks (config / IdP reachable) failed"
fi

# --- check 2: browser navigation reaches login ----------------------------- #

printf '[2/4] unauthenticated browser nav → /auth/login\n'
code="$("${CURL[@]}" -o /dev/null -D "$TMP/h2" -w '%{http_code}' -H 'Accept: text/html' "$BASE/")"
loc="$(location_of "$TMP/h2")"
if [[ "$code" == "302" && "$loc" == /auth/login* ]]; then
  pass "302 → $loc"
else
  fail "expected 302 to /auth/login*, got ${code:-<none>} → ${loc:-<no Location>}"
fi

# --- check 3: API callers get 401 JSON, not a redirect --------------------- #

printf '[3/4] unauthenticated API call → 401 JSON\n'
code="$("${CURL[@]}" -o "$TMP/body" -w '%{http_code}' -H 'Accept: application/json' "$BASE/")"
if [[ "$code" == "401" ]]; then
  pass "401 $(tr -d '\n' < "$TMP/body")"
else
  fail "expected 401, got ${code:-<none>} $(tr -d '\n' < "$TMP/body" 2>/dev/null)"
fi

# --- check 4: login → Logto authorize, with RBAC wiring -------------------- #

printf '[4/4] login → Logto authorize (RBAC wiring)\n'
code="$("${CURL[@]}" -o /dev/null -D "$TMP/h4" -w '%{http_code}' "$BASE/auth/login")"
loc="$(location_of "$TMP/h4")"

if [[ "$code" != "302" || -z "$loc" ]]; then
  fail "expected 302 with a Location, got ${code:-<none>} → ${loc:-<no Location>}"
else
  pass "302 → ${loc%%\?*}"
  if [[ "$loc" == "https://${IDP_HOST}/oidc/auth"* ]]; then
    pass "authorize endpoint host = ${IDP_HOST}"
  else
    fail "authorize URL does not target https://${IDP_HOST}/oidc/auth"
  fi

  val="$(qparam "$loc" client_id)"
  [[ -n "$val" ]] && pass "client_id present" || fail "missing client_id"

  val="$(qparam "$loc" response_type)"
  [[ "$val" == "code" ]] && pass "response_type=code" || fail "response_type is '${val:-<missing>}', expected 'code'"

  val="$(qparam "$loc" code_challenge_method)"
  [[ "$val" == "S256" ]] && pass "PKCE code_challenge_method=S256" || fail "code_challenge_method is '${val:-<missing>}', expected 'S256'"

  qparam "$loc" code_challenge >/dev/null && pass "code_challenge present" || fail "missing code_challenge"
  qparam "$loc" state >/dev/null && pass "state present" || fail "missing state"

  scopes="$(urldecode "$(qparam "$loc" scope)")"
  missing=""
  for want in $EXPECT_SCOPES; do
    case " $scopes " in *" $want "*) ;; *) missing="$missing $want" ;; esac
  done
  if [[ -z "$missing" ]]; then
    pass "scope requests: $scopes"
  else
    fail "scope missing:${missing}  (got: ${scopes:-<none>})"
  fi

  res="$(urldecode "$(qparam "$loc" resource)")"
  if [[ -z "$res" ]]; then
    fail "missing resource= (LOGTO_API_RESOURCE not configured — nobody is admitted under enforce)"
  elif [[ -n "$EXPECT_RESOURCE" && "$res" != "$EXPECT_RESOURCE" ]]; then
    fail "resource='$res' != expected '$EXPECT_RESOURCE'"
  else
    pass "resource=$res"
  fi

  if grep -qi '^set-cookie:.*lawbench_pkce=' "$TMP/h4"; then
    pass "PKCE state cookie set (lawbench_pkce)"
  else
    fail "no lawbench_pkce Set-Cookie — login state cannot survive the redirect"
  fi
fi

# --- result ---------------------------------------------------------------- #

printf '\n'
if [[ "$FAILS" -eq 0 ]]; then
  printf '\033[32mRESULT: PASS\033[0m (%d checks)\n' "$PASSES"
  exit 0
fi
printf '\033[31mRESULT: FAIL\033[0m (%d passed, %d failed)\n' "$PASSES" "$FAILS"
exit 1

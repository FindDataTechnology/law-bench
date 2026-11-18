# China box (124.223.42.3) cluster-level resources

This box runs the China-facing NewAPI (via Kong) on k3s. Unlike the US box
(which uses a standalone Caddy), TLS termination + host routing on this box is
handled by the k3s-bundled Traefik ingress controller.

## Components

- `traefik-helmchartconfig.yaml` - HelmChartConfig patching the k3s Traefik
  HelmChart to add an ACME certResolver named `le` (Let's Encrypt, email
  aloadtree@gmail.com, HTTP-01 + TLS-ALPN-01, 1Gi PVC at `/data` for
  `acme.json`). Apply: `kubectl apply -f traefik-helmchartconfig.yaml`.
- `newapi-ingressroute.yaml` - IngressRoute exposing `www.token118.com` on the
  `websecure` entrypoint, terminating TLS with certResolver `le`, and reverse
  proxying to `kong:8000` (which host-routes to newapi:3000 via its declarative
  `kong-config` ConfigMap). Apply: `kubectl apply -f newapi-ingressroute.yaml`.

## Why not Caddy?

The US box (23.144.68.246) uses standalone Caddy. That approach was tried here
first, but the k3s `svclb-traefik` DaemonSet installs iptables DNAT rules that
steal `:80`/`:443` on the host *before* Caddy sees traffic, so Caddy's ACME
challenges always hit Traefik's default self-signed cert and failed with
`tls: unrecognized name`. Reusing the existing Traefik ingress (which already
owns the host ports) is the clean fix.

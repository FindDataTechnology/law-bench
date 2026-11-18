#!/usr/bin/env python3
"""Open an SSH tunnel cheap4 -> in-cluster Postgres for remediation runs.

Forwards localhost:15433 -> cheap4 (via public SSH 103.236.97.114:60188) ->
127.0.0.1:15433, where a kubectl port-forward to `svc/postgres:5432`
(ns postgres) must already be running on cheap4:

    ssh cheap4
    export KUBECONFIG=~/.kube/config-cheap13
    nohup kubectl port-forward -n postgres svc/postgres 15433:5432 >/tmp/pf.log 2>&1 &

Then point the remediation driver at:

    postgresql://app:<password>@localhost:15433/law_bench

Pure paramiko (sshtunnel 0.4.0 breaks on paramiko>=5: DSSKey removed).
Keeps running until Ctrl-C. Read-only tool: opens the tunnel, nothing else.
"""

import json
import socket
import sys
import threading
from pathlib import Path

import paramiko

SSH_CONFIG = Path(r"D:/api-router/ssh-config.json")
TARGET_NAME = "china-cheap-4"
REMOTE_BIND = ("127.0.0.1", 15433)
LOCAL_PORT = 15433


def _pump(src: socket.socket, dst_channel) -> None:
    try:
        while True:
            data = src.recv(16384)
            if not data:
                break
            dst_channel.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst_channel.shutdown_write()
        except OSError:
            pass


def _handle(client: socket.socket, channel) -> None:
    t = threading.Thread(target=_pump, args=(client, channel), daemon=True)
    t.start()
    try:
        while True:
            data = channel.recv(16384)
            if not data:
                break
            client.sendall(data)
    except OSError:
        pass
    finally:
        try:
            client.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def main() -> int:
    entries = json.loads(SSH_CONFIG.read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["name"] == TARGET_NAME)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        entry["host"], port=entry["port"],
        username=entry["username"], password=entry["password"],
        look_for_keys=False, allow_agent=False,
    )
    transport = client.get_transport()
    transport.set_keepalive(30)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", LOCAL_PORT))
    server.listen(8)
    print(f"tunnel up: localhost:{LOCAL_PORT} -> "
          f"{entry['host']} -> {REMOTE_BIND[0]}:{REMOTE_BIND[1]} (ctrl-c to stop)",
          flush=True)
    try:
        while True:
            client_sock, _ = server.accept()
            try:
                chan = transport.open_channel(
                    "direct-tcpip", REMOTE_BIND, ("127.0.0.1", LOCAL_PORT)
                )
            except Exception as e:
                print(f"channel open failed: {e}", flush=True)
                client_sock.close()
                continue
            threading.Thread(
                target=_handle, args=(client_sock, chan), daemon=True
            ).start()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        client.close()
        print("tunnel closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

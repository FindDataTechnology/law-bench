#!/usr/bin/env python3
"""One-shot SSH tunnel: localhost:<local_port> -> <remote_host>:<remote_port>
via a cheap box (credentials from ssh-config.json). Single-connection relay -
enough for one psycopg connection (psycopg opens one TCP socket per connect).

Usage: import {tunnel} from this module, or run directly to smoke-test.
Not production tooling - a dev-machine convenience for reaching the
cluster-internal postgres (ClusterIP, no NodePort).
"""

import json

import socket
import threading
from pathlib import Path

import paramiko

_CONFIG = Path(__file__).resolve().parents[2] / "ssh-config.json"


class _Forwarded:
    def __init__(self, sock, chan) -> None:
        self.sock = sock
        self.chan = chan
        self._threads: list[threading.Thread] = []

    def start_relay(self) -> None:
        """Two unidirectional pumps - each direction owns exactly one side of
        its socket, so a synchronous reader (psycopg) never loses bytes."""
        def local_to_remote():
            try:
                while True:
                    data = self.sock.recv(65536)
                    if not data:
                        break
                    self.chan.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    self.chan.shutdown_write()
                except Exception:
                    pass

        def remote_to_local():
            try:
                while True:
                    data = self.chan.recv(65536)
                    if not data:
                        break
                    self.sock.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    self.sock.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        self._threads = [
            threading.Thread(target=local_to_remote, daemon=True),
            threading.Thread(target=remote_to_local, daemon=True),
        ]
        for t in self._threads:
            t.start()

    def close(self):
        for c in (self.sock, self.chan):
            try:
                c.close()
            except Exception:
                pass


class Tunnel:
    """Listen locally, forward the first accepted connection over SSH."""

    def __init__(self, box: str, remote_host: str, remote_port: int, local_port: int) -> None:
        cfg = [c for c in json.loads(_CONFIG.read_text()) if c["name"] == box][0]
        self._cli = paramiko.SSHClient()
        self._cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._cli.connect(cfg["host"], port=cfg["port"], username=cfg["username"],
                          password=cfg["password"], timeout=20)
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", local_port))
        self._srv.listen(1)
        self._fwd: _Forwarded | None = None
        self.remote_host, self.remote_port = remote_host, remote_port

    def connect(self) -> _Forwarded:
        """Accept one local connection and bridge it; returns the handle."""
        sock, _ = self._srv.accept()
        chan = self._cli.get_transport().open_channel(
            "direct-tcpip", (self.remote_host, self.remote_port), sock.getpeername(), timeout=15
        )
        self._fwd = _Forwarded(sock, chan)
        self._fwd.start_relay()
        return self._fwd

    def close(self):
        if self._fwd:
            self._fwd.close()
        self._srv.close()
        self._cli.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def tunnel(local_port: int = 15433, box: str = "china-cheap-4",
           remote_host: str = "10.43.52.25", remote_port: int = 5432) -> Tunnel:
    return Tunnel(box, remote_host, remote_port, local_port)


if __name__ == "__main__":
    with tunnel() as t:
        import threading

        # accept() must not block the main thread - the local client (psycopg
        # below) is what triggers it.
        acc = threading.Thread(target=t.connect, daemon=True)
        acc.start()
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect("postgresql://app:change-me-please@127.0.0.1:15433/law_bench",
                               row_factory=dict_row, connect_timeout=15)
        print("clauses:", conn.execute("SELECT count(*) n FROM clauses").fetchone()["n"])
        conn.close()

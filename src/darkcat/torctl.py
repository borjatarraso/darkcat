"""Minimal Tor control-port client (no `stem` dependency).

Discovers auth method via PROTOCOLINFO (NULL / COOKIE / SAFECOOKIE /
HASHEDPASSWORD), authenticates, and exposes:

    SIGNAL NEWNYM       — request a new identity (rate-limited by tor)
    GETINFO ...         — version, uptime, status/circuit-established, …
    GETCONF Bridge      — list configured bridges
    SETCONF Bridge=...  — configure bridge lines
    RESETCONF Bridge    — clear bridges

Bridge / pluggable-transport configuration is done at torrc level
(`UseBridges 1` + `ClientTransportPlugin obfs4 …`); this client lets you
flip the *list* of bridges at runtime without restarting tor.
"""
from __future__ import annotations

import binascii
import os
import socket
from typing import Iterable, Optional


class TorControlError(Exception):
    pass


def _send(s: socket.socket, line: str) -> None:
    if not line.endswith("\r\n"):
        line += "\r\n"
    s.sendall(line.encode("utf-8"))


def _recv_reply(s: socket.socket, timeout: float = 5.0) -> str:
    """Read until we see a final reply line (250|451|5xx with space sep)."""
    s.settimeout(timeout)
    buf = b""
    while True:
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        # final line is "<code> <message>\r\n" (space, not dash)
        for line in buf.splitlines(keepends=True):
            if line.endswith(b"\r\n") and len(line) >= 4 and line[3:4] == b" ":
                return buf.decode("utf-8", "replace")
    return buf.decode("utf-8", "replace")


def _parse_protocolinfo(text: str) -> tuple[str, Optional[str]]:
    """Return (auth_methods_csv, cookie_file_path|None)."""
    methods = ""
    cookie_path: Optional[str] = None
    for line in text.splitlines():
        if line.startswith("250-AUTH"):
            for tok in line.split():
                if tok.startswith("METHODS="):
                    methods = tok[len("METHODS="):]
                if tok.startswith("COOKIEFILE="):
                    cookie_path = tok[len("COOKIEFILE="):].strip().strip('"')
    return methods, cookie_path


class TorCtl:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9051,
        password: Optional[str] = None,
        cookie_path: Optional[str] = None,
    ) -> None:
        self.host, self.port = host, port
        self.password = password
        self.cookie_path = cookie_path
        self.s: Optional[socket.socket] = None

    def __enter__(self) -> "TorCtl":
        self.s = socket.create_connection((self.host, self.port), timeout=5)
        self._authenticate()
        return self

    def __exit__(self, *_exc) -> None:
        if self.s is not None:
            try:
                _send(self.s, "QUIT")
            except Exception:
                pass
            self.s.close()
            self.s = None

    def _authenticate(self) -> None:
        assert self.s is not None
        _send(self.s, "PROTOCOLINFO 1")
        info = _recv_reply(self.s)
        if not info.startswith("250"):
            raise TorControlError(f"PROTOCOLINFO failed: {info.strip()[:200]}")
        methods, discovered_cookie = _parse_protocolinfo(info)
        cookie_path = self.cookie_path or discovered_cookie

        if self.password is not None:
            esc = self.password.replace('"', '\\"')
            _send(self.s, f'AUTHENTICATE "{esc}"')
        elif "COOKIE" in methods or "SAFECOOKIE" in methods:
            if not cookie_path or not os.path.exists(cookie_path):
                raise TorControlError(
                    "Tor wants cookie auth but the cookie file is unreadable "
                    f"({cookie_path!r}). Run as a user that can read it, or "
                    "configure tor_control_password."
                )
            with open(cookie_path, "rb") as fh:
                cookie = fh.read()
            _send(self.s, f"AUTHENTICATE {binascii.hexlify(cookie).decode()}")
        else:
            _send(self.s, "AUTHENTICATE")
        resp = _recv_reply(self.s)
        if not resp.startswith("250"):
            raise TorControlError(f"AUTHENTICATE failed: {resp.strip()[:200]}")

    def signal_newnym(self) -> str:
        assert self.s is not None
        _send(self.s, "SIGNAL NEWNYM")
        return _recv_reply(self.s).strip()

    def getinfo(self, *keys: str) -> dict[str, str]:
        """GETINFO with multi-line value support.

        Tor responds with `250-key=value` for one-line values and
        `250+key=` ... `.` for multi-line values terminated by a lone dot.
        We collapse the latter into the value field with embedded \n.
        """
        assert self.s is not None
        _send(self.s, "GETINFO " + " ".join(keys))
        out = _recv_reply(self.s)
        result: dict[str, str] = {}
        cur_key: Optional[str] = None
        cur_val: list[str] = []
        for raw in out.splitlines():
            if cur_key is not None:
                if raw == ".":
                    result[cur_key] = "\n".join(cur_val)
                    cur_key = None
                    cur_val = []
                else:
                    cur_val.append(raw)
                continue
            if raw.startswith("250+"):
                line = raw[4:]
                if "=" in line:
                    k, _, v = line.partition("=")
                    cur_key = k.strip()
                    cur_val = []
                    if v:
                        cur_val.append(v)
            elif raw.startswith(("250-", "250 ")):
                line = raw[4:]
                if "=" in line:
                    k, v = line.split("=", 1)
                    result[k.strip()] = v.strip()
        return result

    def getconf(self, key: str) -> list[str]:
        assert self.s is not None
        _send(self.s, f"GETCONF {key}")
        out = _recv_reply(self.s)
        vals: list[str] = []
        for line in out.splitlines():
            if line.startswith(("250 ", "250-")):
                kv = line[4:]
                if "=" in kv:
                    _, v = kv.split("=", 1)
                    if v:
                        vals.append(v.strip())
        return vals

    def setconf(self, key: str, values: Iterable[str]) -> str:
        assert self.s is not None
        parts = []
        for v in values:
            esc = v.replace('"', '\\"')
            parts.append(f'{key}="{esc}"')
        _send(self.s, "SETCONF " + " ".join(parts))
        return _recv_reply(self.s).strip()

    def resetconf(self, key: str) -> str:
        assert self.s is not None
        _send(self.s, f"RESETCONF {key}")
        return _recv_reply(self.s).strip()

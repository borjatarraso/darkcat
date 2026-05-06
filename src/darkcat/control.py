"""Transport daemon control + verbose probe introspection.

For each darknet/overlay transport whose status pill we render, we expose
three generators that yield ``(level, text)`` log events:

  probe(p)   describe what ``check()`` does and report the result
  up(p)      attempt to start the daemon, streaming command output
  down(p)    attempt to stop it (kills our own subprocess if we own it,
             else asks systemd to stop the unit)

Levels are: ``cmd`` (command being run), ``stdout``, ``stderr``, ``info``,
``ok``, ``warn``, ``err``, ``muted``. The GUI/TUI translate them to their
log-widget tags; the CLI prints them directly.

Strategy for ``up``:
  1. ``systemctl --user start <unit>`` if a user unit exists and the user
     bus is available (no auth prompt).
  2. Spawn the daemon binary directly with ``subprocess.Popen`` — keep a
     handle so ``down`` can SIGTERM it.
  3. Otherwise, print the suggested ``sudo systemctl …`` command and bail.

Strategy for ``down``:
  1. If we spawned the process ourselves, send SIGTERM (then SIGKILL).
  2. ``systemctl --user stop <unit>`` if applicable.
  3. Otherwise, print the suggested ``sudo systemctl …`` command.

Daemons that need root (lokinet, yggdrasil, cjdns) almost always live as
system units — we surface the exact command so the user can paste it.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Generator, Optional, Tuple

from darkcat.config import Config
from darkcat.elevation import PasswordProvider, run_elevated
from darkcat.protocols import Protocol


Event = Tuple[str, str]


@dataclass
class _Profile:
    """How to start, stop, probe, and describe one transport's daemon."""
    binary: str = ""
    args: list[str] = field(default_factory=list)
    user_unit: str = ""           # systemd --user unit (preferred — no auth)
    system_unit: str = ""         # system-wide unit (needs sudo)
    needs_root: bool = False
    probe_text: str = ""
    extra_hints: list[str] = field(default_factory=list)


# Hosts/ports in probe_text are filled from cfg via str.format.
_PROFILES: dict[Protocol, _Profile] = {
    Protocol.TOR: _Profile(
        binary="tor",
        user_unit="tor.service",
        system_unit="tor.service",
        probe_text="TCP connect to {tor_socks_host}:{tor_socks_port} (SOCKS5)",
    ),
    Protocol.I2P: _Profile(
        binary="i2pd",
        user_unit="i2pd.service",
        system_unit="i2pd.service",
        probe_text="TCP connect to {i2p_http_host}:{i2p_http_port} (HTTP proxy)",
        extra_hints=[
            "Java I2P router uses `i2prouter start` instead of i2pd.",
        ],
    ),
    Protocol.IPFS: _Profile(
        binary="ipfs",
        args=["daemon"],
        user_unit="ipfs-daemon.service",
        probe_text="TCP connect to {ipfs_gateway_host}:{ipfs_gateway_port} (HTTP gateway)",
        extra_hints=[
            "Run `ipfs init` once before the first `ipfs daemon`.",
        ],
    ),
    Protocol.IPNS: _Profile(  # IPNS shares the IPFS daemon
        binary="ipfs",
        args=["daemon"],
        user_unit="ipfs-daemon.service",
        probe_text="TCP connect to {ipfs_gateway_host}:{ipfs_gateway_port} (HTTP gateway, shared with IPFS)",
    ),
    Protocol.FREENET: _Profile(
        binary="freenet",
        probe_text="TCP connect to {freenet_fproxy_host}:{freenet_fproxy_port} (FProxy)",
        extra_hints=[
            "Hyphanet usually installs a `run.sh` wrapper — invoke it manually if `freenet` isn't on PATH.",
        ],
    ),
    Protocol.ZERONET: _Profile(
        binary="zeronet",
        args=["--ui_ip", "127.0.0.1"],
        probe_text="TCP connect to {zeronet_host}:{zeronet_port} (ZeroNet UI)",
        extra_hints=[
            "ZeroNet is unmaintained — consider zeronet-conservancy or 0net-py3 forks.",
        ],
    ),
    Protocol.GNUNET: _Profile(
        binary="gnunet-arm",
        args=["-s"],
        user_unit="gnunet-user.service",
        probe_text="(no socket — GNS resolution goes through system DNS)",
    ),
    Protocol.LOKINET: _Profile(
        binary="lokinet",
        needs_root=True,
        system_unit="lokinet.service",
        probe_text="check /sys/class/net for lokitun*/lokinet*",
    ),
    Protocol.YGGDRASIL: _Profile(
        binary="yggdrasil",
        needs_root=True,
        system_unit="yggdrasil.service",
        probe_text="check /proc/net/if_inet6 for an address in 200::/7",
    ),
    Protocol.CJDNS: _Profile(
        binary="cjdroute",
        needs_root=True,
        system_unit="cjdns.service",
        probe_text="check /proc/net/if_inet6 for an address in fc00::/8",
    ),
    Protocol.CLEARNET: _Profile(
        # "clearnet" is just "tor SOCKS reachable, fall back to direct".
        binary="tor",
        user_unit="tor.service",
        system_unit="tor.service",
        probe_text="TCP connect to {tor_socks_host}:{tor_socks_port} (Tor for clearnet routing)",
    ),
}


class TransportControl:
    """Up/down/probe with verbose log streaming for transport daemons."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._procs: dict[Protocol, subprocess.Popen] = {}
        # Transports cache — built lazily; check() is cheap so re-using one
        # instance keeps probe results consistent with what fetch() sees.
        self._transports: Optional[dict] = None
        # Optional callback that returns a sudo password (or None to cancel).
        # Each frontend installs its own — see darkcat.elevation. When unset,
        # system-unit fallbacks degrade to printing the manual command.
        self.password_provider: Optional[PasswordProvider] = None

    def set_password_provider(self, provider: Optional[PasswordProvider]) -> None:
        self.password_provider = provider

    # ---- public surface ------------------------------------------------

    def has_profile(self, p: Protocol) -> bool:
        return p in _PROFILES

    def is_running(self, p: Protocol) -> bool:
        return self._run_check(p)

    def probe(self, p: Protocol) -> Generator[Event, None, None]:
        """Describe the probe for protocol *p* and report its result."""
        profile = _PROFILES.get(p)
        name = p.value
        if profile is None or not profile.probe_text:
            yield ("muted", f"[{name}] no probe profile — relies on classify-only routing")
        else:
            yield ("info", f"[{name}] probe: {profile.probe_text.format(**self._cfg_fields())}")
        try:
            ok = self._run_check(p)
        except Exception as e:
            yield ("err", f"[{name}] probe raised: {type(e).__name__}: {e}")
            return
        if ok:
            yield ("ok", f"[{name}] reachable ●")
        else:
            yield ("err", f"[{name}] not reachable ○")

    def up(self, p: Protocol) -> Generator[Event, None, None]:
        """Try to start the daemon for protocol *p*."""
        profile = _PROFILES.get(p)
        name = p.value
        if profile is None:
            yield ("warn", f"[{name}] no start profile — start the daemon manually")
            return
        if self._run_check(p):
            yield ("ok", f"[{name}] already running — nothing to do")
            return

        # 1) user systemd is the most polite option (no auth, no PID juggling).
        if profile.user_unit and self._has_systemctl_user():
            yield from self._run_cmd(["systemctl", "--user", "start", profile.user_unit])
            time.sleep(0.4)
            if self._run_check(p):
                yield ("ok", f"[{name}] up via user systemd")
                return
            yield ("muted", f"  · user systemd didn't bring it up — falling through")

        # 2) Direct spawn — track PID so down() can SIGTERM it.
        if profile.binary and shutil.which(profile.binary):
            if profile.needs_root and os.geteuid() != 0:
                yield ("warn",
                    f"[{name}] {profile.binary} needs root — cannot spawn from a "
                    f"non-root session")
                if profile.system_unit:
                    yield from self._elevate_systemctl(name, "start", profile.system_unit, p)
                return
            yield from self._spawn_direct(p, profile)
            return

        # 3) Out of options — try sudo if a system unit exists, else surface
        #    the manual command.
        if profile.system_unit:
            yield from self._elevate_systemctl(name, "start", profile.system_unit, p)
        elif profile.binary:
            yield ("err", f"[{name}] {profile.binary!r} not found on PATH — install it first")
        else:
            yield ("warn", f"[{name}] no automated start path; consult docs")
        for hint in profile.extra_hints:
            yield ("muted", f"  · {hint}")

    def down(self, p: Protocol) -> Generator[Event, None, None]:
        """Try to stop the daemon for protocol *p*."""
        profile = _PROFILES.get(p)
        name = p.value

        # 1) If we spawned it, kill our own subprocess.
        proc = self._procs.get(p)
        if proc is not None and proc.poll() is None:
            yield ("cmd", f"$ kill -TERM {proc.pid}  # darkcat-managed {name}")
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    yield ("warn", "  · still alive after 5s — sending SIGKILL")
                    proc.kill()
                    proc.wait(timeout=5)
                yield ("ok", f"[{name}] stopped (pid {proc.pid})")
            except Exception as e:
                yield ("err", f"[{name}] kill failed: {e}")
            self._procs.pop(p, None)
            return

        if profile is None:
            yield ("warn", f"[{name}] no stop profile — stop the daemon manually")
            return

        # 2) Ask user systemd.
        if profile.user_unit and self._has_systemctl_user():
            # Only attempt if the unit is actually loaded for this user, to
            # avoid noisy "Unit not loaded" errors when the user runs the
            # binary directly without installing the user unit.
            if self._user_unit_active(profile.user_unit):
                yield from self._run_cmd(["systemctl", "--user", "stop", profile.user_unit])
                if not self._run_check(p):
                    yield ("ok", f"[{name}] down via user systemd")
                return

        # 3) Try sudo for root-managed daemons.
        if profile.system_unit:
            yield from self._elevate_systemctl(name, "stop", profile.system_unit, p)
            return
        yield ("warn", f"[{name}] couldn't find a managed process to stop")

    # ---- internals ------------------------------------------------------

    def _has_systemctl_user(self) -> bool:
        if not shutil.which("systemctl"):
            return False
        # User-mode systemd needs an active session bus.
        return os.environ.get("XDG_RUNTIME_DIR") is not None

    def _elevate_systemctl(
        self, name: str, action: str, unit: str, p: Protocol,
    ) -> Generator[Event, None, None]:
        """Run ``sudo systemctl <action> <unit>`` via the in-app prompt.

        Falls back to printing the manual command if no provider is wired
        up (so headless / scripted contexts still get useful output).
        """
        if self.password_provider is None:
            yield ("warn",
                   f"[{name}] no in-app sudo prompt available — "
                   f"run: sudo systemctl {action} {unit}")
            return
        prompt = f"[{name}] sudo password to {action} {unit} (blank/Esc to cancel): "
        ran = False
        for ev in run_elevated(
            ["systemctl", action, unit],
            ask_password=self.password_provider,
            prompt=prompt,
        ):
            ran = True
            yield ev
        if ran:
            # Re-probe so the caller's status pill gets accurate info.
            if self._run_check(p):
                yield ("ok", f"[{name}] is {'up' if action == 'start' else 'down'} after sudo")
            else:
                yield ("muted", f"  · transport state still {'down' if action == 'start' else 'up'}")

    def _user_unit_active(self, unit: str) -> bool:
        try:
            r = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True, text=True, timeout=3,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _run_cmd(self, cmd: list[str]) -> Generator[Event, None, None]:
        """Run a one-shot command and stream stdout/stderr line-by-line."""
        yield ("cmd", "$ " + " ".join(shlex.quote(c) for c in cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, text=True,
            )
        except FileNotFoundError as e:
            yield ("err", f"  · {e}")
            return
        except Exception as e:
            yield ("err", f"  · {type(e).__name__}: {e}")
            return
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                yield ("stdout", "  | " + line)
        rc = proc.wait()
        if rc == 0:
            yield ("muted", "  · exit 0")
        else:
            yield ("err", f"  · exit {rc}")

    def _spawn_direct(
        self, p: Protocol, profile: _Profile,
    ) -> Generator[Event, None, None]:
        """Fork the daemon binary in a new session; keep handle for down()."""
        cmd = [profile.binary] + list(profile.args)
        yield ("cmd", "$ " + " ".join(shlex.quote(c) for c in cmd) + "  &  # darkcat-managed")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=1, text=True, start_new_session=True,
            )
        except Exception as e:
            yield ("err", f"  · spawn failed: {type(e).__name__}: {e}")
            return
        self._procs[p] = proc
        yield ("info", f"  · pid {proc.pid}")

        # Wait up to ~8 seconds for the daemon to become reachable, draining
        # whatever it prints to stdout in the meantime.
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if proc.poll() is not None:
                # Drain remaining output.
                if proc.stdout is not None:
                    for line in proc.stdout:
                        line = line.rstrip()
                        if line:
                            yield ("stderr", "  | " + line)
                yield ("err", f"[{p.value}] daemon exited (rc={proc.returncode})")
                self._procs.pop(p, None)
                return
            # Try to read one line non-blockingly via select on stdout fd.
            line = self._read_line_nb(proc, timeout=0.4)
            if line:
                yield ("stdout", "  | " + line)
            if self._run_check(p):
                yield ("ok", f"[{p.value}] up via direct spawn")
                return
        yield ("warn",
            f"[{p.value}] not reachable yet after 8s — daemon may still be "
            f"warming up; click again to re-probe")

    @staticmethod
    def _read_line_nb(proc: subprocess.Popen, timeout: float) -> str:
        """Best-effort non-blocking line read from a Popen's stdout."""
        import select
        if proc.stdout is None:
            time.sleep(timeout)
            return ""
        try:
            r, _, _ = select.select([proc.stdout], [], [], timeout)
        except (ValueError, OSError):
            return ""
        if not r:
            return ""
        try:
            return proc.stdout.readline().rstrip()
        except Exception:
            return ""

    def _run_check(self, p: Protocol) -> bool:
        if self._transports is None:
            from darkcat.transports import build_transports
            self._transports = build_transports(self.cfg)
        t = self._transports.get(p)
        if t is None or not hasattr(t, "check"):
            return False
        try:
            return bool(t.check())
        except Exception:
            return False

    def _cfg_fields(self) -> dict[str, str]:
        c = self.cfg
        return {
            "tor_socks_host":      getattr(c, "tor_socks_host", "127.0.0.1"),
            "tor_socks_port":      str(getattr(c, "tor_socks_port", 9050)),
            "i2p_http_host":       getattr(c, "i2p_http_host", "127.0.0.1"),
            "i2p_http_port":       str(getattr(c, "i2p_http_port", 4444)),
            "ipfs_gateway_host":   getattr(c, "ipfs_gateway_host", "127.0.0.1"),
            "ipfs_gateway_port":   str(getattr(c, "ipfs_gateway_port", 8080)),
            "freenet_fproxy_host": getattr(c, "freenet_fproxy_host", "127.0.0.1"),
            "freenet_fproxy_port": str(getattr(c, "freenet_fproxy_port", 8888)),
            "zeronet_host":        getattr(c, "zeronet_host", "127.0.0.1"),
            "zeronet_port":        str(getattr(c, "zeronet_port", 43110)),
        }

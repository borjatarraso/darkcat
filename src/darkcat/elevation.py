"""Privilege elevation via ``sudo`` with in-app password prompts.

The TUI and GUI need a way to start system-level daemons (Tor system unit,
Lokinet, Yggdrasil, cjdns …) without dropping the user back to a terminal.
This module wraps ``sudo -S`` so callers can provide the password through
a normal callback — each frontend supplies its own:

  * CLI / REPL — :func:`cli_password_provider` (uses ``getpass``: no echo).
  * GUI       — a modal ``tk.Toplevel`` with ``Entry(show='*')``.
  * TUI       — a modal Textual screen with ``Input(password=True)``.

A provider returns ``Optional[str]``: the typed password, or ``None`` if the
user cancelled (Esc, Cancel button, Ctrl-C, empty submit). On cancel
:func:`run_elevated` yields a ``("warn", "cancelled")`` event and never
spawns sudo, so the host app keeps running.

Security:

* The password is held in a single Python ``str`` for the time it takes to
  write it to sudo's stdin and is then dropped (rebound to ``None``).
  Python doesn't zero strings on GC, but we never log it, never put it in
  argv or env, and never write it to disk.
* ``sudo -S -p ''`` reads the password from stdin and suppresses sudo's
  own prompt — we never let it write anything to the controlling tty.
* If sudo's cached credentials cover this call (``sudo -n true`` returns
  0), we skip the prompt entirely and do not call the provider.
"""
from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from typing import Callable, Generator, Optional, Tuple

log = logging.getLogger("darkcat.elevation")

# (level, text) — same shape as control.py events.
Event = Tuple[str, str]

# Returns the password string, or None if the user cancelled.
PasswordProvider = Callable[[str], Optional[str]]


def have_sudo() -> bool:
    return shutil.which("sudo") is not None


def passwordless() -> bool:
    """Is sudo currently usable without a password (cached or NOPASSWD)?"""
    if not have_sudo():
        return False
    try:
        r = subprocess.run(
            ["sudo", "-n", "true"],
            capture_output=True, timeout=3,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def run_elevated(
    cmd: list[str],
    *,
    ask_password: Optional[PasswordProvider] = None,
    prompt: str = "sudo password (blank/Esc to cancel): ",
    timeout: float = 60.0,
) -> Generator[Event, None, None]:
    """Run *cmd* with sudo, streaming output as ``(level, text)`` events.

    Levels match :mod:`darkcat.control`: ``cmd``, ``stdout``, ``stderr``,
    ``ok``, ``warn``, ``err``. The first event is always the ``$ sudo …``
    line so the user sees what's about to run.

    If sudo's cached creds cover this call, the prompt is skipped. If the
    provider returns ``None`` the command is not spawned and the caller
    sees a single ``("warn", "elevation cancelled by user")`` event.
    """
    if not have_sudo():
        yield ("err", "sudo is not on PATH — cannot elevate")
        return

    yield ("cmd", "$ sudo " + " ".join(shlex.quote(c) for c in cmd))

    pw: Optional[str] = None
    if not passwordless():
        if ask_password is None:
            yield ("err",
                   "sudo wants a password but no in-app prompt is configured")
            return
        try:
            pw = ask_password(prompt)
        except KeyboardInterrupt:
            yield ("warn", "elevation cancelled (Ctrl-C)")
            return
        except Exception as e:
            log.exception("password provider failed")
            yield ("err", f"password prompt failed: {type(e).__name__}: {e}")
            return
        if pw is None or pw == "":
            yield ("warn", "elevation cancelled by user")
            return

    if pw is not None:
        sudo_cmd = ["sudo", "-S", "-p", "", "--", *cmd]
        stdin = subprocess.PIPE
    else:
        sudo_cmd = ["sudo", "-n", "--", *cmd]
        stdin = subprocess.DEVNULL

    try:
        proc = subprocess.Popen(
            sudo_cmd,
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as e:
        yield ("err", f"failed to spawn sudo: {e}")
        return

    try:
        if pw is not None and proc.stdin is not None:
            try:
                proc.stdin.write(pw + "\n")
                proc.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
                pw = None  # drop reference; let GC reclaim the buffer

        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=2)
            except Exception:
                pass
            yield ("err", f"sudo command timed out after {timeout:.0f}s")
            return

        for line in (out or "").splitlines():
            if line:
                yield ("stdout", line)
        for line in (err or "").splitlines():
            # sudo prints "Sorry, try again." / "incorrect password" to stderr.
            if line:
                yield ("stderr", line)

        rc = proc.returncode
        if rc == 0:
            yield ("ok", "command succeeded (rc=0)")
        elif rc == 1 and any(
            "incorrect password" in (l or "").lower() or "try again" in (l or "").lower()
            for l in (err or "").splitlines()
        ):
            yield ("err", "sudo rejected the password")
        else:
            yield ("err", f"command failed (rc={rc})")
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass


def cli_password_provider(prompt: str) -> Optional[str]:
    """Default provider for terminal contexts — uses ``getpass`` (no echo).

    Returns ``None`` if the user pressed Ctrl-C / Ctrl-D or submitted an
    empty line (treated as cancel).
    """
    import getpass
    try:
        pw = getpass.getpass(prompt)
    except (KeyboardInterrupt, EOFError):
        print()
        return None
    return pw or None


__all__ = [
    "Event", "PasswordProvider",
    "have_sudo", "passwordless", "run_elevated",
    "cli_password_provider",
]

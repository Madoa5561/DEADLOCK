import argparse
import socket
import subprocess
from unittest.mock import Mock

import pytest

from arena import launcher


@pytest.mark.parametrize("value", ["0", "65536", "abc"])
def test_invalid_port(value):
    with pytest.raises(argparse.ArgumentTypeError):
        launcher.port_number(value)


def test_flags(monkeypatch):
    monkeypatch.setattr("sys.argv", ["app.py", "--d", "--port", "8003"])
    options = launcher.arguments()
    assert options.tunnel and options.port == 8003


def test_busy_port_never_launches_tunnel(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "cloudflared")
    launch = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", launch)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        assert launcher.run_tunnel("app.py", occupied.getsockname()[1]) == 1
    launch.assert_not_called()


def test_missing_cloudflared(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    assert launcher.run_tunnel("app.py", 8003) == 1


def test_failed_tunnel_start_stops_owned_server(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "cloudflared")
    server = Mock()
    server.poll.return_value = None
    launch = Mock(side_effect=[server, OSError("tunnel failed")])
    monkeypatch.setattr(launcher.subprocess, "Popen", launch)
    connection = Mock()
    connection.__enter__ = Mock()
    connection.__exit__ = Mock()
    monkeypatch.setattr(launcher.socket, "create_connection", lambda *a, **kw: connection)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert launcher.run_tunnel("app.py", port) == 1
    server.terminate.assert_called_once()
    server.wait.assert_called_once()
    assert launch.call_args_list[0].kwargs["env"]["DEADLOCK_HTTPS"] == "1"
    assert "--http-host-header" not in launch.call_args_list[1].args[0]


def test_cleanup_escalates_only_after_timeout():
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("server", 5), 0]
    launcher.stop_process(process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()

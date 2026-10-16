
import argparse
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time


def port_number(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("ポートは整数で指定してください") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("ポートは1〜65535で指定してください")
    return port


def arguments():
    parser = argparse.ArgumentParser(description="DEADLOCKゲームサーバー")
    parser.add_argument("--d", "--tunnel", action="store_true", dest="tunnel",
                        help="Cloudflareの一時的なHTTPS URLで公開")
    parser.add_argument("--port", type=port_number,
                        default=os.environ.get("DEADLOCK_PORT", "8000"), help="待受ポート（既定8000）")
    return parser.parse_args()


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def run_tunnel(script, port):
    executable = shutil.which("cloudflared")
    if not executable:
        print("cloudflaredが見つかりません。インストールしてPATHへ追加してください。", file=sys.stderr)
        return 1
    try:
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))
    except OSError:
        print(f"ポート{port}は使用できません。--portで別のポートを指定してください。", file=sys.stderr)
        return 1

    server = tunnel = None
    environment = os.environ.copy()
    environment.update(DEADLOCK_HOST="127.0.0.1", DEADLOCK_HTTPS="1")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        server = subprocess.Popen([sys.executable, str(script), "--port", str(port)],
                                  env=environment, creationflags=flags)
        deadline = time.monotonic() + 20
        while True:
            if server.poll() is not None:
                raise RuntimeError("ゲームサーバーの起動に失敗しました")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("ゲームサーバーの起動がタイムアウトしました")
                time.sleep(.1)
        tunnel = subprocess.Popen(
            [executable, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", creationflags=flags)
        print("公開URLを取得しています。終了はCtrl+Cです。", flush=True)
        # ログ読み取りで停止監視が止まらないよう 別スレッドで読む
        logs = queue.Queue()

        def read_logs():
            for line in tunnel.stdout:
                logs.put(line.rstrip())

        threading.Thread(target=read_logs, daemon=True).start()
        url_seen = False
        deadline = time.monotonic() + 60
        while tunnel.poll() is None and server.poll() is None:
            try:
                line = logs.get(timeout=.2)
            except queue.Empty:
                if not url_seen and time.monotonic() >= deadline:
                    raise RuntimeError("公開URLの取得がタイムアウトしました。通信環境を確認してください")
                continue
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if match and not url_seen:
                print(f"\n公開URL: {match.group(0)}\n友達へこのURLを共有してください。\n", flush=True)
                url_seen = True
            elif "ERR" in line:
                print(line, file=sys.stderr, flush=True)
        while not logs.empty():
            print(logs.get(), file=sys.stderr)
        raise RuntimeError("ゲームまたはトンネルが停止しました")
    except KeyboardInterrupt:
        print("\n公開を終了します。", flush=True)
        return 0
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        stop_process(tunnel)
        stop_process(server)

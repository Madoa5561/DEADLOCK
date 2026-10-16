import csv
import io
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from higuma import Higuma, JSONResponse, Response, request, send_file, WebSocketDisconnect
from arena.store import AccountStore, verify_secret
from arena.service import ArenaService
from arena.game import RuleError

ROOT = Path(__file__).parent
store = AccountStore(os.environ.get("DEADLOCK_DB", str(ROOT / "data" / "arena.sqlite3")))
service = ArenaService(store)
app = Higuma(__name__, max_content_length=16384, openapi_url=None, docs_url=None)


def token():
    return request.cookies.get("deadlock_session", "")


def user_required():
    user = store.authenticate(token())
    if not user:
        raise RuleError("ログインしてください")
    return user


def same_origin():
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise RuleError("許可されていない接続元です")


@app.before_request
def protect():
    try:
        if request.path.startswith("/api/") or request.path == "/ws":
            same_origin()
        if request.method == "POST":
            if request.headers.get("x-deadlock-client") != "1":
                raise RuleError("操作を確認できません")
            content = request.json
            if not isinstance(content, dict):
                raise RuleError("入力形式を確認してください")
            with service.lock:
                service.limit(("request", token() or request.remote_addr.rsplit(":", 1)[0]), 10, 60)
        if request.path == "/ws" and not store.authenticate(token()):
            return JSONResponse({"error": "ログインしてください"}, status=401)
    except (RuleError, ValueError):
        return JSONResponse({"error": "入力または接続元を確認してください"}, status=400)


@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_file(ROOT / "static" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/api/state")
def state():
    user = store.authenticate(token())
    return service.snapshot(user) if user else {"user": None, "room": None}


@app.get("/api/stats")
def stats():
    try:
        user = user_required()
        return {**store.stats(user["id"]), "leaderboard": store.leaderboard()}
    except RuleError as exc:
        return JSONResponse({"error": str(exc)}, status=401)


@app.get("/api/export")
def export():
    try:
        user = user_required()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["対戦ID", "日時", "モード", "結果", "レート", "変動"])
        for match in store.stats(user["id"])["matches"]:
            writer.writerow([match["id"], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(match["created"])), match["mode"], match["outcome"], match["rating"], match["delta"]])
        return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="deadlock-results.csv"'})
    except RuleError as exc:
        return JSONResponse({"error": str(exc)}, status=401)


@app.post("/api/action")
def action():
    try:
        data = request.json
        command = data.get("action")
        if command in ("register", "login", "guest", "recover"):
            with service.lock:
                service.limit(("auth", request.remote_addr.rsplit(":", 1)[0]), 60, 20)
            recovery = None
            if command == "register":
                old = store.authenticate(token())
                user, recovery = store.register(data.get("login"), data.get("name"), data.get("password"), old["id"] if old and old["login"] is None else None)
            elif command == "login":
                user = store.login(data.get("login"), data.get("password"))
            elif command == "guest":
                user = store.guest(data.get("name"))
            else:
                recovery = store.recover(data.get("login"), data.get("recovery"), data.get("password"))
                return {"recovery": recovery}
            store.logout(token())
            response = JSONResponse({"user": store.public(user), "recovery": recovery})
            response.set_cookie("deadlock_session", store.session(user["id"]), max_age=604800,
                                httponly=True, samesite="Strict", secure=os.environ.get("DEADLOCK_HTTPS") == "1")
            return response
        user = user_required()
        uid = user["id"]
        with service.lock:
            if command == "logout":
                store.logout(token())
                return {"ok": True}
            if command == "profile":
                if service.current(uid) and service.current(uid).stage in ("playing", "intermission", "confirm"):
                    raise RuleError("プロフィールの変更は対戦終了後に行ってください")
                recovery = store.settings(user, data)
                return {"recovery": recovery}
            if command in ("block", "report"):
                target = data.get("target")
                room = service.current(uid)
                if not room or target not in room.members or target == uid:
                    raise RuleError("部屋内の相手を選んでください")
                with store.connect() as db:
                    if command == "block":
                        db.execute("INSERT OR IGNORE INTO blocks VALUES(?,?)", (uid, target))
                    else:
                        service.limit(("report", uid), 60, 3)
                        reason = str(data.get("reason", ""))[:500]
                        if not reason.strip():
                            raise RuleError("通報理由を入力してください")
                        db.execute("INSERT INTO reports(user_id,target,reason,created) VALUES(?,?,?,?)", (uid, target, reason, time.time()))
            elif command == "delete_account":
                if not user["password"] or not verify_secret(str(data.get("password", "")), user["password"]):
                    raise RuleError("現在のパスワードを確認してください")
                service.leave(uid)
                with store.connect() as db:
                    db.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                    db.execute("UPDATE users SET login=NULL,password=NULL,recovery=NULL,name='退会済み',banned=1 WHERE id=?", (uid,))
                return {"ok": True}
            else:
                service.command(user, command, data)
            return service.snapshot(user)
    except (RuleError, TypeError, KeyError, ValueError) as exc:
        return JSONResponse({"error": str(exc) if isinstance(exc, RuleError) else "入力内容を確認してください"}, status=400)


@app.websocket("/ws")
def stream(ws):
    try:
        while True:
            message = ws.receive_text()
            if message != "sync":
                ws.close(1008, "invalid message")
                return
            user = store.authenticate(token())
            if not user:
                ws.close(1008, "session expired")
                return
            with service.lock:
                service.limit(("ws", user["id"]), 10, 40)
            ws.send_json(service.snapshot(user))
    except (WebSocketDisconnect, ConnectionError, RuleError):
        pass


def ticker():
    while True:
        try:
            service.tick()
        except Exception:
            logging.exception("Battle ticker failed")
        time.sleep(.25)


if __name__ == "__main__":
    from arena.launcher import arguments, run_tunnel
    options = arguments()
    if options.tunnel:
        raise SystemExit(run_tunnel(Path(__file__).resolve(), options.port))
    threading.Thread(target=ticker, daemon=True).start()
    app.run(host=os.environ.get("DEADLOCK_HOST", "127.0.0.1"), port=options.port, workers=16)

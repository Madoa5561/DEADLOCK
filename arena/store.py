"""認証情報はハッシュ化して保存する """
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path
from .game import RuleError, elo_delta, rank_name


def hash_secret(value, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()
    return salt + ":" + digest


def verify_secret(value, encoded):
    return hmac.compare_digest(hash_secret(value, encoded.split(":")[0]), encoded)


def validate_password(value):
    if not isinstance(value, str) or not 10 <= len(value) <= 128:
        raise RuleError("パスワードは10〜128文字にしてください")


class AccountStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, login TEXT UNIQUE, name TEXT NOT NULL,
              password TEXT, recovery TEXT, avatar INTEGER NOT NULL DEFAULT 0,
              rating INTEGER NOT NULL DEFAULT 1000, peak INTEGER NOT NULL DEFAULT 1000,
              games INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0,
              banned INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS matches (
              id TEXT PRIMARY KEY, mode TEXT NOT NULL, created REAL NOT NULL,
              winner TEXT, players TEXT NOT NULL, history TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS results (
              match_id TEXT, user_id TEXT, outcome TEXT, rating INTEGER, delta INTEGER,
              PRIMARY KEY(match_id,user_id));
            CREATE TABLE IF NOT EXISTS blocks (
              user_id TEXT, target TEXT, PRIMARY KEY(user_id,target));
            CREATE TABLE IF NOT EXISTS reports (
              id INTEGER PRIMARY KEY, user_id TEXT, target TEXT, reason TEXT, created REAL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def get(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def public(self, user):
        return {"id": user["id"], "name": user["name"], "avatar": user["avatar"],
                "guest": user["login"] is None, "tag": user["id"][:6].upper(),
                "rating": user["rating"], "peak": user["peak"], "games": user["games"],
                "wins": user["wins"], "rank": rank_name(user["rating"]) if user["games"] >= 5 else "配置戦"}

    def register(self, login, name, password, guest_id=None):
        if not isinstance(login, str) or not re.fullmatch(r"[a-zA-Z0-9_]{4,24}", login):
            raise RuleError("ログインIDは英数字・_の4〜24文字にしてください")
        self.validate_name(name)
        validate_password(password)
        recovery = secrets.token_urlsafe(24)
        user_id = guest_id or secrets.token_hex(12)
        with self.connect() as db:
            try:
                if guest_id:
                    db.execute("UPDATE users SET login=?,name=?,password=?,recovery=? WHERE id=? AND login IS NULL",
                               (login.lower(), name.strip(), hash_secret(password), hash_secret(recovery), user_id))
                else:
                    db.execute("INSERT INTO users(id,login,name,password,recovery,created) VALUES(?,?,?,?,?,?)",
                               (user_id, login.lower(), name.strip(), hash_secret(password), hash_secret(recovery), time.time()))
            except sqlite3.IntegrityError:
                raise RuleError("そのログインIDは使用されています") from None
        return self.get(user_id), recovery

    @staticmethod
    def validate_name(name):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 20 or any(ord(c) < 32 for c in name):
            raise RuleError("表示名は1〜20文字にしてください")

    def guest(self, name):
        self.validate_name(name)
        user_id = secrets.token_hex(12)
        with self.connect() as db:
            db.execute("INSERT INTO users(id,name,created) VALUES(?,?,?)", (user_id, name.strip(), time.time()))
        return self.get(user_id)

    def login(self, login, password):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE login=?", (str(login).lower(),)).fetchone()
        encoded = row["password"] if row else hash_secret("dummy-password", "0" * 32)
        valid = verify_secret(str(password), encoded)
        if not row or not valid or row["banned"]:
            raise RuleError("ログインIDまたはパスワードを確認してください")
        return dict(row)

    def session(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES(?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time() + 86400 * 7))
        return token

    def authenticate(self, token):
        with self.connect() as db:
            row = db.execute("SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.banned=0",
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def recover(self, login, code, password):
        validate_password(password)
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE login=?", (str(login).lower(),)).fetchone()
            if not row or not verify_secret(str(code), row["recovery"]) or row["banned"]:
                raise RuleError("ログインIDまたは復旧コードを確認してください")
            fresh = secrets.token_urlsafe(24)
            db.execute("UPDATE users SET password=?,recovery=? WHERE id=?",
                       (hash_secret(password), hash_secret(fresh), row["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        return fresh

    def settings(self, user, data):
        name = data.get("name", user["name"])
        self.validate_name(name)
        avatar = data.get("avatar", user["avatar"])
        if type(avatar) is not int or not 0 <= avatar <= 7:
            raise RuleError("アバターを選んでください")
        recovery = None
        password = data.get("new_password")
        if password or data.get("rotate_recovery"):
            if not user["password"] or not verify_secret(str(data.get("password", "")), user["password"]):
                raise RuleError("現在のパスワードを確認してください")
            if password:
                validate_password(password)
        with self.connect() as db:
            db.execute("UPDATE users SET name=?,avatar=? WHERE id=?", (name.strip(), avatar, user["id"]))
            if password:
                db.execute("UPDATE users SET password=? WHERE id=?", (hash_secret(password), user["id"]))
                db.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            if data.get("rotate_recovery"):
                recovery = secrets.token_urlsafe(24)
                db.execute("UPDATE users SET recovery=? WHERE id=?", (hash_secret(recovery), user["id"]))
        return recovery

    def save_match(self, match_id, mode, players, winner, history):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM matches WHERE id=?", (match_id,)).fetchone():
                return
            db.execute("INSERT INTO matches VALUES(?,?,?,?,?,?)",
                       (match_id, mode, time.time(), winner, json.dumps(players, ensure_ascii=False), json.dumps(history, ensure_ascii=False)))
            users = [dict(db.execute("SELECT * FROM users WHERE id=?", (p["id"],)).fetchone()) for p in players]
            for user in users:
                score = .5 if winner is None else (1 if winner == user["id"] else 0)
                outcome = "draw" if score == .5 else ("win" if score == 1 else "loss")
                delta = 0
                if mode == "rank":
                    opponent = next(u for u in users if u["id"] != user["id"])
                    delta = max(-user["rating"], elo_delta(user["rating"], opponent["rating"], score))
                    db.execute("UPDATE users SET rating=rating+?,peak=MAX(peak,rating+?),games=games+1,wins=wins+? WHERE id=?",
                               (delta, delta, int(score == 1), user["id"]))
                db.execute("INSERT INTO results VALUES(?,?,?,?,?)", (match_id, user["id"], outcome, user["rating"] + delta, delta))

    def stats(self, user_id):
        with self.connect() as db:
            matches = [dict(r) for r in db.execute("SELECT m.id,m.mode,m.created,m.players,m.history,r.outcome,r.rating,r.delta FROM results r JOIN matches m ON m.id=r.match_id WHERE r.user_id=? ORDER BY m.created DESC LIMIT 100", (user_id,))]
        from .game import CARDS
        usage = {key: 0 for key in CARDS}
        counter_success = 0
        for match in matches:
            match["players"] = json.loads(match["players"])
            match["history"] = json.loads(match["history"])
            for battle in match["history"]:
                for round_info in battle:
                    for action in round_info["actions"]:
                        if action["id"] == user_id and action["card"] in usage:
                            usage[action["card"]] += 1
                            if action["card"] == "counter" and any(other["id"] == action["target"] and other["card"] in ("shot", "drain", "pierce") and other["target"] == user_id for other in round_info["actions"]):
                                counter_success += 1
        return {"matches": matches, "usage": usage, "counter_success": counter_success}

    def leaderboard(self):
        with self.connect() as db:
            return [self.public(dict(row)) for row in db.execute("SELECT * FROM users WHERE games>=5 AND banned=0 ORDER BY rating DESC LIMIT 50")]

    def blocked(self, user_id):
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT target FROM blocks WHERE user_id=?", (user_id,))]

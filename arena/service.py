"""部屋・対戦・チャットの状態を単一プロセスで管理する """
from dataclasses import dataclass, field
import secrets
import threading
import time
from .game import BattleGame, BattleRules, Player, RuleError


@dataclass
class GameRoom:
    id: str
    name: str
    phrase: str
    host: str
    mode: str = "arena"
    capacity: int = 6
    members: list = field(default_factory=list)
    roster: list = field(default_factory=list)
    game: BattleGame | None = None
    history: list = field(default_factory=list)
    score: dict = field(default_factory=dict)
    stage: str = "lobby"
    deadline: float = 0
    accepted: set = field(default_factory=set)
    winner: str | None = None
    messages: list = field(default_factory=list)
    match_id: str = ""
    rules: BattleRules = field(default_factory=BattleRules)


class ArenaService:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.rooms = {}
        self.membership = {}
        self.queue = {}
        self.last_pair = {}
        self.rates = {}
        self.seen = {}

    def limit(self, key, seconds, count):
        now = time.time()
        entries = [t for t in self.rates.get(key, []) if t > now - seconds]
        if len(entries) >= count:
            raise RuleError("操作が続いています。少し待ってください")
        self.rates[key] = entries + [now]

    def current(self, user_id):
        return self.rooms.get(self.membership.get(user_id))

    def leave(self, user_id):
        room = self.current(user_id)
        if room and room.stage == "playing" and user_id in room.roster:
            raise RuleError("対戦中は退出できません。再接続で復帰できます")
        self.membership.pop(user_id, None)
        self.queue.pop(user_id, None)
        if room:
            room.members = [m for m in room.members if m != user_id]
            if not room.members:
                self.rooms.pop(room.id, None)
            elif room.host == user_id:
                room.host = room.members[0]
            if room.stage == "confirm":
                self.rooms.pop(room.id, None)
                for member in room.members:
                    self.membership.pop(member, None)
                    if member in room.accepted:
                        original = self.queue.get(member, {"since": time.time(), "wide": False})
                        self.queue[member] = {**original, "seen": time.time()}

    def create(self, user, data):
        self.limit(("create", user["id"]), 60, 5)
        phrase = str(data.get("phrase", "")).strip().casefold()
        name = str(data.get("name", "")).strip()
        capacity = data.get("capacity", 6)
        if not 2 <= len(phrase) <= 32 or not 1 <= len(name) <= 30 or type(capacity) is not int or not 2 <= capacity <= 6:
            raise RuleError("部屋名1〜30文字、合言葉2〜32文字、人数2〜6人で設定してください")
        if any(r.phrase == phrase for r in self.rooms.values() if r.mode == "arena"):
            raise RuleError("その合言葉は使用されています")
        rules = BattleRules.from_data(data)
        self.leave(user["id"])
        room = GameRoom(secrets.token_hex(8), name, phrase, user["id"], capacity=capacity, members=[user["id"]], rules=rules)
        self.rooms[room.id] = room
        self.membership[user["id"]] = room.id

    def join(self, user, phrase):
        self.limit(("join", user["id"]), 60, 15)
        room = next((r for r in self.rooms.values() if r.mode == "arena" and r.phrase == str(phrase).strip().casefold()), None)
        if not room:
            raise RuleError("合言葉に一致する部屋がありません")
        if user["id"] in room.members:
            return
        if len(room.members) >= (room.capacity if room.stage != "playing" else room.capacity + 10):
            raise RuleError("部屋が満員です")
        self.leave(user["id"])
        room.members.append(user["id"])
        self.membership[user["id"]] = room.id

    def start(self, room, user_id):
        if room.mode != "arena" or room.host != user_id or room.stage not in ("lobby", "finished"):
            raise RuleError("部屋主だけが待機中に開始できます")
        if not 2 <= len(room.members) <= room.capacity:
            raise RuleError("観戦者を含む参加人数を定員以内の2人以上にしてください")
        room.roster = list(room.members)
        room.history = []
        room.score = {uid: 0 for uid in room.roster}
        room.winner = None
        room.match_id = secrets.token_hex(12)
        self.new_battle(room)

    def new_battle(self, room):
        players = [self.store.get(uid) for uid in room.roster]
        room.game = BattleGame([Player(u["id"], u["name"], u["avatar"]) for u in players],
                               rules=room.rules if room.mode == "arena" else BattleRules())
        room.stage = "playing"

    def tick(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            for room in list(self.rooms.values()):
                if room.stage == "confirm" and now >= room.deadline:
                    for uid in room.members:
                        self.membership.pop(uid, None)
                        if uid in room.accepted:
                            original = self.queue.get(uid, {"since": now, "wide": False})
                            self.queue[uid] = {**original, "seen": now}
                        else:
                            self.queue.pop(uid, None)
                    self.rooms.pop(room.id, None)
                elif room.stage == "intermission" and now >= room.deadline:
                    self.new_battle(room)
                elif room.stage == "playing":
                    room.game.tick(now)
                    if room.game.phase == "finished":
                        room.history.append(room.game.history)
                        if room.game.winner:
                            room.score[room.game.winner] += 1
                        done = room.mode == "arena" or max(room.score.values()) >= 2 or len(room.history) >= 5
                        if done:
                            winner = room.game.winner if room.mode == "arena" else next((u for u, s in room.score.items() if s >= 2), None)
                            self.finish_match(room, winner, now)
                        else:
                            room.stage = "intermission"
                            room.deadline = now + 5
            waiting = [uid for uid, q in self.queue.items() if not self.current(uid) and now - q["seen"] < 30]
            self.queue = {uid: q for uid, q in self.queue.items() if now - q["seen"] < 30 or self.current(uid)}
            waiting.sort(key=lambda uid: self.queue[uid]["since"])
            for uid in waiting:
                if self.current(uid):
                    continue
                rating = self.store.get(uid)["rating"]
                candidates = []
                for other in waiting:
                    if other == uid or self.current(other):
                        continue
                    if now - self.last_pair.get(tuple(sorted((uid, other))), -1000) < 300:
                        continue
                    difference = abs(rating - self.store.get(other)["rating"])
                    if difference <= min(self.allowed(uid, now), self.allowed(other, now)):
                        candidates.append((difference, self.queue[other]["since"], other))
                if candidates:
                    other = min(candidates)[2]
                    room = GameRoom(secrets.token_hex(8), "RANK / DUEL", "", uid, "rank", 2, [uid, other])
                    room.roster = [uid, other]
                    room.stage, room.deadline = "confirm", now + 10
                    self.rooms[room.id] = room
                    for member in room.members:
                        self.membership[member] = room.id
            for uid in list(self.membership):
                room = self.current(uid)
                if room and room.stage in ("lobby", "finished") and now - self.seen.get(uid, now) > 120:
                    self.leave(uid)
            if len(self.rates) > 2000:
                self.rates = {key: entries for key, entries in self.rates.items() if entries and entries[-1] > now - 60}

    def allowed(self, uid, now):
        q = self.queue[uid]
        elapsed = now - q["since"]
        if q["wide"] and elapsed >= 60:
            return float("inf")
        return 100 if elapsed < 15 else 200 if elapsed < 30 else 300 if elapsed < 60 else 400

    def finish_match(self, room, winner, now):
        room.stage, room.winner = "finished", winner
        players = [self.store.public(self.store.get(uid)) for uid in room.roster]
        self.store.save_match(room.match_id, room.mode, players, room.winner, room.history)
        if room.mode == "rank":
            self.last_pair[tuple(sorted(room.roster))] = now

    def surrender(self, room, uid, match_id):
        now = time.time()
        # 決着済みの結果を確定してから降参を受け付ける
        self.tick(now)
        if (match_id != room.match_id or uid not in room.roster or
                room.stage not in ("playing", "intermission") or
                (room.mode == "arena" and room.stage != "playing")):
            raise RuleError("現在の対戦では降参できません")
        if room.stage == "playing":
            room.game.surrender(uid, now)
        else:
            room.game.record_surrender(uid)
        if room.mode == "rank":
            if room.stage == "playing":
                room.history.append(room.game.history)
            winner = next(other for other in room.roster if other != uid)
            room.score[winner] = 2
            self.finish_match(room, winner, now)
        else:
            self.tick(now)

    def command(self, user, action, data):
        uid = user["id"]
        self.seen[uid] = time.time()
        room = self.current(uid)
        if action == "create":
            self.create(user, data)
        elif action == "join":
            self.join(user, data.get("phrase"))
        elif action == "leave":
            self.leave(uid)
        elif action == "queue":
            if user["login"] is None:
                raise RuleError("ランク対戦にはアカウントが必要です")
            self.leave(uid)
            self.queue[uid] = {"since": time.time(), "wide": False, "seen": time.time()}
        elif action == "wide":
            if uid not in self.queue or time.time() - self.queue[uid]["since"] < 60:
                raise RuleError("検索開始から60秒後に変更できます")
            self.queue[uid]["wide"] = True
        elif action == "cancel":
            self.leave(uid)
        elif not room:
            raise RuleError("部屋に参加してください")
        elif action == "start":
            self.start(room, uid)
        elif action == "surrender":
            self.surrender(room, uid, data.get("match"))
        elif action == "room_settings":
            if room.mode != "arena" or room.host != uid or room.stage not in ("lobby", "finished"):
                raise RuleError("部屋主だけが待機中に変更できます")
            name, phrase = str(data.get("name", room.name)).strip(), str(data.get("phrase", room.phrase)).strip().casefold()
            capacity = data.get("capacity", room.capacity)
            if not 1 <= len(name) <= 30 or not 2 <= len(phrase) <= 32 or type(capacity) is not int or not 2 <= capacity <= 6:
                raise RuleError("部屋名・合言葉・定員を確認してください")
            if any(r.id != room.id and r.mode == "arena" and r.phrase == phrase for r in self.rooms.values()):
                raise RuleError("その合言葉は使用されています")
            rules = BattleRules.from_data(data, room.rules)
            room.name, room.phrase, room.capacity = name, phrase, capacity
            room.rules = rules
        elif action == "accept":
            if room.stage != "confirm" or time.time() >= room.deadline:
                raise RuleError("承認期限が終了しました")
            room.accepted.add(uid)
            if len(room.accepted) == 2:
                room.score = {m: 0 for m in room.roster}
                room.match_id = secrets.token_hex(12)
                for m in room.roster:
                    self.queue.pop(m, None)
                self.new_battle(room)
        elif action in ("select", "choose"):
            self.limit(("choose", uid), 5, 25)
            if room.stage != "playing":
                raise RuleError("対戦は始まっていません")
            if (data.get("round", room.game.round) != room.game.round or
                    data.get("deadline", room.game.deadline) != room.game.deadline):
                raise RuleError("ラウンドが変わりました。現在のカードを選び直してください")
            room.game.choose(uid, data.get("card"), data.get("target"), ready=action == "choose")
        elif action == "kick":
            target = data.get("target")
            if room.host != uid or room.mode != "arena" or room.stage == "playing" or target == uid or target not in room.members:
                raise RuleError("待機中の参加者だけ退出させられます")
            self.leave(target)
        elif action == "chat":
            self.chat(user, room, data)
        else:
            raise RuleError("不明な操作です")

    def chat(self, user, room, data):
        uid = user["id"]
        self.limit(("chat", uid), 10, 5)
        text = str(data.get("text", "")).strip()
        target = data.get("target") or None
        if not text or len(text) > 300 or any(ord(c) < 32 and c != "\n" for c in text):
            raise RuleError("メッセージは1〜300文字にしてください")
        if target and (target not in room.members or target == uid):
            raise RuleError("送信先を確認してください")
        observer = room.stage in ("playing", "intermission") and (uid not in room.roster or room.game.players[uid].hp <= 0)
        if observer and target and target in room.game.players and room.game.players[target].hp > 0:
            raise RuleError("観戦中は生存者へ送信できません")
        if target and uid in self.store.blocked(target):
            raise RuleError("この相手には送信できません")
        room.messages.append({"id": secrets.token_hex(6), "sender": uid, "name": user["name"], "target": target,
                              "text": text, "observer": observer, "time": time.time()})
        room.messages = room.messages[-200:]

    def snapshot(self, user):
        uid = user["id"]
        with self.lock:
            self.seen[uid] = time.time()
            if uid in self.queue:
                self.queue[uid]["seen"] = time.time()
            room = self.current(uid)
            state = {"user": self.store.public(self.store.get(uid)), "queue": self.queue.get(uid),
                     "waiting": len([m for m in self.queue if not self.current(m)]), "room": None, "server_time": time.time()}
            if room:
                alive = room.stage in ("playing", "intermission") and uid in room.roster and room.game.players[uid].hp > 0
                blocked = self.store.blocked(uid)
                messages = [m for m in room.messages if m["sender"] not in blocked
                            and (not m["target"] or uid in (m["sender"], m["target"]))
                            and not (alive and m["observer"])]
                state["room"] = {"id": room.id, "name": room.name, "phrase": room.phrase, "host": room.host,
                                 "match_id": room.match_id,
                                 "mode": room.mode, "capacity": room.capacity, "stage": room.stage,
                                 "members": [self.store.public(self.store.get(m)) for m in room.members],
                                 "score": room.score, "deadline": room.deadline, "accepted": uid in room.accepted,
                                 "rules": room.rules.public(),
                                 "winner": room.winner, "game": room.game.snapshot(uid) if room.game else None,
                                 "messages": messages}
            return state

"""伏せた選択を他人の公開状態に含めない """
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
import time


class RuleError(ValueError):
    pass


class Card(ABC):
    key = ""
    label = ""
    targeted = False
    cost = 0

    @abstractmethod
    def resolve(self, actor, target, choices, effects):
        """支払い済みのカード効果を集計し 全員の結果を同時に反映する """


class Shot(Card):
    key, label, targeted = "shot", "射撃", True

    def resolve(self, actor, target, choices, effects):
        response = choices.get(target.id, ("idle", None))
        if response == ("counter", actor.id):
            effects.damage[actor.id] += 2
        elif response[0] != "shield":
            effects.damage[target.id] += 2


class Shield(Card):
    key, label = "shield", "シールド"

    def resolve(self, actor, target, choices, effects):
        pass


class Counter(Card):
    key, label, targeted = "counter", "カウンター", True

    def resolve(self, actor, target, choices, effects):
        pass  # 防御・反撃は攻撃側で判定し 反撃を再反射させない


class Charge(Card):
    key, label = "charge", "チャージ"

    def resolve(self, actor, target, choices, effects):
        effects.energy[actor.id] += 2


class Pierce(Card):
    key, label, targeted, cost = "pierce", "貫通射撃", True, 2

    def resolve(self, actor, target, choices, effects):
        if choices.get(target.id) == ("counter", actor.id):
            effects.damage[actor.id] += 2
        else:
            effects.damage[target.id] += 3


class Heal(Card):
    key, label, cost = "heal", "ヒール", 2

    def resolve(self, actor, target, choices, effects):
        effects.healing[actor.id] += 3


class Drain(Shot):
    key, label, cost = "drain", "ドレイン", 2

    def resolve(self, actor, target, choices, effects):
        super().resolve(actor, target, choices, effects)
        effects.healing[actor.id] += 1


class EnergyBreak(Card):
    key, label, targeted, cost = "energy_break", "エネルギーブレイク", True, 1

    def resolve(self, actor, target, choices, effects):
        effects.energy[target.id] -= 2


CARDS = {card.key: card for card in (Shot(), Shield(), Counter(), Charge(), Pierce(), Heal(), Drain(), EnergyBreak())}
ROUND_SECONDS = 50
REVEAL_SECONDS = 5


def hazard_damage(round_number):
    return 0 if round_number < 7 else 1 + (round_number - 7) // 5


@dataclass(frozen=True)
class BattleRules:
    initial_hp: int = 15
    initial_energy: int = 0
    allowed_cards: tuple = tuple(CARDS)

    def __post_init__(self):
        if type(self.initial_hp) is not int or not 1 <= self.initial_hp <= 100:
            raise RuleError("初期HPは1〜100の整数で設定してください")
        if type(self.initial_energy) is not int or not 0 <= self.initial_energy <= 4:
            raise RuleError("初期ENは0〜4の整数で設定してください")
        keys = self.allowed_cards
        if (not isinstance(keys, (list, tuple)) or not keys or
                any(not isinstance(key, str) or key not in CARDS for key in keys) or
                len(set(keys)) != len(keys)):
            raise RuleError("使用カードを1種類以上、重複なく選んでください")
        if not any(CARDS[key].cost <= self.initial_energy for key in keys):
            raise RuleError("初期ENで使えるカードを含めるか、初期ENを増やしてください")
        object.__setattr__(self, "allowed_cards", tuple(key for key in CARDS if key in keys))

    @classmethod
    def from_data(cls, data, defaults=None):
        defaults = defaults or cls()
        return cls(data.get("initial_hp", defaults.initial_hp),
                   data.get("initial_energy", defaults.initial_energy),
                   data.get("allowed_cards", defaults.allowed_cards))

    def public(self):
        return {"initial_hp": self.initial_hp, "initial_energy": self.initial_energy,
                "allowed_cards": list(self.allowed_cards)}


@dataclass
class RoundEffects:
    damage: dict
    healing: dict
    energy: dict


class Hand:
    def __init__(self, player, allowed_cards=CARDS):
        self.cards = [key for key, card in CARDS.items()
                      if key in allowed_cards and key != player.previous and player.energy >= card.cost]

    def __len__(self):
        return len(self.cards)

    def __contains__(self, key):
        return key in self.cards


@dataclass
class Player:
    id: str
    name: str
    avatar: int = 0
    hp: int = 15
    energy: int = 0
    previous: str | None = None
    missed: int = 0
    eliminated: int | None = None
    max_hp: int = 15
    surrendered: bool = False

    def public(self):
        return {"id": self.id, "name": self.name, "avatar": self.avatar,
                "hp": self.hp, "energy": self.energy, "previous": self.previous,
                "eliminated": self.eliminated, "max_hp": self.max_hp,
                "surrendered": self.surrendered}


class BattleGame:
    def __init__(self, players, now=None, rules=None):
        self.rules = rules or BattleRules()
        self.players = {p.id: Player(p.id, p.name, p.avatar, hp=self.rules.initial_hp,
                                    energy=self.rules.initial_energy, max_hp=self.rules.initial_hp) for p in players}
        self.round = 1
        self.choices = {}
        self.ready = set()
        self.history = []
        self.phase = "select"
        self.deadline = (time.time() if now is None else now) + ROUND_SECONDS
        self.winner = None

    def choose(self, user_id, key, target=None, now=None, *, ready=True):
        now = time.time() if now is None else now
        actor = self.players.get(user_id)
        if self.phase != "select" or now >= self.deadline or not actor or actor.hp <= 0:
            raise RuleError("現在はカードを選べません")
        if user_id in self.ready:
            raise RuleError("準備完了後は選択を変更できません")
        hand = Hand(actor, self.rules.allowed_cards)
        passing = key == "idle" and not len(hand)
        if not passing and key not in hand:
            raise RuleError("そのカードは使用できません")
        if not passing and CARDS[key].targeted:
            opponent = self.players.get(target)
            if not target and not ready:
                target = None  # 対象が未選択でも 選択中のカードを保存する
            elif not opponent or opponent.hp <= 0 or opponent.id == user_id:
                raise RuleError("生存している相手を選んでください")
        else:
            target = None
        self.choices[user_id] = (key, target)
        if ready:
            self.ready.add(user_id)
            if all(p.id in self.ready for p in self.players.values() if p.hp > 0):
                self.resolve(now)

    def resolve(self, now=None):
        if self.phase != "select":
            return
        now = time.time() if now is None else now
        alive = [p for p in self.players.values() if p.hp > 0]
        effects = RoundEffects(*({p.id: 0 for p in alive} for _ in range(3)))
        before = {p.id: (p.hp, p.energy) for p in alive}
        forfeits = set()
        timed_out = {p.id for p in alive if p.id not in self.ready}
        for p in alive:
            choice = self.choices.get(p.id)
            if not choice or (choice[0] in CARDS and CARDS[choice[0]].targeted and not choice[1]):
                p.missed += 1
                self.choices[p.id] = ("idle", None)
                if p.missed >= 2:
                    forfeits.add(p.id)
            else:
                p.missed = 0
        spent = {p.id: 0 for p in alive}
        failed = {}
        # 相互ブレイクは両方発動し プレイヤーの並びや準備完了順に依存させない
        for p in alive:
            key, target = self.choices[p.id]
            if key == "energy_break":
                p.energy -= CARDS[key].cost
                spent[p.id] = CARDS[key].cost
                CARDS[key].resolve(p, self.players[target], self.choices, effects)
        energy_loss = effects.energy.copy()
        energy_gained = {}
        energy_lost = {}
        for p in alive:
            # チャージを上限まで反映した後 増加分もブレイクの対象にする
            effects.energy[p.id] = 0
            if self.choices[p.id][0] == "charge":
                CARDS["charge"].resolve(p, None, self.choices, effects)
            charged = min(4, p.energy + effects.energy[p.id])
            energy_gained[p.id] = charged - p.energy
            p.energy = max(0, charged + energy_loss[p.id])
            energy_lost[p.id] = charged - p.energy
            effects.energy[p.id] = 0
            key = self.choices[p.id][0]
            card = CARDS.get(key)
            if card and key != "energy_break":
                if p.energy < card.cost:
                    failed[p.id] = {"failure_reason": "EN不足", "energy_required": card.cost,
                                    "energy_available": p.energy}
                else:
                    p.energy -= card.cost
                    spent[p.id] = card.cost
        effective_choices = {uid: ("idle", None) if uid in failed else choice
                             for uid, choice in self.choices.items()}
        for p in alive:
            key, target = self.choices[p.id]
            if key in CARDS and key not in ("energy_break", "charge") and p.id not in failed:
                CARDS[key].resolve(p, self.players.get(target), effective_choices, effects)
            p.previous = key
        for p in alive:
            p.hp = min(p.max_hp, max(0, p.hp + effects.healing[p.id] - effects.damage[p.id] - hazard_damage(self.round)))
            p.energy = min(4, max(0, p.energy + effects.energy[p.id]))
            if p.id in forfeits:
                p.hp = 0
            if not p.hp:
                p.eliminated = self.round
        self.history.append({"round": self.round,
                             "actions": [{"id": p.id, "card": self.choices[p.id][0],
                                          "target": self.choices[p.id][1], "damage": effects.damage[p.id],
                                          "healing": effects.healing[p.id], "energy": p.energy,
                                          "energy_effect": energy_gained[p.id] - energy_lost[p.id],
                                          "energy_gained": energy_gained[p.id], "energy_lost": energy_lost[p.id],
                                          "energy_spent": spent[p.id], "failed": p.id in failed,
                                          **failed.get(p.id, {}),
                                          "hp_before": before[p.id][0], "energy_before": before[p.id][1],
                                          "max_hp": p.max_hp,
                                          "timeout": p.id in timed_out, "hp": p.hp} for p in alive],
                             "hazard": self.round >= 7, "hazard_damage": hazard_damage(self.round)})
        survivors = [p.id for p in alive if p.hp > 0]
        self.choices = {}
        self.ready.clear()
        if len(survivors) <= 1:
            self.winner = survivors[0] if survivors else None
            self.phase = "finished"
        else:
            self.phase = "reveal"
            self.deadline = now + REVEAL_SECONDS

    def tick(self, now):
        if self.phase == "select" and now >= self.deadline:
            self.resolve(now)
        elif self.phase == "reveal" and now >= self.deadline:
            self.round += 1
            self.phase = "select"
            self.deadline = now + ROUND_SECONDS

    def record_surrender(self, user_id):
        actor = self.players[user_id]
        before = actor.hp
        actor.hp = 0
        actor.eliminated = self.round
        actor.surrendered = True
        self.history.append({"round": self.round, "event": "surrender", "hazard": False,
                             "actions": [{"id": actor.id, "card": "surrender", "target": None,
                                          "hp": 0, "hp_before": before, "max_hp": actor.max_hp,
                                          "energy": actor.energy, "damage": 0, "timeout": False}]})

    def surrender(self, user_id, now=None):
        actor = self.players.get(user_id)
        if self.phase not in ("select", "reveal") or not actor or actor.hp <= 0:
            raise RuleError("対戦中の生存している戦闘員だけが降参できます")
        now = time.time() if now is None else now
        self.record_surrender(user_id)
        self.choices.pop(user_id, None)
        self.ready.discard(user_id)
        # 降参した相手への選択を解除し 対象を選び直せるようにする
        for uid, (key, target) in list(self.choices.items()):
            if target == user_id:
                self.choices[uid] = (key, None)
                self.ready.discard(uid)
        survivors = [p.id for p in self.players.values() if p.hp > 0]
        if len(survivors) <= 1:
            self.winner = survivors[0] if survivors else None
            self.phase = "finished"
            self.choices.clear()
            self.ready.clear()
        elif self.phase == "select" and all(uid in self.ready for uid in survivors):
            self.resolve(now)

    def snapshot(self, user_id):
        actor = self.players.get(user_id)
        return {"round": self.round, "phase": self.phase, "deadline": self.deadline,
                "hazard_damage": hazard_damage(self.round),
                "players": [p.public() for p in self.players.values()],
                "history": self.history, "winner": self.winner,
                "rules": self.rules.public(),
                "hand": Hand(actor, self.rules.allowed_cards).cards if actor and actor.hp > 0 else [],
                "hand_count": len(Hand(actor, self.rules.allowed_cards)) if actor and actor.hp > 0 else 0,
                "choice": self.choices.get(user_id), "ready": user_id in self.ready}


def rank_name(rating):
    for threshold, name in ((1700, "ダイヤモンド"), (1400, "プラチナ"),
                            (1100, "ゴールド"), (800, "シルバー")):
        if rating >= threshold:
            return name
    return "ブロンズ"


def elo_delta(rating, opponent, score):
    expected = 1 / (1 + 10 ** ((opponent - rating) / 400))
    value = 32 * (score - expected)
    return math.floor(value + .5) if value >= 0 else math.ceil(value - .5)

import pytest
from arena.game import BattleGame, Player, RuleError, elo_delta, rank_name


def battle(count=2):
    return BattleGame([Player(str(i), f"P{i}") for i in range(count)], now=0)


@pytest.mark.parametrize("response,expected", [("shield",(15,15)),("counter",(13,15)),("charge",(15,13))])
def test_shot_response(response, expected):
    game=battle()
    game.choose("0","shot","1",now=1)
    game.choose("1",response,"0" if response=="counter" else None,now=1)
    game.resolve(20)
    assert (game.players["0"].hp,game.players["1"].hp)==expected


def test_wrong_target_counter_does_not_protect():
    game=battle(3)
    game.choose("0","shot","1",now=1)
    game.choose("1","counter","2",now=1)
    game.choose("2","charge",now=1)
    game.resolve(20)
    assert game.players["1"].hp==13


@pytest.mark.parametrize("response,damage", [("counter",0),("shield",3)])
def test_pierce(response, damage):
    game=battle();game.players["0"].energy=2
    game.choose("0","pierce","1",now=1)
    game.choose("1",response,"0" if response=="counter" else None,now=1)
    game.resolve(20)
    assert game.players["1"].hp==15-damage
    assert game.players["0"].hp==(13 if response=="counter" else 15)
    assert game.players["0"].energy==0


def test_simultaneous_death_and_hazard():
    game=battle();game.round=7
    for p in game.players.values():p.hp=3
    game.choose("0","shot","1",now=1);game.choose("1","shot","0",now=1)
    game.resolve(20)
    assert game.phase=="finished" and game.winner is None
    assert all(p.hp==0 for p in game.players.values())


def test_hidden_choices_and_replacement():
    game=battle();game.choose("0","shot","1",now=1,ready=False)
    assert game.snapshot("1")["choice"] is None
    assert "choices" not in game.snapshot("1")
    game.choose("0","charge",now=2,ready=False)
    assert game.snapshot("0")["choice"]==("charge",None)


def test_cooldown_energy_target_deadline_validation():
    game=battle();game.players["0"].previous="shot"
    for key,target in [("shot","1"),("pierce","1"),("counter","0"),("counter","invalid")]:
        with pytest.raises(RuleError):game.choose("0",key,target,now=1)
    with pytest.raises(RuleError):game.choose("0","charge",now=50)


def test_two_timeouts_forfeit():
    game=battle();game.choose("0","charge",now=1);game.tick(50)
    assert game.players["1"].previous=="idle"
    game.tick(55);game.choose("0","shield",now=56);game.tick(105)
    assert game.winner=="0" and game.players["1"].hp==0


def test_fifty_seconds_and_immediate_resolution_only_when_everyone_ready():
    game=battle()
    assert game.deadline==50
    game.choose("0","shot","1",now=1)
    game.choose("1","charge",now=2,ready=False)
    game.tick(49)
    assert game.phase=="select" and game.history==[]
    assert game.players["1"].hp==15 and game.players["1"].energy==0
    assert game.snapshot("0")["ready"] is True
    assert game.snapshot("1")["ready"] is False
    game.choose("1","charge",now=49)
    assert game.phase=="reveal" and game.deadline==54
    assert game.players["1"].hp==13 and game.players["1"].energy==2
    assert not any(a["timeout"] for a in game.history[0]["actions"])
    game.tick(54)
    assert game.round==2 and game.deadline==104 and not game.ready


@pytest.mark.parametrize("card,target,expected", [("charge",None,"charge"),("shot","0","shot"),("shot",None,"idle"),(None,None,"idle")])
def test_timeout_uses_draft_or_idle(card,target,expected):
    game=battle()
    game.choose("0","charge",now=1)
    if card:game.choose("1",card,target,now=2,ready=False)
    game.tick(50)
    action=game.history[0]["actions"][1]
    assert action["card"]==expected and action["timeout"] is True
    assert game.players["1"].missed==(1 if expected=="idle" else 0)
    assert game.players["0"].hp==(13 if expected=="shot" else 15)
    assert game.players["1"].energy==(2 if expected=="charge" else 0)


def test_ready_choice_is_locked_and_duplicate_resolution_does_not_apply_effects_twice():
    game=battle();game.choose("0","shot","1",now=1)
    with pytest.raises(RuleError):game.choose("0","charge",now=2,ready=False)
    game.choose("1","charge",now=3)
    game.resolve(50)
    assert game.players["1"].hp==13 and game.players["1"].energy==2 and len(game.history)==1


def test_arena_waits_for_all_surviving_players_but_not_spectators():
    game=battle(4);game.players["3"].hp=0
    game.choose("0","charge",now=1);game.choose("1","charge",now=2)
    assert game.phase=="select"
    game.choose("2","charge",now=3)
    assert game.phase=="reveal" and len(game.history[0]["actions"])==3


def test_latest_draft_replaces_card_target_and_incomplete_draft():
    game=battle(3)
    game.choose("0","shot","1",now=1,ready=False)
    game.choose("0","counter",now=2,ready=False)
    assert game.snapshot("0")["choice"]==("counter",None)
    game.choose("0","counter","2",now=3,ready=False)
    game.tick(50)
    assert game.history[0]["actions"][0]["card"]=="counter"
    assert game.history[0]["actions"][0]["target"]=="2"


def test_charge_cap_and_does_not_cancel_on_damage():
    game=battle();game.players["0"].energy=3
    game.choose("0","charge",now=1);game.choose("1","shot","0",now=1);game.resolve(20)
    assert game.players["0"].energy==4 and game.players["0"].hp==13


@pytest.mark.parametrize("rating,opponent,score,delta",[(1000,1000,1,16),(1000,1200,1,24),(1000,1200,0,-8),(1000,800,0,-24),(1000,1000,.5,0)])
def test_elo(rating,opponent,score,delta):assert elo_delta(rating,opponent,score)==delta


def test_rank_boundaries():
    assert [rank_name(x) for x in [799,800,1100,1400,1700]]==["ブロンズ","シルバー","ゴールド","プラチナ","ダイヤモンド"]

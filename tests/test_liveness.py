from itertools import combinations
import random
from arena.game import BattleGame, BattleRules, CARDS, Player, RuleError, hazard_damage


def simulate(rules,policy='heal',count=2,seed=0):
    rng=random.Random(seed)
    game=BattleGame([Player(str(i),str(i)) for i in range(count)],now=0,rules=rules)
    while game.phase!='finished' and game.round<=51:
        alive=[p.id for p in game.players.values() if p.hp>0]
        now=game.deadline-1
        for uid in alive:
            hand=game.snapshot(uid)['hand']
            if policy=='random': key=rng.choice(hand) if hand else 'idle'
            else:
                priority={'heal':['heal','charge','shield','counter','drain','energy_break','shot','pierce'],
                          'break':['energy_break','charge','shield','heal','counter','drain','pierce','shot'],
                          'attack':['pierce','drain','shot','charge','energy_break','heal','counter','shield']}[policy]
                key=next((k for k in priority if k in hand),'idle')
            target=alive[(alive.index(uid)+1)%len(alive)] if key in CARDS and CARDS[key].targeted else None
            game.choose(uid,key,target,now=now)
        assert game.phase in ('finished','reveal')
        if game.phase!='finished':game.tick(game.deadline)
    return game


def test_environment_escalates_at_boundaries_and_is_recorded():
    assert [hazard_damage(r) for r in [1,6,7,11,12,16,17,21,22,26,27]]==[0,0,1,1,2,2,3,3,4,4,5]
    g=BattleGame([Player('a','A'),Player('b','B')],now=0)
    g.round=12
    g.choose('a','shield',now=1);g.choose('b','charge',now=2)
    assert all(p.hp==13 for p in g.players.values())
    assert g.history[-1]['hazard_damage']==2 and g.snapshot('a')['hazard_damage']==2


def test_previous_infinite_charge_heal_loop_now_finishes():
    g=simulate(BattleRules(allowed_cards=['charge','heal']))
    assert g.phase=='finished' and g.round<=31
    assert all(p.hp==0 for p in g.players.values())


def test_all_valid_card_subsets_and_initial_energies_finish():
    keys=list(CARDS)
    checked=0
    for size in range(1,len(keys)+1):
        for subset in combinations(keys,size):
            for energy in range(5):
                try:rules=BattleRules(100,energy,subset)
                except RuleError:continue
                for policy in ['heal','break','attack']:
                    g=simulate(rules,policy)
                    assert g.phase=='finished',(subset,energy,policy,g.round)
                    assert all(0<=p.hp<=100 and 0<=p.energy<=4 for p in g.players.values())
                checked+=1
    assert checked==255*5-(2**4-1)-(2**3-1)  


def test_random_two_to_six_players_finish_with_valid_targets():
    for seed in range(150):
        rules=BattleRules(15 if seed%2 else 100,seed%5)
        g=simulate(rules,'random',2+seed%5,seed)
        assert g.phase=='finished' and g.round<=51


def test_card_independent_upper_bound_for_current_maximum_healing():
    # 毎ラウンド無条件でHPを3回復しても この時点までに必ず決着する
    assert sum(max(0,hazard_damage(r)-3) for r in range(1,52))>=100
    assert sum(max(0,hazard_damage(r)-3) for r in range(1,32))>=15

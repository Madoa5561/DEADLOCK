import pytest
from arena.game import BattleGame, BattleRules, Player, RuleError


def game(keys=None, hp=10, energy=2, reverse=False):
    players = [Player('a', 'A'), Player('b', 'B')]
    return BattleGame(players[::-1] if reverse else players, now=0,
                      rules=BattleRules(hp, energy, keys or tuple(BattleRules().allowed_cards)))


@pytest.mark.parametrize('hp,start,expected', [(10,9,10),(10,4,7),(20,18,20),(3,1,3)])
def test_heal_cap_and_cost(hp,start,expected):
    g=game(hp=hp); g.players['a'].hp=start
    g.choose('a','heal',now=1); g.choose('b','shield',now=2)
    assert g.players['a'].hp==expected and g.players['a'].energy==0
    action=next(a for a in g.history[0]['actions'] if a['id']=='a')
    assert action['healing']==3 and action['max_hp']==hp and action['energy_spent']==2


@pytest.mark.parametrize('response,target,hps', [('shot','a',(5,8)),('shield',None,(7,10)),('counter','a',(5,10))])
def test_drain_defense_counter_and_heal(response,target,hps):
    g=game(); g.players['a'].hp=6
    g.choose('a','drain','b',now=1); g.choose('b',response,target,now=2)
    assert (g.players['a'].hp,g.players['b'].hp)==hps
    assert g.players['a'].energy==0


@pytest.mark.parametrize('reverse', [False,True])
@pytest.mark.parametrize('response,target,energy', [('charge',None,2),('pierce','a',0),('shield',None,0)])
def test_break_precedes_card_cost_and_is_independent_of_player_order(reverse,response,target,energy):
    g=game(reverse=reverse)
    g.choose('a','energy_break','b',now=1); g.choose('b',response,target,now=2)
    assert g.players['a'].energy==1 and g.players['b'].energy==energy
    assert g.players['a'].hp==10
    action=next(a for a in g.history[0]['actions'] if a['id']=='b')
    assert action['failed']==(response=='pierce')
    if action['failed']:assert action['energy_spent']==0


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('card,target',[('heal',None),('pierce','a'),('drain','a')])
@pytest.mark.parametrize('starting_energy,success',[(2,False),(3,False),(4,True)])
def test_disrupted_cost_cards_fail_without_effects_or_cost(reverse,card,target,starting_energy,success):
    g=game(hp=15,energy=starting_energy,reverse=reverse)
    for p in g.players.values():p.hp=13
    g.choose('b',card,target,now=1);g.choose('a','energy_break','b',now=2)
    a,b=g.players['a'],g.players['b']
    action=next(a for a in g.history[-1]['actions'] if a['id']=='b')
    assert b.energy==(0 if success else starting_energy-2)
    assert action['failed'] is not success and action['energy_spent']==(2 if success else 0)
    assert b.missed==0 and b.previous==card
    if not success:
        assert a.hp==b.hp==13 and action['healing']==0
        assert (action['energy_required'],action['energy_available'])==(2,starting_energy-2)
    elif card=='heal':assert b.hp==15 and action['healing']==3
    elif card=='pierce':assert a.hp==10 and b.hp==13
    else:assert a.hp==11 and b.hp==14


@pytest.mark.parametrize('reverse',[False,True])
def test_mutual_breaks_resolve_together_and_cost_only_once(reverse):
    g=game(energy=1,reverse=reverse)
    g.choose('a','energy_break','b',now=1);g.choose('b','energy_break','a',now=2)
    assert all(p.energy==0 for p in g.players.values())
    assert all(not a['failed'] and a['energy_spent']==1 for a in g.history[-1]['actions'])


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('ready_reverse',[False,True])
@pytest.mark.parametrize('start,expected',[(0,0),(1,1),(2,2),(3,2),(4,2)])
def test_break_removes_charge_after_capping_regardless_of_order(reverse,ready_reverse,start,expected):
    g=game(energy=2,reverse=reverse);g.players['b'].energy=start
    choices=[('a','energy_break','b'),('b','charge',None)]
    for uid,card,target in choices[::-1] if ready_reverse else choices:g.choose(uid,card,target,now=1)
    action=next(a for a in g.history[-1]['actions'] if a['id']=='b')
    assert g.players['b'].energy==expected and not action['failed']
    assert action['energy_gained']==min(2,4-start) and action['energy_lost']==2
    assert action['energy_effect']==expected-start and action['energy_spent']==0


def test_multiple_breaks_remove_fresh_charge_but_record_only_actual_loss():
    g=BattleGame([Player('a','A'),Player('b','B'),Player('c','C')],now=0,rules=BattleRules(15,2))
    g.players['a'].energy=0
    g.choose('a','charge',now=1);g.choose('b','energy_break','a',now=1);g.choose('c','energy_break','a',now=1)
    action=g.history[-1]['actions'][0]
    assert g.players['a'].energy==0 and action['energy_gained']==2 and action['energy_lost']==2
    assert action['energy_effect']==0 and not action['failed']


def test_energy_history_matches_actual_caps_and_paid_costs():
    g=game(energy=4)
    g.choose('a','charge',now=1);g.choose('b','heal',now=1)
    for action in g.history[-1]['actions']:
        assert action['energy']==action['energy_before']-action['energy_spent']+action['energy_effect']
    assert g.history[-1]['actions'][0]['energy_gained']==0


def test_multiple_breaks_cancel_heal_and_hazard_still_applies():
    g=BattleGame([Player('a','A'),Player('b','B'),Player('c','C')],now=0,rules=BattleRules(15,4))
    g.round=12;g.players['a'].hp=13
    g.choose('a','heal',now=1,ready=False)
    g.choose('b','energy_break','a',now=2);g.choose('c','energy_break','a',now=2)
    g.tick(50)
    action=next(a for a in g.history[-1]['actions'] if a['id']=='a')
    assert action['failed'] and action['timeout'] and action['healing']==0
    assert g.players['a'].hp==11 and g.players['a'].energy==0 and g.players['a'].missed==0


def test_heal_and_damage_are_simultaneous_even_if_damage_would_be_lethal():
    g=game();g.players['a'].hp=1
    g.choose('a','heal',now=1); g.choose('b','pierce','a',now=2)
    assert g.players['a'].hp==1 and g.phase=='reveal'


def test_restricted_single_card_can_ready_pass_without_inactivity_penalty():
    g=game(keys=['heal'])
    for uid in ('a','b'):g.choose(uid,'heal',now=1)
    g.tick(6)
    assert g.snapshot('a')['hand']==[]
    for uid in ('a','b'):g.choose(uid,'idle',now=7)
    assert g.phase=='reveal' and all(p.missed==0 for p in g.players.values())
    assert all(not a['timeout'] for a in g.history[-1]['actions'])


def test_card_cost_restriction_target_and_cooldown():
    g=game(keys=['charge','heal','energy_break'],energy=0)
    for key in ['shot','heal','energy_break','idle']:
        with pytest.raises(RuleError):g.choose('a',key,'b',now=1)
    g.choose('a','charge',now=1);g.choose('b','charge',now=2);g.tick(7)
    assert g.snapshot('a')['hand']==['heal','energy_break']
    with pytest.raises(RuleError):g.choose('a','energy_break','a',now=8)


@pytest.mark.parametrize('data', [{'initial_hp':0},{'initial_hp':101},{'initial_hp':True},{'initial_energy':5},{'initial_energy':-1},{'allowed_cards':[]},{'allowed_cards':['evil']},{'allowed_cards':['shot','shot']},{'allowed_cards':'shot'},{'allowed_cards':['heal'],'initial_energy':0}])
def test_invalid_rules(data):
    with pytest.raises(RuleError):BattleRules.from_data(data)

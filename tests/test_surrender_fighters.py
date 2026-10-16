import secrets
import time
from pathlib import Path
import pytest
from arena.game import BattleGame, BattleRules, Player, RuleError
from arena.store import AccountStore
from arena.service import ArenaService


@pytest.fixture
def arena():
    store=AccountStore(Path('data/tests')/secrets.token_hex(8)/'surrender.sqlite3')
    users=[store.register(f'player{i}',f'P{i}','test-password')[0] for i in range(3)]
    return store,ArenaService(store),users


def make_room(service,users):
    service.create(users[0],{'name':'Test','phrase':secrets.token_hex(8)})
    room=service.current(users[0]['id'])
    for user in users[1:]:service.join(user,room.phrase)
    service.start(room,users[0]['id'])
    return room


def rank_room(service,users):
    for user in users[:2]:service.command(user,'queue',{})
    service.tick(time.time())
    room=service.current(users[0]['id'])
    for user in users[:2]:service.command(user,'accept',{})
    return room


@pytest.mark.parametrize('avatar',[0,4,5,6,7])
def test_all_eight_avatars_persist(arena,avatar):
    store,_,users=arena
    store.settings(users[0],{'avatar':avatar})
    assert store.get(users[0]['id'])['avatar']==avatar


@pytest.mark.parametrize('avatar',[-1,8,True,'6'])
def test_invalid_avatars_rejected(arena,avatar):
    store,_,users=arena
    with pytest.raises(RuleError):store.settings(users[0],{'avatar':avatar})


def test_default_hp_is_fifteen_and_rank_resets_each_battle(arena):
    _,service,users=arena
    assert BattleRules().initial_hp==15 and Player('x','X').hp==15
    room=rank_room(service,users)
    assert all(p.hp==15 and p.max_hp==15 for p in room.game.players.values())
    room.game.players[users[1]['id']].hp=0
    room.game.resolve(time.time());service.tick()
    service.tick(room.deadline+1)
    assert all(p.hp==15 and p.max_hp==15 for p in room.game.players.values())


def test_arena_duel_surrender_finishes_and_records_once(arena):
    store,service,users=arena
    room=make_room(service,users[:2])
    match=room.match_id
    service.command(users[0],'choose',{'card':'charge'})
    service.command(users[0],'surrender',{'match':match})
    assert room.stage=='finished' and room.winner==users[1]['id']
    assert room.game.players[users[0]['id']].surrendered
    assert room.game.players[users[1]['id']].hp==15
    assert store.stats(users[0]['id'])['matches'][0]['outcome']=='loss'
    assert store.stats(users[1]['id'])['matches'][0]['outcome']=='win'
    with pytest.raises(RuleError):service.command(users[0],'surrender',{'match':match})
    assert len(store.stats(users[0]['id'])['matches'])==1
    service.start(room,users[0]['id'])
    with pytest.raises(RuleError):service.command(users[0],'surrender',{'match':match})
    assert all(p.hp==15 and not p.surrendered for p in room.game.players.values())


def test_multiplayer_surrender_invalidates_ready_target_and_allows_retarget(arena):
    _,service,users=arena
    room=make_room(service,users)
    a,b,c=[u['id'] for u in users]
    room.game.choose(a,'shot',b)
    room.game.choose(b,'charge')
    service.command(users[1],'surrender',{'match':room.match_id})
    own=room.game.snapshot(a)
    assert own['choice']==('shot',None) and not own['ready']
    room.game.choose(c,'charge'); assert room.game.phase=='select'
    room.game.choose(a,'shot',c)
    assert room.game.phase=='reveal' and room.game.players[c].hp==13
    assert room.game.players[b].hp==0 and room.game.players[b].energy==0


def test_surrender_does_not_wait_for_missing_player_or_repeat_revealed_effects():
    g=BattleGame([Player(str(i),str(i)) for i in range(3)],now=0)
    g.choose('0','charge',now=1);g.choose('1','shield',now=2)
    g.surrender('2',now=3)
    assert g.phase=='reveal' and g.players['0'].energy==2
    g.surrender('1',now=4)
    assert g.phase=='finished' and g.winner=='0' and g.players['0'].energy==2


@pytest.mark.parametrize('last_winner',[0,1])
def test_rank_surrender_between_battles_loses_entire_series(arena,last_winner):
    store,service,users=arena
    room=rank_room(service,users)
    room.game.players[users[1-last_winner]['id']].hp=0
    room.game.resolve(time.time());service.tick()
    assert room.stage=='intermission'
    service.command(users[0],'surrender',{'match':room.match_id})
    assert room.stage=='finished' and room.winner==users[1]['id']
    assert store.get(users[0]['id'])['rating']==984
    assert store.get(users[1]['id'])['rating']==1016
    service.tick(time.time()+10)
    assert store.get(users[0]['id'])['games']==1
    assert len(room.history)==1
    assert room.history[-1][-1]['event']=='surrender'


def test_rank_surrender_during_first_battle_updates_elo_once(arena):
    store,service,users=arena
    room=rank_room(service,users)
    service.command(users[0],'surrender',{'match':room.match_id})
    assert room.stage=='finished' and room.score[users[1]['id']]==2
    assert store.get(users[0]['id'])['rating']==984 and len(room.history)==1
    with pytest.raises(RuleError):service.command(users[0],'surrender',{'match':room.match_id})
    assert store.get(users[0]['id'])['games']==1


def test_surrender_rejects_lobby_and_observer(arena):
    store,service,users=arena
    service.create(users[0],{'name':'Lobby','phrase':'lobby'})
    room=service.current(users[0]['id'])
    with pytest.raises(RuleError):service.command(users[0],'surrender',{'match':room.match_id})
    service.join(users[1],room.phrase);service.start(room,users[0]['id'])
    observer=store.guest('Observer');service.join(observer,room.phrase)
    with pytest.raises(RuleError):service.command(observer,'surrender',{'match':room.match_id})


def test_pierce_counter_requires_correct_target_and_counts_in_stats(arena):
    store,service,users=arena
    room=make_room(service,users)
    a,b,c=[u['id'] for u in users]
    room.game.players[a].energy=2
    room.game.choose(a,'pierce',b);room.game.choose(b,'counter',c);room.game.choose(c,'shield')
    assert room.game.players[b].hp==12 and room.game.players[a].hp==15
    game=BattleGame([Player(a,'A'),Player(b,'B')],now=0)
    game.players[a].energy=2
    game.choose(a,'pierce',b,now=1);game.choose(b,'counter',a,now=2)
    assert game.players[a].hp==13 and game.players[b].hp==15
    store.save_match(secrets.token_hex(12),'arena',[store.public(users[0]),store.public(users[1])],b,[game.history])
    assert store.stats(b)['counter_success']==1

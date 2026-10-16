import time
import secrets
from pathlib import Path
import pytest
from arena.store import AccountStore
from arena.service import ArenaService
from arena.game import RuleError


@pytest.fixture
def setup():
    store=AccountStore(Path('data/tests') / secrets.token_hex(8) / 'test.sqlite3')
    users=[store.register(f"user{i}",f"戦闘員{i}","test-password")[0] for i in range(3)]
    return store,ArenaService(store),users


def test_recovery_revokes_sessions_and_old_code(setup):
    store,_,users=setup
    user,code=store.register("recovery","復旧","test-password")
    token=store.session(user['id'])
    fresh=store.recover("recovery",code,"new-password")
    assert store.authenticate(token) is None
    assert store.login("recovery","new-password")['id']==user['id']
    with pytest.raises(RuleError):store.recover("recovery",code,"other-password")
    assert fresh!=code


def room_for(service,users):
    service.create(users[0],{'name':'TEST','phrase':'testroom','capacity':6})
    for user in users[1:]:service.join(user,'testroom')
    return service.current(users[0]['id'])


def test_arena_custom_settings_permissions_validation_and_rematch(setup):
    _,service,users=setup
    room=room_for(service,users)
    data={'initial_hp':20,'initial_energy':2,'allowed_cards':['charge','heal','drain']}
    with pytest.raises(RuleError):service.command(users[1],'room_settings',data)
    service.command(users[0],'room_settings',data)
    assert service.snapshot(users[1])['room']['rules']==data
    with pytest.raises(RuleError):service.command(users[0],'room_settings',{'name':'INVALID','initial_hp':0})
    assert room.name=='TEST'
    service.start(room,users[0]['id'])
    assert all(p.hp==20 and p.max_hp==20 and p.energy==2 for p in room.game.players.values())
    with pytest.raises(RuleError):service.command(users[0],'room_settings',{'initial_hp':5})
    with pytest.raises(RuleError):room.game.choose(users[0]['id'],'shot',users[1]['id'])
    room.stage='finished'; service.start(room,users[0]['id'])
    assert all(p.hp==20 and p.energy==2 for p in room.game.players.values())


def test_whispers_observers_and_blocks(setup):
    store,service,users=setup
    room=room_for(service,users)
    service.chat(users[0],room,{'target':users[1]['id'],'text':'秘密'})
    assert len(service.snapshot(users[0])['room']['messages'])==1
    assert len(service.snapshot(users[1])['room']['messages'])==1
    assert service.snapshot(users[2])['room']['messages']==[]
    service.start(room,users[0]['id'])
    room.game.players[users[2]['id']].hp=0
    service.chat(users[2],room,{'text':'観戦メッセージ'})
    assert all(m['text']!='観戦メッセージ' for m in service.snapshot(users[0])['room']['messages'])
    with pytest.raises(RuleError):service.chat(users[2],room,{'target':users[0]['id'],'text':'助言'})


def test_matchmaking_confirmation_series_elo_once(setup):
    store,service,users=setup
    now=time.time()
    for user in users[:2]:service.command(user,'queue',{})
    service.tick(now+1)
    room=service.current(users[0]['id'])
    assert room.stage=='confirm'
    for user in users[:2]:service.command(user,'accept',{})
    for index in range(2):
        room.game.players[users[1]['id']].hp=0
        room.game.resolve(time.time())
        service.tick(time.time())
        if index==0:
            assert room.stage=='intermission'
            assert store.get(users[0]['id'])['games']==0
            service.tick(room.deadline+1)
    assert room.stage=='finished' and room.winner==users[0]['id']
    assert store.get(users[0]['id'])['rating']==1016
    assert store.get(users[1]['id'])['rating']==984
    service.tick(time.time()+1)
    assert store.get(users[0]['id'])['games']==1


def test_confirmation_timeout_returns_accepted_player(setup):
    _,service,users=setup
    for user in users[:2]:service.command(user,'queue',{})
    service.tick(time.time()+1)
    room=service.current(users[0]['id'])
    service.command(users[0],'accept',{})
    since=service.queue[users[0]['id']]['since']
    service.tick(room.deadline+1)
    assert users[0]['id'] in service.queue and users[1]['id'] not in service.queue
    assert service.queue[users[0]['id']]['since']==since


def test_guest_upgrade_keeps_room(setup):
    store,service,_=setup
    guest=store.guest('ゲスト')
    service.create(guest,{'name':'test','phrase':'phrase'})
    old_room=service.current(guest['id']).id
    user,_=store.register('upgrade','正式','test-password',guest['id'])
    assert service.current(user['id']).id==old_room


def test_duplicate_phrase_host_transfer_and_start_permissions(setup):
    _,service,users=setup
    room=room_for(service,users)
    with pytest.raises(RuleError):service.create(users[2],{'name':'x','phrase':'testroom'})
    with pytest.raises(RuleError):service.start(room,users[1]['id'])
    service.leave(users[0]['id'])
    assert room.host==users[1]['id']


def test_history_retains_all_battles(setup):
    store,service,users=setup
    room=room_for(service,users[:2]);service.start(room,users[0]['id'])
    room.game.players[users[1]['id']].hp=0;room.game.resolve(time.time());service.tick()
    stats=store.stats(users[0]['id'])
    assert len(stats['matches'])==1 and stats['matches'][0]['history'][0][0]['round']==1


def test_draft_timeout_and_stale_round_commands(setup):
    _,service,users=setup
    room=room_for(service,users[:2]);service.start(room,users[0]['id'])
    game=room.game
    draft={'card':'shot','target':users[1]['id'],'round':game.round,'deadline':game.deadline}
    service.command(users[0],'select',draft)
    own=service.snapshot(users[0])['room']['game']
    other=service.snapshot(users[1])['room']['game']
    assert own['choice']==('shot',users[1]['id']) and own['ready'] is False
    assert other['choice'] is None and other['ready'] is False
    service.tick(game.deadline)
    assert game.players[users[1]['id']].hp==13
    assert [a['card'] for a in game.history[0]['actions']]==['shot','idle']
    service.tick(game.deadline)
    for action in ('select','choose'):
        with pytest.raises(RuleError):service.command(users[0],action,draft)
    assert game.choices=={} and game.phase=='select'

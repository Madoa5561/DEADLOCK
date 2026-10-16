"""独立したローカルサーバーで通信を検証する """
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import pytest
import requests
from websockets.sync.client import connect


@pytest.fixture(scope='module')
def server():
    env=dict(os.environ, DEADLOCK_PORT='8002', DEADLOCK_DB=str(Path('data/tests')/secrets.token_hex(8)/'http.sqlite3'))
    process=subprocess.Popen([sys.executable,'app.py'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(80):
            try:
                if requests.get('http://127.0.0.1:8002/api/state',timeout=.5).status_code==200:
                    break
            except requests.RequestException:
                time.sleep(.1)
        else:
            raise RuntimeError('Test server did not start')
        yield 'http://127.0.0.1:8002'
    finally:
        process.terminate()
        process.wait(timeout=10)


def call(session, server, action, **data):
    response=session.post(server+'/api/action',json={'action':action,**data},headers={'X-Deadlock-Client':'1'},timeout=5)
    assert response.status_code==200,response.text
    return response.json()


def test_custom_rules_and_new_cards_through_http(server):
    sessions=[requests.Session() for _ in range(3)]
    for i,s in enumerate(sessions):call(s,server,'guest',name=f'Custom{i}')
    users=[s.get(server+'/api/state').json()['user'] for s in sessions]
    rules={'initial_hp':15,'initial_energy':4,'allowed_cards':['heal','drain','energy_break']}
    created=call(sessions[0],server,'create',name='CUSTOM',phrase='custom-http',capacity=3,**rules)
    assert created['room']['rules']==rules
    for s in sessions[1:]:call(s,server,'join',phrase='custom-http')
    forbidden=sessions[1].post(server+'/api/action',json={'action':'room_settings',**rules},headers={'X-Deadlock-Client':'1'})
    assert forbidden.status_code==400
    call(sessions[0],server,'start')
    for s in sessions:
        g=s.get(server+'/api/state').json()['room']['game']
        assert g['hand']==rules['allowed_cards']
        assert all(p['hp']==15 and p['energy']==4 for p in g['players'])
    call(sessions[0],server,'choose',card='heal')
    call(sessions[1],server,'choose',card='drain',target=users[0]['id'])
    result=call(sessions[2],server,'choose',card='energy_break',target=users[1]['id'])
    g=result['room']['game']
    assert g['phase']=='reveal'
    assert [p['hp'] for p in g['players']]==[15,15,15]
    assert [p['energy'] for p in g['players']]==[2,0,3]
    assert [a['card'] for a in g['history'][0]['actions']]==rules['allowed_cards']


def test_new_fighter_profile_default_hp_and_surrender_http(server):
    sessions=[requests.Session() for _ in range(2)]
    for i,s in enumerate(sessions):call(s,server,'guest',name=f'Fighter{i}')
    for avatar in (5,6,7):
        call(sessions[0],server,'profile',avatar=avatar)
        assert sessions[0].get(server+'/api/state').json()['user']['avatar']==avatar
    call(sessions[0],server,'create',name='FORFEIT',phrase='forfeit-http')
    call(sessions[1],server,'join',phrase='forfeit-http')
    started=call(sessions[0],server,'start')['room']
    assert all(p['hp']==15 and p['max_hp']==15 for p in started['game']['players'])
    response=sessions[0].post(server+'/api/action',json={'action':'surrender','match':'stale'},headers={'X-Deadlock-Client':'1'})
    assert response.status_code==400
    result=call(sessions[0],server,'surrender',match=started['match_id'])['room']
    assert result['stage']=='finished' and result['game']['players'][0]['surrendered']
    assert sessions[0].get(server+'/api/stats').json()['matches'][0]['outcome']=='loss'


def test_real_http_websocket_and_private_messages(server):
    players=[requests.Session() for _ in range(3)]
    for i,session in enumerate(players):call(session,server,'guest',name=f'HTTP{i}')
    users=[s.get(server+'/api/state').json()['user'] for s in players]
    call(players[0],server,'create',name='通信検証',phrase='http-test',capacity=6)
    for session in players[1:]:call(session,server,'join',phrase='http-test')
    call(players[0],server,'chat',text='非公開のテスト',target=users[1]['id'])
    assert players[2].get(server+'/api/state').json()['room']['messages']==[]
    assert players[1].get(server+'/api/state').json()['room']['messages'][0]['text']=='非公開のテスト'
    call(players[0],server,'start')
    call(players[0],server,'choose',card='shot',target=users[1]['id'])
    opponent=players[1].get(server+'/api/state').json()['room']['game']
    assert opponent['choice'] is None and opponent['history']==[]
    cookie='deadlock_session='+players[1].cookies.get('deadlock_session')
    with connect(server.replace('http:','ws:')+'/ws',additional_headers={'Cookie':cookie},origin=server) as ws:
        ws.send('sync');snapshot=json.loads(ws.recv(timeout=5))
        assert snapshot['room']['game']['choice'] is None
        assert len(snapshot['room']['game']['players'])==3
    response=players[0].get(server+'/api/export')
    assert response.status_code==200 and response.content.startswith(b'\xef\xbb\xbf')


def test_auth_origin_and_guest_rank(server):
    session=requests.Session()
    assert session.post(server+'/api/action',json={'action':'guest','name':'x'}).status_code==400
    assert session.post(server+'/api/action',json={'action':'guest','name':'x'},headers={'X-Deadlock-Client':'1','Origin':'https://evil.example'}).status_code==400
    call(session,server,'guest',name='ゲスト')
    assert session.post(server+'/api/action',json={'action':'queue'},headers={'X-Deadlock-Client':'1'}).status_code==400
    registration=call(session,server,'register',login='httpaccount',name='正式',password='test-password')
    assert registration['recovery']
    user=session.get(server+'/api/state').json()['user']
    assert user['guest'] is False
    assert 'password' not in user and 'login' not in user
    call(session,server,'logout')
    assert session.get(server+'/api/state').json()['user'] is None
    call(session,server,'login',login='httpaccount',password='test-password')
    assert session.get(server+'/api/state').json()['user']['id']==user['id']

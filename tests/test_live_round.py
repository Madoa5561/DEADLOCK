from test_http import server, call
import time
import requests


def test_real_ready_resolves_simultaneously_before_deadline(server):
    sessions=[requests.Session() for _ in range(2)]
    users=[call(s,server,'guest',name=f'ROUND{i}')['user'] for i,s in enumerate(sessions)]
    call(sessions[0],server,'create',name='実時間検証',phrase='live-round')
    call(sessions[1],server,'join',phrase='live-round')
    started=call(sessions[0],server,'start')['room']['game']
    assert 49<=started['deadline']-time.time()<=50
    call(sessions[0],server,'select',card='shot',target=users[1]['id'])
    draft=sessions[0].get(server+'/api/state').json()['room']['game']
    assert draft['choice']==['shot',users[1]['id']] and draft['ready'] is False
    assert draft['history']==[]
    prepared=call(sessions[0],server,'choose',card='shot',target=users[1]['id'])['room']['game']
    assert prepared['ready'] is True and prepared['history']==[]
    began=time.monotonic()
    call(sessions[1],server,'choose',card='counter',target=users[0]['id'])
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        game=sessions[0].get(server+'/api/state').json()['room']['game']
        if game['history']:
            break
        time.sleep(.5)
    assert game['history'][0]['round']==1
    assert time.monotonic()-began<2 and time.time()<started['deadline']
    assert game['players'][0]['hp']==13
    assert game['players'][1]['hp']==15
    assert game['choice'] is None
    second=sessions[1].get(server+'/api/state').json()['room']['game']
    assert second['players']==game['players'] and second['history']==game['history']

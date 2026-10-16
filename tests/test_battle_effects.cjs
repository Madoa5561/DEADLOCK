const {test}=require('node:test');
const assert=require('node:assert/strict');
const {EffectStream,roundEvents,outcome,hazardState,roundDamage,energyFlow}=require('../static/battle-effects.js');
const players=[{id:'a',name:'A',hp:15,avatar:5},{id:'b',name:'B',hp:15,avatar:6}];
test('charge gain and break loss remain visible when the net effect is zero',()=>{
  assert.deepEqual(energyFlow({card:'charge',energy_gained:2,energy_lost:2,energy_effect:0}),{recorded:true,gained:2,lost:2,canceled:true});
  assert.equal(energyFlow({card:'charge',energy_gained:1,energy_lost:2}).canceled,true);
  assert.equal(energyFlow({card:'charge',energy_gained:0,energy_lost:2}).canceled,false);
  assert.equal(energyFlow({card:'heal',energy_gained:0,energy_lost:2}).canceled,false);
});
test('old public histories retain their recorded net energy effects',()=>{
  assert.deepEqual(energyFlow({energy_effect:-2}),{recorded:false,gained:0,lost:2,canceled:false});
  assert.deepEqual(energyFlow({card:'charge',energy_effect:2}),{recorded:false,gained:2,lost:0,canceled:false});
});
test('environment preview follows the server R7 / R12 / R17 schedule',()=>{
  for(const [round,damage,nextRound,nextDamage,remaining] of [[1,0,7,1,6],[6,0,7,1,1],[7,1,12,2,5],[11,1,12,2,1],[12,2,17,3,5],[17,3,22,4,5]]){
    assert.deepEqual(hazardState({round}),{round,damage,active:round>=7,nextRound,nextDamage,remaining});
    assert.equal(hazardState({round,hazard_damage:damage}).damage,damage);
  }
});
test('public round damage separates attack from unblockable environment damage',()=>{
  assert.deepEqual(roundDamage({hazard:true,hazard_damage:2},{damage:3}),{attack:3,hazard:2});
  assert.deepEqual(roundDamage({hazard:true,hazard_damage:2},{card:'shield',damage:0}),{attack:0,hazard:2});
  assert.deepEqual(roundDamage({hazard:false},{damage:2}),{attack:2,hazard:0});
  assert.equal(roundDamage({hazard:true},{damage:0}).hazard,1);
  assert.equal(roundDamage({event:'surrender',hazard:true},{damage:0}).hazard,0);
});
const record=(round=1)=>({round,actions:[{id:'a',card:'pierce',target:'b',damage:0,hp:15},{id:'b',card:'shield',target:null,damage:3,hp:12}],hazard:false});
function state({history=[],stage='playing',phase='select',round=1,winner=null,mode='arena',match='match',viewer='a',roster=players,gameWinner=winner}={}) {
  return {user:{id:viewer},room:{id:'room',match_id:match,stage,mode,winner,game:{round,phase,winner:gameWinner,history,players:structuredClone(roster)}}};
}
test('first sync does not replay historical attacks, duplicate sync does not repeat effects',()=>{
  const stream=new EffectStream(),first=state({history:[record()]});
  assert.deepEqual(stream.update(first).rounds,[]);
  assert.deepEqual(stream.update(first).rounds,[]);
  const next=state({history:[record(),record(2)],round:2,phase:'reveal'});
  assert.equal(stream.update(next).rounds.length,1);
  assert.equal(stream.update(next).rounds.length,0);
});
test('all ready result before tick and saved finished result produce one finisher',()=>{
  const stream=new EffectStream();stream.update(state());
  assert.equal(stream.update(state({history:[record()],phase:'finished',winner:'a'})).finisher,null);
  const end=state({history:[record()],stage:'finished',phase:'finished',winner:'a'});
  assert.equal(stream.update(end).finisher.word,'VICTORY');
  assert.equal(stream.update(end).finisher,null);
});
test('duel defeat waits for match result, not an elimination announcement',()=>{
  const stream=new EffectStream();stream.update(state());
  const roster=[{...players[0],hp:0},players[1]];
  assert.equal(stream.update(state({history:[record()],phase:'finished',roster,gameWinner:'b'})).finisher,null);
  assert.equal(stream.update(state({history:[record()],stage:'finished',phase:'finished',roster,winner:'b'})).finisher.scope,'match');
});
test('rank battle win and final match loss are distinguished',()=>{
  const stream=new EffectStream();stream.update(state({mode:'rank'}));
  const battle=state({mode:'rank',stage:'intermission',phase:'finished',history:[record()],gameWinner:'a'});
  assert.equal(stream.update(battle).finisher.scope,'battle');
  assert.equal(stream.update(battle).finisher,null);
  assert.equal(stream.update(state({mode:'rank'})).reset,true);
  assert.equal(stream.update(state({mode:'rank',stage:'finished',phase:'finished',history:[record()],winner:'b'})).finisher.word,'DEFEAT');
});
test('repeated drawn ranked battles reset without a score change',()=>{
  const stream=new EffectStream();stream.update(state({mode:'rank'}));
  const draw=state({mode:'rank',stage:'intermission',phase:'finished',history:[record()]});
  assert.equal(stream.update(draw).finisher.word,'DRAW');
  stream.update(state({mode:'rank'}));
  assert.equal(stream.update(draw).finisher.word,'DRAW');
});
test('rematch and logout clear consumed events',()=>{
  const stream=new EffectStream(),finish=state({stage:'finished',phase:'finished',winner:'a'});
  assert.equal(stream.update(finish).finisher.word,'VICTORY');
  assert.equal(stream.update(finish).finisher,null);
  assert.equal(stream.update(state({match:'rematch'})).reset,true);
  assert.equal(stream.update(state({match:'rematch',stage:'finished',phase:'finished',winner:'a'})).finisher.word,'VICTORY');
  assert.equal(stream.update({user:null,room:null}).reset,true);
});
test('multiplayer elimination is shown once and does not repeat at match end',()=>{
  const stream=new EffectStream(),roster=[...players,{id:'c',name:'C',hp:15,avatar:7}];
  stream.update(state({roster}));roster[0]={...roster[0],hp:0};
  const lost=state({roster,history:[record()],phase:'reveal'});
  assert.equal(stream.update(lost).finisher.scope,'elimination');
  assert.equal(stream.update(lost).finisher,null);
  assert.equal(stream.update(state({roster,history:[record()],phase:'finished',stage:'finished',winner:'b'})).finisher,null);
});
test('observers see winner announcement instead of their own victory or defeat',()=>{
  assert.equal(outcome(state({viewer:'observer',winner:'a'}).room,'observer').word,'BATTLE OVER');
  assert.equal(outcome(state({winner:null}).room,'a').word,'DRAW');
});
test('shield blocks shots and drains but never piercing fire',()=>{
  for(const [card,response] of [['shot','block'],['drain','block'],['pierce','hit']]) {
    const r=record();r.actions[0].card=card;
    assert.equal(roundEvents(r)[0].response,response);
  }
});
test('counter effect requires matching attacker and supports pierce',()=>{
  const r=record();r.actions[1]={id:'b',card:'counter',target:'a'};
  assert.equal(roundEvents(r)[0].response,'counter');
  r.actions[1].target='c';assert.equal(roundEvents(r)[0].response,'hit');
});
test('support cards and surrender are not misrepresented as attacks',()=>{
  const r={round:1,actions:[{id:'a',card:'heal'},{id:'b',card:'energy_break',target:'a'}]};
  assert.equal(roundEvents(r)[0].attack,false);
  assert.equal(roundEvents(r)[1].attack,true);
  assert.deepEqual(roundEvents({...r,event:'surrender'}),[]);
});
test('failed cost cards never produce attack or successful healing events',()=>{
  for(const card of ['heal','pierce','drain']){
    const events=roundEvents({round:1,actions:[{id:'a',card,target:'b',failed:true},{id:'b',card:'energy_break',target:'a'}]});
    assert.equal(events[0].failed,true);assert.equal(events[0].attack,false);
    assert.equal(events[1].failed,false);assert.equal(events[1].attack,true);
  }
});
test('a failed defensive card does not falsely block incoming attack effects',()=>{
  const events=roundEvents({round:1,actions:[{id:'a',card:'shot',target:'b'},{id:'b',card:'shield',failed:true}]});
  assert.equal(events[0].response,'hit');
});

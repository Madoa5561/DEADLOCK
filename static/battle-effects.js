'use strict';
// 演出にはサーバーが公開済みの行動だけを使う
(() => {
  const attacks = new Set(['shot', 'pierce', 'drain', 'energy_break']);
  const labels = {shot:'射撃', shield:'シールド', counter:'カウンター', charge:'チャージ', pierce:'貫通射撃', heal:'ヒール', drain:'ドレイン', energy_break:'エネルギーブレイク'};
  const words = {victory:'VICTORY', defeat:'DEFEAT', draw:'DRAW', spectator:'BATTLE OVER'};
  function hazardState(game) {
    const round=Number(game.round),damage=Number(game.hazard_damage??(round<7?0:1+Math.floor((round-7)/5)));
    const active=round>=7,nextRound=active?7+Math.floor((round-7)/5)*5+5:7;
    return {round,damage:active?damage:0,active,nextRound,nextDamage:active?damage+1:1,remaining:nextRound-round};
  }
  function roundDamage(round,action) {
    return {attack:action.damage||0,hazard:round.hazard&&round.event!=='surrender'?(round.hazard_damage??1):0};
  }
  function energyFlow(action) {
    const recorded=action.energy_gained!=null||action.energy_lost!=null;
    const gained=recorded?(action.energy_gained||0):Math.max(0,action.energy_effect||0);
    const lost=recorded?(action.energy_lost||0):Math.max(0,-(action.energy_effect||0));
    return {recorded,gained,lost,canceled:action.card==='charge'&&gained>0&&lost>=gained};
  }
  function outcome(room, viewer, scope='match') {
    const players=room.game?.players||[], actor=players.find(p=>p.id===viewer);
    const winner=scope==='battle'?room.game?.winner:room.winner;
    const kind=!winner?'draw':!actor?'spectator':winner===viewer?'victory':'defeat';
    const title={victory:'勝利',defeat:'敗北',draw:'引き分け',spectator:'対戦終了'}[kind];
    return {kind,word:words[kind],title,scope,winner:players.find(p=>p.id===winner),
      fighter:kind==='spectator'?players.find(p=>p.id===winner):actor,
      detail:scope==='elimination'?'脱落しました。残りの対戦を観戦できます。':scope==='battle'?'バトル決着 · 次のバトルへ':room.mode==='rank'?'ランク試合終了 · 戦績とレートに反映':'アリーナ決着 · 対戦結果を保存しました。'};
  }
  function roundEvents(round) {
    if(round.event==='surrender')return [];
    const actions=round.actions||[], byId=new Map(actions.filter(a=>!a.failed).map(a=>[a.id,a]));
    return actions.filter(a=>labels[a.card]).map(action=>{
      const response=byId.get(action.target);
      let responseType='hit';
      if(['shot','pierce','drain'].includes(action.card)) {
        if(response?.card==='counter'&&response.target===action.id)responseType='counter';
        else if(response?.card==='shield'&&action.card!=='pierce')responseType='block';
      }
      return {actor:action.id,target:action.target,card:action.card,label:labels[action.card],
        attack:!action.failed&&attacks.has(action.card),response:responseType,failed:!!action.failed};
    });
  }
  class EffectStream {
    constructor(){this.roomKey='';this.history=[];this.stage='';this.round=0;this.battle=0;this.finished=new Set();this.eliminated=false;}
    update(state) {
      const room=state.room,game=room?.game,key=room?`${state.user?.id}:${room.id}:${room.match_id}`:'';
      const reset=key!==this.roomKey;
      if(reset){this.roomKey=key;this.history=[];this.stage='';this.round=0;this.battle=0;this.finished.clear();this.eliminated=false;}
      if(!game){this.history=[];this.stage=room?.stage||'';return {reset,rounds:[],finisher:null};}
      const history=game.history||[], stamps=history.map(r=>JSON.stringify(r));
      const newBattle=!reset&&((this.stage==='intermission'&&room.stage==='playing'&&game.phase==='select')||game.round<this.round||stamps.length<this.history.length);
      if(newBattle){this.history=[];this.battle+=1;this.eliminated=false;}
      const start=this.history.length;
      // 初回取得時は過去の攻撃を再生せず 再接続での重複を防ぐ
      const rounds=reset?[]:history.slice(start).filter((r,i)=>stamps[start+i]!==this.history[start+i]);
      this.history=stamps;this.round=game.round;this.stage=room.stage;
      let finisher=null, finishKey='';
      if(room.stage==='finished') {
        finisher=outcome(room,state.user?.id);finishKey='match';
        if(this.eliminated&&finisher.kind==='defeat')finisher=null;
      }else if(room.stage==='intermission') {
        finisher=outcome(room,state.user?.id,'battle');finishKey=`battle:${this.battle}`;
      }else if(room.mode==='arena'&&game.phase!=='finished') {
        const actor=game.players.find(p=>p.id===state.user?.id);
        if(actor&&actor.hp<=0&&!this.eliminated){
          finisher={...outcome(room,state.user.id,'elimination'),kind:'defeat',word:'DEFEAT',title:'敗北'};
          finishKey='elimination';this.eliminated=true;
        }
      }
      if(finisher){if(this.finished.has(finishKey))finisher=null;else this.finished.add(finishKey);}
      return {reset:reset||newBattle,rounds,finisher};
    }
  }
  function crest(kind) {
    const shape=kind==='victory'?'M12 35L8 14L22 23L32 7L42 23L56 14L52 35ZM14 43H50M21 51H43':kind==='defeat'?'M32 7L53 15L49 36L32 55L15 36L11 15ZM35 12L26 28L38 34L29 49':kind==='draw'?'M11 24H53M11 40H53':'M32 8L54 32L32 56L10 32Z';
    return `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="${shape}"></path></svg>`;
  }
  class BattleEffects {
    constructor({reduced=()=>false,sound=()=>{}}={}) {
      this.reduced=reduced;this.sound=sound;this.stream=new EffectStream();this.timers=new Set();this.visible=false;this.until=0;this.resultVersion=0;this.resultTimer=null;
      this.layer=document.createElement('div');this.layer.id='battle-effects';this.layer.setAttribute('aria-hidden','true');
      this.result=document.createElement('aside');this.result.id='battle-finisher';this.result.hidden=true;
      this.result.setAttribute('role','status');this.result.setAttribute('aria-live','polite');this.result.setAttribute('aria-atomic','true');
      document.body.append(this.layer,this.result);
      this.result.addEventListener('click',event=>{if(event.target.closest('.finisher-dismiss'))this.dismiss();});
      document.addEventListener('keydown',event=>{if(event.key==='Escape')this.dismiss();});
      document.addEventListener('visibilitychange',()=>{if(document.hidden)this.clear();});
      window.addEventListener('resize',()=>this.clearAttacks());
    }
    later(callback,delay){const id=setTimeout(()=>{this.timers.delete(id);callback();},delay);this.timers.add(id);return id;}
    dismiss(){this.result.hidden=true;this.resultVersion+=1;if(this.resultTimer){clearTimeout(this.resultTimer);this.timers.delete(this.resultTimer);this.resultTimer=null;}}
    clearAttacks(){this.layer.replaceChildren();this.until=0;}
    clear(){for(const id of this.timers)clearTimeout(id);this.timers.clear();this.clearAttacks();this.dismiss();}
    setVisible(visible){this.visible=visible;if(!visible)this.clear();}
    update(state,{visible,sound=false}={}) {
      const events=this.stream.update(state);this.setVisible(visible);
      if(events.reset)this.clear();
      if(!visible||document.hidden)return;
      const latest=events.rounds.filter(round=>round.event!=='surrender').at(-1);
      if(latest){this.playRound(latest,state.room.game.players,state.user.id);if(sound)this.sound('round');}
      if(events.finisher){
        const result=events.finisher,version=++this.resultVersion,wait=this.reduced()?0:Math.min(2800,Math.max(0,this.until-Date.now()));
        this.later(()=>{if(this.visible&&version===this.resultVersion){this.showResult(result);if(sound)this.sound(result.kind);}},wait);
      }
    }
    point(id,viewer) {
      const candidates=Array.from(document.querySelectorAll('#battle-panel [data-fx-player]'));
      const node=candidates.find(e=>e.dataset.fxPlayer===id),r=node?.getBoundingClientRect();
      const width=document.documentElement.clientWidth,height=innerHeight;
      return {x:Math.max(38,Math.min(width-38,r?r.x+r.width/2:width/2)),
        y:Math.max(105,Math.min(height-70,r?r.y+r.height/2:height*(id===viewer ? 0.55 : 0.28)))};
    }
    place(node,point){node.style.left=`${point.x}px`;node.style.top=`${point.y}px`;this.layer.append(node);}
    stamp(point,label,kind,delay=0) {
      const node=document.createElement('span');node.className=`fx-stamp fx-${kind}`;node.textContent=label;
      node.style.animationDelay=`${delay}ms`;this.place(node,point);this.later(()=>node.remove(),delay+1900);
      const half=Math.min(node.offsetWidth/2,document.documentElement.clientWidth/2-8);
      node.style.left=`${Math.max(half+8,Math.min(document.documentElement.clientWidth-half-8,point.x))}px`;
    }
    burst(point,kind,delay=0) {
      const node=document.createElement('span');node.className=`fx-burst fx-${kind}`;
      node.innerHTML='<svg viewBox="0 0 100 100"><path d="M50 3L58 31L80 14L69 39L97 44L72 54L91 76L64 67L55 96L45 70L18 88L30 62L3 52L30 44L15 18L40 30Z"></path><circle cx="50" cy="50" r="19"></circle></svg>';
      node.style.animationDelay=`${delay}ms`;this.place(node,point);this.later(()=>node.remove(),delay+1400);
    }
    failure(point,card,delay) {
      const node=document.createElement('span');node.className='fx-failed-card';
      node.innerHTML=`<span class="card-art art-${card}"></span><b>×</b>`;
      node.style.animationDelay=`${delay}ms`;this.place(node,point);this.later(()=>node.remove(),delay+1900);
    }
    missile(event,start,end,delay) {
      const dx=end.x-start.x,dy=end.y-start.y,angle=Math.atan2(dy,dx)*180/Math.PI;
      const node=document.createElement('span');node.className=`fx-missile fx-${event.card}`;
      node.innerHTML=`<span class="card-art art-${event.card}"></span>`;
      node.style.setProperty('--dx',`${dx}px`);node.style.setProperty('--dy',`${dy}px`);node.style.setProperty('--angle',`${angle}deg`);node.style.animationDelay=`${delay}ms`;
      this.place(node,start);
      const trail=document.createElement('span');trail.className=`fx-trail fx-${event.card}`;
      trail.style.width=`${Math.hypot(dx,dy)}px`;trail.style.transform=`rotate(${angle}deg)`;trail.style.animationDelay=`${delay}ms`;this.place(trail,start);
      this.later(()=>{node.remove();trail.remove();},delay+1200);
    }
    playRound(round,players,viewer) {
      if(round.event==='surrender')return;
      this.clearAttacks();
      const order=e=>e.card==='charge'?-2:e.card==='energy_break'?-1:e.failed?1:0;
      const events=roundEvents(round).sort((a,b)=>order(a)-order(b)),byId=new Map(players.map(p=>[p.id,p]));
      const notice=document.createElement('div');notice.className='fx-round-notice';
      const heading=document.createElement('strong');heading.textContent=`ラウンド ${round.round} · 一斉公開`;
      const description=document.createElement('span');description.textContent=events.map(e=>`${byId.get(e.actor)?.name||'戦闘員'}：${e.label}${e.failed?'（EN不足で失敗）':''}`).join(' / ')||'無操作';
      notice.append(heading,description);
      const failures=events.filter(e=>e.failed);
      const canceled=(round.actions||[]).filter(a=>energyFlow(a).canceled);
      if(canceled.length){
        notice.classList.add('fx-energy-notice');
        const title=document.createElement('b');title.className='fx-energy-heading';title.textContent='チャージ相殺 · ENを破壊されました';
        const detail=document.createElement('span');detail.className='fx-energy-detail';
        detail.textContent=canceled.map(a=>`${byId.get(a.id)?.name||'戦闘員'}：残りEN ${a.energy}`).join(' / ');
        notice.prepend(title,detail);
      }
      if(failures.length){
        notice.classList.add('fx-failure-notice');
        const failure=document.createElement('b');failure.className='fx-failure-heading';
        failure.textContent='発動失敗 · EN不足';
        const detail=document.createElement('span');detail.className='fx-failure-detail';
        detail.textContent=failures.map(e=>`${byId.get(e.actor)?.name||'戦闘員'}：${e.label}失敗`).join(' / ');
        notice.prepend(failure,detail);
      }
      if(round.hazard){
        notice.classList.add('fx-hazard-notice');
        const hazard=document.createElement('b');hazard.className='fx-hazard-heading';
        hazard.textContent=`環境ダメージ発動 · 全員 −${round.hazard_damage??1} HP`;
        const warning=document.createElement('span');warning.textContent='シールド・カウンターで防げません';
        notice.prepend(hazard);notice.append(warning);
      }
      this.layer.append(notice);
      this.later(()=>notice.remove(),round.hazard||failures.length||canceled.length?4200:this.reduced()?2400:3000);
      if(this.reduced())return;
      events.forEach((event,index)=>{
        const start=this.point(event.actor,viewer),end=this.point(event.target,viewer),delay=250+index*130;
        if(event.failed){
          this.failure(start,event.card,delay+850);
          this.stamp({...start,y:start.y+44},`${event.label}失敗 · EN不足`,'failure',delay+850);
          return;
        }
        if(event.attack){
          this.missile(event,start,end,delay);
          const time=delay+850;
          this.burst(end,event.response==='block'?'shield':event.response==='counter'?'counter':event.card,time);
          if(event.response==='block')this.stamp(end,'BLOCK','shield',time);
          else if(event.response==='counter'){
            this.stamp(end,'COUNTER','counter',time);
            this.missile({...event,card:'counter'},end,start,time);
            this.burst(start,'counter',time+850);
          }else if(event.card==='energy_break')this.stamp(end,'EN BREAK','energy_break',time);
          else this.stamp(end,event.card==='pierce'?'PIERCE!':'HIT!','hit',time);
        }else{
          this.burst(start,event.card,delay+350);
          if(event.card==='shield'||event.card==='counter')this.stamp(start,event.card==='shield'?'GUARD':'構え','shield',delay+250);
        }
      });
      (round.actions||[]).forEach((action,index)=>{
        const point=this.point(action.id,viewer),damage=roundDamage(round,action),time=1300+index*130;
        if(damage.attack)this.stamp({...point,y:point.y-18},`−${damage.attack} HP`,'damage',time);
        if(damage.hazard)this.stamp({...point,y:point.y-44},`環境 −${damage.hazard} HP`,'hazard',time+320);
        if(action.healing)this.stamp({...point,y:point.y+18},`回復 +${action.healing}`,'heal',time+140);
        const flow=energyFlow(action);
        if(flow.gained)this.stamp({...point,y:point.y+40},`チャージ +${flow.gained}`,'charge',500+index*130);
        if(flow.lost)this.stamp({...point,y:point.y+40},`ブレイク −${flow.lost} EN`,'energy_break',time+260);
        if(flow.canceled)this.stamp({...point,y:point.y+65},`チャージ相殺 · EN ${action.energy}`,'energy_break',time+550);
      });
      this.until=Date.now()+2800;
    }
    showResult(result) {
      if(this.resultTimer){clearTimeout(this.resultTimer);this.timers.delete(this.resultTimer);}
      this.result.className=`finisher-${result.kind}${this.reduced()?' finisher-still':''}`;
      this.result.dataset.ready=this.reduced()?'true':'false';
      this.result.replaceChildren();
      const panel=document.createElement('div');panel.className='finisher-panel';
      const mark=document.createElement('div');mark.className='finisher-crest';mark.innerHTML=crest(result.kind);
      const kicker=document.createElement('p');kicker.className='finisher-kicker';kicker.textContent=result.scope==='battle'?'BATTLE RESULT':'DEADLOCK';
      const word=document.createElement('strong');word.className='finisher-word';word.textContent=result.word;
      word.addEventListener('animationend',()=>{if(this.result.contains(word))this.result.dataset.ready='true';},{once:true});
      const title=document.createElement('p');title.className='finisher-title';title.textContent=result.title;
      const fighter=document.createElement('div');fighter.className='finisher-fighter';
      if(result.fighter){
        const portrait=document.createElement('span');portrait.className='portrait';portrait.dataset.sprite=result.fighter.avatar;portrait.setAttribute('aria-hidden','true');
        portrait.style.backgroundPosition=result.fighter.avatar>=5?'center center':`${result.fighter.avatar*25}% 0%`;
        const name=document.createElement('span');name.textContent=result.fighter.name;fighter.append(portrait,name);
      }
      const detail=document.createElement('p');detail.className='finisher-detail';detail.textContent=result.detail;
      const close=document.createElement('button');close.type='button';close.className='finisher-dismiss';close.textContent='結果を見る';close.setAttribute('aria-label','演出を閉じて結果を見る');
      panel.append(kicker,mark,word,title,fighter,detail,close);this.result.append(panel);this.result.hidden=false;
      this.resultTimer=this.later(()=>this.dismiss(),this.reduced()?3000:4800);
    }
  }
  const api={EffectStream,roundEvents,outcome,BattleEffects,hazardState,roundDamage,energyFlow};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else window.DeadlockEffects=api;
})();

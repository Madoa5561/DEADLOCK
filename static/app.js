'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fighterNames=['戦闘員 1','戦闘員 2','戦闘員 3','戦闘員 4','戦闘員 5','戦闘員 6 · メカニック','戦闘員 7 · パイロット','戦闘員 8 · メディック'];
const cards = {
  shot: {name:'射撃', symbol:'↗', text:'相手に2ダメージ。消費なし。',target:true},
  shield:{name:'シールド',symbol:'□',text:'射撃・ドレインを防ぐ。貫通は防げない。'},
  counter:{name:'カウンター',symbol:'↩',text:'指定相手の射撃・ドレイン・貫通を防ぎ2反撃。',target:true},
  charge:{name:'チャージ',symbol:'＋',text:'先にEN＋2。最大4。その後ブレイクで減少。'},
  pierce:{name:'貫通射撃',symbol:'↗↗',text:'EN2消費、3ダメージ。シールド不可・カウンター可能。',target:true,cost:2},
  heal:{name:'ヒール',symbol:'＋',text:'EN2消費。HPを3回復。初期HPが回復上限。',cost:2},
  drain:{name:'ドレイン',symbol:'↙',text:'EN2消費。相手に2ダメージ、自分を1回復。防御・反撃されても回復。',target:true,cost:2},
  energy_break:{name:'エネルギーブレイク',symbol:'ϟ',text:'EN1消費。相手のENを2減らす。チャージ分も対象。EN不足のカードは失敗。防御・反撃不可。',target:true,cost:1}
};
const cardNumbers = {shot:'攻撃 2',shield:'軽減 2',counter:'反撃 2',charge:'EN +2',pierce:'EN2 / 攻撃 3',heal:'EN2 / HP +3',drain:'EN2 / 攻撃 2',energy_break:'EN1 / EN −2'};
const cardTitles = {counter:'カウン<wbr>ター',shield:'シー<wbr>ルド',charge:'チャー<wbr>ジ',pierce:'貫通<wbr>射撃',drain:'ドレ<wbr>イン',energy_break:'エネルギー<wbr>ブレイク'};
function cardIcon(key){
  const paths={shot:'M5 24L23 6M13 6H23V16M7 7L10 10M22 21L25 24',shield:'M16 3L26 7V16C26 23 16 29 16 29C16 29 6 23 6 16V7Z',counter:'M25 9H13C7 9 5 13 5 18C5 23 9 26 15 26H25M13 3L7 9L13 15',charge:'M18 3L7 18H15L13 29L25 13H17Z',pierce:'M4 25L22 7M12 7H22V17M11 28L28 11M24 3L29 8'};
  return `<span class="card-art art-${key}" aria-hidden="true"></span><span class="card-icon" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="${paths[key]||paths.charge}"></path></svg></span>`;
}
function recapPlayer(id,players,viewer){
  const player=players.find(p=>p.id===id),name=player?.name||'戦闘員';
  const avatar=Number.isInteger(player?.avatar)&&player.avatar>=0&&player.avatar<fighterNames.length?player.avatar:0;
  return `<span class="recap-player"><span class="portrait" data-sprite="${avatar}" aria-hidden="true"></span><span>${esc(name)}${id===viewer?'<small class="recap-you">自分</small>':''}</span></span>`;
}
function hazardNotice(game,actor){
  const h=DeadlockEffects.hazardState(game),urgent=h.active||h.remaining===1;
  const title=h.active?'環境ダメージ発生中':h.remaining===1?'次のラウンドから環境ダメージ':'環境ダメージ予告';
  const amount=h.active?`全員 −${h.damage} HP`:`R7から 全員 −1 HP`;
  const timing=h.active?`${game.phase==='select'?'このラウンドの終了時に発生':'このラウンドで発動済み'} · R${h.nextRound}から −${h.nextDamage} HP`:`開始まで あと${h.remaining}ラウンド`;
  return `<aside class="hazard-notice ${h.active?'hazard-active':urgent?'hazard-soon':'hazard-preview'}" role="note" aria-label="環境ダメージの案内"><span class="hazard-symbol" aria-hidden="true">!</span><div class="hazard-copy"><strong>${title}</strong><p>${timing}</p><p class="hazard-defense">シールド・カウンターで防げません${h.active?' · 毎ラウンド継続':''}</p>${h.active&&actor?.hp>0&&actor.hp<=h.damage?'<p class="hazard-critical">自分のHPが環境ダメージ以下です。回復しないと脱落するおそれがあります。</p>':''}</div><strong class="hazard-amount">${amount}</strong></aside>`;
}
function energyRecap(action){
  if(action.energy==null)return '';
  const flow=DeadlockEffects.energyFlow(action);
  const details=flow.recorded?`${flow.gained?`チャージ +${esc(flow.gained)}`:''}${flow.gained&&flow.lost?' / ':''}${flow.lost?`ブレイク −${esc(flow.lost)}`:''}`:action.energy_effect?`効果 ${action.energy_effect>0?'+':''}${esc(action.energy_effect)}`:'';
  return `<span class="recap-energy"><small>残りEN${action.energy_spent?` / 消費${esc(action.energy_spent)}`:''}</small><strong>${esc(action.energy)}</strong>${action.energy_before!=null?`<small>開始 ${esc(action.energy_before)} → 結果 ${esc(action.energy)}</small>`:''}${details?`<small>${details}</small>`:''}</span>`;
}
function roundRecap(round,players,viewer){
  return `<article class="round-recap"><div class="recap-heading"><h3>ラウンド ${esc(round.round)}${round.event==='surrender'?' · 降参':''}</h3>${round.hazard?`<span class="recap-tag hazard-tag">全員に環境 −${esc(round.hazard_damage??1)} HP · 防御不可</span>`:''}</div><div class="recap-actions">${round.actions.map(action=>{
    const card=cards[action.card],surrendered=action.card==='surrender',idle=!card;
    const art=idle?'<span class="recap-idle" aria-hidden="true">—</span>':`<span class="card-art art-${action.card}" aria-hidden="true"></span>`;
    const destination=action.target?`<span class="recap-target-label">対象 →</span>${recapPlayer(action.target,players,viewer)}`:`<span class="recap-target-label">${surrendered?'降参しました':idle?'カードを使用しませんでした':action.card==='shield'?'自分を防御':action.card==='charge'?'自分のENを増やす':'自分に使用'}</span>`;
    return `<div class="action-recap ${action.id===viewer?'recap-self':''}"><div class="recap-actor">${recapPlayer(action.id,players,viewer)}${DeadlockEffects.energyFlow(action).canceled?'<span class="recap-tag energy-canceled-tag">チャージ相殺</span>':''}${action.failed?'<span class="recap-tag failure-tag">発動失敗 · EN不足</span>':''}${action.timeout?'<span class="recap-tag timeout-tag">時間切れ</span>':''}</div><div class="recap-play"><div class="recap-card ${idle?'is-idle':''}">${art}<span><strong>${card?.name||(surrendered?'降参':'無操作')}</strong>${card?`<small>${cardNumbers[action.card]}</small>`:surrendered?'<small>対戦から脱落</small>':''}</span></div><div class="recap-target">${destination}</div></div><div class="recap-result"><span class="${action.damage>0?'recap-damage':'recap-safe'}"><small>カードダメージ</small><strong>${action.damage>0?'−':''}${esc(action.damage??0)}</strong></span>${action.failed?`<span class="recap-failure"><small>発動失敗 · コスト消費なし</small><strong>必要EN ${esc(action.energy_required??cards[action.card]?.cost)} / 残りEN ${esc(action.energy_available??0)}</strong></span>`:''}${round.hazard?`<span class="recap-hazard"><small>環境ダメージ</small><strong>−${esc(round.hazard_damage??1)}<small> HP / 防御不可</small></strong></span>`:''}${action.healing?`<span class="recap-healing"><small>回復効果</small><strong>+${esc(action.healing)}</strong></span>`:''}${energyRecap(action)}${action.hp!=null?`<span class="recap-hp"><small>残りHP</small><strong>${esc(action.hp)}<small> / ${esc(action.max_hp||10)}</small></strong></span>`:''}</div></div>`;
  }).join('')}</div></article>`;
}
$('#home-view .page-heading').insertAdjacentHTML('afterend', `<div class="lobby-hero"><div class="hero-copy"><p class="hero-kicker">心理戦カードバトル / 2〜6人</p><h2>その一手を、<br>読み切れ。</h2><p>攻撃、防御、カウンター。<br>最大50秒で選び、準備完了で一斉公開。</p><div class="hero-actions"><button class="primary" data-lobby="join-form">友達とアリーナへ <span aria-hidden="true">↗</span></button><button data-lobby="queue-button">ランクで決闘</button></div></div><div class="hero-fighter"><div id="hero-portrait" class="portrait" data-sprite="0" role="img" aria-label="選択中の戦闘員"></div><span>YOUR FIGHTER</span></div><div class="hero-caption">ARENA / DEADLOCK</div></div>`);
let state = {user:null,room:null}, view = 'home', authMode = 'login', socket, selectedCard, selectedTarget, avatar = 0;
let recoveryCode = '', lastMessages = '', profileLoaded = false, soundEnabled = false, lastPhase = '';
let serverOffset = 0, toastTimeout, reconnectTimer, lastState = 0, warnedRound = '';
let battleContext = '', battleMarkup = '';
let surrenderContext=null;
let roomHeaderMarkup = '', selectionQueue = Promise.resolve(), commitPending = '';
const battleEffects=new DeadlockEffects.BattleEffects({reduced:()=>document.body.classList.contains('reduce-motion')||window.matchMedia('(prefers-reduced-motion: reduce)').matches,sound:effectSound});
function saveSelection(ready=false){
  const game=state.room?.game;
  if(!game||game.phase!=='select'||game.ready||(!selectedCard&&(!ready||game.hand.length)))return Promise.resolve();
  const data={card:selectedCard||'idle',target:cards[selectedCard]?.target?selectedTarget:null,round:game.round,deadline:game.deadline};
  const context=battleContext;
  if(ready){commitPending=context;renderRoom();decorateSprites();}
  const request=selectionQueue.then(()=>api(ready?'choose':'select',data));
  selectionQueue=request.catch(()=>{});
  return request.finally(()=>{if(ready&&commitPending===context){commitPending='';render();}});
}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>$('#toast').hidden=true,4500);}
async function api(action, data={}){
  const response = await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Deadlock-Client':'1'},body:JSON.stringify({action,...data})});
  const result = await response.json();
  if(!response.ok) throw new Error(result.error || '操作に失敗しました');
  if(result.recovery) showRecovery(result.recovery);
  if(result.user && 'room' in result) applyState(result);
  return result;
}
function formData(form){const values=new FormData(form),data=Object.fromEntries(values);if(form.querySelector('[name=allowed_cards]')){data.allowed_cards=values.getAll('allowed_cards');data.initial_hp=Number(data.initial_hp);data.initial_energy=Number(data.initial_energy);}return data;}
function rulesForm(rules={initial_hp:15,initial_energy:0,allowed_cards:Object.keys(cards)}){
  return `<fieldset class="battle-rules-form"><legend>対戦ルール</legend><div class="initial-resources"><label>初期HP・回復上限<input name="initial_hp" type="number" min="1" max="100" step="1" value="${esc(rules.initial_hp)}" required></label><label>初期EN<select name="initial_energy">${[0,1,2,3,4].map(n=>`<option ${n===rules.initial_energy?'selected':''}>${n}</option>`).join('')}</select></label></div><p class="note">使用カード（1種類以上）・全員に適用</p><div class="allowed-card-options">${Object.entries(cards).map(([key,c])=>`<label class="allowed-card-option"><input type="checkbox" name="allowed_cards" value="${key}" ${rules.allowed_cards.includes(key)?'checked':''}>${cardIcon(key)}<span>${c.name}<small>${cardNumbers[key]}</small></span></label>`).join('')}</div><p class="note">初期ENで使えるカードを含めてください。使用できるカードがないラウンドは「無操作で準備完了」を選べます。</p></fieldset>`;
}
$('#create-rules').innerHTML=rulesForm();
function showRecovery(code){recoveryCode=code;$('#recovery-code').textContent=code;$('#recovery-dialog').showModal();}
function download(text,filename){const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('#save-recovery').onclick=()=>download('DEADLOCK 復旧コード\n'+recoveryCode+'\n他人に共有しないでください。\n','deadlock-recovery.txt');
$('#close-recovery').onclick=()=>{$('#recovery-dialog').close();recoveryCode='';$('#recovery-code').textContent='';};
function setAuth(mode){
  authMode=mode;const register=mode==='register',guest=mode==='guest',recover=mode==='recover';
  $('#auth-title').textContent=({login:'ログイン',register:'新規登録',guest:'ゲストで参加',recover:'パスワードの復旧'})[mode];
  $('#name-field').hidden=!(register||guest);$('#login-field').hidden=guest;$('#password-field').hidden=guest;
  $('#confirm-field').hidden=!(register||recover);$('#recovery-field').hidden=!recover;
  $('#auth-password-label').textContent=recover?'新しいパスワード':'パスワード';
  $('#auth-confirm-label').textContent=recover?'新しいパスワードの確認':'パスワード確認';
  for(const input of $('#auth-form').querySelectorAll('input')) input.required=!input.closest('label').hidden;
  $('#password-field input').autocomplete=mode==='login'?'current-password':'new-password';
  $('#auth-submit').textContent=({login:'ログイン',register:'アカウントを作成',guest:'ゲストで遊ぶ',recover:'パスワードを再設定'})[mode];
  document.querySelectorAll('[data-auth]').forEach(b=>b.classList.toggle('active',b.dataset.auth===mode));
  $('#auth-note').textContent=register?'IDは英数字・_の4〜24文字。パスワードは10文字以上。登録後、復旧コードを必ず保管してください。':recover?'復旧すると、既存のログインと旧復旧コードは無効になります。':'メールアドレスは使用しません。ゲストはアリーナで遊べます。';
}
document.querySelectorAll('[data-auth]').forEach(button=>button.onclick=()=>setAuth(button.dataset.auth));
$('#auth-form').onsubmit=async event=>{
  event.preventDefault();const data=formData(event.target);if(['register','recover'].includes(authMode)&&data.password!==data.confirm){toast('パスワードが一致していません');return;}
  $('#auth-submit').disabled=true;
  try{await api(authMode,data);event.target.reset();if(authMode==='recover'){setAuth('login');toast('再設定しました。ログインしてください');}else{view='home';profileLoaded=false;await sync();connect();}}
  catch(error){toast(error.message);}finally{$('#auth-submit').disabled=false;}
};
function spriteStyle(index,row){return `background-position:${index*25}% ${row?100:0}%`;}
function decorateSprites(){document.querySelectorAll('[data-sprite]').forEach(el=>{el.style.backgroundPosition=el.classList.contains('portrait')&&Number(el.dataset.sprite)>=5?'center center':`${Number(el.dataset.sprite)*25}% ${el.dataset.row==='1'?100:0}%`;});document.querySelectorAll('[data-width]').forEach(el=>el.style.width=el.dataset.width+'%');}
function rankIndex(rating){return rating>=1700?4:rating>=1400?3:rating>=1100?2:rating>=800?1:0;}
function showView(next){view=next;if(next==='register')setAuth('register');render();if(next==='stats')loadStats();if(next==='profile')loadProfile();window.scrollTo({top:0,behavior:'instant'});}
document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>showView(button.dataset.view));
function canSurrender(room=state.room){return !!room?.game&&((room.stage==='playing'&&room.game.players.some(p=>p.id===state.user?.id&&p.hp>0))||(room.mode==='rank'&&room.stage==='intermission'&&room.game.players.some(p=>p.id===state.user?.id)));}
function openSurrender(){if(!canSurrender())return;surrenderContext={room:state.room.id,match:state.room.match_id};$('#surrender-description').textContent=state.room.mode==='rank'?'このランク試合は敗北になります。戦績とレートに反映されます。':'この対戦から脱落します。残りの対戦は観戦できます。';$('#surrender-dialog').showModal();$('#cancel-surrender').focus();}
$('#cancel-surrender').onclick=()=>$('#surrender-dialog').close();
$('#surrender-dialog').onclose=()=>{surrenderContext=null;};
$('#confirm-surrender').onclick=async()=>{const context=surrenderContext;if(!context||context.room!==state.room?.id||context.match!==state.room?.match_id)return;$('#confirm-surrender').disabled=true;try{await api('surrender',{match:context.match});$('#surrender-dialog').close();}catch(error){toast(error.message);}finally{$('#confirm-surrender').disabled=false;}};
function render(){
  battleEffects.setVisible(!!state.user&&(view==='room'||view==='home'&&!!state.room));
  if(surrenderContext&&(!canSurrender()||surrenderContext.room!==state.room?.id||surrenderContext.match!==state.room?.match_id))$('#surrender-dialog').close();
  updateReadyWarning();
  const user=state.user;$('#navigation').hidden=!user;$('#auth-view').hidden=!!user&&view!=='register';
  document.body.classList.toggle('signed-in',!!user);
  for(const name of ['home','room','stats','profile','rules'])$('#'+name+'-view').hidden=true;
  $('#identity').innerHTML=user?`<span class="identity-name" title="${esc(user.name)}">${esc(user.name)}</span><span class="identity-meta">#${esc(user.tag)} · ${user.guest?'ゲスト':esc(user.rank)}</span>`:'未ログイン';
  if(!user){if(view==='rules'){$('#auth-view').hidden=true;$('#rules-view').hidden=false;}return;}
  document.querySelectorAll('[data-view]').forEach(b=>{const active=b.dataset.view===(view==='room'?'home':view);b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  if(view==='register')return;
  if(state.room&&view==='home')view='room';
  if(!state.room&&view==='room')view='home';
  $('#'+view+'-view').hidden=false;
  $('#player-dossier').innerHTML=`<div class="portrait dossier-portrait" data-sprite="${user.avatar}" role="img" aria-label="選択中のアバター"></div><h2>${esc(user.name)}</h2><p>#${user.tag} · ${user.guest?'ゲスト':esc(user.rank)}</p><button data-go="profile">戦闘員を変更</button>`;
  $('#hero-portrait').dataset.sprite=user.avatar;
  $('#rank-summary').innerHTML=user.guest?'<p class="rank-unplaced">登録するとランク対戦に参加できます。</p>':`${user.games>=5?`<div class="badge" data-sprite="${rankIndex(user.rating)}" data-row="1" role="img" aria-label="${esc(user.rank)}のバッジ"></div>`:''}<div><p>${esc(user.rank)}</p><div class="rank-score">${user.rating}<small> RP</small></div><p class="note">${user.games<5?`配置戦 ${user.games} / 5`:`${user.games}試合 / ${user.wins}勝`}</p></div>`;
  $('#queue-button').disabled=!!state.queue;$('#queue-button').textContent=user.guest?'アカウント登録':'対戦を探す';
  const queue=state.queue;$('#queue-panel').hidden=!queue||!!state.room;
  if(queue&&!state.room){const elapsed=Math.floor(Date.now()/1000+serverOffset-queue.since);$('#queue-panel').innerHTML=`<h2>対戦相手を検索中 · ${elapsed}秒</h2><p>待機人数：${state.waiting}人 / ${queue.wide?'レート差制限なし':'近いレートを優先'}</p><button data-command="cancel">検索を中止</button>${elapsed>=60&&!queue.wide?'<button data-command="wide">レート差の制限を外す</button>':''}`;}
  if(state.room)renderRoom();
  decorateSprites();
}
function renderRoom(){
  const r=state.room,u=state.user,g=r.game;const nameOf=id=>r.members.find(m=>m.id===id)?.name||g?.players.find(p=>p.id===id)?.name||'退出した戦闘員';
  $('#room-view').classList.toggle('in-battle',['playing','intermission'].includes(r.stage));
  const roomHeader=`<div class="room-top"><div><p class="eyebrow">${r.mode==='rank'?'ランク · 1対1':'アリーナ · 個人戦'}</p><h1>${esc(r.name)}</h1><p class="sub">${r.mode==='arena'?`合言葉：${esc(r.phrase)} / ${r.members.length}人 / 定員${r.capacity}`:'2本先取 / 最大5バトル'}</p></div>${r.stage!=='playing'&&r.stage!=='intermission'?'<button data-command="leave">部屋から退出</button>':`<div class="room-controls"><span class="note">再接続で復帰できます</span>${canSurrender(r)?'<button type="button" id="open-surrender" class="surrender-button" aria-haspopup="dialog"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 21V3M5 4H18L15 8L18 12H5"></path></svg>降参</button>':''}</div>`}</div>`;
  const settings=r.mode==='arena'&&r.host===u.id&&['lobby','finished'].includes(r.stage)?`<details class="room-settings"><summary>部屋設定を変更</summary><form id="room-settings-form"><label>部屋名<input name="name" value="${esc(r.name)}" maxlength="30" required></label><label>合言葉<input name="phrase" value="${esc(r.phrase)}" minlength="2" maxlength="32" required></label><label>定員<select name="capacity">${[2,3,4,5,6].map(n=>`<option ${n===r.capacity?'selected':''}>${n}</option>`).join('')}</select></label>${rulesForm(r.rules)}<button>設定を保存</button></form></details>`:'';
  const ruleSummary=r.rules?`<div class="room-rules-summary"><strong>初期HP ${esc(r.rules.initial_hp)} / 初期EN ${esc(r.rules.initial_energy)}</strong><span>使用カード：${r.rules.allowed_cards.map(key=>esc(cards[key]?.name||key)).join('・')}</span></div>`:'';
  if(roomHeader+ruleSummary+settings!==roomHeaderMarkup){$('#room-header').innerHTML=roomHeader+ruleSummary+settings;roomHeaderMarkup=roomHeader+ruleSummary+settings;}
  let html='';
  if(r.stage==='confirm'){
    html=`<div class="outcome"><h2>対戦相手が見つかりました</h2><p>${r.members.map(m=>esc(m.name)+' / '+m.rating+' RP').join(' vs ')}</p><p>残り <span class="countdown" data-deadline="${r.deadline}"></span> 秒</p><button class="primary" data-command="accept" ${r.accepted?'disabled':''}>${r.accepted?'承認済み · 相手を待っています':'対戦を承認する'}</button></div>`;
  }else if(!g){
    html=`<p class="eyebrow">参加者</p><div class="player-grid">${r.members.map(m=>`<article class="player"><div class="portrait" data-sprite="${m.avatar}"></div><h3>${esc(m.name)}</h3><small>#${m.tag} ${m.id===r.host?' / 部屋主':''}</small>${r.host===u.id&&m.id!==u.id?`<button data-command="kick" data-target="${m.id}">退出</button>`:''}</article>`).join('')}</div><div class="battle-status"><p>2人以上で開始できます。</p>${r.host===u.id?`<button class="primary" data-command="start" ${r.members.length<2?'disabled':''}>対戦を開始</button>`:'<p>部屋主の開始を待っています。</p>'}</div>`;
  }else{
    const actor=g.players.find(p=>p.id===u.id);
    const context=r.id+':'+Object.values(r.score).join(',')+':'+g.round+':'+g.deadline;
    const can=r.stage==='playing'&&actor?.hp>0&&g.phase==='select'&&!g.ready&&commitPending!==context;
    if(context!==battleContext){selectedCard=g.choice?.[0]||null;selectedTarget=g.choice?.[1]||null;battleContext=context;}
    if(!g.hand.includes(selectedCard))selectedCard=null;
    if(!g.players.some(p=>p.id===selectedTarget&&p.hp>0&&p.id!==u.id))selectedTarget=null;
    const activeBattle=r.stage!=='finished';
    const visiblePlayers=g.players.filter(p=>!activeBattle||p.id!==actor?.id);
    html=`${activeBattle&&visiblePlayers.length>1?'<p class="opponent-hint">相手の戦闘員 · 横にスワイプして確認</p>':''}<div class="player-grid ${visiblePlayers.length===1?'duel':activeBattle?'opponent-strip':''}">${visiblePlayers.map(p=>{
      const targetable=can&&cards[selectedCard]?.target&&p.hp>0&&p.id!==u.id;
      return `<article data-fx-player="${esc(p.id)}" class="player ${p.id===u.id?'self':''} ${p.hp<=0?'dead':''} ${targetable?'targetable':''} ${targetable&&p.id===selectedTarget?'targeted':''}"><div class="portrait" data-sprite="${p.avatar}"></div><h3 title="${esc(p.name)}">${esc(p.name)}${p.id===u.id?'（自分）':''}</h3><div class="numbers">HP ${p.hp} / EN ${p.energy}</div><small>${p.hp<=0?(p.surrendered?'降参':'脱落'):`直前：${cards[p.previous]?.name||'—'}`}${r.mode==='rank'?` / ${r.score[p.id]||0}勝`:''}</small><div class="hp-track"><div class="hp-fill" data-width="${100*p.hp/(p.max_hp||10)}"></div></div>${targetable?`<button type="button" class="player-target" data-opponent="${p.id}" aria-label="${esc(p.name)}を対象に選択、HP ${p.hp}、EN ${p.energy}" aria-pressed="${p.id===selectedTarget}"></button>`:''}</article>`;
    }).join('')}</div>`;
    if(activeBattle&&actor)html+=`<div class="self-hud" data-fx-player="${esc(actor.id)}"><div class="portrait" data-sprite="${actor.avatar}" aria-hidden="true"></div><div><strong>自分${r.mode==='rank'?` · ${r.score[actor.id]||0}勝`:''}</strong><br><span>${actor.hp<=0?(actor.surrendered?'降参・観戦中':'脱落・観戦中'):`直前：${cards[actor.previous]?.name||'—'}`}</span></div><span class="self-numbers">HP ${actor.hp} / EN ${actor.energy}</span></div>`;
    if(r.stage==='finished'){
      const result=DeadlockEffects.outcome(r,u.id);
      html+=`<div class="outcome"><p class="outcome-word result-${result.kind}">${result.word}</p><h2>${r.winner?esc(nameOf(r.winner))+' の勝利':'引き分け'}</h2><p>${r.mode==='rank'?'試合結果を保存し、レートを更新しました。':'対戦結果を保存しました。'}</p>${r.mode==='arena'&&r.host===u.id?'<button class="primary" data-command="start">同じ部屋で再戦</button>':'<button data-command="leave">ロビーに戻る</button>'}<button data-go="stats">戦績を見る</button></div>`;
      if(r.mode==='arena')html+=`<p class="note">${[...g.players].sort((a,b)=>(b.eliminated??999)-(a.eliminated??999)).map(p=>esc(p.name)+': '+(p.hp>0?'生存':`R${p.eliminated}脱落`)).join(' / ')}</p>`;
    }else if(r.stage==='intermission'){
      html+=`<div class="outcome"><h2>${g.winner?esc(nameOf(g.winner))+' が1本獲得':'このバトルは引き分け'}</h2><p>次のバトルまで <span class="countdown" data-deadline="${r.deadline}"></span> 秒</p></div>`;
    }else{
      html+=`<div class="battle-status"><div><p class="eyebrow">ラウンド ${g.round} · ${g.phase==='select'?'カードを選択':'結果を公開'}</p>${!actor||actor.hp<=0?'<p>観戦中</p>':''}</div><span class="timer"><span class="countdown" data-deadline="${g.deadline}"></span><small>秒</small></span></div>`;
      html+=hazardNotice(g,actor);
      html+=`<div class="card-grid">${Object.entries(cards).filter(([key])=>(g.rules?.allowed_cards||Object.keys(cards)).includes(key)).map(([key,c])=>`<button class="card ${selectedCard===key?'selected':''}" data-card="${key}" aria-pressed="${selectedCard===key}" aria-label="${c.name}、${cardNumbers[key]}。${c.text}${actor?.previous===key?' 連続使用不可。':actor?.energy<(c.cost||0)?' エネルギー不足。':''}" ${!can||!g.hand.includes(key)?'disabled':''}>${cardIcon(key)}<span class="card-cost">${cardNumbers[key]}</span><strong>${cardTitles[key]||c.name}</strong><small>${c.text}</small><small>${actor?.previous===key?'連続不可':actor?.energy<(c.cost||0)?'EN不足':''}</small></button>`).join('')}</div><p class="card-help" role="status">${!actor||actor.hp<=0?'観戦中です。公開済みの行動を確認できます。':g.phase!=='select'?'結果公開中。次のラウンドを待ってください。':selectedCard?esc(cards[selectedCard].name+'：'+cards[selectedCard].text+(cards[selectedCard].target?(selectedTarget?' 対象：'+nameOf(selectedTarget):' 上の戦闘員をタップして対象を選択。'):'') ):!g.hand.length?'使用できるカードがありません。無操作で準備完了できます。':'カードを選ぶと、ここに効果が表示されます。'}</p>`;
      if(actor?.hp>0&&g.phase==='select'){html+=`<div class="target-line"><label><span class="target-caption">対象</span><select id="battle-target" ${!can||!cards[selectedCard]?.target?'disabled':''}><option value="">相手を選択</option>${g.players.filter(p=>p.id!==u.id&&p.hp>0).map(p=>`<option value="${p.id}" ${p.id===selectedTarget?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label><button class="primary" id="commit" ${!can||g.hand.length>0&&(!selectedCard||cards[selectedCard]?.target&&!selectedTarget)?'disabled':''}>${g.ready?'準備完了':commitPending===context?'準備完了を送信中…':!g.hand.length?'無操作で準備完了':'カードを伏せる'}</button></div><p class="selection-note" role="status">${g.ready?'準備完了。全員の準備完了でカード効果が発動します。':selectedCard?(cards[selectedCard].target&&!selectedTarget?'対象を選んでください。対象が未選択のまま時間切れになると無操作です。':'選択中。カードを伏せると準備完了。時間切れは選択中のカードを使用します。'):!g.hand.length?'使用できるカードがありません。無操作で準備完了できます。':'未選択。時間切れは無操作になります。'}</p>`;}
    }
  }
  if(html!==battleMarkup){$('#battle-panel').innerHTML=html;battleMarkup=html;}
  $('#history-panel').innerHTML=g?`<div class="history"><h3>公開済みの行動</h3><p class="recap-guide">戦闘員・使ったカード・対象・受けたダメージを確認できます。</p>${g.history.slice(-5).reverse().map(round=>roundRecap(round,g.players,u.id)).join('')||'<p class="note">公開された行動はまだありません。</p>'}</div>`:'';
  const targets=r.members.filter(m=>m.id!==u.id);const signature=targets.map(m=>m.id+m.name).join();
  if($('#chat-target').dataset.signature!==signature){const previous=$('#chat-target').value;$('#chat-target').innerHTML='<option value="">公開チャット</option>'+targets.map(m=>`<option value="${m.id}">ウィスパー：${esc(m.name)}</option>`).join('');$('#chat-target').value=targets.some(t=>t.id===previous)?previous:'';$('#moderation-target').innerHTML=targets.map(m=>`<option value="${m.id}">${esc(m.name)}</option>`).join('');$('#chat-target').dataset.signature=signature;}
  const messageSignature=JSON.stringify(r.messages);if(lastMessages!==messageSignature){const panel=$('#messages');const bottom=panel.scrollHeight-panel.scrollTop-panel.clientHeight<50;panel.innerHTML=r.messages.map(m=>`<div class="message ${m.target?'whisper':''}"><b>${esc(m.name)}${m.target?' → '+esc(nameOf(m.target))+' / ウィスパー':' / 公開'}${m.observer?' / 観戦':''}</b>${esc(m.text)}</div>`).join('');if(bottom)panel.scrollTop=panel.scrollHeight;lastMessages=messageSignature;}
  updateTimers();
}
function updateTimers(){document.querySelectorAll('.countdown').forEach(el=>el.textContent=Math.max(0,Math.ceil(Number(el.dataset.deadline)-Date.now()/1000-serverOffset)));updateReadyWarning();}
function updateReadyWarning(){
  const room=state.room,game=room?.game,actor=game?.players.find(p=>p.id===state.user?.id);
  const remaining=game?game.deadline-Date.now()/1000-serverOffset:0;
  const urgent=room?.stage==='playing'&&game?.phase==='select'&&actor?.hp>0&&!game.ready&&remaining>0&&remaining<10;
  const warning=$('#ready-warning');warning.hidden=!urgent;
  document.querySelectorAll('.timer').forEach(el=>el.classList.toggle('timer-urgent',!!urgent));
  if(!urgent)return;
  const seconds=Math.ceil(remaining),context=room.id+':'+game.round+':'+game.deadline;
  $('#ready-warning-time').textContent=`残り${seconds}秒・まだ準備完了していません`;
  $('#ready-warning-help').textContent=!game.hand.length?'「無操作で準備完了」を押してください。':selectedCard?cards[selectedCard]?.target&&!selectedTarget?'対象を選び、「カードを伏せる」を押してください。':'「カードを伏せる」を押して準備完了してください。':'カードと必要な対象を選び、「カードを伏せる」を押してください。';
  if(warnedRound!==context){warnedRound=context;if(soundEnabled)beep();}
}
function applyState(next){if(next.server_time&&state.server_time&&next.server_time<state.server_time)return;state=next;lastState=Date.now();if(next.server_time)serverOffset=next.server_time-Date.now()/1000;const phase=next.room?.game?.phase+':'+next.room?.game?.round;if(lastPhase&&phase!==lastPhase&&soundEnabled&&next.room?.game?.phase==='select')beep();lastPhase=phase;render();battleEffects.update(next,{visible:view==='room',sound:soundEnabled});}
async function sync(){try{const response=await fetch('/api/state');applyState(await response.json());}catch{ $('#connection').textContent='再接続中';}}
function connect(){clearTimeout(reconnectTimer);if(socket)socket.close();if(!state.user)return;socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);socket.onopen=()=>{$('#connection').textContent='接続済み';socket.send('sync');};socket.onmessage=e=>{applyState(JSON.parse(e.data));$('#connection').textContent='接続済み';};socket.onclose=()=>{if(state.user){$('#connection').textContent='再接続中';reconnectTimer=setTimeout(connect,2500);}};socket.onerror=()=>socket.close();}
setInterval(()=>{updateTimers();if(state.user){if(socket?.readyState===WebSocket.OPEN)socket.send('sync');else sync();if(Date.now()-lastState>5000)$('#connection').textContent='応答待ち';}},1000);
document.addEventListener('click',async event=>{
  if(!event.target.closest('.nav-tools summary'))$('.nav-tools').removeAttribute('open');
  const button=event.target.closest('button');if(!button)return;
  try{
    if(button.dataset.command){button.disabled=true;await api(button.dataset.command,{target:button.dataset.target});}
    if(button.dataset.go)showView(button.dataset.go);
    if(button.dataset.lobby){const target=document.getElementById(button.dataset.lobby);target.scrollIntoView({behavior:document.body.classList.contains('reduce-motion')?'instant':'smooth',block:'center'});(target.querySelector('input')||target).focus({preventScroll:true});}
    if(button.dataset.card){selectedCard=button.dataset.card;renderRoom();decorateSprites();await saveSelection();}
    if(button.dataset.opponent){selectedTarget=button.dataset.opponent;renderRoom();decorateSprites();await saveSelection();}
    if(button.id==='commit'){await saveSelection(true);}
    if(button.id==='open-surrender')openSurrender();
    if(button.dataset.avatar){avatar=Number(button.dataset.avatar);document.querySelectorAll('[data-avatar]').forEach(b=>{const active=Number(b.dataset.avatar)===avatar;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}
  }catch(error){toast(error.message);button.disabled=false;}
});
document.addEventListener('change',async event=>{if(event.target.id==='battle-target'){selectedTarget=event.target.value;renderRoom();decorateSprites();try{await saveSelection();}catch(error){toast(error.message);}}});
document.addEventListener('submit',async event=>{if(event.target.id==='room-settings-form'){event.preventDefault();const data=formData(event.target);data.capacity=Number(data.capacity);try{await api('room_settings',data);toast('部屋設定を更新しました');}catch(error){toast(error.message);}}});
for(const [id,action] of [['join-form','join'],['create-form','create'],['chat-form','chat']])$('#'+id).onsubmit=async event=>{event.preventDefault();const data=formData(event.target);if(action==='create')data.capacity=Number(data.capacity);try{await api(action,data);if(action==='chat')$('#chat-input').value='';else{view='room';render();}}catch(error){toast(error.message);}};
$('#queue-button').onclick=async()=>{if(state.user.guest){showView('register');return;}try{await api('queue');}catch(error){toast(error.message);}};
$('#logout').onclick=async()=>{try{await api('logout');state={user:null,room:null};socket?.close();view='home';profileLoaded=false;render();}catch(error){toast(error.message);}};
$('#moderation-form').onsubmit=async event=>{event.preventDefault();try{await api(event.submitter.value,formData(event.target));toast(event.submitter.value==='report'?'通報を受け付けました':'相手をブロックしました');}catch(error){toast(error.message);}};
function loadProfile(){if(profileLoaded)return;avatar=state.user.avatar;$('#profile-form [name=name]').value=state.user.name;$('#avatar-options').innerHTML=fighterNames.map((name,i)=>`<button type="button" class="avatar-option ${i===avatar?'active':''}" data-avatar="${i}" aria-label="${esc(name)}" aria-pressed="${i===avatar}"><div class="portrait" data-sprite="${i}"></div><span>${esc(name)}</span></button>`).join('');$('#account-settings').hidden=state.user.guest;$('#upgrade').hidden=!state.user.guest;profileLoaded=true;decorateSprites();}
$('#profile-form').onsubmit=async event=>{event.preventDefault();try{await api('profile',{...formData(event.target),avatar});await sync();toast('戦闘員を更新しました');}catch(error){toast(error.message);}};
$('#security-form').onsubmit=async event=>{event.preventDefault();const data=formData(event.target);data.rotate_recovery=!!data.rotate_recovery;if(!data.new_password&&!data.rotate_recovery){toast('変更する項目を選んでください');return;}try{await api('profile',data);event.target.reset();await sync();if(!state.user){socket?.close();toast('パスワードを変更しました。再ログインしてください');}else toast('復旧コードを更新しました');}catch(error){toast(error.message);}};
$('#delete-form').onsubmit=async event=>{event.preventDefault();try{await api('delete_account',formData(event.target));state={user:null,room:null};socket?.close();event.target.reset();render();toast('退会しました');}catch(error){toast(error.message);}};
$('#upgrade').onclick=()=>showView('register');
$('#reduced-motion').checked=localStorage.getItem('reduce-motion')==='1';document.body.classList.toggle('reduce-motion',$('#reduced-motion').checked);
$('#reduced-motion').onchange=e=>{document.body.classList.toggle('reduce-motion',e.target.checked);localStorage.setItem('reduce-motion',e.target.checked?'1':'0');};
let audioContext;function beep(){try{audioContext ||= new AudioContext();const oscillator=audioContext.createOscillator(),gain=audioContext.createGain();gain.gain.value=.035;oscillator.frequency.value=540;oscillator.connect(gain);gain.connect(audioContext.destination);oscillator.start();oscillator.stop(audioContext.currentTime+.08);}catch{}}
function effectSound(kind){try{audioContext ||= new AudioContext();audioContext.resume().catch(()=>{});const tones=({victory:[392,494,587,784],defeat:[330,277,220],draw:[330,330],spectator:[392,494],round:[720,380]})[kind]||[540];tones.forEach((frequency,i)=>{const oscillator=audioContext.createOscillator(),gain=audioContext.createGain(),start=audioContext.currentTime+i*.11;oscillator.type=kind==='round'?'triangle':'sine';oscillator.frequency.value=frequency;gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(.025,start+.012);gain.gain.exponentialRampToValueAtTime(.001,start+.18);oscillator.connect(gain);gain.connect(audioContext.destination);oscillator.start(start);oscillator.stop(start+.2);});}catch{}}
$('#sound').onclick=()=>{soundEnabled=!soundEnabled;$('#sound').textContent=soundEnabled?'音 ON':'音 OFF';if(soundEnabled)beep();};
async function loadStats(){
  try{const response=await fetch('/api/stats');const data=await response.json();if(!response.ok)throw new Error(data.error);
    const max=Math.max(1,...Object.values(data.usage));const ranked=data.matches.filter(m=>m.mode==='rank').reverse();
    const ratings=ranked.map(m=>m.rating);const low=Math.min(1000,...ratings)-30,high=Math.max(1000,...ratings)+30;
    const points=ratings.map((rating,i)=>`${60+i*460/Math.max(1,ratings.length-1)},${160-(rating-low)*130/(high-low)}`).join(' ');
    $('#stats-content').innerHTML=`<div class="stats-grid"><article class="stat-box"><h2>カード使用回数</h2>${Object.entries(data.usage).map(([key,count])=>`<div class="bar-row"><span>${cards[key].name}</span><div><div class="bar" data-width="${100*count/max}"></div></div><span>${count}</span></div>`).join('')}</article><article class="stat-box"><h2>レート推移</h2>${ratings.length?`<svg class="rating-chart" viewBox="0 0 550 180" role="img" aria-label="直近のランクレート推移"><text x="0" y="20">${high}</text><text x="0" y="160">${low}</text><polyline points="${points}"></polyline>${points.split(' ').map(point=>{const [x,y]=point.split(',');return `<circle cx="${x}" cy="${y}" r="4"></circle>`;}).join('')}</svg><p class="note">最新レート ${ratings.at(-1)} RP / 直近${ratings.length}試合</p>`:'<p class="empty">ランク対戦後に表示されます。</p>'}</article></div><h2 class="history">対戦履歴</h2>${data.matches.map(m=>`<details class="match-detail"><summary>${new Date(m.created*1000).toLocaleString('ja-JP')} / ${m.mode==='rank'?'ランク':'アリーナ'} / ${{win:'勝利',loss:'敗北',draw:'引き分け'}[m.outcome]} / ${m.rating} RP (${m.delta>=0?'+':''}${m.delta})</summary>${m.history.map((battle,index)=>`<section class="recap-battle"><h3>バトル ${index+1}</h3>${battle.map(round=>roundRecap(round,m.players,state.user.id)).join('')}</section>`).join('')}</details>`).join('')||'<p class="empty">対戦履歴はまだありません。</p>'}<h2 class="history">ランキング</h2><table><thead><tr><th>順位</th><th>戦闘員</th><th>ランク</th><th>RP</th></tr></thead><tbody>${data.leaderboard.map((p,i)=>`<tr><td>${i+1}</td><td>${esc(p.name)} #${p.tag}</td><td>${p.rank}</td><td>${p.rating}</td></tr>`).join('')}</tbody></table><p class="note">配置戦を終えたプレイヤーが掲載されます。</p>`;
    const counterInfo=document.createElement('p');counterInfo.className='note';counterInfo.textContent=`カウンター成功：${data.counter_success} / ${data.usage.counter}回（${data.usage.counter?Math.round(100*data.counter_success/data.usage.counter):0}%）`;$('#stats-content .stat-box').append(counterInfo);
    decorateSprites();
  }catch(error){toast(error.message);}
}
$('#fighter-lineup').innerHTML=fighterNames.map((name,i)=>`<span class="portrait" data-sprite="${i}" aria-hidden="true"></span>`).join('');decorateSprites();
$('#rule-cards').innerHTML=Object.entries(cards).map(([key,c])=>`<article class="rule-card">${cardIcon(key)}<h3>${c.name}</h3><p class="card-cost">${cardNumbers[key]}</p><p>${c.text}</p></article>`).join('');
(async()=>{setAuth('login');await sync();connect();})();

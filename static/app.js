const $=id=>document.getElementById(id);
let job=null, tab='origin', uploading=false, chatBusy=false, activeJobs=[], heartbeatJobs=[];
let uploadAttempt=null;
const fields={origin:'transcript',translation:'translation',summary:'summary'};
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{'X-FLF-Request':'1',...options.headers}});
  const body=await response.json();
  if(!response.ok) { const error=Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));error.status=response.status;throw error; }
  return body;
}
let chatStorage, chatStorageAvailable=true;
try {
  chatStorage=window.sessionStorage;
  const probe='flf-storage-probe';
  chatStorage.setItem(probe,'1');
  if(chatStorage.getItem(probe)!=='1')throw Error('storage unavailable');
  chatStorage.removeItem(probe);
} catch(error) {
  chatStorageAvailable=false;
  // Demo remains useful; never use this volatile fallback for paid chat.
  const memory=new Map();
  chatStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
}
const chatTransport=new FLFChatTransport(api,chatStorage,()=>crypto.randomUUID());
function pendingChat(id){try{return chatTransport.pending(id);}catch(error){chatStorageAvailable=false;return null;}}
function forgetChat(id){try{chatStorage.removeItem(chatTransport.key(id));}catch(error){chatStorageAvailable=false;}}
function report(e){$('error').textContent=e.message;}
function selectTab(id){tab=id;for(const key of Object.keys(fields))$(key).setAttribute('aria-selected',String(key===tab));render();}
for(const id of Object.keys(fields)){
  $(id).onclick=()=>selectTab(id);
  $(id).onkeydown=e=>{if(['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){
    e.preventDefault();const ids=Object.keys(fields), i=ids.indexOf(id);
    const next=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:2))%3;
    selectTab(ids[next]);$(ids[next]).focus();
  }};
}
function render(){
  $('content').textContent=job?.[fields[tab]]||'아직 결과가 없습니다.';
  $('status').textContent=job?`${job.mode==='demo'?'[고정 예시 데모] ':''}${job.state}${job.failedStep?' · 실패 단계: '+job.failedStep:''}${job.error?' · '+job.error:''}`:'작업을 선택하세요.';
  if(job?.legacyReadOnly)$('status').textContent+=' · 구 강의 조회/종료 전용 (보존된 상태이며 처리 중이 아닙니다)';
  $('retry').hidden=job?.state!=='FAILED'||job?.legacyReadOnly;$('delete').hidden=!job;
  $('adopt').hidden=!job?.quarantined;
  $('question').disabled=$('ask').disabled=!job?.summary||job?.quarantined||job?.legacyReadOnly||chatBusy||(!chatStorageAvailable&&job.mode==='live');
  $('storage-notice').textContent=chatStorageAvailable?'':'브라우저 세션 저장소를 사용할 수 없어 실제 API 채팅만 비활성화했습니다. 업로드·결과 조회는 계속 사용할 수 있으며, 데모 채팅은 이 페이지의 임시 메모리만 사용합니다.';
  $('history').replaceChildren();
  for(const turn of job?.history||[]){const p=document.createElement('p');p.textContent=`질문: ${turn.question}\n답변: ${turn.answer}\n근거: ${turn.evidence.map(r=>'['+r.source+'] '+r.text).join('\n')}`;$('history').append(p);}
}
async function list(){const jobs=await api('/api/jobs');const ids=jobs.map(j=>j.id);for(const id of activeJobs)if(!ids.includes(id))forgetChat(id);activeJobs=ids;
  heartbeatJobs=jobs.filter(j=>!j.quarantined).map(j=>j.id);
  try{for(let i=chatStorage.length-1;i>=0;i--){const key=chatStorage.key(i);if(key?.startsWith('flf-pending-chat:')&&!ids.includes(key.slice(17)))chatStorage.removeItem(key);}}catch(e){chatStorageAvailable=false;}
  $('jobs').replaceChildren(new Option('작업 선택',''));for(const j of jobs)$('jobs').add(new Option(j.id.slice(0,8)+' · '+j.state,j.id));if(job)$('jobs').value=job.id;}
$('jobs').onchange=async()=>{try{job=$('jobs').value?await api('/api/jobs/'+$('jobs').value):null;$('question').value=job?(pendingChat(job.id)?.text||''):'';selectTab(job?.summary?'summary':'origin');}catch(e){report(e);}};
$('refresh').onclick=()=>list().catch(report);
$('upload').onsubmit=async e=>{e.preventDefault();if(uploading)return;uploading=true;$('submit').disabled=true;$('error').textContent='';
  try{const file=$('audio').files[0], fingerprint=JSON.stringify([file.size,file.lastModified]);
    const saved=chatStorage.getItem('flf-upload-attempt');if(saved)uploadAttempt=JSON.parse(saved);
    if(!uploadAttempt||uploadAttempt.fingerprint!==fingerprint)uploadAttempt={fingerprint,id:crypto.randomUUID()};
    chatStorage.setItem('flf-upload-attempt',JSON.stringify(uploadAttempt));
    const form=new FormData();form.append('audio',file);form.append('consent',$('consent').checked);
    job=await api('/api/jobs',{method:'POST',headers:{'X-FLF-Upload-ID':uploadAttempt.id},body:form});
    job=await api(`/api/jobs/${job.id}/submit`,{method:'POST'});uploadAttempt=null;chatStorage.removeItem('flf-upload-attempt');selectTab('origin');await list();
  }catch(e){report(e);}finally{uploading=false;$('submit').disabled=false;}};
$('retry').onclick=async()=>{try{job=await api(`/api/jobs/${job.id}/retry`,{method:'POST'});render();}catch(e){report(e);}};
$('adopt').onclick=async()=>{if(!confirm('구 강의를 기존 결과 조회/종료 전용 임시 세션으로 채택할까요? 미완료 상태는 보존하며 처리 재개/새 질문 기능은 없습니다. 이후 활성 탭이 없으면 만료 삭제됩니다.'))return;try{job=await api(`/api/jobs/${job.id}/adopt`,{method:'POST'});render();await list();}catch(e){report(e);}};
$('delete').onclick=async()=>{if(!confirm('강의 세션을 종료하고 음성/결과/대화 및 앱 관리 외부 객체를 삭제할까요? 다른 탭도 종료됩니다.'))return;try{const id=job.id;const result=await api('/api/jobs/'+id+'/end',{method:'POST'});forgetChat(id);chatStorage.removeItem('flf-upload-attempt');uploadAttempt=null;job=null;$('question').value='';render();await list();if(result.cleanupPending)$('status').textContent='세션 종료됨 · 진행 중 호출 종료/외부 삭제 재시도 대기';}catch(e){report(e);}};
$('chat').onsubmit=async e=>{e.preventDefault();if(!job?.summary||chatBusy||(!chatStorageAvailable&&job.mode==='live'))return;chatBusy=true;$('ask').disabled=true;const id=job.id;
  try{const turn=await chatTransport.send(id,$('question').value);if(job?.id===id){if(!job.history.some(t=>t.requestId===turn.requestId))job.history.push(turn);$('question').value='';$('error').textContent='';render();}}catch(e){report(e);const pending=pendingChat(id);if(pending&&job?.id===id)$('question').value=pending.text;}finally{chatBusy=false;render();}};
$('demo').onclick=()=>{const n=16000,b=new ArrayBuffer(44+n*2),v=new DataView(b);const s=(o,t)=>[...t].forEach((c,i)=>v.setUint8(o+i,c.charCodeAt()));s(0,'RIFF');v.setUint32(4,36+n*2,true);s(8,'WAVEfmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);s(36,'data');v.setUint32(40,n*2,true);for(let i=0;i<n;i++)v.setInt16(44+i*2,Math.sin(i*2*Math.PI*440/16000)*2000,true);const dt=new DataTransfer();dt.items.add(new File([b],'demo-tone.wav',{type:'audio/wav'}));$('audio').files=dt.files;};
async function heartbeat(){if(document.visibilityState==='hidden')return;await list();for(const id of heartbeatJobs)await api(`/api/jobs/${id}/heartbeat`,{method:'POST'});}
async function init(){const config=await api('/api/session');$('mode').textContent=config.mode==='demo'?'DEMO · 실제 음성 인식/번역 아님 · API 호출 없음':'LIVE · 유료 NAVER Cloud API';$('translation').textContent=config.translationLabel;$('limits').textContent=`최대 ${Math.floor(config.maxBytes/1024/1024)} MiB, ${config.maxSeconds/60}분`;if(config.mode!=='demo')$('demo').hidden=true;await heartbeat();render();setInterval(()=>heartbeat().catch(report),(config.heartbeatSeconds||30)*1000);}
document.addEventListener?.('visibilitychange',()=>{if(document.visibilityState==='visible')heartbeat().catch(report);});
init().catch(report);
setInterval(async()=>{if(!job)return;try{const id=job.id,previous=job.state,next=await api('/api/jobs/'+id);if(job?.id!==id)return;job=next;if(next.state==='COMPLETED'&&previous!=='COMPLETED')selectTab('summary');else render();}catch(e){if(e.status===404||e.status===410){forgetChat(job.id);job=null;$('question').value='';render();await list();}report(e);}},1500);

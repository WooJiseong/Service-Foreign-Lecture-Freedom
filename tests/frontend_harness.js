// Deliberately small DOM model: executes production handlers, not a browser/layout test.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const event=(extra={})=>({preventDefault(){this.prevented=true;},...extra});
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
const lecture=(id='lecture-a',extra={})=>({id,mode:'demo',state:'COMPLETED',summary:'요약',transcript:'origin',translation:'번역',history:[],...extra});
async function harness({mode='demo',storageFailure,storage=new Map(),jobs=[],handler}={}){
  const nodes=new Map(),timers=new Map(),events=new Map(),calls=[];let sequence=0;
  function element(id=''){return {id,textContent:'',value:'',disabled:false,hidden:false,checked:false,files:[],children:[],dataset:{},attrs:{},scrollTop:0,scrollHeight:500,clientHeight:500,
    classList:{add(){},remove(){}},setAttribute(k,v){this.attrs[k]=v;},replaceChildren(...items){this.children=items;this.textContent='';},append(...items){this.children.push(...items);},focus(){ctx.focused=this.id;}};}
  const node=id=>{if(!nodes.has(id))nodes.set(id,element(id));return nodes.get(id);};
  const ctx={console,AbortController,setTimeout,clearTimeout,document:{visibilityState:'visible',getElementById:node,createElement:()=>element(),addEventListener:(name,fn)=>events.set(name,fn)},
    crypto:{randomUUID:()=>`request-id-${++sequence}`},setInterval:(fn,ms)=>timers.set(ms,fn),FormData:class{append(){}},confirm:()=>true,
    sessionStorage:{get length(){return storage.size;},key:i=>[...storage.keys()][i],getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    fetch:async(url,options={})=>{calls.push({url,options});const override=handler&&await handler(url,options);if(override instanceof Error)throw override;let body=override;
      if(body===undefined){if(url==='/api/session')body={mode,maxBytes:100000,maxSeconds:60,heartbeatSeconds:30};else if(url==='/api/jobs'&&options.method!=='POST')body=jobs;else if(url.endsWith('/heartbeat'))body={active:true};else if(url.endsWith('/end')){jobs.splice(0);body={ended:true,cleanupPending:false};}else body=jobs.find(j=>url.includes(j.id))||{};}
      return {ok:true,status:200,json:async()=>body};}};
  ctx.window=ctx;
  if(storageFailure==='getter')Object.defineProperty(ctx,'sessionStorage',{get(){throw Error('SecurityError');}});
  if(storageFailure==='write')ctx.sessionStorage.setItem=()=>{throw Error('storage disabled');};
  vm.createContext(ctx);for(const name of ['chat_transport.js','app.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../static',name),'utf8'),ctx);
  await flush();
  return {ctx,node,calls,storage,timers,events,jobs,run:code=>vm.runInContext(code,ctx),choose(file={name:'lecture.wav',size:100,lastModified:1}){node('audio').files=Array.isArray(file)?file:[file];node('audio').onchange();},event,flush};
}
module.exports={harness,lecture,flush,event,deferred};

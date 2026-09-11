'use strict';
const $=id=>document.getElementById(id),canvas=$('canvas');
let renderer=null;
try{renderer=new FluidRenderer(canvas);}catch(error){$('status').textContent=error.message;console.error(error);}
let state=null,kind=0,tool='emit',pointer=null,cursor=null,last=null,commands=[];
// Two most recent solver frames; rendering interpolates between them so the
// picture stays smooth even when the Python solver publishes below 60 Hz.
let prev=null,curr=null,interval=16,blend=null,stamp=0,shownFrame=-1,shownAlpha=-1,sentGravity=null,rate=1;
// Commands are queued on the server, so a response can still predate them.
let pendingMaterials=-1,pendingResolution=null;

let materialCount=-1;
function materialUI(){
 if(!state)return;
 if(materialCount!==state.materials.length){
  materialCount=state.materials.length;$('materials').replaceChildren();
  state.materials.forEach((m,i)=>{const b=document.createElement('button');b.className='material';const dot=document.createElement('span');dot.className='swatch';dot.style.background=m.color;b.append(dot,document.createTextNode(m.name));b.onclick=()=>{kind=i;materialUI();};$('materials').append(b);});
 }
 [...$('materials').children].forEach((b,i)=>{b.classList.toggle('selected',i===kind);b.setAttribute('aria-pressed',i===kind);});
 const m=state.materials[kind];$('rhoInfo').textContent=m.density+' kg/m³';$('muInfo').textContent=m.viscosity+' Pa·s';$('fireInfo').textContent=m.flammability?Math.round(m.flammability*100)+' % · ab '+m.ignition+' °C':'Nein';
 $('toolLabel').textContent=tool==='emit'?m.name.toUpperCase()+' EINGIESSEN':({stir:'FLÜSSIGKEIT RÜHREN',heat:'ERHITZEN / ZÜNDEN',cool:'FLÜSSIGKEIT KÜHLEN',obstacle:'HINDERNIS SETZEN',erase:'PARTIKEL ENTFERNEN'})[tool];
}
function command(action,extra={}){commands.push({action,...extra});}
document.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>{tool=b.dataset.tool;document.querySelectorAll('[data-tool]').forEach(t=>{t.classList.toggle('selected',t===b);t.setAttribute('aria-pressed',t===b);});materialUI();});
document.querySelectorAll('[data-scene]').forEach(b=>b.onclick=()=>command('scene',{scene:b.dataset.scene}));
$('pause').onclick=()=>command('pause');$('single').onclick=()=>command('single');$('clear').onclick=()=>command('scene',{scene:'empty'});
$('resolution').onchange=()=>command('resolution',{resolution:$('resolution').value});
$('quality').onchange=()=>{if(renderer)renderer.resize(+$('quality').value);};
document.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','SELECT','BUTTON','SUMMARY'].includes(document.activeElement.tagName)){e.preventDefault();command('pause');}});
for(const [id,out,suffix,mul] of [['radius','radiusValue',' cm',1],['temperature','tempValue',' °C',1],['gravity','gravityValue',' m/s²',1],['flammability','flameValue',' %',100]])$(id).oninput=()=>$(out).textContent=+(+$(id).value*mul).toFixed(2)+suffix;
$('create').onclick=()=>{
 const data={};for(const id of ['density','viscosity','flammability','ignition','cohesion']){if(!$(id).reportValidity())return;data[id]=+$(id).value;}
 command('material',data);
};
function point(e){const r=canvas.getBoundingClientRect();return{x:Math.max(0,Math.min(1.8,(e.clientX-r.left)/r.width*1.8)),y:Math.max(0,Math.min(1.1,(1-(e.clientY-r.top)/r.height)*1.1))};}
function brush(){return{kind,tool,radius:+$('radius').value/100,temperature:+$('temperature').value};}
canvas.onpointerdown=e=>{if(e.button!==0)return;canvas.setPointerCapture(e.pointerId);pointer=point(e);cursor=pointer;last={...pointer};commands.push({action:null,pointer:{...pointer,...brush()}});if(tool==='obstacle')pointer=null;};
canvas.onpointermove=e=>{cursor=point(e);if(pointer)pointer=cursor;};
canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>{pointer=null;last=null;};
canvas.onpointerleave=()=>{if(!pointer)cursor=null;};
document.addEventListener('visibilitychange',()=>{pointer=null;last=null;});
new ResizeObserver(()=>{if(renderer)renderer.resize(+$('quality').value);}).observe(canvas);

const STRIDE=8;
function decode(buffer){
 const view=new DataView(buffer),length=view.getUint32(0,true);
 const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,length)));
 return{meta,bytes:new Uint8Array(buffer,4+length,meta.count*STRIDE),
        shorts:new Uint16Array(buffer,4+length,meta.count*STRIDE/2)};
}
function accept(frame){
 if(curr&&frame.meta.frame===curr.meta.frame)return;
 const now=performance.now();
 if(curr){const span=Math.min(500,now-curr.at);interval=.8*interval+.2*span;
  if(span>0&&!frame.meta.paused)rate=.85*rate+.15*Math.min(1,Math.max(0,(frame.meta.time-curr.meta.time)/(span/1000)));
  prev=curr;}
 frame.at=now;curr=frame;if(!prev)prev=frame;
 state=frame.meta;
 // Select the new material only once the server actually reports it.
 if(pendingMaterials>=0&&state.materials.length>pendingMaterials){kind=state.materials.length-1;pendingMaterials=-1;}
 if(kind>=state.materials.length)kind=state.materials.length-1;
 if(pendingResolution&&state.resolution===pendingResolution)pendingResolution=null;
 if(!pendingResolution&&$('resolution').value!==state.resolution)$('resolution').value=state.resolution;
 if(state.count>0&&(!blend||blend.bytes.length<state.count*STRIDE)){
  const room=new ArrayBuffer(state.count*STRIDE+4096);
  blend={bytes:new Uint8Array(room),shorts:new Uint16Array(room)};
 }
}
// Rendering: pick the geometry for "now" between the last two solver frames.
function geometry(){
 const a=prev,b=curr;
 if(!b)return null;
 let alpha=Math.max(0,Math.min(1,(performance.now()-b.at)/Math.max(interval,1)));
 if(!b.meta.count||a===b||a.meta.topology!==b.meta.topology||a.meta.count!==b.meta.count||b.meta.paused)
  return{data:b.bytes,count:b.meta.count,key:b.meta.frame*2};
 // Material and burning flag come from the newer frame; position and
 // temperature are the interpolated uint16 triples.
 blend.bytes.set(b.bytes);
 const n=b.meta.count*4,src=a.shorts,dst=b.shorts,out=blend.shorts;
 for(let k=0;k<n;k+=4)for(let c=0;c<3;c++)out[k+c]=src[k+c]+(dst[k+c]-src[k+c])*alpha;
 return{data:blend.bytes,count:b.meta.count,key:b.meta.frame*2+1,alpha};
}
function draw(){
 requestAnimationFrame(draw);
 if(!renderer)return;
 const g=geometry();
 if(g&&(g.key!==shownFrame||g.alpha!==shownAlpha)){shownFrame=g.key;shownAlpha=g.alpha;renderer.upload(g.data,g.count,++stamp);}
 renderer.draw(state,$('view').value,cursor,+$('radius').value/100);
 $('rendererInfo').textContent=renderer.lost?'WEBGL UNTERBROCHEN':'WEBGL 2 · GPU';
}
let lastReadout=0;
function readout(force){
 if(!state)return;
 const now=performance.now();
 if(!force&&now-lastReadout<100)return;          // the panel does not need 120 Hz
 lastReadout=now;
 materialUI();$('pause').textContent=state.paused?'▶ Fortsetzen':'Ⅱ Pause';
 $('count').innerHTML=state.count+' <small>/ '+state.limit+'</small>';
 $('time').innerHTML=state.time.toFixed(2)+' <small>s</small>';
 $('meanTemp').innerHTML=state.temperature+' <small>°C</small>';
 $('speed').textContent=state.paused?'Pause':rate.toFixed(2)+'×';
 $('status').textContent=state.count>=state.limit?'PARTIKELLIMIT ERREICHT':state.paused?'PAUSIERT · WERKZEUGE AKTIV':
  state.hot?state.hot+' BRENNENDE PARTIKEL':'SPH AKTIV · '+state.compute_ms+' ms / SCHRITT · '+Math.round(1000/Math.max(state.interval_ms,.1))+' SCHRITTE/S';
}
function nextBody(){
 const cmd=commands.shift();
 if(cmd){sentGravity=+$('gravity').value;const body={...cmd,gravity:sentGravity};if(cmd.action===null)delete body.action;return{cmd,body};}
 if(pointer){sentGravity=+$('gravity').value;
  const body={gravity:sentGravity,pointer:{...pointer,...brush(),dx:pointer.x-(last?.x??pointer.x),dy:pointer.y-(last?.y??pointer.y)}};
  last={...pointer};return{cmd:null,body};}
 if(+$('gravity').value!==sentGravity){sentGravity=+$('gravity').value;return{cmd:null,body:{gravity:sentGravity}};}
 return null;
}
function applied(cmd){
 if(cmd?.action==='material')pendingMaterials=materialCount;
 if(cmd?.action==='resolution')pendingResolution=cmd.resolution;
}
function fail(error){$('status').textContent='FEHLER: '+error.message+' · Python-Server prüfen';}
// Input loop: one request per command or pointer sample, never per rendered
// frame. Idle means no requests at all — the stream below carries the frames.
async function input(){
 for(;;){
  const started=performance.now();
  const next=nextBody();
  if(next){
   try{
    const response=await fetch('/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(next.body)});
    if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.error||'Serverfehler');}
    accept(decode(await response.arrayBuffer()));applied(next.cmd);readout(true);
   }catch(error){fail(error);await new Promise(r=>setTimeout(r,400));}
  }
  // Pointer drags sample at 40 Hz; idle costs no requests at all.
  const budget=commands.length?0:(pointer?25:60),rest=budget-(performance.now()-started);
  await new Promise(r=>setTimeout(r,rest>0?rest:0));
 }
}
// Frame loop: a single long-lived chunked response carries every solver frame,
// so a proxy in front of this server sees one connection instead of dozens of
// requests per second. If a proxy buffers the stream away, fall back to polling.
async function stream(){
 let streaming=true,failures=0;
 for(;;){
  if(streaming){
   let got=0;
   try{
    const response=await fetch('/api/stream',{headers:{'Accept':'application/octet-stream'}});
    if(!response.ok||!response.body)throw Error('Stream nicht verfügbar');
    const reader=response.body.getReader();
    let buffer=new Uint8Array(0);
    for(;;){
     const {done,value}=await reader.read();
     if(done)break;
     const merged=new Uint8Array(buffer.length+value.length);
     merged.set(buffer);merged.set(value,buffer.length);buffer=merged;
     for(;;){
      if(buffer.length<4)break;
      const size=new DataView(buffer.buffer,buffer.byteOffset,4).getUint32(0,true);
      if(buffer.length<4+size)break;
      accept(decode(buffer.slice(4,4+size).buffer));readout();got++;
      buffer=buffer.subarray(4+size);
     }
    }
   }catch(error){if(!got)failures++;}
   if(got)failures=0;
   // Two silent attempts mean the stream does not survive the path to here.
   if(failures>=2){streaming=false;$('rendererInfo').textContent='WEBGL 2 · GPU';}
   await new Promise(r=>setTimeout(r,got?0:500));
  }else{
   try{
    const response=await fetch('/api/frame',{headers:{'Accept':'application/octet-stream'}});
    if(!response.ok)throw Error('Serverfehler');
    accept(decode(await response.arrayBuffer()));readout();
   }catch(error){fail(error);await new Promise(r=>setTimeout(r,400));}
   await new Promise(r=>setTimeout(r,20));
  }
 }
}
if(renderer){renderer.resize(+$('quality').value);draw();stream();input();}

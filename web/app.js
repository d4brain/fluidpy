'use strict';
const $=id=>document.getElementById(id),canvas=$('canvas');
let renderer=null;
try{renderer=new FluidRenderer(canvas);}catch(error){$('status').textContent=error.message;console.error(error);}
let state=null,kind=0,tool='emit',pointer=null,cursor=null,last=null,commands=[];
// Two most recent solver frames; rendering interpolates between them so the
// picture stays smooth even when the Python solver publishes below 60 Hz.
let prev=null,curr=null,interval=16,blend=null,stamp=0,shownFrame=-1,shownAlpha=-1,sentGravity=null,rate=1;

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

function decode(buffer){
 const view=new DataView(buffer),length=view.getUint32(0,true);
 const meta=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,length)));
 return{meta,data:new Float32Array(buffer,4+length,meta.count*5)};
}
function accept(frame){
 if(curr&&frame.meta.frame===curr.meta.frame)return;
 const now=performance.now();
 if(curr){const span=Math.min(500,now-curr.at);interval=.8*interval+.2*span;
  if(span>0&&!frame.meta.paused)rate=.85*rate+.15*Math.min(1,Math.max(0,(frame.meta.time-curr.meta.time)/(span/1000)));
  prev=curr;}
 frame.at=now;curr=frame;if(!prev)prev=frame;
 state=frame.meta;
 if(state.count>0&&(!blend||blend.length<state.count*5))blend=new Float32Array(state.count*5+2048);
}
// Rendering: pick the geometry for "now" between the last two solver frames.
function geometry(){
 const a=prev,b=curr;
 if(!b)return null;
 let alpha=Math.max(0,Math.min(1,(performance.now()-b.at)/Math.max(interval,1)));
 if(!b.meta.count||a===b||a.meta.topology!==b.meta.topology||a.meta.count!==b.meta.count||b.meta.paused)return{data:b.data,count:b.meta.count,key:b.meta.frame*2};
 const n=b.meta.count*5,src=a.data,dst=b.data,out=blend;
 for(let k=0;k<n;k++)out[k]=src[k]+(dst[k]-src[k])*alpha;
 return{data:out,count:b.meta.count,key:b.meta.frame*2+1,alpha};
}
function draw(){
 requestAnimationFrame(draw);
 if(!renderer)return;
 const g=geometry();
 if(g&&(g.key!==shownFrame||g.alpha!==shownAlpha)){shownFrame=g.key;shownAlpha=g.alpha;renderer.upload(g.data,g.count,++stamp);}
 renderer.draw(state,$('view').value,cursor,+$('radius').value/100);
 $('rendererInfo').textContent=renderer.lost?'WEBGL UNTERBROCHEN':'WEBGL 2 · GPU';
}
function readout(){
 if(!state)return;
 materialUI();$('pause').textContent=state.paused?'▶ Fortsetzen':'Ⅱ Pause';
 $('count').innerHTML=state.count+' <small>/ '+state.limit+'</small>';
 $('time').innerHTML=state.time.toFixed(2)+' <small>s</small>';
 $('meanTemp').innerHTML=state.temperature+' <small>°C</small>';
 $('speed').textContent=state.paused?'Pause':rate.toFixed(2)+'×';
 $('status').textContent=state.count>=state.limit?'PARTIKELLIMIT ERREICHT':state.paused?'PAUSIERT · WERKZEUGE AKTIV':
  state.hot?state.hot+' BRENNENDE PARTIKEL':'SPH AKTIV · '+state.compute_ms+' ms / SCHRITT · '+Math.round(1000/Math.max(state.interval_ms,.1))+' SCHRITTE/S';
}
// Network loop: independent of rendering, at most one request in flight.
async function poll(){
 for(;;){
  const started=performance.now();
  const cmd=commands.shift();
  let body=null;
  if(cmd){sentGravity=+$('gravity').value;body={...cmd,gravity:sentGravity};if(cmd.action===null)delete body.action;}
  else if(+$('gravity').value!==sentGravity&&!pointer){sentGravity=+$('gravity').value;body={gravity:sentGravity};}
  else if(pointer){sentGravity=+$('gravity').value;body={gravity:sentGravity,pointer:{...pointer,...brush(),dx:pointer.x-(last?.x??pointer.x),dy:pointer.y-(last?.y??pointer.y)}};last={...pointer};}
  try{
   const response=await fetch('/api/step',body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}
                                         :{method:'POST',headers:{'Content-Type':'application/json'}});
   if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(error.error||'Serverfehler');}
   accept(decode(await response.arrayBuffer()));
   if(cmd?.action==='material')kind=state.materials.length-1;
   if(cmd?.action==='resolution')$('resolution').value=state.resolution;
   readout();
  }catch(error){$('status').textContent='FEHLER: '+error.message+' · Python-Server prüfen';await new Promise(r=>setTimeout(r,400));}
  const wait=commands.length?0:Math.max(0,12-(performance.now()-started));
  await new Promise(r=>setTimeout(r,wait));
 }
}
if(renderer){renderer.resize(+$('quality').value);draw();poll();}

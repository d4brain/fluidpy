'use strict';
const $=id=>document.getElementById(id),canvas=$('canvas');
let renderer=null;
try{renderer=new FluidRenderer(canvas);}catch(error){$('status').textContent=error.message;console.error(error);}
let state=null,kind=0,tool='emit',pointer=null,cursor=null,last=null,busy=false,commands=[],lastTime=performance.now(),speed=1;

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
document.addEventListener('keydown',e=>{if(e.code==='Space'&&!['INPUT','SELECT','BUTTON','SUMMARY'].includes(document.activeElement.tagName)){e.preventDefault();command('pause');}});
for(const [id,out,suffix,mul] of [['radius','radiusValue',' cm',1],['temperature','tempValue',' °C',1],['gravity','gravityValue',' m/s²',1],['flammability','flameValue',' %',100]])$(id).oninput=()=>$(out).textContent=+(+$(id).value*mul).toFixed(2)+suffix;
$('create').onclick=()=>{
 const data={};for(const id of ['density','viscosity','flammability','ignition','cohesion']){if(!$(id).reportValidity())return;data[id]=+$(id).value;}
 command('material',data);
};
function point(e){const r=canvas.getBoundingClientRect();return{x:Math.max(0,Math.min(1.8,(e.clientX-r.left)/r.width*1.8)),y:Math.max(0,Math.min(1.1,(1-(e.clientY-r.top)/r.height)*1.1))};}
canvas.onpointerdown=e=>{if(e.button!==0)return;canvas.setPointerCapture(e.pointerId);pointer=point(e);cursor=pointer;last={...pointer};commands.push({action:'pointer',pointer:{...pointer,kind,tool,radius:+$('radius').value/100,temperature:+$('temperature').value}});if(tool==='obstacle')pointer=null;};
canvas.onpointermove=e=>{cursor=point(e);if(pointer)pointer=cursor;};
canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>{pointer=null;last=null;};
canvas.onpointerleave=()=>{if(!pointer)cursor=null;};
document.addEventListener('visibilitychange',()=>{pointer=null;last=null;});
function resize(){if(renderer)renderer.resize();}
new ResizeObserver(resize).observe(canvas);
function draw(){
 if(renderer){
  renderer.draw(state,$('view').value,cursor,+$('radius').value/100);
  $('rendererInfo').textContent=renderer.lost?'WEBGL UNTERBROCHEN':'WEBGL 2 · GPU';
 }
 requestAnimationFrame(draw);
}
async function tick(){
 if(busy)return;busy=true;
 const cmd=commands.shift();const data={dt:1/60,gravity:+$('gravity').value,...cmd};
 if(pointer&&!cmd){data.pointer={...pointer,kind,tool,radius:+$('radius').value/100,temperature:+$('temperature').value,dx:pointer.x-(last?.x??pointer.x),dy:pointer.y-(last?.y??pointer.y)};last={...pointer};}
 try{
  const response=await fetch('/api/step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const next=await response.json();if(!response.ok)throw Error(next.error||'Serverfehler');
  const now=performance.now();if(state&&!next.paused&&!cmd){const rate=Math.max(0,next.time-state.time)/((now-lastTime)/1000);speed=.9*speed+.1*rate;}lastTime=now;
  state=next;if(cmd?.action==='material')kind=state.materials.length-1;
  materialUI();$('pause').textContent=state.paused?'▶ Fortsetzen':'Ⅱ Pause';
  $('count').innerHTML=state.count+' <small>/ '+state.limit+'</small>';$('time').innerHTML=state.time.toFixed(2)+' <small>s</small>';$('meanTemp').innerHTML=state.temperature+' <small>°C</small>';$('speed').textContent=state.paused?'Pause':speed.toFixed(2)+'×';
  $('status').textContent=state.count>=state.limit?'PARTIKELLIMIT ERREICHT':state.paused?'PAUSIERT · WERKZEUGE AKTIV':state.hot?state.hot+' BRENNENDE PARTIKEL':'SPH AKTIV · '+state.compute_ms+' ms / SCHRITT';
 }catch(error){$('status').textContent='FEHLER: '+error.message+' · Python-Server prüfen';}
 finally{busy=false;setTimeout(tick,16);}
}
if(renderer){resize();draw();tick();}

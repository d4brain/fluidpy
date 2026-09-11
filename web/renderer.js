'use strict';
// WebGL 2: additive particle density followed by a shaded surface pass.
// No Canvas2D drawing and no external rendering framework.
class FluidRenderer {
 constructor(canvas){
  this.canvas=canvas;this.lost=false;this.source=null;this.count=0;
  this.gl=canvas.getContext('webgl2',{alpha:false,antialias:false,depth:false,stencil:false,powerPreference:'high-performance'});
  if(!this.gl)throw Error('WebGL 2 ist nicht verfügbar. Bitte einen Browser mit WebGL 2 verwenden.');
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.lost=true;canvas.dataset.renderer='WebGL-Kontext verloren';});
  canvas.addEventListener('webglcontextrestored',()=>{this.lost=false;this.init();this.resize();this.source=null;});
  this.init();
 }
 program(vertex,fragment){
  const g=this.gl,shaders=[];
  for(const [type,source] of [[g.VERTEX_SHADER,vertex],[g.FRAGMENT_SHADER,fragment]]){
   const s=g.createShader(type);g.shaderSource(s,source);g.compileShader(s);
   if(!g.getShaderParameter(s,g.COMPILE_STATUS))throw Error(g.getShaderInfoLog(s));shaders.push(s);
  }
  const p=g.createProgram();shaders.forEach(s=>g.attachShader(p,s));g.linkProgram(p);
  if(!g.getProgramParameter(p,g.LINK_STATUS))throw Error(g.getProgramInfoLog(p));
  shaders.forEach(s=>g.deleteShader(s));return p;
 }
 init(){
  const g=this.gl;
  this.splat=this.program(`#version 300 es
   precision highp float;
   layout(location=0) in vec2 position;
   layout(location=1) in vec3 color;
   layout(location=2) in float temperature;
   layout(location=3) in float burning;
   uniform vec2 world; uniform float pixelsPerMeter; uniform float radius;
   out vec3 tint; out float heat; out float fire;
   void main(){gl_Position=vec4(position/world*2.0-1.0,0,1);gl_PointSize=2.0*radius*pixelsPerMeter;tint=color;heat=temperature;fire=burning;}
  `,`#version 300 es
   precision highp float;
   in vec3 tint; in float heat; in float fire;
   uniform int mode;out vec4 fragColor;
   vec3 thermal(float t){float h=clamp(0.64-t/1550.0,0.0,0.64);return clamp(abs(fract(vec3(h)+vec3(0,0.6667,0.3333))*6.0-3.0)-1.0,0.0,1.0)*0.8+0.16;}
   void main(){
    vec2 p=gl_PointCoord*2.0-1.0;float r2=dot(p,p);if(r2>1.0)discard;
    vec3 c=mode==2?thermal(heat):tint;c=mix(c,vec3(1.0,0.44,0.06),fire*0.88);
    if(mode==1){float edge=1.0-smoothstep(0.78,1.0,r2);float light=0.8+0.2*sqrt(1.0-r2);fragColor=vec4(c*light,edge);}
    else{float density=0.30*exp(-3.0*r2)*(1.0-smoothstep(0.85,1.0,r2));fragColor=vec4(c*density,density);}
   }
  `);
  this.surface=this.program(`#version 300 es
   precision highp float;out vec2 uv;
   void main(){vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));uv=p;gl_Position=vec4(p*2.0-1.0,0,1);}
  `,`#version 300 es
   precision highp float;
   in vec2 uv;out vec4 fragColor;
   uniform sampler2D densityMap;uniform vec2 resolution;uniform vec2 world;
   uniform int fluid;uniform vec3 brush;uniform int obstacleCount;uniform vec3 obstacles[30];
   void main(){
    vec2 xy=uv*world,fw=fwidth(xy),grid=abs(fract(xy/0.1-0.5)-0.5)*0.1;
    float line=1.0-min(smoothstep(fw.x*.4,fw.x*1.2,grid.x),smoothstep(fw.y*.4,fw.y*1.2,grid.y));
    vec3 c=mix(vec3(.025,.046,.072),vec3(.065,.105,.145),line*.68);
    if(fluid==1){
     vec4 d=texture(densityMap,uv);vec2 texel=1.0/resolution;
     float dx=texture(densityMap,uv+vec2(texel.x,0)).a-texture(densityMap,uv-vec2(texel.x,0)).a;
     float dy=texture(densityMap,uv+vec2(0,texel.y)).a-texture(densityMap,uv-vec2(0,texel.y)).a;
     vec3 normal=normalize(vec3(-dx*9.0,-dy*9.0,1.0));
     float lighting=.78+.22*max(0.0,dot(normal,normalize(vec3(-.5,.7,1.0))));
     vec3 tint=d.rgb/max(d.a,.001);
     float rim=(1.0-smoothstep(.13,.32,d.a))*.22;
     float cover=smoothstep(.105,.145,d.a);
     c=mix(c,tint*lighting+vec3(.38,.65,.75)*rim,cover);
    }
    for(int i=0;i<30;i++){if(i>=obstacleCount)break;float dist=length(xy-obstacles[i].xy)-obstacles[i].z;
     float edge=1.0-smoothstep(-fw.x,fw.x,dist);vec3 solid=mix(vec3(.14,.21,.27),vec3(.44,.57,.66),smoothstep(-fw.x*3.0,0.0,dist));c=mix(c,solid,edge);}
    if(brush.z>0.0){float dist=abs(length(xy-brush.xy)-brush.z);float ring=1.0-smoothstep(fw.x,fw.x*2.0,dist);float dash=step(0.0,sin(atan(xy.y-brush.y,xy.x-brush.x)*40.0));c=mix(c,vec3(.75,.96,.88),ring*dash*.8);}
    fragColor=vec4(c,1);
   }
  `);
  this.uniforms=new Map();
  this.vao=g.createVertexArray();g.bindVertexArray(this.vao);
  this.buffer=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,this.buffer);
  for(const [loc,size,offset] of [[0,2,0],[1,3,8],[2,1,20],[3,1,24]]){g.enableVertexAttribArray(loc);g.vertexAttribPointer(loc,size,g.FLOAT,false,28,offset);}
  g.bindVertexArray(null);this.emptyVao=g.createVertexArray();
  this.texture=g.createTexture();g.bindTexture(g.TEXTURE_2D,this.texture);
  g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MIN_FILTER,g.LINEAR);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MAG_FILTER,g.LINEAR);
  g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_S,g.CLAMP_TO_EDGE);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_T,g.CLAMP_TO_EDGE);
  this.fbo=g.createFramebuffer();g.bindFramebuffer(g.FRAMEBUFFER,this.fbo);
  g.framebufferTexture2D(g.FRAMEBUFFER,g.COLOR_ATTACHMENT0,g.TEXTURE_2D,this.texture,0);
  g.bindFramebuffer(g.FRAMEBUFFER,null);this.canvas.dataset.renderer='WebGL 2';
 }
 u(program,name){let cache=this.uniforms.get(program);if(!cache){cache={};this.uniforms.set(program,cache);}if(!(name in cache))cache[name]=this.gl.getUniformLocation(program,name);return cache[name];}
 resize(){
  if(this.lost)return;const g=this.gl,r=this.canvas.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2);
  const max=g.getParameter(g.MAX_TEXTURE_SIZE),w=Math.max(1,Math.min(max,Math.round(r.width*d))),h=Math.max(1,Math.min(max,Math.round(r.height*d)));
  this.canvas.width=w;this.canvas.height=h;g.bindTexture(g.TEXTURE_2D,this.texture);
  g.texImage2D(g.TEXTURE_2D,0,g.RGBA8,w,h,0,g.RGBA,g.UNSIGNED_BYTE,null);
  g.bindFramebuffer(g.FRAMEBUFFER,this.fbo);if(g.checkFramebufferStatus(g.FRAMEBUFFER)!==g.FRAMEBUFFER_COMPLETE)throw Error('WebGL Renderziel unvollständig');g.bindFramebuffer(g.FRAMEBUFFER,null);
 }
 upload(state){
  if(this.source===state)return;this.source=state;this.count=state?.particles.length||0;
  const data=new Float32Array(this.count*7),colors=(state?.materials||[]).map(m=>[1,3,5].map(start=>parseInt(m.color.slice(start,start+2),16)/255));
  state?.particles.forEach((p,i)=>data.set([p[0],p[1],...colors[p[2]],p[3],p[4]],i*7));
  const g=this.gl;g.bindBuffer(g.ARRAY_BUFFER,this.buffer);g.bufferData(g.ARRAY_BUFFER,data,g.DYNAMIC_DRAW);
 }
 particles(state,mode){
  const g=this.gl,p=this.splat;g.useProgram(p);g.bindVertexArray(this.vao);
  g.uniform2f(this.u(p,'world'),1.8,1.1);g.uniform1f(this.u(p,'pixelsPerMeter'),this.canvas.width/1.8);
  g.uniform1f(this.u(p,'radius'),(state?.spacing||.015)*(mode===1?.26:1.5));g.uniform1i(this.u(p,'mode'),mode);
  g.drawArrays(g.POINTS,0,this.count);
 }
 draw(state,view,cursor,radius){
  if(this.lost)return;const g=this.gl,w=this.canvas.width,h=this.canvas.height,mode=view==='particles'?1:view==='thermal'?2:0;
  this.upload(state);g.viewport(0,0,w,h);
  // Explicitly unbind the sample texture while it is a render target.
  g.bindTexture(g.TEXTURE_2D,null);g.bindFramebuffer(g.FRAMEBUFFER,this.fbo);g.clearColor(0,0,0,0);g.clear(g.COLOR_BUFFER_BIT);
  if(mode!==1){g.enable(g.BLEND);g.blendFunc(g.ONE,g.ONE);this.particles(state,mode);g.disable(g.BLEND);}
  g.bindFramebuffer(g.FRAMEBUFFER,null);g.useProgram(this.surface);g.bindVertexArray(this.emptyVao);
  g.activeTexture(g.TEXTURE0);g.bindTexture(g.TEXTURE_2D,this.texture);
  const p=this.surface;g.uniform1i(this.u(p,'densityMap'),0);g.uniform2f(this.u(p,'resolution'),w,h);g.uniform2f(this.u(p,'world'),1.8,1.1);g.uniform1i(this.u(p,'fluid'),mode===1?0:1);
  g.uniform3f(this.u(p,'brush'),cursor?.x||0,cursor?.y||0,cursor?radius:0);
  const obstacles=state?.obstacles||[];g.uniform1i(this.u(p,'obstacleCount'),obstacles.length);
  const obs=new Float32Array(90);obstacles.forEach((o,i)=>obs.set(o,i*3));g.uniform3fv(this.u(p,'obstacles[0]'),obs);g.drawArrays(g.TRIANGLES,0,3);
  if(mode===1){g.enable(g.BLEND);g.blendFunc(g.SRC_ALPHA,g.ONE_MINUS_SRC_ALPHA);this.particles(state,mode);g.disable(g.BLEND);}
 }
}

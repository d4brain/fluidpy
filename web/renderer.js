'use strict';
// WebGL 2: additive particle density followed by a shaded surface pass.
// No Canvas2D drawing and no external rendering framework.
// The vertex buffer is uploaded straight from the server's float32 payload;
// material colours live in a uniform palette, so no per-particle JavaScript
// runs per frame. The density pass renders at a reduced resolution because it
// is filtered by the surface pass anyway.
class FluidRenderer {
 constructor(canvas){
  this.canvas=canvas;this.lost=false;this.stamp=-1;this.count=0;this.paletteKey='';this.density=0.55;
  this.gl=canvas.getContext('webgl2',{alpha:false,antialias:false,depth:false,stencil:false,desynchronized:true,powerPreference:'high-performance'});
  if(!this.gl)throw Error('WebGL 2 ist nicht verfügbar. Bitte einen Browser mit WebGL 2 verwenden.');
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.lost=true;canvas.dataset.renderer='WebGL-Kontext verloren';});
  canvas.addEventListener('webglcontextrestored',()=>{this.lost=false;this.init();this.resize();this.stamp=-1;this.paletteKey='';});
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
   precision highp float; precision highp int;
   layout(location=0) in vec2 position;
   layout(location=1) in float material;
   layout(location=2) in float temperature;
   layout(location=3) in float burning;
   uniform float pixelsPerMeter; uniform float radius; uniform vec3 palette[32]; uniform float tempScale; uniform float solids[32];
   out vec3 tint; out float heat; out float fire; out float solid;
   void main(){gl_Position=vec4(position*2.0-1.0,0,1);gl_PointSize=2.0*radius*pixelsPerMeter;
    int k=int(clamp(material,0.0,31.0));solid=solids[k];tint=palette[k];heat=temperature*tempScale;fire=burning;}
  `,`#version 300 es
   precision highp float; precision highp int;
   in vec3 tint; in float heat; in float fire; in float solid;
   uniform int mode; uniform int thermalView;out vec4 fragColor;
   vec3 thermal(float t){float h=clamp(0.64-t/1550.0,0.0,0.64);return clamp(abs(fract(vec3(h)+vec3(0,0.6667,0.3333))*6.0-3.0)-1.0,0.0,1.0)*0.8+0.16;}
   void main(){
    if(mode==3 && solid<0.5)discard;
    if(mode!=1 && mode!=3 && solid>0.5)discard;
    vec2 p=gl_PointCoord*2.0-1.0;float r2=dot(p,p);if(r2>1.0)discard;
    vec3 c=(mode==2 || thermalView==1)?thermal(heat):tint;c=mix(c,vec3(1.0,0.44,0.06),fire*0.88);
    if(mode==1 || mode==3){float edge=1.0-smoothstep(0.78,1.0,r2);float light=0.8+0.2*sqrt(1.0-r2);fragColor=vec4(c*light,edge);}
    else{float density=0.30*exp(-3.0*r2)*(1.0-smoothstep(0.85,1.0,r2));fragColor=vec4(c*density,density);}
   }
  `);
  this.surface=this.program(`#version 300 es
   precision highp float; precision highp int;
   layout(location=0) in vec2 corner;out vec2 uv;
   void main(){uv=corner;gl_Position=vec4(corner*2.0-1.0,0,1);}
  `,`#version 300 es
   precision highp float; precision highp int;
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
  this.vesselProgram=this.program(`#version 300 es
   precision highp float;precision highp int;
   layout(location=0) in vec2 pos;layout(location=1) in vec3 color;out vec3 tint;out vec2 world;
   void main(){tint=color;world=pos+vec2(.85,.10);gl_Position=vec4(world/vec2(1.8,1.1)*2.0-1.0,0,1);}
  `,`#version 300 es
   precision highp float;precision highp int;in vec3 tint;in vec2 world;out vec4 fragColor;
   uniform int holeCount;uniform vec3 holes[48];
   void main(){
    // Weggeätzte Scheiben fehlen ganz; knapp daneben bleibt ein angefressener Rand.
    float near=1e9;
    for(int i=0;i<48;i++){if(i>=holeCount)break;near=min(near,length(world-holes[i].xy)-holes[i].z);}
    if(near<0.0)discard;
    fragColor=vec4(mix(vec3(.30,.40,.16),tint,smoothstep(0.0,.014,near)),1);
   }
  `);
  this.vesselVao=g.createVertexArray();g.bindVertexArray(this.vesselVao);
  this.vesselBuffer=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,this.vesselBuffer);
  g.enableVertexAttribArray(0);g.vertexAttribPointer(0,2,g.FLOAT,false,20,0);
  g.enableVertexAttribArray(1);g.vertexAttribPointer(1,3,g.FLOAT,false,20,8);
  this.vesselKey=null;
  this.uniforms=new Map();
  this.palette=new Float32Array(96);this.solids=new Float32Array(32);
  this.vao=g.createVertexArray();g.bindVertexArray(this.vao);
  this.buffer=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,this.buffer);
  // Server layout, 8 bytes: uint16 x, uint16 y, uint16 temp, uint8 kind, uint8 burning.
  // Positions and temperature arrive normalised; the shader scales them back.
  for(const [loc,size,type,normalized,offset] of [
   [0,2,g.UNSIGNED_SHORT,true,0],[2,1,g.UNSIGNED_SHORT,true,4],
   [1,1,g.UNSIGNED_BYTE,false,6],[3,1,g.UNSIGNED_BYTE,true,7]]){
   g.enableVertexAttribArray(loc);g.vertexAttribPointer(loc,size,type,normalized,8,offset);}
  this.emptyVao=g.createVertexArray();g.bindVertexArray(this.emptyVao);
  this.corners=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,this.corners);
  g.bufferData(g.ARRAY_BUFFER,new Float32Array([0,0,2,0,0,2]),g.STATIC_DRAW);
  g.enableVertexAttribArray(0);g.vertexAttribPointer(0,2,g.FLOAT,false,0,0);
  g.bindVertexArray(null);g.bindBuffer(g.ARRAY_BUFFER,null);
  this.capacity=0;this.allocated=false;
  this.texture=g.createTexture();g.bindTexture(g.TEXTURE_2D,this.texture);
  g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MIN_FILTER,g.LINEAR);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MAG_FILTER,g.LINEAR);
  g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_S,g.CLAMP_TO_EDGE);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_T,g.CLAMP_TO_EDGE);
  this.fbo=g.createFramebuffer();g.bindFramebuffer(g.FRAMEBUFFER,this.fbo);
  g.framebufferTexture2D(g.FRAMEBUFFER,g.COLOR_ATTACHMENT0,g.TEXTURE_2D,this.texture,0);
  g.bindFramebuffer(g.FRAMEBUFFER,null);this.canvas.dataset.renderer='WebGL 2';
 }
 u(program,name){let cache=this.uniforms.get(program);if(!cache){cache={};this.uniforms.set(program,cache);}if(!(name in cache))cache[name]=this.gl.getUniformLocation(program,name);return cache[name];}
 resize(scale){
  if(this.lost)return;const g=this.gl,r=this.canvas.getBoundingClientRect();
  // Device pixel ratio is capped: fill rate, not geometry, limits this renderer.
  const d=Math.min(devicePixelRatio||1,1.5)*(scale||this.scale||1);
  const max=g.getParameter(g.MAX_TEXTURE_SIZE),w=Math.max(1,Math.min(max,Math.round(r.width*d))),h=Math.max(1,Math.min(max,Math.round(r.height*d)));
  if(this.allocated&&w===this.canvas.width&&h===this.canvas.height)return;
  this.allocated=true;this.scale=scale||this.scale||1;this.canvas.width=w;this.canvas.height=h;
  this.fieldWidth=Math.max(1,Math.round(w*this.density));this.fieldHeight=Math.max(1,Math.round(h*this.density));
  g.bindTexture(g.TEXTURE_2D,this.texture);
  g.texImage2D(g.TEXTURE_2D,0,g.RGBA8,this.fieldWidth,this.fieldHeight,0,g.RGBA,g.UNSIGNED_BYTE,null);
  g.bindFramebuffer(g.FRAMEBUFFER,this.fbo);if(g.checkFramebufferStatus(g.FRAMEBUFFER)!==g.FRAMEBUFFER_COMPLETE)throw Error('WebGL Renderziel unvollständig');g.bindFramebuffer(g.FRAMEBUFFER,null);
 }
 setPalette(materials){
  const key=materials.map(m=>m.color+m.render).join('');if(key===this.paletteKey)return;this.paletteKey=key;
  materials.slice(0,32).forEach((m,i)=>{this.solids[i]=m.render==='solid'?1:0;for(let k=0;k<3;k++)this.palette[i*3+k]=parseInt(m.color.slice(1+k*2,3+k*2),16)/255;});
  const g=this.gl;g.useProgram(this.splat);g.uniform3fv(this.u(this.splat,'palette[0]'),this.palette);g.uniform1fv(this.u(this.splat,'solids[0]'),this.solids);
 }
 // buffer: Uint8Array in the server's 8-byte layout, already interpolated.
 upload(buffer,count,stamp){
  if(stamp===this.stamp)return;this.stamp=stamp;this.count=count;
  const bytes=count*8,g=this.gl;g.bindBuffer(g.ARRAY_BUFFER,this.buffer);
  if(bytes>this.capacity){this.capacity=bytes+8192;g.bufferData(g.ARRAY_BUFFER,this.capacity,g.DYNAMIC_DRAW);}
  if(bytes)g.bufferSubData(g.ARRAY_BUFFER,0,buffer,0,bytes);
 }
 particles(state,mode){
  const g=this.gl,p=this.splat;g.useProgram(p);g.bindVertexArray(this.vao);
  g.uniform1f(this.u(p,'tempScale'),65535/40);
  g.uniform1f(this.u(p,'pixelsPerMeter'),((mode===1||mode===3)?this.canvas.width:this.fieldWidth)/1.8);
  g.uniform1f(this.u(p,'radius'),(state?.spacing||.015)*(mode===1?.26:mode===3?.76:1.5));g.uniform1i(this.u(p,'mode'),mode);
  g.drawArrays(g.POINTS,0,this.count);
 }
 draw(state,view,cursor,radius){
  if(this.lost||!state)return;
  const g=this.gl,w=this.canvas.width,h=this.canvas.height,mode=view==='particles'?1:view==='thermal'?2:0;
  this.setPalette(state.materials);
  g.useProgram(this.splat);g.uniform1i(this.u(this.splat,'thermalView'),mode===2?1:0);
  // Explicitly unbind the sample texture while it is a render target.
  g.bindTexture(g.TEXTURE_2D,null);
  if(mode!==1){
   g.bindFramebuffer(g.FRAMEBUFFER,this.fbo);g.viewport(0,0,this.fieldWidth,this.fieldHeight);
   g.clearColor(0,0,0,0);g.clear(g.COLOR_BUFFER_BIT);
   g.enable(g.BLEND);g.blendFunc(g.ONE,g.ONE);this.particles(state,mode);g.disable(g.BLEND);
  }
  g.bindFramebuffer(g.FRAMEBUFFER,null);g.viewport(0,0,w,h);
  g.useProgram(this.surface);g.bindVertexArray(this.emptyVao);
  g.activeTexture(g.TEXTURE0);g.bindTexture(g.TEXTURE_2D,this.texture);
  const p=this.surface;g.uniform1i(this.u(p,'densityMap'),0);g.uniform2f(this.u(p,'resolution'),this.fieldWidth,this.fieldHeight);
  g.uniform2f(this.u(p,'world'),1.8,1.1);g.uniform1i(this.u(p,'fluid'),mode===1?0:1);
  g.uniform3f(this.u(p,'brush'),cursor?.x||0,cursor?.y||0,cursor?radius:0);
  const obstacles=state.obstacles||[];g.uniform1i(this.u(p,'obstacleCount'),obstacles.length);
  if(obstacles.length||this.hadObstacles){const obs=new Float32Array(90);obstacles.forEach((o,i)=>obs.set(o,i*3));g.uniform3fv(this.u(p,'obstacles[0]'),obs);this.hadObstacles=obstacles.length>0;}
  g.drawArrays(g.TRIANGLES,0,3);
  g.enable(g.BLEND);g.blendFunc(g.SRC_ALPHA,g.ONE_MINUS_SRC_ALPHA);this.particles(state,mode===1?1:3);g.disable(g.BLEND);
  const asset=this.assets?.[state.container];
  if(asset){
   g.useProgram(this.vesselProgram);g.bindVertexArray(this.vesselVao);
   if(this.vesselKey!==state.container){g.bindBuffer(g.ARRAY_BUFFER,this.vesselBuffer);g.bufferData(g.ARRAY_BUFFER,new Float32Array(asset.vertices),g.STATIC_DRAW);this.vesselKey=state.container;}
   const holes=state.holes||[],v=this.vesselProgram;
   g.uniform1i(this.u(v,'holeCount'),Math.min(holes.length,48));
   if(holes.length||this.hadHoles){const buf=new Float32Array(144);holes.slice(0,48).forEach((o,i)=>buf.set(o,i*3));g.uniform3fv(this.u(v,'holes[0]'),buf);this.hadHoles=holes.length>0;}
   g.drawArrays(g.TRIANGLES,0,asset.vertices.length/5);
  }
 }
}

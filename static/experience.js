'use strict';
(() => {
  const key='nzi-cookie-preferences';
  let preferences;
  try { preferences=JSON.parse(decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith(key+'='))?.slice(key.length+1)||'null')); } catch {}
  const panel=document.createElement('section');panel.className='cookie-panel';panel.setAttribute('aria-label','Preferências de Cookies');
  panel.innerHTML=`<h2>Preferências de Cookies</h2><p>Usamos cookies para melhorar sua experiência, analisar o tráfego e personalizar a pesquisa do site. Você pode aceitar todos ou apenas os essenciais.</p><p class="cookie-note">Personalização salva buscas e itens recentes no navegador. Análise de tráfego contabiliza visitas e região aproximada por IP, sem armazenar o endereço IP no relatório. Ao aceitar análise de tráfego, dados da compra (nome, email, produtos e valores) e campanhas podem ser enviados à UTMify quando a integração estiver ativa.</p><div class="cookie-options"><label><input type="checkbox" checked disabled> Essenciais</label><label><input id="consent-analytics" type="checkbox"> Análise de tráfego</label><label><input id="consent-personalization" type="checkbox"> Personalização da busca</label></div><div class="cookie-actions"><button data-consent="essential">Apenas essenciais</button><button data-consent="all">Aceitar todos</button><button data-consent="save">Salvar preferências</button></div>`;
  const reopen=document.createElement('button');reopen.className='cookie-reopen';reopen.textContent='Cookies';reopen.type='button';
  document.body.append(panel,reopen);
  function show(){panel.hidden=false;panel.querySelector('#consent-analytics').checked=preferences?.analytics===true;panel.querySelector('#consent-personalization').checked=preferences?.personalization===true;}
  panel.hidden=preferences?.version===2;
  reopen.onclick=show;
  panel.onclick=e=>{const button=e.target.closest('[data-consent]');if(!button)return;const mode=button.dataset.consent;
    preferences={version:2,essential:true,analytics:mode==='all'||(mode==='save'&&panel.querySelector('#consent-analytics').checked),personalization:mode==='all'||(mode==='save'&&panel.querySelector('#consent-personalization').checked)};
    document.cookie=key+'='+encodeURIComponent(JSON.stringify(preferences))+'; Path=/; Max-Age=15552000; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');
    panel.hidden=true;window.dispatchEvent(new CustomEvent('nzi:consent',{detail:preferences}));
  };
  // Cosmetic only: no cursor coordinates are sent or persisted.
  const media=matchMedia('(prefers-reduced-motion: reduce)'), fine=matchMedia('(pointer: fine)');
  const canvas=document.createElement('canvas');canvas.className='cursor-lightning';canvas.setAttribute('aria-hidden','true');document.body.append(canvas);
  const ctx=canvas.getContext('2d');if(!ctx)return;
  let bolts=[],frame=0,last=null,lastAt=0;
  function size(){canvas.width=innerWidth;canvas.height=innerHeight;}
  size();window.addEventListener('resize',size);
  function tick(now){ctx.clearRect(0,0,canvas.width,canvas.height);bolts=bolts.filter(b=>now-b.time<220);
    for(const bolt of bolts){ctx.globalAlpha=1-(now-bolt.time)/220;ctx.beginPath();bolt.points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.lineJoin='round';ctx.lineCap='round';ctx.shadowColor='#ff123a';ctx.shadowBlur=12;ctx.strokeStyle='#fff';ctx.lineWidth=3.5;ctx.stroke();ctx.shadowBlur=5;ctx.strokeStyle='#ef1638';ctx.lineWidth=1.7;ctx.stroke();}
    ctx.globalAlpha=1;frame=bolts.length?requestAnimationFrame(tick):0;
  }
  function clear(){bolts=[];last=null;cancelAnimationFrame(frame);frame=0;ctx.clearRect(0,0,canvas.width,canvas.height);}
  window.addEventListener('pointermove',e=>{if(media.matches||!fine.matches||e.pointerType!=='mouse')return;const now=performance.now();if(now-lastAt<35)return;lastAt=now;const point={x:e.clientX,y:e.clientY};if(last&&Math.hypot(point.x-last.x,point.y-last.y)>5){const points=[last];for(let i=1;i<5;i++)points.push({x:last.x+(point.x-last.x)*i/5+(Math.random()-.5)*15,y:last.y+(point.y-last.y)*i/5+(Math.random()-.5)*15});points.push(point);bolts.push({time:now,points});if(!frame)frame=requestAnimationFrame(tick);}last=point;},{passive:true});
  document.addEventListener('pointerleave',clear);document.addEventListener('visibilitychange',clear);media.addEventListener('change',clear);
})();

/* Perspective-projected constellation. Local animation; no tracking or dependencies. */
(() => {
  const canvas=document.createElement('canvas');
  canvas.id='constellation';canvas.className='red-constellation';canvas.setAttribute('aria-hidden','true');
  document.body.prepend(canvas);
  const ctx=canvas.getContext('2d');if(!ctx){canvas.remove();return;}
  const reduce=matchMedia('(prefers-reduced-motion: reduce)'),fine=matchMedia('(pointer: fine)');
  const toggle=document.createElement('button');toggle.type='button';toggle.className='ambient-toggle';
  document.body.append(toggle);
  let enabled=true;
  try{enabled=localStorage.getItem('nzi-ambient')!=='off';}catch{}
  let width=0,height=0,points=[],frame=0,lastTime=0,angle=0,mouse={x:0,y:0},target={x:0,y:0},cursor=null;
  let seed=92731;
  const random=()=>{seed=(seed*16807)%2147483647;return(seed-1)/2147483646;};
  function resize(){
    width=innerWidth;height=innerHeight;
    const ratio=Math.min(devicePixelRatio||1,1.5);
    canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);
    seed=92731;
    const count=width<600?48:100;
    points=Array.from({length:count},()=>({x:(random()-.5)*2.5,y:(random()-.5)*2.3,z:(random()-.5)*.85,r:.8+random()*1.5,vx:(random()-.5)*.018,vy:(random()-.5)*.018}));
    draw();
  }
  function draw(){
    ctx.clearRect(0,0,width,height);if(!enabled)return;
    const yaw=mouse.x*.16+Math.sin(angle)*.035,pitch=mouse.y*.10;
    const cy=Math.cos(yaw),sy=Math.sin(yaw),cx=Math.cos(pitch),sx=Math.sin(pitch);
    const projected=points.map(p=>{const x=p.x*cy+p.z*sy,z=p.z*cy-p.x*sy,y=p.y*cx-z*sx,depth=z*cx+p.y*sx,scale=1.4/(1.4+depth*.4);return{x:width*.5+x*width*.47*scale,y:height*.5+y*height*.48*scale,depth,scale,r:p.r};});
    const reach=Math.min(170,width*.28);
    ctx.lineWidth=.85;
    for(let i=0;i<projected.length;i++){
      const a=projected[i];let connected=0;
      for(let j=i+1;j<projected.length&&connected<4;j++){
        const b=projected[j],distance=Math.hypot(a.x-b.x,a.y-b.y);
        if(distance>reach||Math.abs(a.depth-b.depth)>.45)continue;
        connected++;ctx.strokeStyle=`rgba(255,38,76,${(1-distance/reach)*.55})`;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
      }
    }
    if(cursor&&!reduce.matches&&fine.matches){
      for(const p of projected){
        const distance=Math.hypot(p.x-cursor.x,p.y-cursor.y);
        if(distance>=180)continue;
        ctx.strokeStyle=`rgba(255,35,65,${(1-distance/180)*.85})`;ctx.lineWidth=1;
        ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(cursor.x,cursor.y);ctx.stroke();
      }
    }
    for(const p of projected){const radius=p.r*p.scale;ctx.fillStyle=`rgba(255,38,65,${.5+p.scale*.25})`;ctx.shadowColor='#fa163f';ctx.shadowBlur=radius*5;ctx.beginPath();ctx.arc(p.x,p.y,radius,0,Math.PI*2);ctx.fill();}
    ctx.shadowBlur=0;
  }
  function animate(time){
    frame=0;if(!enabled||document.hidden||reduce.matches||!fine.matches)return;
    if(time-lastTime>=32){const dt=Math.min((time-lastTime)/1000,.05);lastTime=time;angle+=dt*.16;for(const p of points){p.x+=p.vx*dt;p.y+=p.vy*dt;if(p.x>1.25)p.x=-1.25;if(p.x< -1.25)p.x=1.25;if(p.y>1.15)p.y=-1.15;if(p.y< -1.15)p.y=1.15;}mouse.x+=(target.x-mouse.x)*.07;mouse.y+=(target.y-mouse.y)*.07;draw();}
    frame=requestAnimationFrame(animate);
  }
  function sync(){
    cancelAnimationFrame(frame);frame=0;
    canvas.hidden=!enabled;toggle.textContent=enabled?'✦ Efeitos ativos':'✦ Ativar efeitos';toggle.setAttribute('aria-pressed',String(enabled));
    document.body.classList.toggle('ambient-off',!enabled);
    if(reduce.matches||!fine.matches){mouse={x:0,y:0};angle=0;}
    draw();lastTime=performance.now();
    if(enabled&&!document.hidden&&!reduce.matches&&fine.matches)frame=requestAnimationFrame(animate);
  }
  toggle.onclick=()=>{enabled=!enabled;try{localStorage.setItem('nzi-ambient',enabled?'on':'off');}catch{}sync();};
  window.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'&&!reduce.matches){cursor={x:e.clientX,y:e.clientY};target.x=e.clientX/width-.5;target.y=e.clientY/height-.5;}},{passive:true});
  document.documentElement.addEventListener('pointerleave',()=>{target={x:0,y:0};cursor=null;});
  window.addEventListener('resize',resize);document.addEventListener('visibilitychange',sync);reduce.addEventListener('change',sync);fine.addEventListener('change',sync);
  resize();sync();
})();

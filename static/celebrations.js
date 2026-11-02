/* Local, bounded celebration; no external scripts or tracking. */
window.addEventListener('nzi:celebrate',()=>{
 if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
 const host=document.querySelector('dialog[open]')||document.body;
 let canvas=host.querySelector('.nzi-confetti');if(canvas)return;
 canvas=document.createElement('canvas');canvas.className='nzi-confetti';canvas.setAttribute('aria-hidden','true');
 canvas.style.cssText='position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:2147483647';host.append(canvas);
 const w=canvas.width=innerWidth,h=canvas.height=innerHeight,ctx=canvas.getContext('2d');if(!ctx){canvas.remove();return;}
 const colors=['#ff304d','#ffffff','#fbbf24','#4ade80','#a20202'];
 const pieces=Array.from({length:90},()=>({x:w/2,y:h*.4,vx:(Math.random()-.5)*650,vy:-150-Math.random()*450,r:Math.random()*6,a:Math.random()*6,c:colors[Math.floor(Math.random()*colors.length)]}));
 let start,last;function draw(t){start??=t;last??=t;const dt=Math.min((t-last)/1000,.04);last=t;ctx.clearRect(0,0,w,h);ctx.globalAlpha=Math.max(0,1-(t-start)/2200);
 for(const p of pieces){p.vy+=480*dt;p.x+=p.vx*dt;p.y+=p.vy*dt;p.a+=dt*6;ctx.save();ctx.translate(p.x,p.y);ctx.rotate(p.a);ctx.fillStyle=p.c;ctx.fillRect(-3,-3,6,p.r+4);ctx.restore();}
 if(t-start<2200&&canvas.isConnected)requestAnimationFrame(draw);else canvas.remove();}requestAnimationFrame(draw);
});

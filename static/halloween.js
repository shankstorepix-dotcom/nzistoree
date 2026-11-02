'use strict';
(async () => {
  let coupon;try{const response=await fetch('/api/coupon',{cache:'no-store'});if(!response.ok)return;coupon=(await response.json()).coupon;}catch{return;}if(!coupon)return;
  let seen=false;
  try { seen=sessionStorage.getItem('nzi-halloween-seen')==='1'; } catch {}
  const dialog=document.createElement('dialog');
  dialog.className='halloween-popup';
  dialog.setAttribute('aria-labelledby','halloween-title');
  dialog.innerHTML=`<div class="halloween-popup-inner"><button class="halloween-close" type="button" aria-label="Fechar boas-vindas">×</button><span class="nzi-logo-frame popup-brand"><img src="/static/nzi-logo.png?v=2" alt="Nzi Store"></span><span class="halloween-eyebrow">DOCES, TRAVESSURAS E DESCONTOS</span><h2 id="halloween-title">Bem-vindo ao<br><em>Halloween NZI</em></h2><p>Antes de comprar, leia a descrição do produto. Seu próximo upgrade vem com uma surpresa.</p><div class="halloween-coupon-frame"><img class="halloween-gif" src="/static/halloween.gif" alt="Fantasminha com uma abóbora de Halloween"><span class="halloween-static" aria-hidden="true">👻</span><strong>10% DE DESCONTO</strong><div class="coupon-code-row"><span class="coupon-bolt" aria-hidden="true">ϟ</span><code>DESCONTO10</code><button id="halloween-copy" type="button" aria-label="Copiar e aplicar cupom DESCONTO10"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2" stroke="currentColor" stroke-width="1.8"/><path d="M15 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h1" stroke="currentColor" stroke-width="1.8"/></svg><span>Copiar código</span></button></div></div><p id="halloween-message" role="status">Válido para os produtos da loja.</p><button class="halloween-continue" type="button">Explorar a loja →</button><button class="halloween-animation" type="button">Pausar GIF</button></div>`;
  dialog.querySelector('.halloween-coupon-frame strong').textContent=coupon.percent+'% DE DESCONTO';
  dialog.querySelector('code').textContent=coupon.code;dialog.querySelector('#halloween-copy').setAttribute('aria-label','Copiar e aplicar cupom '+coupon.code);
  document.body.append(dialog);
  let previous;
  function open(){previous=document.activeElement;dialog.showModal();document.body.classList.add('halloween-modal-open');}
  function close(){dialog.close();}
  dialog.querySelector('.halloween-close').onclick=close;
  dialog.querySelector('.halloween-continue').onclick=close;
  dialog.addEventListener('click',e=>{if(e.target===dialog)close();});
  dialog.addEventListener('close',()=>{document.body.classList.remove('halloween-modal-open');try{sessionStorage.setItem('nzi-halloween-seen','1');}catch{}previous?.focus();});
  const motion=matchMedia('(prefers-reduced-motion: reduce)');
  let paused=motion.matches;
  const animation=dialog.querySelector('.halloween-animation');
  function animationState(){dialog.classList.toggle('animation-paused',paused);animation.textContent=paused?'Reproduzir GIF':'Pausar GIF';}
  animation.onclick=()=>{paused=!paused;animationState();};animationState();
  motion.addEventListener('change',()=>{paused=motion.matches;animationState();});
  dialog.querySelector('#halloween-copy').onclick=async()=>{
    window.dispatchEvent(new CustomEvent('nzi:coupon',{detail:coupon}));
    const message=dialog.querySelector('#halloween-message');
    try{await navigator.clipboard.writeText(coupon.code);message.textContent='Prontinho! Cupom '+coupon.code+' copiado com sucesso. Aproveite seu desconto!';window.dispatchEvent(new Event('nzi:celebrate'));dialog.querySelector('#halloween-copy span').textContent='Copiado!';dialog.querySelector('#halloween-copy').classList.add('is-copied');}
    catch{message.textContent='Cupom aplicado ao carrinho! Código: '+coupon.code;}
  };
  const reopen=document.createElement('button');reopen.type='button';reopen.className='halloween-reopen';reopen.textContent='🎃 Cupom Halloween';reopen.onclick=open;document.body.append(reopen);
  if(!seen)open();
})();

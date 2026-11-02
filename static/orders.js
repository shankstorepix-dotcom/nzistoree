'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => (n / 100).toLocaleString('pt-BR', {style:'currency',currency:'BRL'});
const date = n => new Date(n*1000).toLocaleString('pt-BR');
const paymentLabels = {expirado:'Expirado',nao_iniciado:'Pendente', criando:'Pendente', pendente:'Pendente', revisao:'Cobrança em verificação. Aguarde ou fale com o suporte.', pago:'Concluído', falha:'Pagamento não concluído. Fale com o suporte.', reembolsado:'Pagamento reembolsado ou contestado. Fale com o suporte.'};
const paymentBadgeClass = p => p==='pago'?'paid':['nao_iniciado','criando','pendente','revisao'].includes(p)?'pending':'failed';
const paymentShortLabel = p => p==='pago'?'Concluído':['nao_iniciado','criando','pendente','revisao'].includes(p)?'Pendente':(paymentLabels[p] || p);
let csrf = '', admin = false, page = 1, selected = '', lastMessage = 0, misticReady = false, polling = false;
let messageRequest = null, chatEnabled=false,lastTyped=0;
async function api(path, body, method, retried = false) {
  const r = await fetch(path, {method:method || (body ? 'POST':'GET'), cache:'no-store', headers:{'Content-Type':'application/json', ...(csrf ? {'X-CSRF-Token':csrf}:{})}, ...(body ? {body:JSON.stringify(body)}:{})});
  if (r.status === 401 && !retried && path !== '/api/auth/refresh') {
    const rot = await fetch('/api/auth/refresh', {method:'POST', cache:'no-store', headers:{'Content-Type':'application/json', ...(csrf ? {'X-CSRF-Token':csrf}:{})}, body:'{}'});
    if (rot.ok) { const s = await rot.json(); csrf = s.csrf; return api(path, body, method, true); }
  }
  const result = await r.json();
  if (!r.ok) { const e = new Error(result.error || 'Não foi possível concluir.'); e.status = r.status; throw e; }
  return result;
}
function handleError(error) {
  $('#orders-status').textContent = error.message;
  if (error.status === 401) {
    selected = ''; $('#order-detail').hidden = true; $('#orders-list').replaceChildren(); $('#chat-messages').replaceChildren();
    $('#chat-form').reset(); $('#login-needed').hidden = false;
  }
}
async function loadOrders() {
  const result = await api('/api/orders?page=' + page);
  admin = result.admin;
  $('#page-title').textContent = admin ? 'Pedidos e suporte' : 'Meus pedidos';
  $('#admin-link').hidden = !admin;
  $('#orders-list').innerHTML = result.orders.map(o => `<article class="order-card"><strong>Pedido #${esc(o.id.slice(0,8))}</strong><small>${esc(date(o.created))}</small>${admin ? `<small>${esc(o.email)}</small>`:''}<p>${esc(o.items.map(i => `${i.quantity}× ${i.name}`).join(', '))}</p><p>${money(o.total)} · ${esc(o.status)}</p><p><span class="payment-tag ${paymentBadgeClass(o.payment)}">${esc(paymentShortLabel(o.payment))}</span></p><button class="btn ghost sm" type="button" data-order="${esc(o.id)}">${o.chat_enabled?'Abrir chat':'Ver pedido / pagar'}</button></article>`).join('') || '<p class="muted">Você ainda não tem pedidos.</p>';
  $('#previous-page').disabled = page === 1;
  $('#next-page').disabled = !result.has_more;
}
function renderOrder(o) {
  currentPayment=o.payment;chatEnabled=o.chat_enabled;$('.order-chat').hidden=!chatEnabled;
  $('#order-detail').hidden = false;
  $('#order-title').textContent = 'Pedido #' + o.id.slice(0,8);
  $('#order-info').textContent = `${money(o.total)} · ${o.status}${admin ? ' · ' + o.email : ''}${o.roblox_username ? ' · Roblox @' + o.roblox_username : ''}`;
  // Preserve unsent manual delivery drafts during polling.
  const drafts = new Map(Array.from(document.querySelectorAll('[data-delivery]')).map(f => [f.dataset.delivery, f.querySelector('textarea').value]));
  $('#order-items').innerHTML = o.items.map(i => `<article class="order-item"><h3>${esc(i.name)}</h3><p>${esc(i.quantity)} unidade(s) · ${money(i.unit_price*i.quantity)} · ${i.mode === 'automatic' ? 'Entrega automática' : 'Entrega manual'}</p>${i.category==='Robux' ? `<p>${esc(i.robux_quantity*i.quantity)} Robux para @${esc(o.roblox_username)}</p>`:''}<p>${i.delivered_at ? 'Entregue em ' + esc(date(i.delivered_at)) : 'Aguardando entrega'}</p>${i.delivered_at && o.payment==='pago' ? `<a class="btn" href="/api/orders/${esc(o.id)}/items/${esc(i.id)}/download">Baixar entrega .txt</a>`:''}${admin && o.payment==='pago' && !i.delivered_at && i.mode==='manual' ? `<form data-delivery="${esc(i.id)}"><label for="delivery-${esc(i.id)}">Texto da entrega (todas as ${esc(i.quantity)} unidades)</label><textarea id="delivery-${esc(i.id)}" required maxlength="20000"></textarea><button class="btn" type="submit">Entregar arquivo .txt</button></form>`:''}${admin && o.payment==='pago' && !i.delivered_at && i.mode==='automatic' ? '<p>Reponha o estoque no painel para liberar este item.</p>':''}</article>`).join('');
  document.querySelectorAll('[data-delivery]').forEach(f => { f.querySelector('textarea').value = drafts.get(f.dataset.delivery) || ''; });
  $('#payment-status').textContent=paymentLabels[o.payment]||o.payment;
  $('#payment-status').className='payment-tag '+paymentBadgeClass(o.payment);
  $('#open-payment-page').href='/pagamento/'+o.id;
  $('#open-payment-page').hidden=['pago','falha','reembolsado','expirado'].includes(o.payment);
  $('#payment-expiry-note').textContent=o.payment==='expirado'?'O prazo deste Pix terminou. Faça um novo pedido para gerar outro pagamento.':o.pix_expires_at&&o.payment==='pendente'?'Disponível até '+date(o.pix_expires_at)+'.':'';

}
let lastOrderJSON = '', nextPaymentCheck=0, currentPayment='';
async function refreshOrder(id) {
  const result = await api('/api/orders/' + encodeURIComponent(id));
  if (selected !== id) return;
  const serialized = JSON.stringify(result.order);
  if (serialized !== lastOrderJSON) { renderOrder(result.order); lastOrderJSON = serialized; }
}
async function messages(id) {
  if(!chatEnabled)return;
  const result = await api('/api/orders/' + encodeURIComponent(id) + '/messages?after=' + lastMessage);
  if (selected !== id) return;
  const box = $('#chat-messages');
  const wasBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 50;
  for (const message of result.messages) {
    if (message.id <= lastMessage) continue;
    const article = document.createElement('article'); article.className = 'chat-message' + (message.role === 'admin' ? ' support':'');
    const label = document.createElement('small'); label.textContent = `${message.role==='admin' ? 'Suporte':'Cliente'} · ${date(message.created)}`;
    const text = document.createElement('p'); text.textContent = message.text;
    article.dataset.messageId=message.id;article.append(label, text); box.append(article); lastMessage = message.id;
  }
  if (wasBottom) box.scrollTop = box.scrollHeight;
  $('#chat-presence').textContent=result.peer.typing?(admin?'Comprador digitando…':'Suporte digitando…'):result.peer.online?(admin?'● Comprador online':'● Suporte online'):(admin?'Comprador offline':'O suporte responderá por aqui.');
  box.querySelectorAll(admin?'.chat-message.support':'.chat-message:not(.support)').forEach(b=>b.dataset.receipt=Number(b.dataset.messageId)<=result.peer.read_id?'Lida':'Enviada');
  if (result.has_more) await messages(id);
  else await api(`/api/orders/${id}/chat-state`,{read_id:lastMessage,typing:Date.now()-lastTyped<4000});
}
async function openOrder(id) {
  if (!/^[a-f0-9]{32}$/.test(id)) return;
  selected = id; lastMessage = 0; lastOrderJSON = ''; messageRequest = null;
  $('#order-detail').hidden = true; $('#order-items').replaceChildren(); $('#chat-messages').replaceChildren();
  $('#chat-form').reset(); $('#chat-status').textContent = ''; $('#orders-status').textContent = '';
  history.replaceState(null, '', '/pedidos#' + id);
  try { await refreshOrder(id); await messages(id); if (selected===id) $('#order-detail').scrollIntoView({block:'start',behavior:'smooth'}); }
  catch (e) { handleError(e); }
}
$('#orders-list').onclick = event => { const button=event.target.closest('[data-order]'); if (button) openOrder(button.dataset.order); };
$('#refresh-orders').onclick = () => loadOrders().catch(handleError);
$('#previous-page').onclick = () => { page--; loadOrders().catch(handleError); };
$('#next-page').onclick = () => { page++; loadOrders().catch(handleError); };
$('#chat-form').onsubmit = async event => {
  event.preventDefault(); const id=selected, text=$('#chat-text').value.trim();
  if (!text || !id) return;
  if (!messageRequest || messageRequest.text!==text || messageRequest.order!==id) messageRequest={text,order:id,key:crypto.randomUUID()};
  $('#send-chat').disabled=true;
  try {
    await api(`/api/orders/${id}/messages`, {text,request_key:messageRequest.key});
    if (selected===id) { $('#chat-text').value=''; $('#chat-status').textContent=''; messageRequest=null;lastTyped=0; await messages(id); }
  } catch(e) { $('#chat-status').textContent=e.message; if(e.status===401) handleError(e); }
  finally { $('#send-chat').disabled=false; }
};
$('#order-items').onsubmit = async event => {
  const form=event.target.closest('[data-delivery]'); if(!form) return;
  event.preventDefault(); const id=selected;
  if (!confirm('Confirmar a entrega deste conteúdo? O cliente poderá baixá-lo imediatamente.')) return;
  const button=form.querySelector('button'); button.disabled=true;
  try { await api(`/api/admin/orders/${id}/items/${form.dataset.delivery}/deliver`, {content:form.querySelector('textarea').value}); await refreshOrder(id); await loadOrders(); }
  catch(e) { handleError(e); } finally { button.disabled=false; }
};
async function start() {
  try {
    const session=await api('/api/auth/me'); csrf=session.csrf;
    const config=await api('/api/checkout/config'); misticReady=config.mistic_ready;
    await loadOrders();
    if (location.hash) await openOrder(location.hash.slice(1));
  } catch(e) { handleError(e); }
}
setInterval(async () => {
  if(!selected || document.hidden || polling) return;
  polling=true; const id=selected;
  try { if(['pendente','criando','revisao'].includes(currentPayment)&&Date.now()>=nextPaymentCheck){nextPaymentCheck=Date.now()+15000;await api(`/api/orders/${id}/payment/check`,{});} await refreshOrder(id); await messages(id); } catch(e) { handleError(e); } finally { polling=false; }
},3000);
$('#chat-text').oninput=()=>{lastTyped=Date.now();};
$('#chat-text').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#chat-form').requestSubmit();}};
start();

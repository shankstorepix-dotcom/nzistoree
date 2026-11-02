'use strict';
(() => {
  const titles={overview:['Dashboard','Receita, vendas e atendimento em um só lugar.'],sales:['Vendas e pedidos','Acompanhe pagamentos, entregas e compradores.'],conversations:['Conversas','Atenda seus compradores diretamente pelo painel.'],products:['Produtos e estoque','Cadastre produtos e configure entregas.'],categories:['Categorias','Personalize a vitrine da sua loja.'],customers:['Clientes','Contas cadastradas e histórico de compras.'],coupons:['Cupons','Descontos ativos e uso em pedidos pagos.'],integrations:['Integrações','Pagamentos e notificações da loja.'],security:['Segurança','Controles de acesso e proteção da loja.']};
  const date=n=>new Date(n*1000).toLocaleString('pt-BR');
  const payment={expirado:'Expirado',nao_iniciado:'Pendente',criando:'Pendente',pendente:'Pendente',revisao:'Pendente',pago:'Concluído',falha:'Falha',reembolsado:'Reembolsado'};
  const paymentBadgeClass=p=>p==='pago'?'paid':['nao_iniciado','criando','pendente','revisao'].includes(p)?'pending':'failed';
  let authenticated=false,view='overview',generation=0,salesPage=1,customersPage=1,inboxPage=1,inboxVersion=0;
  let selected='',lastMessage=0,threadVersion=0,polling=false,nextInbox=0,nextMetrics=0,queryTimer;
  let draftRequest=null,lastTyped=0;
  $('#inbox-text').oninput=()=>{lastTyped=Date.now();};
  $('#inbox-text').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#inbox-form').requestSubmit();}};
  const drafts=new Map();
  const table=(headers,rows)=>`<table><thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.join(''):`<tr><td colspan="${headers.length}" class="muted">Nenhum registro encontrado.</td></tr>`}</tbody></table>`;
  function fail(error){
    $('#workspace-status').textContent=error.message;
    if(error.status===401||error.status===403){authenticated=false;generation++;threadVersion++;selected='';drafts.clear();draftRequest=null;$('#inbox-text').value='';$('#inbox-messages').replaceChildren();$('#inbox-list').replaceChildren();$('#workspace-sales').replaceChildren();$('#workspace-customers').replaceChildren();$('#metric-cards').replaceChildren();$('#dashboard').hidden=true;$('#auth').hidden=false;$('#login-error').textContent='Sua sessão terminou. Entre novamente.';}
  }
  function chart(series){
    const width=700,height=210,top=20,bottom=178,left=66,right=680,max=Math.max(100,...series.map(d=>d.revenue));
    const x=i=>left+(right-left)*(series.length===1?.5:i/(series.length-1));
    const y=v=>bottom-(bottom-top)*v/max;
    const path=series.map((d,i)=>`${i?'L':'M'} ${x(i).toFixed(1)} ${y(d.revenue).toFixed(1)}`).join(' ');
    const labels=[...new Set([0,Math.floor((series.length-1)/2),series.length-1])];
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Faturamento diário em reais. Valores detalhados na tabela abaixo.">${[0,.5,1].map(f=>`<line x1="${left}" x2="${right}" y1="${y(max*f)}" y2="${y(max*f)}" stroke="#ffffff12"/><text x="${left-8}" y="${y(max*f)+4}" text-anchor="end">${esc(money(max*f))}</text>`).join('')}<path d="${path}" fill="none" stroke="#ed3657" stroke-width="3"/>${series.map((d,i)=>`<circle cx="${x(i)}" cy="${y(d.revenue)}" r="3" fill="#ff6f8a"><title>${esc(d.date)}: ${esc(money(d.revenue))} · ${d.sales} vendas</title></circle>`).join('')}${labels.map(i=>`<text x="${x(i)}" y="203" text-anchor="middle">${series[i].date.slice(8)}/${series[i].date.slice(5,7)}</text>`).join('')}</svg>`;
  }
  async function metrics(){
    const epoch=generation,days=$('#metric-days').value;
    const data=await api('/api/admin/metrics?days='+days);
    if(!authenticated||epoch!==generation||days!==$('#metric-days').value)return;
    const cards=[['Faturamento',money(data.revenue),'Pagamentos confirmados no período'],['Vendas pagas',String(data.sales),'Pedidos com pagamento confirmado'],['Aprovação de pedidos',data.approval_rate.toLocaleString('pt-BR')+'%','Pagos entre os pedidos criados no período'],['Ticket médio',money(data.average_ticket),'Valor médio por pedido pago'],['Visitas',String(data.visits),'Sessões de aba por dia com consentimento']];
    $('#metric-cards').innerHTML=cards.map(([label,value,note])=>`<article class="metric-card"><h2>${label}</h2><strong>${value}</strong><p>${note}</p></article>`).join('');
    $('#sales-chart').innerHTML=chart(data.series);
    renderInsights(data).catch(fail);
    $('#sales-daily').innerHTML=table(['Dia','Faturamento','Vendas'],data.series.map(d=>`<tr><td>${esc(d.date.split('-').reverse().join('/'))}</td><td>${money(d.revenue)}</td><td>${d.sales}</td></tr>`));
    $('#operation-metrics').innerHTML=`<div class="operation-row"><span>Entregas pendentes de pedidos pagos</span><strong>${data.pending_deliveries}</strong></div><div class="operation-row"><span>Conversas aguardando resposta</span><strong>${data.waiting_conversations}</strong></div><div class="operation-row"><span>Clientes cadastrados</span><strong>${data.customers}</strong></div><div class="operation-row"><span>Pedidos criados no período</span><strong>${data.orders}</strong></div><p class="muted">${data.revenue_change===null?'Sem base paga no período anterior para comparação.':`Faturamento: ${data.revenue_change>0?'+':''}${data.revenue_change}% em relação ao período anterior.`}</p>`;
    $('#coupon-metrics').textContent=`Últimos ${data.days} dia(s): ${data.coupon.uses} pedido(s) pago(s) com cupom · ${money(data.coupon.discount)} em descontos.`;
    $('#inbox-badge').textContent=data.waiting_conversations||'';
  }
  let mapPromise;
  async function renderInsights(data){
    const epoch=generation;
    $('#buyer-summary').innerHTML=`<div class="buyer-stats"><div><strong>${data.buyers-data.recurring}</strong><span>Primeira compra</span></div><div><strong>${data.recurring}</strong><span>Clientes recorrentes</span></div></div><p class="muted">Compradores pagos no período. Recorrentes possuem mais de uma compra paga até o fim do período.</p>`;
    $('#approval-gauge').innerHTML=`<svg viewBox="0 0 220 125" role="img" aria-label="${data.approval_rate}% de pedidos aprovados"><path d="M20 110 A90 90 0 0 1 200 110" pathLength="100" fill="none" stroke="#ffffff13" stroke-width="12" stroke-linecap="round"/><path d="M20 110 A90 90 0 0 1 200 110" pathLength="100" fill="none" stroke="#ef3657" stroke-width="12" stroke-linecap="round" stroke-dasharray="${data.approval_rate} 100"/><text x="110" y="100" text-anchor="middle" fill="white" font-size="28">${data.approval_rate}%</text></svg>`;
    $('#top-products').innerHTML=table(['Produto','Unidades','Faturamento'],data.top_products.map(p=>`<tr><td>${esc(p.name)}</td><td>${p.quantity}</td><td>${money(p.revenue)}</td></tr>`));
    const visits=Object.fromEntries(data.visit_series.map(d=>[d.day,d.visits])),max=Math.max(1,...Object.values(visits));
    $('#visits-chart').innerHTML='<div class="visit-bars">'+data.series.map(d=>`<div title="${esc(d.date)}: ${visits[d.date]||0} visitas"><span style="height:${Math.max(1,(visits[d.date]||0)/max*100)}%"></span><small>${d.date.slice(8)}</small></div>`).join('')+'</div><p class="muted">'+data.visits+' visitas contabilizadas no período.</p>';
    $('#geo-status').textContent=(data.geo_ready?'Localização aproximada por IP.':'Configure uma base GeoIP local para identificar estados.')+` ${data.geo_unknown} sem localização · ${data.geo_abroad} fora do Brasil.`;
    $('#geo-list').innerHTML=table(['Estado','Visitas'],data.states.map(s=>`<tr><td>${esc(s.state)}</td><td>${s.visits}</td></tr>`));
    if(!mapPromise)mapPromise=fetch('/static/brazil-states.json').then(r=>{if(!r.ok)throw Error('Mapa indisponível.');return r.json();}).catch(e=>{mapPromise=null;throw e;});
    const states=await mapPromise;if(!authenticated||epoch!==generation)return;
    const counts=Object.fromEntries(data.states.map(s=>[s.state,s.visits])),high=Math.max(1,...Object.values(counts));
    $('#geo-map').innerHTML=`<svg viewBox="0 0 420 410" role="img" aria-label="Mapa de visitas por estado brasileiro">${states.map(s=>`<path d="${esc(s.d)}" fill="${counts[s.uf]?`hsl(350 72% ${25+counts[s.uf]/high*30}%)`:'#302b33'}" stroke="#0c0a10" stroke-width=".8" tabindex="0" aria-label="${esc(s.name)}: ${counts[s.uf]||0} visitas"><title>${esc(s.name)}: ${counts[s.uf]||0} visitas</title></path>`).join('')}</svg>`;
  }
  async function sales(){
    const epoch=generation,page=salesPage,data=await api('/api/orders?page='+page);
    if(!authenticated||epoch!==generation||page!==salesPage)return;
    $('#workspace-sales').innerHTML=table(['Pedido / comprador','Valor','Pagamento','Entrega','Ações'],data.orders.map(o=>`<tr><td><strong>#${esc(o.id.slice(0,8))}</strong><small>${esc(o.email||'')}</small><small>${esc(date(o.created))}</small></td><td>${money(o.total)}</td><td><span class="payment-tag ${paymentBadgeClass(o.payment)}">${esc(payment[o.payment]||o.payment)}</span></td><td>${esc(o.status)}</td><td>${o.chat_enabled?`<button class="btn ghost sm" data-support-order="${esc(o.id)}">Conversar</button>`:""}<a href="/pedidos#${esc(o.id)}" target="_blank" rel="noopener">Abrir pedido ↗</a></td></tr>`));
    $('#sales-page').textContent='Página '+page;$('#sales-prev').disabled=page===1;$('#sales-next').disabled=!data.has_more;
  }
  async function customers(){
    const epoch=generation,page=customersPage,data=await api('/api/admin/customers?page='+page);
    if(!authenticated||epoch!==generation||page!==customersPage)return;
    $('#workspace-customers').innerHTML=table(['Cliente','Pedidos','Total pago'],data.customers.map(c=>`<tr><td>${esc(c.email)}</td><td>${c.orders}</td><td>${money(c.paid_total)}</td></tr>`));
    $('#customers-page').textContent='Página '+page;$('#customers-prev').disabled=page===1;$('#customers-next').disabled=!data.has_more;
  }
  async function inbox(){
    const version=++inboxVersion,epoch=generation;
    const params=new URLSearchParams({page:inboxPage,q:$('#inbox-query').value,waiting:$('#inbox-waiting').checked?'1':'0'});
    const data=await api('/api/admin/conversations?'+params);
    if(!authenticated||version!==inboxVersion||epoch!==generation)return;
    $('#inbox-badge').textContent=data.waiting_count||'';
    $('#inbox-list').innerHTML=data.conversations.map(c=>`<button class="conversation ${selected===c.id?'selected':''}" type="button" data-thread="${esc(c.id)}"><strong>${esc(c.email)}</strong><small>#${esc(c.id.slice(0,8))} · ${esc(date(c.message_at||c.created))}</small><p>${esc(c.preview||'Pedido criado. Inicie o atendimento.')}</p>${c.last_role==='customer'?'<span class="waiting-tag">Aguardando resposta</span>':''}</button>`).join('')||'<p class="muted">Nenhuma conversa encontrada.</p>';
    $('#inbox-page').textContent='Página '+inboxPage;$('#inbox-prev').disabled=inboxPage===1;$('#inbox-next').disabled=!data.has_more;
  }
  async function messages(){
    const id=selected,version=threadVersion;if(!id)return;
    let more=true,pages=0;
    while(more&&pages++<10){
      const data=await api(`/api/orders/${id}/messages?after=${lastMessage}`);
      if(!authenticated||selected!==id||version!==threadVersion)return;
      const box=$('#inbox-messages'),bottom=box.scrollTop+box.clientHeight>=box.scrollHeight-60;
      for(const message of data.messages){if(message.id<=lastMessage)continue;const article=document.createElement('article');article.className='inbox-bubble '+(message.role==='admin'?'from-support':'');const label=document.createElement('small');label.textContent=(message.role==='admin'?'Você / suporte':'Comprador')+' · '+date(message.created);const text=document.createElement('p');text.textContent=message.text;article.dataset.messageId=message.id;article.append(label,text);box.append(article);lastMessage=message.id;}
      $('#inbox-presence').textContent=data.peer.typing?'Comprador digitando…':data.peer.online?'● Comprador online':'Comprador offline';
      box.querySelectorAll('.from-support').forEach(b=>b.dataset.receipt=Number(b.dataset.messageId)<=data.peer.read_id?'Lida':'Enviada');
      if(bottom)box.scrollTop=box.scrollHeight;more=data.has_more;
    }
    if(selected===id&&version===threadVersion)await api(`/api/orders/${id}/chat-state`,'POST',{read_id:lastMessage,typing:Date.now()-lastTyped<4000});
  }
  async function openThread(id){
    if(!/^[a-f0-9]{32}$/.test(id))return;
    if(selected)drafts.set(selected,$('#inbox-text').value);
    selected=id;lastMessage=0;const version=++threadVersion;draftRequest=null;
    $('#inbox-thread').hidden=true;$('#inbox-empty').hidden=false;$('#inbox-messages').replaceChildren();$('#inbox-text').value=drafts.get(id)||'';$('#inbox-send-status').textContent='';
    const data=await api('/api/orders/'+id);
    if(selected!==id||version!==threadVersion||!authenticated)return;
    $('#inbox-title').textContent=data.order.email||'Comprador';$('#inbox-context').textContent=`Pedido #${id.slice(0,8)} · ${money(data.order.total)} · ${payment[data.order.payment]||data.order.payment}`;$('#inbox-order-link').href='/pedidos#'+id;$('#inbox-empty').hidden=true;$('#inbox-thread').hidden=false;
    await messages();await inbox();
  }
  async function refresh(){
    if(!authenticated)return;
    if(view==='overview')await metrics();
    else if(view==='coupons'){const {coupon}=await api('/api/admin/coupon');$('#coupon-admin-code').value=coupon.code;$('#coupon-admin-percent').value=coupon.percent;$('#coupon-admin-enabled').checked=!!coupon.enabled;await metrics();}
    else if(view==='sales')await sales();
    else if(view==='customers')await customers();
    else if(view==='conversations'){await inbox();await messages();}
    else if(view==='products'||view==='categories')await load();
    else if(view==='integrations'){const data=await api('/api/admin/commerce/status');$('#integration-status').textContent=`Pantera Pay: ${data.pantera_ready?'configurada':'não configurada'} · Provedor ativo: ${data.payment_provider} · Mistic Pay: ${data.mistic_ready?'configurada':'não configurada'} · Discord Webhook: ${data.discord_ready?'configurado':'não configurado'} · Google OAuth: ${data.google_oauth_ready?'configurado':'não configurado'} · Discord OAuth: ${data.discord_oauth_ready?'configurado':'não configurado'} · UTMify: ${data.utmify_ready?'configurada':'não configurada'} · Tarefas pendentes: ${data.jobs.reduce((sum,j)=>sum+j.pending,0)}`;}
  }
  function selectView(name){
    if(!titles[name])name='overview';view=name;generation++;
    document.querySelectorAll('[data-workspace-panel]').forEach(p=>p.hidden=p.dataset.workspacePanel!==name);
    document.querySelectorAll('[data-workspace]').forEach(b=>{b.classList.toggle('active',b.dataset.workspace===name);if(b.dataset.workspace===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    $('#workspace-title').textContent=titles[name][0];$('#workspace-subtitle').textContent=titles[name][1];$('#workspace-status').textContent='';
    history.replaceState(null,'','/dashboard#'+name);refresh().catch(fail);
  }
  document.querySelector('.workspace-nav').onclick=e=>{const b=e.target.closest('[data-workspace]');if(b)selectView(b.dataset.workspace);};
  $('#workspace-refresh').onclick=()=>refresh().catch(fail);$('#metric-days').onchange=()=>metrics().catch(fail);
  for(const kind of ['sales','customers','inbox'])for(const direction of ['prev','next'])$('#'+kind+'-'+direction).onclick=()=>{const delta=direction==='next'?1:-1;if(kind==='sales'){salesPage=Math.max(1,salesPage+delta);sales().catch(fail);}else if(kind==='customers'){customersPage=Math.max(1,customersPage+delta);customers().catch(fail);}else{inboxPage=Math.max(1,inboxPage+delta);inbox().catch(fail);}};
  $('#workspace-sales').onclick=e=>{const b=e.target.closest('[data-support-order]');if(b){selectView('conversations');openThread(b.dataset.supportOrder).catch(fail);}};
  $('#inbox-list').onclick=e=>{const b=e.target.closest('[data-thread]');if(b)openThread(b.dataset.thread).catch(fail);};
  $('#inbox-query').oninput=()=>{inboxVersion++;clearTimeout(queryTimer);queryTimer=setTimeout(()=>{inboxPage=1;inbox().catch(fail);},300);};$('#inbox-waiting').onchange=()=>{inboxPage=1;inbox().catch(fail);};
  $('#inbox-form').onsubmit=async e=>{
    e.preventDefault();const id=selected,text=$('#inbox-text').value.trim();if(!text||!id)return;
    if(!draftRequest||draftRequest.id!==id||draftRequest.text!==text)draftRequest={id,text,key:crypto.randomUUID()};
    const request=draftRequest;$('#inbox-send').disabled=true;
    try{await api(`/api/orders/${id}/messages`,'POST',{text,request_key:request.key});drafts.delete(id);lastTyped=0;if(selected===id&&$('#inbox-text').value.trim()===text){$('#inbox-text').value='';$('#inbox-send-status').textContent='Mensagem enviada.';}if(draftRequest===request)draftRequest=null;await messages();await inbox();}
    catch(error){$('#inbox-send-status').textContent=error.message;if(error.status===401||error.status===403)fail(error);}
    finally{$('#inbox-send').disabled=false;}
  };
  $('#coupon-editor').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{await api('/api/admin/coupon','PUT',{code:$('#coupon-admin-code').value.trim().toUpperCase(),percent:Number($('#coupon-admin-percent').value),enabled:$('#coupon-admin-enabled').checked});$('#coupon-edit-status').textContent='Cupom salvo. Novas compras usam esta configuração.';}catch(error){$('#coupon-edit-status').textContent=error.message;}finally{button.disabled=false;}};
  const localDay=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  $('#report-to').value=localDay(new Date());$('#report-from').value=localDay(new Date(Date.now()-29*86400000));
  $('#email-report').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{await api('/api/status');const params=new URLSearchParams({from:$('#report-from').value,to:$('#report-to').value});const response=await fetch('/api/admin/sales/emails.csv?'+params,{cache:'no-store'});if(!response.ok)throw new Error((await response.json()).error||'Falha ao exportar.');const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='emails-vendas.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('#report-status').textContent='Relatório gerado.';}catch(error){$('#report-status').textContent=error.message;}finally{button.disabled=false;}};
  window.addEventListener('nzi:admin-session',e=>{
    authenticated=e.detail.authenticated;generation++;
    if(authenticated)selectView(location.hash.slice(1)||'overview');
    else{selected='';threadVersion++;drafts.clear();draftRequest=null;$('#inbox-text').value='';$('#inbox-messages').replaceChildren();$('#inbox-list').replaceChildren();$('#workspace-customers').replaceChildren();$('#workspace-sales').replaceChildren();}
  });
  setInterval(async()=>{
    if(!authenticated||document.hidden||polling)return;polling=true;
    try{const now=Date.now();if(view==='conversations'){await messages();if(now>=nextInbox){await inbox();nextInbox=now+3000;}$('#inbox-live').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR');}else if(view==='overview'&&now>=nextMetrics){await metrics();nextMetrics=now+30000;}}
    catch(error){$('#inbox-live').textContent='Conexão interrompida. Tentando novamente…';fail(error);}finally{polling=false;}
  },3000);
})();

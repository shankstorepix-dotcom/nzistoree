'use strict';

const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = cents => (cents / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const norm = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const CATEGORIES = ['Robux', 'Painel (login)', 'Streamings', 'Contas Discord', 'Contas Roblox'];

let configured = false;
let csrf = ''; 
let products = [];
let games=[];
let categorySettings = [];
let categoryImage = "";
const categoryTitle = name => categorySettings.find(c => c.name === name)?.title || name;
let image = '';

async function tryRefreshSession() {
  try {
    const rot = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
      body: '{}'
    });
    if (rot.ok) {
      const s = await rot.json();
      if (s && s.csrf) csrf = s.csrf;
      return true;
    }
  } catch (e) { /* falha de rede no refresh */ }
  return false;
}

async function api(path, method = 'GET', data, retried = false) {
  let r;
  try {
    r = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
      ...(data ? { body: JSON.stringify(data) } : {})
    });
  } catch (networkErr) {
    if (!retried && path !== '/api/login' && path !== '/api/auth/refresh') {
      if (await tryRefreshSession()) return api(path, method, data, true);
    }
    throw Error('Falha de conexão com o servidor. Verifique se sua sessão está ativa e tente novamente.');
  }
  if ((r.status === 401 || r.status === 403) && !retried && path !== '/api/login' && path !== '/api/auth/refresh') {
    if (await tryRefreshSession()) return api(path, method, data, true);
  }
  let result = {};
  try { result = await r.json(); } catch (e) { result = {}; }
  if (!r.ok) { const error=Error(result.error || 'Não foi possível concluir'); error.status=r.status; throw error; }
  return result;
}

async function encodeImageForUpload(file) {
  if (file.size > 10000000) throw Error('A imagem deve ter até 10 MB.');
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(Error('Não foi possível ler o arquivo de imagem.'));
    reader.readAsDataURL(file);
  });
  const rawBase64 = dataUrl.includes(',') ? dataUrl.split(',')[1] : dataUrl;
  if (file.size <= 700000) return rawBase64;
  try {
    const img = await new Promise((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = reject;
      el.src = dataUrl;
    });
    const maxDim = 1600;
    let w = img.naturalWidth || img.width;
    let h = img.naturalHeight || img.height;
    if (!w || !h) return rawBase64;
    if (w > maxDim || h > maxDim) {
      const ratio = Math.min(maxDim / w, maxDim / h);
      w = Math.max(1, Math.round(w * ratio));
      h = Math.max(1, Math.round(h * ratio));
    }
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return rawBase64;
    ctx.drawImage(img, 0, 0, w, h);
    let compressed = canvas.toDataURL('image/webp', 0.88);
    if (!compressed.startsWith('data:image/webp')) {
      compressed = canvas.toDataURL('image/jpeg', 0.88);
    }
    const encoded = compressed.includes(',') ? compressed.split(',')[1] : '';
    return encoded && encoded.length < rawBase64.length ? encoded : rawBase64;
  } catch (e) {
    return rawBase64;
  }
}

async function uploadImageFile(file) {
  const s = await api('/api/status');
  if (!s.authenticated) {
    await tryRefreshSession();
  } else if (s.csrf) {
    csrf = s.csrf;
  }
  const data = await encodeImageForUpload(file);
  return (await api('/api/upload', 'POST', { data })).url;
}
function say(text, type = '') {
  const m = $('#message');
  m.textContent = text;
  m.className = 'msg' + (type ? ' ' + type : '');
}

/* ---------- acesso ---------- */
async function status() {
  let s = await api('/api/status');
  if (!s.authenticated && s.configured) {
    if (await tryRefreshSession()) {
      s = await api('/api/status');
    }
  }
  configured = s.configured;
  csrf = s.csrf || '';
  $('#auth').hidden = s.authenticated;
  $('#dashboard').hidden = !s.authenticated;
  window.dispatchEvent(new CustomEvent('nzi:admin-session',{detail:{authenticated:s.authenticated}}));
  $('#auth-title').textContent = configured ? 'Entrar no painel' : 'Configure pelo terminal';
  $('#auth-hint').textContent = configured
    ? 'Informe seu usuário, senha e PIN de seis dígitos.'
    : 'Execute no servidor: .venv/bin/flask --app server create-admin';
  $('#login').hidden = !configured;
  $('#password').minLength = 1;
  $('#password').autocomplete = configured ? 'current-password' : 'new-password';
  if (s.authenticated) {
    await load();
    const integrations = await api('/api/admin/commerce/status');
    $('#integration-status').textContent = `Mistic Pay: ${integrations.mistic_ready ? 'configurada' : 'aguardando configuração no servidor'} · Discord: ${integrations.discord_ready ? 'configurado' : 'aguardando webhook no servidor'} · Notificações pendentes: ${integrations.jobs.filter(j => j.kind === 'discord').reduce((n,j) => n+j.pending,0)}`;
  }
}
$('#login').onsubmit = async e => {
  e.preventDefault();
  try {
    await api(configured ? '/api/login' : '/api/setup', 'POST', { username: $('#admin-user').value, password: $('#password').value, pin: $('#admin-pin').value });
    $('#password').value = '';
    $('#admin-pin').value = '';
    $('#login-error').textContent = '';
    await status();
  } catch (err) { $('#login-error').textContent = err.message; }
};
$('#logout').onclick = async () => {
  try { await api('/api/logout', 'POST', {}); } catch (e) { /* sessão já expirada */ }
  reset();
  await status();
};

/* ---------- catálogo ---------- */
async function load() {
  [products, categorySettings, games] = await Promise.all([api('/api/products'), api('/api/categories'),api('/api/roblox/subcategories')]);
  renderGames();
  renderCategoryOptions();
  renderStats();
  renderFilter();
  renderList();
}
function renderStats() {
  const counts = {};
  products.forEach(p => { counts[p.category] = (counts[p.category] || 0) + 1; });
  $('#stats').innerHTML =
    `<div class="stat main"><b>${products.length}</b><span>produtos no total</span></div>` +
    CATEGORIES.map(c => `<div class="stat"><b>${counts[c] || 0}</b><span>${esc(categoryTitle(c))}</span></div>`).join('');
}
function renderFilter() {
  const current = $('#list-filter').value || '';
  $('#list-filter').innerHTML = '<option value="">Todas as categorias</option>' +
    CATEGORIES.map(c => `<option value="${esc(c)}"${c === current ? ' selected' : ''}>${esc(categoryTitle(c))}</option>`).join('');
}
function renderList() {
  const q = norm($('#list-search').value.trim());
  const cat = $('#list-filter').value;
  const visible = products.filter(p => (!cat || p.category === cat) && (!q || norm(p.name + ' ' + p.description).includes(q)));
  $('#total').textContent = visible.length === products.length
    ? products.length + (products.length === 1 ? ' produto' : ' produtos')
    : visible.length + ' de ' + products.length;
  $('#list').innerHTML = visible.map(p => {
    const disc = p.compare_price && p.compare_price > p.price ? Math.round((1 - p.price / p.compare_price) * 100) : 0;
    const typeLabel = p.has_variants ? ` · ${p.variants?.length || 0} var.` : '';
    return `<div class="admin-row">
      ${p.image
        ? `<img class="thumb" src="${esc(p.image)}" alt="" loading="lazy">`
        : `<span class="thumb" aria-hidden="true">${esc(p.name.trim().charAt(0).toUpperCase())}</span>`}
      <div><strong>${esc(p.name)}</strong><p>${esc(categoryTitle(p.category))} · <span class="price">${money(p.price)}</span>${disc > 0 ? ` <small class="muted"><s>${money(p.compare_price)}</s> (-${disc}%)</small>` : ''}${esc(typeLabel)}</p></div>
      <div class="actions">
        <button class="btn ghost sm" type="button" data-edit="${p.id}">Editar</button>
        <button class="btn ghost sm" type="button" data-delete="${p.id}">Excluir</button>
      </div></div>`;
  }).join('') ||
    `<p class="empty-list">${products.length ? 'Nenhum produto com esse filtro.' : 'Nenhum produto cadastrado ainda.'}</p>`;
}
$('#list-search').oninput = renderList;
$('#list-filter').onchange = renderList;

/* ---------- formulário ---------- */
function updateDiscountPreview() {
  const realVal = Number($('#price').value || 0);
  const compVal = Number($('#compare-price').value || 0);
  const el = $('#discount-preview');
  if (!el) return;
  if (realVal > 0 && compVal > realVal) {
    const pct = Math.round((1 - realVal / compVal) * 100);
    el.textContent = `Comparação ativa: de ${money(Math.round(compVal * 100))} por ${money(Math.round(realVal * 100))} (${pct}% OFF arredondado).`;
  } else if (compVal > 0 && compVal <= realVal) {
    el.textContent = 'Atenção: o preço de comparação precisa ser maior que o preço real para exibir o desconto riscado.';
  } else {
    el.textContent = '';
  }
}
$('#price')?.addEventListener('input', updateDiscountPreview);
$('#compare-price')?.addEventListener('input', updateDiscountPreview);

function variantRowHtml(v = {}) {
  const name = v.name || '';
  const price = v.price ? (v.price / 100).toFixed(2) : '';
  const compare = v.compare_price ? (v.compare_price / 100).toFixed(2) : '';
  const stock = v.stock !== undefined ? v.stock : 1;
  return `<div class="variant-admin-row">
    <div class="variant-admin-fields">
      <div>
        <label>Nome da variação</label>
        <input type="text" class="var-name" maxlength="120" placeholder="Ex.: AMAZON PRIME VIDEO (30 DIAS)" value="${esc(name)}">
      </div>
      <div>
        <label>Preço real (R$)</label>
        <input type="number" class="var-price" min="0.01" max="1000000" step="0.01" placeholder="3,99" value="${esc(price)}">
      </div>
      <div>
        <label>Comparação riscado (R$)</label>
        <input type="number" class="var-compare" min="0" max="1000000" step="0.01" placeholder="30,00" value="${esc(compare)}">
      </div>
      <div>
        <label>Estoque disp.</label>
        <input type="number" class="var-stock" min="0" max="100000" step="1" value="${esc(stock)}">
      </div>
    </div>
    <button type="button" class="btn ghost sm" data-remove-variant>Remover</button>
  </div>`;
}

function renderVariantsEditor(list = []) {
  const container = $('#variants-list');
  if (!container) return;
  const rows = list.length ? list : [{}];
  container.innerHTML = rows.map(v => variantRowHtml(v)).join('');
}

function collectVariants() {
  if ($('#product-type')?.value !== 'variants') return [];
  const rows = Array.from(document.querySelectorAll('#variants-list .variant-admin-row'));
  return rows.map(row => {
    const name = row.querySelector('.var-name')?.value.trim() || '';
    const price = Math.round(Number(row.querySelector('.var-price')?.value || 0) * 100);
    const compareRaw = Number(row.querySelector('.var-compare')?.value || 0);
    const compare_price = compareRaw > 0 ? Math.round(compareRaw * 100) : 0;
    const stock = Math.max(0, Math.round(Number(row.querySelector('.var-stock')?.value || 0)));
    return { name, price, compare_price, stock };
  }).filter(v => v.name || v.price > 0);
}

$('#add-variant-row')?.addEventListener('click', () => {
  $('#variants-list')?.insertAdjacentHTML('beforeend', variantRowHtml({}));
});

$('#variants-list')?.addEventListener('click', e => {
  const rm = e.target.closest('[data-remove-variant]');
  if (!rm) return;
  const row = rm.closest('.variant-admin-row');
  if (row) row.remove();
  if (!document.querySelectorAll('#variants-list .variant-admin-row').length) {
    renderVariantsEditor([{}]);
  }
});

$('#product-type')?.addEventListener('change', () => {
  const isVar = $('#product-type').value === 'variants';
  if ($('#variants-panel')) $('#variants-panel').hidden = !isVar;
  if (isVar && !document.querySelectorAll('#variants-list .variant-admin-row').length) {
    renderVariantsEditor([{}]);
  }
});

function preview() {
  const p = $('#preview');
  p.hidden = !image;
  if (image) p.src = image; else p.removeAttribute('src');
  $('#remove-image').hidden = !image;
}
function resetStockEditor() {
  if ($('#editing-stock-id')) $('#editing-stock-id').value = '';
  if ($('#stock-content')) $('#stock-content').value = '';
  if ($('#stock-content-label')) $('#stock-content-label').textContent = 'Conteúdo de uma unidade';
  if ($('#add-stock')) $('#add-stock').textContent = 'Adicionar unidade ao estoque';
  if ($('#cancel-edit-stock')) $('#cancel-edit-stock').hidden = true;
}
$('#cancel-edit-stock')?.addEventListener('click', () => {
  resetStockEditor();
  $('#stock-status').textContent = '';
});
function reset() {
  $('#product-form').reset();
  $('#product-id').value = '';
  if ($('#compare-price')) $('#compare-price').value = '';
  if ($('#video-url')) $('#video-url').value = '';
  if ($('#min-quantity')) $('#min-quantity').value = '1';
  if ($('#max-quantity')) $('#max-quantity').value = '99';
  if ($('#product-type')) $('#product-type').value = 'normal';
  if ($('#variants-panel')) $('#variants-panel').hidden = true;
  renderVariantsEditor([]);
  updateDiscountPreview();
  image = '';
  preview();
  $('#form-title').textContent = 'Novo produto';
  $('#stock-panel').hidden = true;
  resetStockEditor();
  deliveryVisibility();
  say('');
}
$('#cancel').onclick = reset;
$('#remove-image').onclick = () => { image = ''; $('#image').value = ''; preview(); };
$('#image').onchange = () => {
  const file = $('#image').files[0];
  if (!file) return;
  if (file.size > 10000000) { say('A imagem deve ter até 10 MB.', 'error'); $('#image').value = ''; return; }
  const r = new FileReader();
  r.onload = () => { $('#preview').src = r.result; $('#preview').hidden = false; $('#remove-image').hidden = false; };
  r.readAsDataURL(file);
};
$('#product-form').onsubmit = async e => {
  e.preventDefault();
  $('#save').disabled = true;
  say('Salvando…');
  try {
    const file = $('#image').files[0];
    if (file) {
      image = await uploadImageFile(file);
    }
    const id = $('#product-id').value;
    const hasVariants = $('#product-type')?.value === 'variants';
    const variants = collectVariants();
    const compareVal = Number($('#compare-price')?.value || 0);
    const saved = await api('/api/products' + (id ? '/' + id : ''), id ? 'PUT' : 'POST', {
      name: $('#name').value,
      category: $('#category').value,
      subcategory_id:$('#category').value==='Contas Roblox'&&$('#product-game').value?Number($('#product-game').value):null,
      description: $('#description').value,
      price: Math.round(Number($('#price').value) * 100),
      compare_price: compareVal > 0 ? Math.round(compareVal * 100) : 0,
      video_url: ($('#video-url')?.value || '').trim(),
      min_quantity: Math.max(1, Math.round(Number($('#min-quantity')?.value || 1))),
      max_quantity: Math.max(1, Math.round(Number($('#max-quantity')?.value || 99))),
      has_variants: hasVariants,
      variants,
      image,
      delivery_mode: $('#delivery-mode').value,
      robux_quantity: $('#category').value === 'Robux' ? Number($('#robux-quantity').value) : 0
    });
    $('#product-id').value = saved.id;
    $('#form-title').textContent = 'Editar produto';
    await loadDelivery(saved.id);
    say('Produto salvo com sucesso.', 'ok');
    await load();
  } catch (err) {
    say(err.message, 'error');
  } finally {
    $('#save').disabled = false;
  }
};

$('#list').onclick = async e => {
  const editBtn = e.target.closest('[data-edit]');
  const delBtn = e.target.closest('[data-delete]');
  if (editBtn) {
    const p = products.find(x => x.id == editBtn.dataset.edit);
    if (!p) return;
    $('#stock-panel').hidden = true;
    resetStockEditor();
    $('#product-id').value = p.id;
    $('#name').value = p.name;
    $('#category').value = p.category;
    $('#product-game').value=p.subcategory_id||'';
    $('#description').value = p.description;
    $('#price').value = (p.price / 100).toFixed(2);
    if ($('#compare-price')) $('#compare-price').value = p.compare_price > 0 ? (p.compare_price / 100).toFixed(2) : '';
    if ($('#video-url')) $('#video-url').value = p.video_url || '';
    if ($('#min-quantity')) $('#min-quantity').value = p.min_quantity || 1;
    if ($('#max-quantity')) $('#max-quantity').value = p.max_quantity || 99;
    if ($('#product-type')) {
      $('#product-type').value = p.has_variants ? 'variants' : 'normal';
      if ($('#variants-panel')) $('#variants-panel').hidden = !p.has_variants;
    }
    renderVariantsEditor(p.variants || []);
    updateDiscountPreview();
    image = p.image;
    $('#image').value = '';
    preview();
    $('#form-title').textContent = 'Editar produto';
    say('');
    $('#product-form').scrollIntoView({ behavior: 'smooth', block: 'start' });
    $('#name').focus({ preventScroll: true });
    try { await loadDelivery(p.id); } catch (err) { say(err.message, 'error'); }
  }
  if (delBtn && confirm('Excluir este produto?')) {
    try {
      await api('/api/products/' + delBtn.dataset.delete, 'DELETE', {});
      if ($('#product-id').value == delBtn.dataset.delete) reset();
      await load();
    } catch (err) { say(err.message, 'error'); }
  }
};

status().catch(err => { $('#login-error').textContent = err.message; });

function deliveryVisibility() {
  $('#product-game-field').hidden=$('#category').value!=='Contas Roblox';
  const robux = $('#category').value === 'Robux';
  $('#robux-config').hidden = !robux;
  $('#robux-quantity').required = robux;
  $('#stock-panel').hidden = !$('#product-id').value || $('#delivery-mode').value !== 'automatic';
}
async function loadDelivery(id) {
  const config = await api(`/api/admin/products/${id}/delivery`);
  if (String(id) !== $('#product-id').value) return;
  $('#delivery-mode').value = config.mode;
  $('#robux-quantity').value = config.robux_quantity || '';
  $('#stock-count').textContent = `${config.available} unidade(s) disponível(is).`;
  $('#stock-list').innerHTML = config.stock.map(unit => `<div class="stock-unit"><span>Unidade #${esc(unit.id)}</span><div class="actions"><button class="btn ghost sm" type="button" data-edit-stock="${esc(unit.id)}">Editar</button><button class="btn ghost sm" type="button" data-remove-stock="${esc(unit.id)}">Remover</button></div></div>`).join('');
  deliveryVisibility();
}
$('#category').addEventListener('change', deliveryVisibility);
$('#delivery-mode').addEventListener('change', deliveryVisibility);
$('#add-stock').onclick = async () => {
  const id = $('#product-id').value;
  const editingStockId = $('#editing-stock-id')?.value || '';
  if (!id || !$('#stock-content').value.trim()) { $('#stock-status').textContent = 'Salve o produto e preencha o texto da unidade.'; return; }
  $('#add-stock').disabled = true;
  try {
    if (editingStockId) {
      await api(`/api/admin/products/${id}/stock/${editingStockId}`, 'PUT', {content: $('#stock-content').value});
      resetStockEditor();
      $('#stock-status').textContent = `Unidade #${editingStockId} atualizada com sucesso.`;
    } else {
      await api(`/api/admin/products/${id}/stock`, 'POST', {content:$('#stock-content').value});
      $('#stock-content').value = '';
      $('#stock-status').textContent = 'Unidade cadastrada. Pedidos pagos aguardando estoque são atendidos automaticamente.';
    }
    await loadDelivery(id);
  } catch (err) { $('#stock-status').textContent = err.message; }
  finally { $('#add-stock').disabled = false; }
};
$('#stock-list').onclick = async event => {
  const editButton = event.target.closest('[data-edit-stock]');
  if (editButton) {
    const id = $('#product-id').value;
    const stockId = editButton.dataset.editStock;
    try {
      const unit = await api(`/api/admin/products/${id}/stock/${stockId}`);
      if ($('#editing-stock-id')) $('#editing-stock-id').value = String(unit.id);
      $('#stock-content').value = unit.content || '';
      if ($('#stock-content-label')) $('#stock-content-label').textContent = `Editando unidade #${unit.id}`;
      $('#add-stock').textContent = `Salvar unidade #${unit.id}`;
      if ($('#cancel-edit-stock')) $('#cancel-edit-stock').hidden = false;
      $('#stock-content').focus();
      $('#stock-status').textContent = `Editando o conteúdo da unidade #${unit.id}.`;
    } catch (err) {
      $('#stock-status').textContent = err.message;
    }
    return;
  }
  const button = event.target.closest('[data-remove-stock]');
  if (!button || !confirm('Remover esta unidade ainda não entregue?')) return;
  const id = $('#product-id').value;
  try {
    await api(`/api/admin/products/${id}/stock/${button.dataset.removeStock}`, 'DELETE', {});
    if ($('#editing-stock-id')?.value === String(button.dataset.removeStock)) resetStockEditor();
    await loadDelivery(id);
  }
  catch (err) { $('#stock-status').textContent = err.message; }
};
deliveryVisibility();

function renderCategoryOptions() {
  const selected = $('#category-select').value;
  $('#category-select').innerHTML = categorySettings.map(c => `<option value="${esc(c.slug)}">${esc(c.title)}</option>`).join('');
  if (categorySettings.some(c => c.slug === selected)) $('#category-select').value = selected;
  const productCategory = $('#category').value;
  $('#category').innerHTML = categorySettings.map(c => `<option value="${esc(c.name)}">${esc(c.title)}</option>`).join('');
  $('#category').value = productCategory || CATEGORIES[0];
  showCategory();
}
function categoryPreview(source = categoryImage) {
  $('#category-preview').hidden = !source;
  if (source) $('#category-preview').src = source;
  else $('#category-preview').removeAttribute('src');
  $('#category-remove-photo').hidden = !source;
}
function showCategory() {
  const category = categorySettings.find(c => c.slug === $('#category-select').value);
  if (!category) return;
  categoryImage = category.image;
  $('#category-title').value = category.title;
  $('#category-photo').value = '';
  $('#category-message').textContent = '';
  categoryPreview();
}
$('#category-select').onchange = showCategory;
$('#category-remove-photo').onclick = () => { categoryImage = ''; $('#category-photo').value = ''; categoryPreview(); };
$('#category-photo').onchange = () => {
  const file = $('#category-photo').files[0];
  if (!file) return;
  if (file.size > 10000000) { $('#category-message').textContent = 'Máximo de 10 MB por imagem.'; $('#category-photo').value = ''; return; }
  const reader = new FileReader();
  const selected = $('#category-select').value;
  reader.onload = () => { if (selected === $('#category-select').value && $('#category-photo').files[0] === file) categoryPreview(reader.result); };
  reader.readAsDataURL(file);
};
$('#category-form').onsubmit = async event => {
  event.preventDefault();
  $('#category-save').disabled = true;
  $('#category-select').disabled = true;
  $('#category-message').textContent = 'Enviando imagem e salvando…';
  try {
    const slug = $('#category-select').value;
    const file = $('#category-photo').files[0];
    let photo = categoryImage;
    if (file) {
      photo = await uploadImageFile(file);
    }
    await api('/api/admin/categories/' + slug, 'PUT', {title:$('#category-title').value,image:photo});
    await load();
    $('#category-message').textContent = 'Categoria salva na vitrine.';
  } catch (error) { $('#category-message').textContent = error.message; }
  finally { $('#category-save').disabled = false; $('#category-select').disabled = false; }
};

function renderGames(){
 const selected=$('#product-game').value;$('#product-game').innerHTML='<option value="">Sem subcategoria</option>'+games.map(g=>`<option value="${g.id}">${esc(g.title)}</option>`).join('');$('#product-game').value=selected;
 $('#game-list').innerHTML=games.map(g=>`<div class="admin-row"><div><strong>${esc(g.title)}</strong><p>/roblox/${esc(g.slug)}</p></div><button class="btn ghost sm" data-edit-game="${g.id}">Editar</button><button class="btn ghost sm" data-delete-game="${g.id}">Excluir</button></div>`).join('')||'<p>Nenhum jogo cadastrado.</p>';
}
$('#game-clear').onclick=()=>{$('#game-form').reset();$('#game-id').value='';$('#game-status').textContent='';};
$('#game-list').onclick=async e=>{const edit=e.target.closest('[data-edit-game]'),del=e.target.closest('[data-delete-game]');if(edit){const game=games.find(g=>g.id===Number(edit.dataset.editGame));$('#game-form').reset();$('#game-id').value=game.id;$('#game-title').value=game.title;$('#game-title').focus();}if(del&&confirm('Excluir este jogo? Jogos com produtos vinculados não podem ser excluídos.')){try{await api('/api/admin/roblox/subcategories/'+del.dataset.deleteGame,'DELETE',{});await load();}catch(error){$('#game-status').textContent=error.message;}}};
$('#game-form').onsubmit=async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const id=$('#game-id').value,file=$('#game-image').files[0];let image=games.find(g=>g.id===Number(id))?.image||'';if($('#game-remove-image').checked)image='';if(file){image=await uploadImageFile(file);}await api('/api/admin/roblox/subcategories'+(id?'/'+id:''),id?'PUT':'POST',{title:$('#game-title').value,image});$('#game-form').reset();$('#game-id').value='';await load();$('#game-status').textContent='Jogo salvo.';}catch(error){$('#game-status').textContent=error.message;}finally{button.disabled=false;}};

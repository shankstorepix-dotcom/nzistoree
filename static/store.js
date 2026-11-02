'use strict';

/* ==========================================================
   Nzi Store · vitrine
   Os produtos vêm de /api/products (cadastrados no painel).
   Preencha os links abaixo para mostrar os botões de contato.
   Deixe '' para esconder o botão correspondente.
   ========================================================== */
const CONFIG = {
  supportUrl: '',    // atendimento (convite do Discord, WhatsApp, Telegram...)
  discordUrl: '',    // servidor da comunidade
  instagramUrl: ''   // perfil no Instagram
};

/* "name" precisa ser igual ao nome da categoria usado no painel e no server.py */
let CATEGORIES = [
  { slug: 'robux', name: 'Robux', title: 'Robux',
    desc: 'Robux para a sua conta Roblox. Escolha o valor, pague no Pix e combine a entrega pelo atendimento.' },
  { slug: 'painel', name: 'Painel (login)', title: 'Painéis',
    desc: 'Logins de painel com acesso por tempo determinado. Escolha o prazo, pague no Pix e acompanhe a entrega na página do pedido.' },
  { slug: 'streaming', name: 'Streamings', title: 'Streamings',
    desc: 'Contas e acessos de streaming. Veja os planos disponíveis, pague no Pix e peça pelo atendimento.' },
  { slug: 'contas-discord', name: 'Contas Discord', title: 'Contas Discord',
    desc: 'Contas Discord, incluindo contas com Nitro. Acompanhe a entrega na página do pedido depois do Pix.' },
  { slug: 'contas-roblox', name: 'Contas Roblox', title: 'Roblox',
    desc: 'Contas Roblox prontas para uso. Acompanhe a entrega na página do pedido depois do Pix.' }
];

const FAQ = [
  ['Quais formas de pagamento vocês aceitam?', 'Aceitamos apenas Pix. Pagamento por cartão e criptomoedas chega em breve.'],
  ['Quando eu recebo meu pedido?', 'Após o Pix confirmado, a entrega automática libera um arquivo na página do pedido. Para produtos manuais, acompanhe a entrega pelo chat do pedido.'],
  ['Posso compartilhar o login de um painel?', 'Não. O acesso é pessoal e o compartilhamento pode causar bloqueio. Guarde os dados e não repasse a ninguém.'],
  ['E se o produto não funcionar?', 'Abra o chat do seu pedido e descreva o problema. A equipe acompanha seu atendimento por lá.'],
  ['Vocês têm ligação com a Roblox ou o Discord?', 'Não. A Nzi Store é independente e não é afiliada, patrocinada ou aprovada pela Roblox nem pelo Discord. Os nomes são citados apenas para identificar os produtos.']
];

/* ---------- utilitários ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = cents => (cents / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const norm = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const ic = (name, size = 18) => {
  if (name === 'pix' || name === 'card') {
    const source = name === 'pix' ? 'pix.png' : 'cards.png';
    const width = name === 'card' ? size * 2.3 : size;
    return `<img class="ic payment-icon" src="/static/${source}?v=2" width="${width}" height="${size}" alt="" aria-hidden="true">`;
  }
  return `<svg class="ic" width="${size}" height="${size}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
};
const glyph = slug => `<svg class="glyph" viewBox="0 0 64 64" aria-hidden="true"><use href="#g-${slug === 'streaming' ? 'streamings' : slug}"/></svg>`;
const safeUrl = u => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : ''; } catch (e) { return ''; } };
const links = {
  support: safeUrl(CONFIG.supportUrl),
  discord: safeUrl(CONFIG.discordUrl),
  instagram: safeUrl(CONFIG.instagramUrl)
};
let subcategories=[];
const categoryUrl=c=>c.name==='Contas Roblox'?'/roblox':'/'+c.slug;
const catBySlug = slug => CATEGORIES.find(c => c.slug === slug);
const catByName = name => CATEGORIES.find(c => c.name === name) || CATEGORIES[0];

/* ---------- estado ---------- */
const state = { products: [], status: 'loading', sort: 'padrao', term: '', cart: loadCart(), selectedVariants: {} };

function loadCart() {
  try {
    const v = JSON.parse(localStorage.getItem('nzi-cart') || '{}');
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
  } catch (e) { return {}; }
}
function saveCart() { try { localStorage.setItem('nzi-cart', JSON.stringify(state.cart)); } catch (e) { /* sem armazenamento */ } }
const byId = id => state.products.find(p => p.id === Number(id));
function parseCartKey(rawKey) {
  const parts = String(rawKey).split(':');
  const pid = Number(parts[0]);
  const vid = parts[1] !== undefined ? Number(parts[1]) : null;
  const p = byId(pid);
  if (!p) return null;
  const minQ = Math.max(1, Number(p.min_quantity) || 1);
  const maxQ = Math.min(99, Math.max(minQ, Number(p.max_quantity) || 99));
  if (p.has_variants && Array.isArray(p.variants) && p.variants.length) {
    const v = (vid !== null ? p.variants.find(x => x.id === vid) : null) || p.variants[0];
    if (!v) return null;
    const stockCap = v.stock > 0 ? Math.min(maxQ, v.stock) : maxQ;
    return {
      key: `${p.id}:${v.id}`,
      product: p,
      variant: v,
      product_id: p.id,
      variant_id: v.id,
      name: `${p.name} — ${v.name}`,
      price: v.price,
      min_quantity: minQ,
      max_quantity: Math.max(minQ, stockCap)
    };
  }
  if (vid !== null) return null;
  return {
    key: String(p.id),
    product: p,
    variant: null,
    product_id: p.id,
    variant_id: null,
    name: p.name,
    price: p.price,
    min_quantity: minQ,
    max_quantity: maxQ
  };
}
function cleanCart() {
  const next = {};
  Object.keys(state.cart).forEach(rawKey => {
    const entry = parseCartKey(rawKey);
    const q = Math.floor(Number(state.cart[rawKey]));
    if (!entry || !(q > 0)) return;
    next[entry.key] = Math.max(entry.min_quantity, Math.min(q, entry.max_quantity));
  });
  state.cart = next;
  saveCart();
}
function countByCat() {
  const out = {};
  CATEGORIES.forEach(c => { out[c.name] = 0; });
  state.products.forEach(p => { if (p.category in out) out[p.category]++; });
  return out;
}

/* ---------- peças de interface ---------- */
function shortLabel(name) {
  const part = name.split(/\s[•·|–—-]\s/)[0].trim();
  const label = part.length <= 10 ? part : part.split(/\s+/)[0];
  return label.length > 12 ? label.slice(0, 11) + '…' : label;
}
function artHtml(p, open = true) {
  const attr = open ? ` data-open="${p.id}"` : '';
  if (p.image) return `<div class="art-box"${attr}><img class="art-img" src="${esc(p.image)}" alt="${esc(p.name)}" loading="lazy"></div>`;
  const label = shortLabel(p.name);
  return `<div class="art-box"${attr}><div class="art" aria-hidden="true">${glyph(catByName(p.category).slug)}<span class="art-label${label.length > 7 ? ' sm' : ''}">${esc(label)}</span><span class="art-wm"><img src="/static/nzi-logo.png?v=2" alt=""></span></div></div>`;
}
function cardHtml(p) {
  const isAuto = p.delivery_mode === 'automatic';
  const hasVariants = Boolean(p.has_variants && Array.isArray(p.variants) && p.variants.length);
  const firstVar = hasVariants ? p.variants[0] : null;
  const displayPrice = firstVar ? firstVar.price : p.price;
  const comparePrice = firstVar ? (firstVar.compare_price || p.compare_price || 0) : (p.compare_price || 0);
  const discountPct = comparePrice > displayPrice ? Math.round((1 - displayPrice / comparePrice) * 100) : 0;
  return `<article class="card product-card-v2">
    <div class="card-top-delivery ${isAuto ? 'is-auto' : 'is-manual'}">
      ${isAuto ? '<img class="delivery-thunder" src="/static/icon-thunder.png" alt="">' : ''}<span>${isAuto ? 'ENTREGA AUTOMÁTICA' : 'ENTREGA MANUAL'}</span>
    </div>
    ${artHtml(p)}
    <div class="card-body-v2">
      <h3><button class="card-title" type="button" data-open="${p.id}">${esc(p.name)}</button></h3>
      <div class="card-rating-row" aria-label="Avaliação 5.0 de 5">
        <span class="card-stars" aria-hidden="true">★★★★★</span>
        <span class="card-rating-val">5.0</span>
      </div>
      ${discountPct > 0 ? `<div class="card-compare-row">
        <s class="card-old-price">${money(comparePrice)}</s>
        <span class="card-discount-pill">${discountPct}% OFF</span>
      </div>` : `<div class="card-compare-row is-empty" aria-hidden="true"></div>`}
      <div class="card-price-main-row">
        <div class="card-price-stack">
          <span class="price">${money(displayPrice)}</span>
          <span class="card-pix-caption">À vista no Pix</span>
        </div>
        <span class="card-pix-box" title="Pagamento via Pix">${ic('pix', 18)}</span>
      </div>
      ${hasVariants
        ? `<div class="jp-row"><button class="jp-btn btn-glass-options" type="button" data-open="${p.id}"><span>Opções</span></button></div>`
        : `<div class="jp-row"><button class="jp-btn jp-primary card-buy-full" type="button" data-buy="${p.id}"><span>Comprar agora</span></button><button class="jp-btn jp-outline card-add-compact" type="button" data-add="${p.id}" title="Adicionar ao carrinho"><span>add to cart</span></button></div>`
      }
    </div>
  </article>`;
}
function skeletonGrid(n = 4) {
  return `<div class="grid" aria-hidden="true">${'<div class="skel"><i></i><i></i><i></i><i></i></div>'.repeat(n)}</div>`;
}
function tileHtml(c, counts, tag = 'a') {
  const n = counts ? counts[c.name] : null;
  const count = state.status !== 'ready' ? '' : n > 0
    ? `<span class="count">${n} ${n === 1 ? 'produto' : 'produtos'}</span>`
    : '<span class="count soon">Em breve</span>';
  const attrs = tag === 'a' ? ` href="${categoryUrl(c)}" aria-label="Ver ${esc(c.title)}"` : '';
  return `<${tag} class="tile cat-card"${attrs}><div class="category-inner">${c.image ? `<img class="category-photo" src="${esc(c.image)}" alt="" loading="lazy" draggable="false">` : glyph(c.slug)}<span class="category-base" aria-hidden="true"></span><span class="category-shine" aria-hidden="true"></span><div class="category-caption">${count}<h3>${esc(c.title)}</h3><span class="category-explore">Explorar <span aria-hidden="true">↗</span></span></div></div></${tag}>`;
}
function tilesHtml(list, counts, extra = '') {
  return `<div class="tiles ${list.length === 5 ? 'n5' : ''} ${extra}">${list.map(c => tileHtml(c, counts)).join('')}</div>`;
}
function faqHtml(list) {
  return list.map(f => `<details><summary>${esc(f[0])}</summary><p>${esc(f[1])}</p></details>`).join('');
}
function payHtml(id = '') {
  return `<section class="block"${id ? ` id="${id}"` : ''}><div class="pill-wrap"><h2 class="pill">Formas de pagamento</h2></div><div class="pay-grid">
    <div class="pay-item on"><span class="ic-box">${ic('pix', 26)}</span><div><b>Pix</b><span class="sub">Aceitamos apenas Pix</span></div><span class="st">Disponível</span></div>
    <div class="pay-item pay-item-card"><span class="ic-box">${ic('card', 26)}</span><div><b>Cartão</b><span class="sub">Crédito e débito</span></div><span class="st">Em breve</span></div>
    <div class="pay-item"><span class="ic-box">${ic('coin', 26)}</span><div><b>Criptomoedas</b><span class="sub">Pagamento em cripto</span></div><span class="st">Em breve</span></div>
  </div></section>`;
}
function supportBand() {
  if (!links.support) return '';
  return `<section class="block" id="atendimento"><div class="band"><div><h2>Ficou com dúvida antes de comprar?</h2><p>Fale com a equipe antes de fechar o pedido.</p></div>
    <a class="btn" href="${esc(links.support)}" target="_blank" rel="noopener">Abrir atendimento</a></div></section>`;
}
function emptyState(title, text, action = '') {
  return `<div class="state">${glyph('robux')}<h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;
}
function errorState() {
  return `<div class="state"><h3>Não foi possível carregar os produtos</h3><p>Confira se a loja está em execução e tente de novo.</p><button class="btn" type="button" data-retry>Tentar novamente</button></div>`;
}

/* Banner uses local category artwork, real category routes and one disposable timer. */
function heroHtml() {
  const slides = CATEGORIES;
  return `<section class="hero showcase" aria-label="Destaques da loja">
    <div class="hero-copy"><span class="hero-badge">HALLOWEEN NZI</span><h1>Gostosuras ou<br><em>upgrades?</em></h1>
      <p class="lead">Explore todas as categorias e encontre o que combina com você.</p>
      <div class="hero-actions"><a class="btn catalog-cta" href="#categorias">Explorar catálogo</a><a class="btn ghost" href="/pedidos">Meus pedidos</a></div>
    </div>
    <div class="banner" role="region" aria-roledescription="carrossel" aria-label="Categorias em destaque">
      <div class="banner-window"><div class="banner-track">${slides.map((c,i)=>`<a class="banner-slide banner-${c.slug}" href="${categoryUrl(c)}" aria-label="Ver ${esc(c.title)}" aria-hidden="${i!==0}" tabindex="${i===0?0:-1}">${c.image?`<img src="${esc(c.image)}" alt="" draggable="false">`:glyph(c.slug)}<div class="banner-caption"><small>EXPLORE A CATEGORIA</small><h2>${esc(c.title)}</h2><span>Ver produtos ↗</span></div></a>`).join('')}</div></div>
      <div class="banner-progress"><span></span></div>
      <div class="banner-controls"><button type="button" class="banner-prev" aria-label="Banner anterior">←</button><div class="banner-dots">${slides.map((c,i)=>`<button type="button" data-slide="${i}" aria-label="Mostrar banner ${esc(c.title)}" aria-pressed="${i===0}"></button>`).join('')}</div><button type="button" class="banner-next" aria-label="Próximo banner">→</button><button type="button" class="banner-pause" aria-label="Pausar banners">Ⅱ</button></div>
    </div></section>`;
}
let disposeHero = () => {};
function initHero() {
  disposeHero();
  const hero = $('.showcase');
  if (!hero) return;
  const banner=hero.querySelector('.banner'), track=hero.querySelector('.banner-track');
  const slides=[...hero.querySelectorAll('.banner-slide')], dots=[...hero.querySelectorAll('[data-slide]')];
  const progress=hero.querySelector('.banner-progress span'), pause=hero.querySelector('.banner-pause');
  const motion=window.matchMedia('(prefers-reduced-motion: reduce)');
  let index=0, timer, paused=motion.matches, hover=false, touchX=null;
  function schedule() {
    clearTimeout(timer);
    progress.classList.remove('running');
    if (paused || hover || document.hidden || hero.contains(document.activeElement)) return;
    void progress.offsetWidth;
    progress.classList.add('running');
    timer=setTimeout(()=>show(index+1),5000);
  }
  function show(next) {
    index=(next+slides.length)%slides.length;
    track.style.transform=`translateX(-${index*100}%)`;
    slides.forEach((slide,i)=>{ slide.setAttribute('aria-hidden',String(i!==index)); slide.tabIndex=i===index?0:-1; });
    dots.forEach((dot,i)=>dot.setAttribute('aria-pressed',String(i===index)));
    schedule();
  }
  function pauseLabel() { pause.textContent=paused?'▶':'Ⅱ'; pause.setAttribute('aria-label',paused?'Reproduzir banners':'Pausar banners'); }
  hero.querySelector('.banner-prev').onclick=()=>show(index-1);
  hero.querySelector('.banner-next').onclick=()=>show(index+1);
  dots.forEach((dot,i)=>dot.onclick=()=>show(i));
  pause.onclick=()=>{paused=!paused;pauseLabel();schedule();};
  hero.onmouseenter=()=>{hover=true;schedule();}; hero.onmouseleave=()=>{hover=false;schedule();};
  hero.onfocusin=schedule; hero.onfocusout=()=>queueMicrotask(schedule);
  banner.addEventListener('touchstart',e=>{touchX=e.changedTouches[0].clientX;},{passive:true});
  banner.addEventListener('touchend',e=>{if(touchX!==null){const dx=e.changedTouches[0].clientX-touchX;if(Math.abs(dx)>50)show(index+(dx<0?1:-1));}touchX=null;},{passive:true});
  banner.addEventListener('touchcancel',()=>{touchX=null;});
  const onMotion=()=>{paused=motion.matches;pauseLabel();schedule();};
  document.addEventListener('visibilitychange',schedule); motion.addEventListener('change',onMotion);
  disposeHero=()=>{clearTimeout(timer);document.removeEventListener('visibilitychange',schedule);motion.removeEventListener('change',onMotion);};
  pauseLabel();show(0);
}

/* ---------- páginas ---------- */
function homeView() {
  const counts = countByCat();
  return `<div class="view">
    <a class="home-banner" href="#categorias" aria-label="Nzi Store: explore nossas categorias"><img src="/static/home-banner.png" width="2048" height="554" alt="Nzi Store — a melhor loja da web. Compre aqui!" fetchpriority="high" decoding="async"></a>
    ${heroHtml()}
    <section class="block" id="categorias"><div class="pill-wrap"><h2 class="pill">${ic('grid', 18)} Categorias disponíveis</h2></div><div class="category-showcase">${CATEGORIES.map(c => tileHtml(c, counts)).join('')}</div></section>
    ${payHtml('formas-de-pagamento')}
    <section class="block" id="como-funciona"><h2 class="title">Como funciona</h2><div class="steps">
      <div class="step"><div class="n">1</div><h3>Escolha o item</h3><p>Escolha uma categoria e selecione o produto que você quer.</p></div>
      <div class="step"><div class="n">2</div><h3>Pague com Pix</h3><p>Finalize o pedido no carrinho e pague no Pix.</p></div>
      <div class="step"><div class="n">3</div><h3>Receba</h3><p>Com o Pix confirmado, abra o pedido para baixar a entrega ou falar com o suporte.</p></div>
    </div></section>
    <section class="block" id="duvidas"><h2 class="title">Dúvidas frequentes</h2><div class="faq">${faqHtml(FAQ)}</div></section>
    ${supportBand()}
  </div>`;
}

function sorted(list) {
  const l = list.slice();
  if (state.sort === 'menor') l.sort((a, b) => a.price - b.price);
  else if (state.sort === 'maior') l.sort((a, b) => b.price - a.price);
  else if (state.sort === 'nome') l.sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'));
  return l;
}
function robloxGamesView(c){
  const legacy=state.products.filter(p=>p.category===c.name&&!p.subcategory_id);
  const games=subcategories.map(game=>`<a class="tile cat-card" href="/roblox/${esc(game.slug)}"><div class="category-inner">${game.image?`<img class="category-photo" src="${esc(game.image)}" alt="" loading="lazy">`:glyph('contas-roblox')}<span class="category-shine"></span><div class="category-caption"><small>${state.products.filter(p=>p.subcategory_id===game.id).length} produtos</small><h3>${esc(game.title)}</h3><span class="category-explore">Explorar ↗</span></div></div></a>`).join('');
  return `<div class="view"><nav class="crumbs"><a href="/">Início</a><span>/</span><span>Roblox</span></nav><h1>Roblox</h1><p>Escolha um jogo para encontrar seus produtos.</p>${state.status==='loading'?skeletonGrid(3):state.status==='error'?errorState():games?`<div class="category-showcase">${games}</div>`:'<p class="empty">Os jogos estarão disponíveis em breve.</p>'}${legacy.length?`<section class="block"><h2>Outros produtos Roblox</h2><div class="grid">${legacy.map(cardHtml).join('')}</div></section>`:''}</div>`;
}
function categoryView(c,game=null) {
  if(c.name==='Contas Roblox'&&!game)return robloxGamesView(c);
  const counts = countByCat();
  const list = state.products.filter(p => p.category === c.name && (!game||p.subcategory_id===game.id));
  const others = CATEGORIES.filter(x => x.slug !== c.slug);
  if(game)c={...c,title:game.title,image:game.image,desc:'Produtos de '+game.title+' na Nzi Store.'};
  let body;
  if (state.status === 'loading') body = skeletonGrid(4);
  else if (state.status === 'error') body = errorState();
  else if (!list.length) body = emptyState('Em breve nesta categoria', 'Ainda não há produtos aqui. Veja as outras categorias ou fale com o atendimento.', '<a class="btn" href="#inicio">Voltar ao início</a>');
  else body = `<div class="grid" id="cat-grid">${sorted(list).map(cardHtml).join('')}</div>`;
  const n = list.length;
  const toolbar = state.status === 'ready' && n ? `<div class="toolbar"><span class="count">${n} ${n === 1 ? 'produto' : 'produtos'}</span>
    <label for="sort">Ordenar por <select id="sort">${[['padrao', 'Mais recentes'], ['menor', 'Menor preço'], ['maior', 'Maior preço'], ['nome', 'Nome']].map(o => `<option value="${o[0]}"${state.sort === o[0] ? ' selected' : ''}>${o[1]}</option>`).join('')}</select></label></div>` : '<div style="height:28px"></div>';
  return `<div class="view">
    <nav class="crumbs" aria-label="Você está em"><a href="#inicio">Início</a><span aria-hidden="true">/</span><span>${esc(c.title)}</span></nav>
    <div class="cat-hero"><div><h1>${esc(c.title)}</h1><p>${esc(c.desc)}</p>
      </div>
      ${tileHtml(c, counts, 'div')}</div>
    ${toolbar}
    ${body}
    ${payHtml()}
    <section class="block"><h2 class="title">Dúvidas sobre pagamento e entrega</h2><div class="faq">${faqHtml(FAQ.slice(0, 4))}</div></section>
    <section class="block"><div class="pill-wrap"><h2 class="pill">Outras categorias</h2></div>${tilesHtml(others, counts, 'compact')}</section>
    ${supportBand()}
  </div>`;
}
function searchView() {
  const raw = $('#search').value.trim();
  const list = state.term ? state.products.filter(p => norm(`${p.name} ${p.description} ${p.category} ${catByName(p.category).title}`).includes(state.term)) : [];
  let body;
  if (!state.term) body = emptyState('Buscar produto', 'Digite o nome de um produto na barra de busca.');
  else if (state.status === 'loading') body = skeletonGrid(4);
  else if (state.status === 'error') body = errorState();
  else if (!list.length) body = emptyState('Nenhum produto encontrado', 'Tente outro nome ou veja as categorias.', '<a class="btn" href="#categorias">Ver categorias</a>');
  else body = `<div class="toolbar" style="margin-top:8px"><span class="count">${list.length} ${list.length === 1 ? 'produto encontrado' : 'produtos encontrados'}</span></div><div class="grid">${list.map(cardHtml).join('')}</div>`;
  return `<div class="view"><nav class="crumbs" aria-label="Você está em"><a href="#inicio">Início</a><span aria-hidden="true">/</span><span>Busca</span></nav>
    <h1 class="page-title">${state.term ? `Resultados para “${esc(raw)}”` : 'Buscar produto'}</h1>${body}</div>`;
}

/* ---------- navegação e rodapé ---------- */
function renderChrome() {
  const catLinks = CATEGORIES.map(c => `<a href="${categoryUrl(c)}">${esc(c.title)}</a>`).join('');
  const social = (url, icon, label) => url ? `<a class="icon-link hide-md" href="${esc(url)}" target="_blank" rel="noopener" aria-label="${label}">${ic(icon, 20)}</a>` : '';
  $('#nav').innerHTML = `<a href="#inicio">Início</a>
    <div class="dd"><button type="button" data-dd="dd-cat" aria-expanded="false" aria-controls="dd-cat">Categorias ${ic('chev', 12)}</button><div class="dd-menu" id="dd-cat" hidden>${catLinks}</div></div>
    <div class="dd"><button type="button" data-dd="dd-about" aria-expanded="false" aria-controls="dd-about">Sobre nós ${ic('chev', 12)}</button><div class="dd-menu" id="dd-about" hidden>
      <a href="#como-funciona">Como funciona</a><a href="#formas-de-pagamento">Formas de pagamento</a><a href="#duvidas">Dúvidas frequentes</a></div></div>
    ${links.support ? '<a href="#atendimento">Atendimento</a>' : ''}
    ${social(links.instagram, 'insta', 'Instagram')}${social(links.discord, 'discord', 'Servidor no Discord')}`;
  const sidebarItems = [
    `<a class="side-link side-home" href="/" data-side-route="inicio"><span class="side-icon">${ic('grid', 18)}</span><span><b>Início</b><small>Visão geral da loja</small></span></a>`,
    ...CATEGORIES.map(c => `<a class="side-link" href="${categoryUrl(c)}" data-side-route="${c.slug}"><span class="side-icon">${glyph(c.slug)}</span><span><b>${esc(c.title)}</b><small>Ver produtos</small></span></a>`),
    `<a class="side-link" href="/conta"><span class="side-icon">${ic('headset',18)}</span><span><b>Minha conta</b><small>Acesso e cadastro</small></span></a>`
  ];
  $('#sidebar-nav').innerHTML = sidebarItems.join('');
  $('#sidebar-community').innerHTML = `${links.discord ? `<a href="${esc(links.discord)}" target="_blank" rel="noopener">${ic('discord',16)} Discord</a>` : '<span>Novidades em breve</span>'}`;
  $('#menu').innerHTML = `<a href="#inicio">Início</a><small>Categorias</small>${catLinks}<small>Loja</small>
    <a href="#como-funciona">Como funciona</a><a href="#formas-de-pagamento">Formas de pagamento</a><a href="#duvidas">Dúvidas frequentes</a>${links.support ? '<a href="#atendimento">Atendimento</a>' : ''}`;
  $('#foot').innerHTML = `<div class="foot-in">
    <div><span class="nzi-logo-frame"><img src="/static/nzi-logo.png?v=2" alt="Nzi Store"></span><span>© ${new Date().getFullYear()} Nzi Store. Todos os direitos reservados.</span>
</div>
    <div><h4>Categorias</h4>${catLinks}</div>
    <div><h4>Institucional</h4><a href="/terms">Termos de Uso e Condições</a><a href="/pedidos">Meus pedidos</a></div>
    <div><h4>Pagamento</h4><span>${ic('pix', 16)}Somente Pix</span><span>Em breve: cartão e criptomoedas</span></div></div>`;
  const fab = $('#fab');
  if (links.support) { fab.href = links.support; fab.hidden = false; }
}

/* ---------- rotas por hash ---------- */
const SECTIONS = ['categorias', 'formas-de-pagamento', 'como-funciona', 'duvidas', 'atendimento'];
function currentRoute() {
  let h = '';
  try { h = decodeURIComponent((location.hash || '').slice(1)); } catch (e) { h = ''; }
  if (h) return h;
  const path = location.pathname.replace(/^\/+|\/+$/g, '').toLowerCase();
  return path === 'checkout' || path === 'terms' || /^produto\/\d+$/.test(path) || /^roblox(?:\/[a-z0-9-]+)?$/.test(path) || catBySlug(path) ? path : 'inicio';
}
function render() {
  const h = currentRoute();
  const c = catBySlug(h);
  const view = $('#app');
  let html, title = 'Nzi Store';
  if (h === 'checkout') { html = checkoutView(); title = 'Checkout · Nzi Store'; }
  else if (h === 'terms') { html = termsView(); title = 'Termos de Uso e Condições de Compra · Nzi Store'; }
  else if (/^produto\/\d+$/.test(h)) { const product=byId(h.split('/')[1]); html=productView(product); title=product?`${product.name} · Nzi Store`:'Produto · Nzi Store'; }
  else if(h==='roblox'||h.startsWith('roblox/')){const game=subcategories.find(g=>g.slug===h.split('/')[1]);html=h==='roblox'?robloxGamesView(catBySlug('contas-roblox')):game?categoryView(catBySlug('contas-roblox'),game):state.status==='loading'?skeletonGrid(3):emptyState('Jogo não encontrado','Volte à categoria Roblox.','<a href="/roblox">Ver jogos</a>');title=(game?.title||'Roblox')+' · Nzi Store';}
  else if (c) { html = categoryView(c); title = `${c.title} · Nzi Store`; }
  else if (h === 'busca') { html = searchView(); title = 'Busca · Nzi Store'; }
  else html = homeView();
  const keepSearch = document.activeElement === $('#search');
  view.innerHTML = html;
  initHero();
  if (h === 'checkout') initCheckoutEvents();
  $$('.side-link').forEach(link => { const active = link.dataset.sideRoute === ((h==='roblox'||h.startsWith('roblox/'))?'contas-roblox':h); link.classList.toggle('active', active); if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current'); });
  view.setAttribute('aria-busy', String(state.status === 'loading'));
  document.title = title;
  if (keepSearch) $('#search').focus();
}
function route() {
  const h = currentRoute();
  setDd(null); setMenu(false);
  if (!catBySlug(h) && h !== 'busca' && $('#search').value) { $('#search').value = ''; state.term = ''; }
  render();
  const el = SECTIONS.includes(h) ? document.getElementById(h) : null;
  if (el) el.scrollIntoView({ behavior: 'instant', block: 'start' });
  else window.scrollTo({ top: 0, behavior: 'instant' });
}

/* ---------- menus ---------- */
function setMenu(open) {
  const sidebar=$('#store-sidebar');
  const wasOpen=document.body.classList.contains('sidebar-open');
  const focusInside=sidebar.contains(document.activeElement);
  document.body.classList.toggle('sidebar-open',open);
  sidebar.inert=!open;sidebar.setAttribute('aria-hidden',String(!open));
  $('#sidebar-backdrop').hidden=!open;
  $('#burger').setAttribute('aria-expanded',String(open));
  $('#burger').setAttribute('aria-label',open?'Ocultar menu':'Abrir menu');
  $('#menu').hidden=true;
  if(open)requestAnimationFrame(()=>{if(document.body.classList.contains('sidebar-open'))$('#sidebar-close').focus();});
  else if(wasOpen&&focusInside)$('#burger').focus();
}
$('#sidebar-backdrop').onclick=()=>setMenu(false);
$('#sidebar-close').onclick=()=>setMenu(false);
$('#store-sidebar').addEventListener('keydown',e=>{
  if(e.key!=='Tab')return;
  const controls=[...$('#store-sidebar').querySelectorAll('a[href],button')];
  if(e.shiftKey&&document.activeElement===controls[0]){e.preventDefault();controls.at(-1).focus();}
  else if(!e.shiftKey&&document.activeElement===controls.at(-1)){e.preventDefault();controls[0].focus();}
});
function setDd(id) {
  $$('.dd-menu').forEach(m => { m.hidden = !(id && m.id === id && m.hidden); });
  $$('[data-dd]').forEach(b => b.setAttribute('aria-expanded', String(!$('#' + b.dataset.dd).hidden)));
}

/* ---------- carrinho ---------- */
function cartIds() { return Object.keys(state.cart).filter(k => parseCartKey(k)); }
function cartCount() {
  return state.status === 'ready' ? cartIds().reduce((n, k) => n + state.cart[k], 0)
    : Object.keys(state.cart).reduce((n, k) => n + (Number(state.cart[k]) || 0), 0);
}
let activeCoupon = '', couponPercent=0;
async function couponConfig(){const r=await fetch('/api/coupon',{cache:'no-store'});if(!r.ok)throw new Error('Não foi possível validar o cupom.');return (await r.json()).coupon;}
couponConfig().then(c=>{let saved='';try{saved=sessionStorage.getItem('nzi-coupon');}catch{}if(c&&saved===c.code){activeCoupon=c.code;couponPercent=c.percent;renderCart();}}).catch(()=>{});
function cartTotal() {
  return cartIds().reduce((t, k) => {
    const entry = parseCartKey(k);
    if (!entry) return t;
    const price = entry.price;
    return t + state.cart[k] * (price - (activeCoupon ? Math.floor(price * couponPercent / 100) : 0));
  }, 0);
}
async function applyCoupon(value) {
  const code=value.trim().toUpperCase();
  let config;try{config=await couponConfig();}catch(e){$('#coupon-status').textContent=e.message;return false;}
  if(code && (!config||code!==config.code)) { $('#coupon-status').textContent='Cupom inválido.'; return false; }
  activeCoupon=code;couponPercent=config?.percent||0;
  try { sessionStorage.setItem('nzi-coupon',code); } catch {}
  renderCart(); if(code){window.dispatchEvent(new Event('nzi:celebrate')); if($('#chk-coupon-msg')) $('#chk-coupon-msg').textContent=`Boa! Cupom ${code} aplicado: você ganhou ${couponPercent}% de desconto!`;} return true;
}
$('#coupon-form').onsubmit=e=>{e.preventDefault();applyCoupon($('#coupon-code').value);};
$('#coupon-remove').onclick=()=>applyCoupon('');
window.addEventListener('nzi:coupon',e=>applyCoupon(e.detail.code));
let robloxUser = null;
let robloxConfirmed = false;
let robloxRequest = 0;
const needsRoblox = () => cartIds().some(k => parseCartKey(k)?.product.category === 'Robux');
function renderCart() {
  const ids = cartIds();
  $('#coupon-code').value=activeCoupon;
  $('#coupon-remove').hidden=!activeCoupon;
  $('#coupon-status').textContent=activeCoupon?`Boa! ${activeCoupon} ativado — aproveite ${couponPercent}% de desconto!`:'';
  $('#cart-count').textContent = cartCount();
  if (state.status === 'loading') { $('#cart-foot').hidden = true; $('#cart-body').innerHTML = '<p class="empty">Carregando…</p>'; return; }
  $('#cart-foot').hidden = !ids.length;
  if (!ids.length) { $('#cart-body').innerHTML = '<p class="empty">Seu carrinho está vazio. Escolha um item no catálogo.</p>'; return; }
  $('#cart-body').innerHTML = ids.map(k => {
    const entry = parseCartKey(k), q = state.cart[k];
    if (!entry) return '';
    return `<div class="line">${artHtml(entry.product, false)}<b>${esc(entry.name)}</b><span class="lp">${money(entry.price * q)}</span>
      <div class="row2"><div class="qty"><button type="button" data-dec="${esc(entry.key)}" aria-label="Diminuir quantidade">−</button><span aria-live="polite">${q}</span><button type="button" data-inc="${esc(entry.key)}" aria-label="Aumentar quantidade">+</button></div>
      <button class="rm" type="button" data-rm="${esc(entry.key)}">Remover</button></div></div>`;
  }).join('');
  $('#total').textContent = money(cartTotal());
}
function addItemToCart(rawKey, addCount = 1) {
  const entry = parseCartKey(rawKey);
  if (!entry) return null;
  const current = Number(state.cart[entry.key]) || 0;
  const base = current === 0 ? Math.max(entry.min_quantity, addCount) : current + addCount;
  state.cart[entry.key] = Math.max(entry.min_quantity, Math.min(base, entry.max_quantity));
  saveCart();
  renderCart();
  return entry;
}
function changeQty(key, d) {
  const entry = parseCartKey(key);
  if (!entry) { delete state.cart[key]; saveCart(); renderCart(); if (currentRoute() === 'checkout') render(); return; }
  const q = (Number(state.cart[entry.key]) || 0) + d;
  if (q < entry.min_quantity) delete state.cart[entry.key];
  else state.cart[entry.key] = Math.min(q, entry.max_quantity);
  saveCart(); renderCart();
  if (currentRoute() === 'checkout') render();
}
let lastFocus = null;
function openCart() {
  lastFocus = document.activeElement;
  $('#scrim').hidden = false;
  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  document.body.classList.add('lock');
  $('#close-cart').focus();
}
function closeCart() {
  $('#scrim').hidden = true;
  $('#drawer').classList.remove('open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  document.body.classList.remove('lock');
  if (lastFocus && lastFocus.focus) lastFocus.focus();
}

/* ---------- detalhes do produto ---------- */
function cartSubtotal() {
  return cartIds().reduce((t, k) => {
    const entry = parseCartKey(k);
    return entry ? t + state.cart[k] * entry.price : t;
  }, 0);
}
function cartDiscount() {
  return Math.max(0, cartSubtotal() - cartTotal());
}
function openCheckoutPage() {
  closeCart();
  if ($('#detail')?.open) $('#detail').close();
  history.pushState({}, '', '/checkout');
  route();
}
let checkoutContactDraft = { email: '', emailConfirmation: '', robloxQuery: '', terms: false };
try {
  const savedPayer = JSON.parse(sessionStorage.getItem('nzi-payer-info') || 'null');
  if (savedPayer && typeof savedPayer === 'object') {
    checkoutContactDraft.email = savedPayer.email || '';
  }
} catch {}
fetch('/api/auth/me', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).then(me => {
  if (me && me.email && !checkoutContactDraft.email) {
    checkoutContactDraft.email = me.email;
    const emailEl = $('#chk-payer-email');
    if (emailEl && !emailEl.value) emailEl.value = me.email;
  }
}).catch(() => {});

function checkoutView() {
  if (state.status === 'loading') return '<div class="view">' + skeletonGrid(2) + '</div>';
  const ids = cartIds();
  if (!ids.length) {
    return `<div class="view"><nav class="crumbs"><a href="/">Início</a><span>/</span><span>Checkout</span></nav>${emptyState('Seu carrinho está vazio', 'Adicione pelo menos um produto para prosseguir para o pagamento.', '<a class="btn" href="/">Voltar para a loja</a>')}</div>`;
  }
  const subtotal = cartSubtotal();
  const discount = cartDiscount();
  const total = cartTotal();
  const pts = Math.max(1, Math.round(total / 10));
  const cartProductIds = new Set(ids.map(k => parseCartKey(k)?.product_id).filter(Boolean));
  const upsells = state.products.filter(p => !cartProductIds.has(p.id) && !p.has_variants).slice(0, 2);

  const itemsHtml = ids.map(k => {
    const entry = parseCartKey(k);
    if (!entry) return '';
    const q = state.cart[k];
    const p = entry.product;
    const cat = catByName(p.category);
    const thumb = p.image
      ? `<img class="chk-item-thumb" src="${esc(p.image)}" alt="" loading="lazy">`
      : `<span class="chk-item-thumb chk-item-glyph" aria-hidden="true">${glyph(cat.slug)}</span>`;
    return `<div class="chk-item-card">
      <div class="chk-item-top">
        ${thumb}
        <div class="chk-item-meta">
          <strong>${esc(entry.name)}</strong>
          <span>${money(entry.price)} cada</span>
        </div>
      </div>
      <div class="chk-item-bottom">
        <div class="chk-qty-controls">
          <button type="button" class="chk-circle-btn" data-dec="${esc(entry.key)}" aria-label="Diminuir">−</button>
          <span class="chk-qty-box" aria-live="polite">${q}</span>
          <button type="button" class="chk-circle-btn" data-inc="${esc(entry.key)}" aria-label="Aumentar">+</button>
          <button type="button" class="chk-circle-btn is-danger" data-rm="${esc(entry.key)}" aria-label="Remover item">×</button>
        </div>
        <strong class="chk-item-total">${money(entry.price * q)}</strong>
      </div>
    </div>`;
  }).join('');

  const upsellHtml = upsells.length ? `<div class="chk-upsell-box">
    <div class="chk-upsell-head">
      <span class="chk-upsell-spark" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 3 1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3L12 3Z"/></svg>
      </span>
      <div>
        <h4>Combina com o seu pedido</h4>
        <p>Adicione agora e some mais pontos na mesma compra.</p>
      </div>
    </div>
    <div class="chk-upsell-list">
      ${upsells.map(u => {
        const cat = catByName(u.category);
        const uDisc = u.compare_price && u.compare_price > u.price ? Math.round((1 - u.price / u.compare_price) * 100) : 0;
        const uPts = Math.max(1, Math.round(u.price / 10));
        const thumb = u.image
          ? `<img class="chk-upsell-thumb" src="${esc(u.image)}" alt="" loading="lazy">`
          : `<span class="chk-upsell-thumb chk-item-glyph" aria-hidden="true">${glyph(cat.slug)}</span>`;
        return `<div class="chk-upsell-row">
          ${thumb}
          <div class="chk-upsell-info">
            <strong class="chk-upsell-title">${esc(u.name)}</strong>
            <div class="chk-upsell-prices">
              <b class="chk-upsell-price">${money(u.price)}</b>
              ${uDisc > 0 ? `<s class="chk-upsell-old">${money(u.compare_price)}</s><span class="chk-upsell-disc">-${uDisc}%</span>` : ''}
            </div>
            <span class="chk-upsell-pts">+${uPts.toLocaleString('pt-BR')} pts</span>
          </div>
          <button type="button" class="chk-upsell-add" data-upsell-add="${u.id}">+ Adicionar</button>
        </div>`;
      }).join('')}
    </div>
  </div>` : '';

  const robloxLookupHtml = needsRoblox() ? `<div class="chk-roblox-block">
    <div class="chk-search-input-wrap">
      <svg class="chk-search-ic" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
      <input id="chk-roblox-input" type="text" autocomplete="off" maxlength="20" placeholder="Seu @username do Roblox (obrigatório para Robux)" value="${esc(checkoutContactDraft.robloxQuery || robloxUser?.username || '')}">
      <button type="button" class="chk-roblox-lookup-btn" id="chk-roblox-lookup">Buscar</button>
    </div>
    <p id="chk-roblox-msg" class="chk-roblox-msg" role="status"></p>
    <div id="chk-roblox-result" class="chk-roblox-card"${robloxUser ? '' : ' hidden'}>
      <img id="chk-roblox-avatar" class="chk-roblox-avatar" src="${esc(robloxUser?.avatar || '/static/nzi-logo.png')}" alt="">
      <div class="chk-roblox-meta">
        <strong id="chk-roblox-display">${esc(robloxUser?.displayName || '')}</strong>
        <span id="chk-roblox-handle">${robloxUser ? '@' + esc(robloxUser.username) : ''}</span>
      </div>
      <button type="button" id="chk-roblox-select" class="chk-roblox-select-btn${robloxConfirmed ? ' is-selected' : ''}">${robloxConfirmed ? 'Selecionado' : 'Selecionar'}</button>
    </div>
  </div>` : '';

  return `<div class="view chk-view">
    <nav class="crumbs" aria-label="Você está em"><a href="/">Início</a><span>/</span><span>Checkout</span></nav>
    <div class="checkout-page-grid">
      <div class="checkout-col-left">
        <section class="chk-panel">
          <header class="chk-sec-head"><span class="chk-sec-dot" aria-hidden="true"></span><h2>Formas de pagamento</h2></header>
          <div class="chk-pay-method is-selected" role="radio" aria-checked="true" tabindex="0">
            <span class="chk-pay-icon">${ic('pix', 22)}</span>
            <div class="chk-pay-copy">
              <div class="chk-pay-title-row">
                <strong>Pix</strong>
                <span class="chk-fast-pill">Mais rápido</span>
              </div>
              <span>Aprovação imediata</span>
            </div>
          </div>
        </section>

        <section class="chk-panel">
          <header class="chk-sec-head"><span class="chk-sec-dot" aria-hidden="true"></span><h2>Informações de contato</h2></header>
          <div class="chk-contact-fields">
            <input id="chk-payer-email" class="chk-input" type="email" maxlength="254" placeholder="seuemail@exemplo.com" aria-label="E-mail" value="${esc(checkoutContactDraft.email)}" required>
            <input id="chk-payer-email-confirm" class="chk-input" type="email" maxlength="254" placeholder="Confirme seu e-mail" aria-label="Confirme seu e-mail" value="${esc(checkoutContactDraft.emailConfirmation)}" required>
            ${robloxLookupHtml}
          </div>
        </section>

        <label class="chk-terms-row">
          <input id="chk-terms" type="checkbox"${checkoutContactDraft.terms ? ' checked' : ''}>
          <span>Eu aceito os <a href="/terms" target="_blank" rel="noopener"><b>termos e condições</b></a> desta compra.</span>
        </label>

        <button type="button" id="chk-pay-btn" class="chk-pay-cta">Pagar &nbsp;${money(total)}</button>
        <p id="chk-status" class="msg" role="status"></p>
        <a id="chk-login-btn" class="btn ghost block" href="/conta" hidden>Entrar ou criar conta para continuar</a>
      </div>

      <div class="checkout-col-right">
        <section class="chk-panel chk-summary-panel">
          <header class="chk-sec-head"><span class="chk-sec-dot" aria-hidden="true"></span><h2>Resumo do pedido</h2><span class="checkout-secure"><img src="/static/icon-secure.png" alt="">Pagamento seguro</span></header>
          <div class="chk-items-list">${itemsHtml}</div>
          ${upsellHtml}
          <form id="chk-coupon-form" class="chk-coupon-bar">
            <input id="chk-coupon-input" class="chk-input" type="text" maxlength="32" placeholder="Cupom de desconto" value="${esc(activeCoupon)}">
            <button type="submit" class="chk-coupon-btn">
              <img class="coupon-apply-icon" src="/static/icon-coupon.png" alt=""><span>Aplicar cupom</span>
            </button>
          </form>
          <p id="chk-coupon-msg" class="chk-coupon-msg" role="status">${activeCoupon ? `${esc(activeCoupon)} aplicado (-${couponPercent}%)` : ''}</p>
          <div class="chk-totals-box">
            <div class="chk-tot-line"><span>Subtotal</span><span>${money(subtotal)}</span></div>
            <div class="chk-tot-line"><span>Descontos</span><span>${money(discount)}</span></div>
            <div class="chk-tot-divider"></div>
            <div class="chk-tot-main"><strong>Total</strong><strong>${money(total)}</strong></div>
            <div class="chk-tot-pts">
              <span>Você ganha</span>
              <b>+${pts.toLocaleString('pt-BR')} pts</b>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>`;
}

function initCheckoutEvents() {
  const confirmInput = $('#chk-payer-email-confirm');
  const emailInput = $('#chk-payer-email');
  const termsInput = $('#chk-terms');
  const robloxInput = $('#chk-roblox-input');
  const lookupBtn = $('#chk-roblox-lookup');
  const selectBtn = $('#chk-roblox-select');
  const couponForm = $('#chk-coupon-form');
  const payBtn = $('#chk-pay-btn');

  confirmInput?.addEventListener('input', () => { checkoutContactDraft.emailConfirmation = confirmInput.value; });
  emailInput?.addEventListener('input', () => { checkoutContactDraft.email = emailInput.value; });
  termsInput?.addEventListener('change', () => { checkoutContactDraft.terms = termsInput.checked; });

  async function doRobloxLookup() {
    const u = (robloxInput?.value || '').trim();
    checkoutContactDraft.robloxQuery = u;
    if (!u || u.length < 3) {
      if ($('#chk-roblox-msg')) $('#chk-roblox-msg').textContent = 'Digite um username do Roblox de 3 a 20 caracteres.';
      return;
    }
    const reqId = ++robloxRequest;
    robloxUser = null;
    robloxConfirmed = false;
    if (lookupBtn) lookupBtn.disabled = true;
    if ($('#chk-roblox-msg')) $('#chk-roblox-msg').textContent = 'Consultando conta Roblox…';
    try {
      const r = await fetch('/api/roblox/user?username=' + encodeURIComponent(u));
      const res = await r.json();
      if (reqId !== robloxRequest) return;
      if (!r.ok) throw new Error(res.error || 'Conta Roblox não encontrada.');
      robloxUser = res;
      robloxConfirmed = true;
      if ($('#chk-roblox-display')) $('#chk-roblox-display').textContent = res.displayName;
      if ($('#chk-roblox-handle')) $('#chk-roblox-handle').textContent = '@' + res.username;
      if ($('#chk-roblox-avatar')) $('#chk-roblox-avatar').src = res.avatar || '/static/nzi-logo.png';
      if ($('#chk-roblox-result')) $('#chk-roblox-result').hidden = false;
      if (selectBtn) {
        selectBtn.textContent = 'Selecionado';
        selectBtn.classList.add('is-selected');
      }
      if ($('#chk-roblox-msg')) $('#chk-roblox-msg').textContent = '';
    } catch (err) {
      if (reqId === robloxRequest && $('#chk-roblox-msg')) $('#chk-roblox-msg').textContent = err.message;
    } finally {
      if (reqId === robloxRequest && lookupBtn) lookupBtn.disabled = false;
    }
  }

  lookupBtn?.addEventListener('click', doRobloxLookup);
  robloxInput?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); doRobloxLookup(); }
  });
  selectBtn?.addEventListener('click', () => {
    if (!robloxUser) return;
    robloxConfirmed = !robloxConfirmed;
    selectBtn.textContent = robloxConfirmed ? 'Selecionado' : 'Selecionar';
    selectBtn.classList.toggle('is-selected', robloxConfirmed);
  });

  couponForm?.addEventListener('submit', async e => {
    e.preventDefault();
    const code = $('#chk-coupon-input')?.value || '';
    const ok = await applyCoupon(code);
    render();
    if (!ok && $('#chk-coupon-msg')) $('#chk-coupon-msg').textContent = 'Cupom inválido ou desativado.';
  });

  payBtn?.addEventListener('click', () => {
    const email = (emailInput?.value || '').trim();
    const emailConfirmation=(confirmInput?.value||'').trim();
    checkoutContactDraft.email=email;checkoutContactDraft.emailConfirmation=emailConfirmation;
    if(email.toLowerCase()!==emailConfirmation.toLowerCase()){$('#chk-status').textContent='Os e-mails precisam ser iguais.';confirmInput?.focus();return;}
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      if ($('#chk-status')) $('#chk-status').textContent = 'Informe um e-mail válido para acompanhamento do pedido.';
      emailInput?.focus();
      return;
    }
    if (!termsInput?.checked) {
      if ($('#chk-status')) $('#chk-status').textContent = 'Aceite os termos e condições desta compra para continuar.';
      return;
    }
    if (needsRoblox() && (!robloxUser || !robloxConfirmed)) {
      if ($('#chk-status')) $('#chk-status').textContent = 'Busque e selecione seu usuário do Roblox antes de pagar.';
      robloxInput?.focus();
      return;
    }
    try { sessionStorage.setItem('nzi-payer-info', JSON.stringify({ email,emailConfirmation,termsAccepted:true })); } catch {}
    finishCheckout({ email,emailConfirmation,termsAccepted:true });
  });
}

function termsView() {
  return `<div class="view terms-view">
    <nav class="crumbs" aria-label="Você está em"><a href="/">Início</a><span>/</span><span>Termos de Uso e Condições de Compra</span></nav>
    <article class="terms-card">
      <header class="terms-head">
        <span class="badge-cat">Institucional · NziStore</span>
        <h1>Termos de Uso e Condições de Compra</h1>
        <p>Ao acessar, utilizar a plataforma ou realizar qualquer compra na NziStore, o usuário declara que leu, compreendeu e concorda com estes Termos de Uso e Condições de Compra.</p>
        <p>Antes de finalizar um pedido, recomendamos a leitura integral deste documento e das informações específicas apresentadas na página do produto.</p>
      </header>

      <section class="terms-section">
        <h2>1. Aceitação dos Termos</h2>
        <p>Ao utilizar os serviços da NziStore ou concluir uma compra, o cliente declara que:</p>
        <ul>
          <li>Leu e compreendeu as condições apresentadas neste documento;</li>
          <li>Concorda com as regras aplicáveis ao produto adquirido;</li>
          <li>Fornecerá informações corretas e um meio de contato válido para comunicação sobre pedidos e suporte;</li>
          <li>Possui autorização para utilizar o método de pagamento informado.</li>
        </ul>
        <p>A realização da compra representa a concordância do usuário com estes termos.</p>
      </section>

      <section class="terms-section">
        <h2>2. Produtos Comercializados</h2>
        <p>A NziStore trabalha principalmente com produtos e conteúdos digitais relacionados à plataforma Roblox, podendo incluir, conforme disponibilidade:</p>
        <ul>
          <li>Contas;</li>
          <li>Itens virtuais;</li>
          <li>Robux;</li>
          <li>Pets, gemas e outros conteúdos digitais;</li>
          <li>Outros produtos descritos na página de cada oferta.</li>
        </ul>
        <p>Cada produto pode possuir requisitos, características e prazos próprios. O cliente deve conferir cuidadosamente a descrição antes de efetuar a compra.</p>
      </section>

      <section class="terms-section">
        <h2>3. Processamento e Entrega</h2>
        <h3>3.1. Entregas automáticas</h3>
        <p>Quando disponível, a entrega automática será iniciada após a confirmação do pagamento, podendo ocorrer em poucos instantes.</p>
        <h3>3.2. Entregas manuais</h3>
        <p>Pedidos que dependam de processamento manual serão encaminhados assim que possível. Normalmente, esse processo ocorre em poucos minutos, mas situações excepcionais podem ocasionar atrasos.</p>
        <p>Caso o pedido ultrapasse o prazo informado ou apresente algum problema, o cliente deverá entrar em contato com o suporte oficial.</p>
        <h3>3.3. Prazos específicos</h3>
        <p>Alguns produtos possuem prazos próprios de entrega. Quando indicado na descrição, o prazo informado para aquele produto terá prioridade.</p>
        <p>Como exemplo, determinados pedidos de Robux podem levar de 5 a 7 dias úteis, enquanto contas e alguns itens digitais podem ser disponibilizados de maneira imediata.</p>
      </section>

      <section class="terms-section">
        <h2>4. Confirmação do Pagamento</h2>
        <p>Atualmente, os pagamentos disponibilizados pela NziStore poderão ser realizados através de PIX, conforme as opções apresentadas no momento da compra.</p>
        <p>Após a confirmação do pagamento, o sistema poderá identificar automaticamente a transação e liberar ou iniciar o processamento do pedido.</p>
        <p>Caso o pagamento seja realizado, mas não seja identificado corretamente, o cliente deverá entrar em contato com o suporte e fornecer as informações necessárias para a verificação.</p>
        <p>Os dados utilizados no processamento do pagamento devem ser fornecidos de maneira correta pelo comprador.</p>
      </section>

      <section class="terms-section">
        <h2>5. Segurança das Transações</h2>
        <p>A NziStore busca utilizar meios de pagamento e sistemas apropriados para proporcionar segurança durante as transações.</p>
        <p>Os dados fornecidos pelo cliente devem ser tratados de acordo com as políticas aplicáveis aos serviços utilizados para processamento do pagamento.</p>
        <p>O usuário também é responsável por manter protegidos seus dispositivos, contas, senhas e informações de pagamento.</p>
      </section>

      <section class="terms-section">
        <h2>6. Comprovação da Compra</h2>
        <p>Para facilitar a resolução de possíveis problemas, recomendamos que o cliente mantenha registros do processo de compra, como comprovantes de pagamento, número do pedido, recibos e, quando possível, gravação ou captura de tela da operação.</p>
        <p>Essas informações poderão ser solicitadas pelo suporte quando forem necessárias para verificar uma divergência relacionada ao pedido.</p>
        <p>A ausência de uma gravação de tela, por si só, não significa automaticamente a perda de qualquer direito previsto pela legislação aplicável.</p>
      </section>

      <section class="terms-section">
        <h2>7. Contas Digitais</h2>
        <p>Quando o produto adquirido for uma conta, o cliente deverá verificar cuidadosamente todas as informações apresentadas na descrição antes da compra.</p>
        <p>Quando a oferta indicar que a conta possui Full Access (FA), isso significa que serão fornecidos os meios de acesso e gerenciamento descritos na respectiva oferta, permitindo ao comprador administrar os dados disponibilizados para aquela conta.</p>
        <p>Após receber uma conta, recomendamos imediatamente:</p>
        <ul>
          <li>Alterar a senha;</li>
          <li>Adicionar ou atualizar métodos de recuperação disponíveis;</li>
          <li>Ativar autenticação em dois fatores, quando disponível;</li>
          <li>Verificar os dispositivos conectados;</li>
          <li>Remover acessos que não reconheça.</li>
        </ul>
        <p>O comprador é responsável pela proteção das credenciais após o recebimento.</p>
      </section>

      <section class="terms-section">
        <h2>8. Requisitos dos Produtos</h2>
        <p>Alguns produtos podem possuir requisitos específicos relacionados ao jogo, à conta ou à plataforma.</p>
        <p>Quando houver alguma exigência, ela deverá estar indicada na descrição do produto ou ser informada pelo suporte.</p>
        <p>O cliente deve verificar essas condições antes de realizar a compra.</p>
      </section>

      <section class="terms-section">
        <h2>9. Política de Reembolso, Troca e Garantia</h2>
        <p>Devido à natureza digital dos produtos comercializados, não são aceitos pedidos de reembolso ou troca simplesmente por arrependimento, mudança de opinião ou expectativa diferente daquela apresentada na descrição do produto.</p>
        <p>Exemplos de situações que, isoladamente, não justificam reembolso:</p>
        <ul>
          <li>“Não gostei da conta”;</li>
          <li>“Me arrependi da compra”;</li>
          <li>“Esperava outro produto”;</li>
          <li>“Não quero mais o item após recebê-lo”.</li>
        </ul>
        <p>Entretanto, caso o cliente receba um produto diferente daquele adquirido, ou exista algum problema coberto pela garantia específica da oferta, o caso poderá ser analisado pelo suporte.</p>
        <h3>9.1. Garantia</h3>
        <p>Quando uma garantia estiver indicada para determinado produto, ela será válida dentro do período e das condições informadas na respectiva oferta.</p>
        <p>No caso de produtos que possuam garantia de 7 dias, o cliente deverá comunicar o problema dentro desse período, apresentando as informações necessárias para análise.</p>
        <p>A garantia poderá não se aplicar quando for constatado uso indevido, alteração não autorizada, compartilhamento de credenciais, negligência do comprador ou qualquer outra situação causada após a entrega que comprometa a análise do problema.</p>
        <h3>9.2. Análise de solicitações</h3>
        <p>Toda solicitação de troca, correção ou reembolso será analisada individualmente com base nas informações do pedido, no produto adquirido e nas circunstâncias apresentadas.</p>
        <p>Quando aprovada, uma eventual devolução de valores será processada dentro do prazo informado pelo suporte, podendo levar até 3 dias úteis para processamento pela NziStore, sem prejuízo de eventuais prazos adicionais do meio de pagamento.</p>
      </section>

      <section class="terms-section">
        <h2>10. Responsabilidade do Comprador</h2>
        <p>O cliente é responsável pelas informações fornecidas durante a compra, incluindo dados de contato, informações da conta e demais dados necessários para a entrega.</p>
        <p>A NziStore não se responsabiliza por problemas decorrentes de informações incorretas fornecidas pelo próprio comprador.</p>
        <p>Também é responsabilidade do usuário manter suas credenciais protegidas após o recebimento do produto.</p>
      </section>

      <section class="terms-section">
        <h2>11. Fraudes e Atividades Irregulares</h2>
        <p>A NziStore poderá adotar medidas de segurança para identificar e prevenir atividades suspeitas ou fraudulentas.</p>
        <p>Poderão ser considerados comportamentos irregulares, entre outros:</p>
        <ul>
          <li>Tentativas de fraude de pagamento;</li>
          <li>Utilização indevida de métodos de pagamento;</li>
          <li>Tentativas de obter produtos sem efetuar o pagamento correspondente;</li>
          <li>Apresentação de comprovantes falsificados;</li>
          <li>Manipulação ou adulteração de informações relacionadas ao pedido.</li>
        </ul>
        <p>Quando houver indícios de fraude, o pedido poderá ser suspenso para análise.</p>
        <p>Em situações graves, a NziStore poderá restringir ou bloquear o acesso do usuário à plataforma e, quando necessário, buscar as medidas legais cabíveis.</p>
      </section>

      <section class="terms-section">
        <h2>12. Idade e Autorização — NziStore</h2>
        <p>A plataforma é destinada preferencialmente a maiores de 18 anos.</p>
        <p>Caso um menor de idade utilize os serviços ou realize uma compra, deverá possuir autorização e supervisão de seu responsável legal, quando exigido pela legislação aplicável.</p>
        <p>O responsável deve acompanhar o uso dos dispositivos, contas e métodos de pagamento utilizados pelo menor.</p>
      </section>

      <section class="terms-section">
        <h2>13. Compras Não Autorizadas</h2>
        <p>O usuário deve proteger seus dispositivos, contas e métodos de pagamento contra acesso de terceiros.</p>
        <p>A NziStore não poderá ser responsabilizada por compras realizadas por terceiros que tenham obtido acesso indevido ao dispositivo, conta ou informações de pagamento do usuário, ressalvadas as hipóteses em que a legislação aplicável determine responsabilidade diversa.</p>
        <p>Recomendamos o uso de senhas fortes, autenticação em dois fatores e controles parentais sempre que apropriado.</p>
      </section>

      <section class="terms-section">
        <h2>14. Produtos Digitais e Irreversibilidade</h2>
        <p>O cliente reconhece que determinados produtos comercializados pela NziStore são digitais e podem ser disponibilizados diretamente em uma conta ou por meio de informações de acesso.</p>
        <p>Após a entrega e utilização do produto, sua reversão ou devolução pode ser tecnicamente impossível.</p>
        <p>Por esse motivo, o comprador deve conferir atentamente a descrição, as características, os requisitos e as condições do produto antes de concluir o pedido.</p>
      </section>

      <section class="terms-section">
        <h2>15. Suporte ao Cliente</h2>
        <p>Em caso de dúvidas, problemas com a entrega ou divergências relacionadas ao pedido, o cliente deverá procurar os canais oficiais de atendimento disponibilizados pela NziStore.</p>
        <p>Para agilizar o atendimento, poderão ser solicitados:</p>
        <ul>
          <li>Número ou identificação do pedido;</li>
          <li>Comprovante de pagamento;</li>
          <li>Informações relacionadas ao produto;</li>
          <li>Capturas de tela ou gravações;</li>
          <li>Outras informações necessárias para verificar a situação.</li>
        </ul>
      </section>

      <section class="terms-section">
        <h2>16. Alterações dos Termos</h2>
        <p>A NziStore poderá atualizar estes Termos de Uso e Condições de Compra sempre que necessário, inclusive para melhorar seus procedimentos, atualizar serviços ou adequar suas regras às normas aplicáveis.</p>
        <p>A versão vigente será aquela disponibilizada na plataforma no momento da consulta.</p>
      </section>

      <section class="terms-section">
        <h2>17. Disposições Finais</h2>
        <p>A NziStore busca realizar as entregas de forma correta, transparente e dentro das condições apresentadas ao cliente no momento da compra.</p>
        <p>Nenhuma disposição destes termos tem a intenção de excluir ou limitar direitos que não possam ser afastados pela legislação aplicável.</p>
        <p>Ao realizar uma compra, o usuário confirma que teve a oportunidade de consultar as informações do produto e concorda com as condições estabelecidas neste documento.</p>
      </section>
    </article>
  </div>`;
}
function openDetail(id) {
  if(!byId(id))return;
  const url='/produto/'+encodeURIComponent(id);
  recordSearchVisit(url);
  history.pushState({},'', url);route();
}
function formatCentsSplit(cents) {
  const str = (cents / 100).toFixed(2).replace('.', ',');
  const [intPart, decPart] = str.split(',');
  return `R$ ${Number(intPart).toLocaleString('pt-BR')}<sup>${decPart}</sup>`;
}
function productView(p) {
  if(state.status==='loading')return '<div class="view">'+skeletonGrid(2)+'</div>';
  if(state.status==='error')return '<div class="view">'+errorState()+'</div>';
  if(!p)return '<div class="view">'+emptyState('Produto não encontrado','Este produto saiu do catálogo.','<a class="btn" href="/">Voltar à loja</a>')+'</div>';
  const category=catByName(p.category),automatic=p.delivery_mode==='automatic';
  const related=state.products.filter(other=>other.id!==p.id&&other.category===p.category).slice(0,4);
  const hasVariants=Boolean(p.has_variants&&Array.isArray(p.variants)&&p.variants.length);
  const selectedVarId=hasVariants?(state.selectedVariants[p.id]||p.variants[0].id):null;
  const activeVar=hasVariants?(p.variants.find(v=>v.id===Number(selectedVarId))||p.variants[0]):null;
  const activePrice=activeVar?activeVar.price:p.price;
  const activeCompare=activeVar?(activeVar.compare_price||p.compare_price||0):(p.compare_price||0);
  const activeDiscount=activeCompare>activePrice?Math.round((1-activePrice/activeCompare)*100):0;
  const cartActionKey=activeVar?`${p.id}:${activeVar.id}`:String(p.id);
  const minQ=Math.max(1,Number(p.min_quantity)||1);
  const maxQ=Math.min(99,Math.max(minQ,Number(p.max_quantity)||99));
  const thumbHtml=p.image?`<img class="variant-thumb" src="${esc(p.image)}" alt="" loading="lazy">`:`<span class="variant-thumb variant-thumb-glyph" aria-hidden="true">${glyph(category.slug)}</span>`;
  const variantsHtml=hasVariants?`<div class="variants-selector" data-product-variants="${p.id}">
    <div class="variants-selector-head">
      <h3>Variações</h3>
      <p>Selecione o produto desejado abaixo.</p>
    </div>
    <div class="variants-cards">
      ${p.variants.map(v=>{
        const isSel=v.id===activeVar.id;
        const vDisc=v.compare_price&&v.compare_price>v.price?Math.round((1-v.price/v.compare_price)*100):0;
        return `<button type="button" class="variant-card${isSel?' is-selected':''}" data-select-variant="${v.id}" data-product-id="${p.id}">
          ${isSel?'<span class="variant-selected-pill">Selecionado</span>':''}
          ${thumbHtml}
          <span class="variant-card-info">
            <strong class="variant-card-title">${esc(v.name)}</strong>
            <span class="variant-card-stock">Disponível ( ${v.stock} )</span>
          </span>
          <span class="variant-card-pricing">
            ${vDisc>0?`<s class="variant-old-price">${money(v.compare_price)}</s>`:''}
            <span class="variant-new-line">
              ${vDisc>0?`<span class="variant-disc-pct">-${vDisc}%</span>`:''}
              <strong class="variant-new-price">${formatCentsSplit(v.price)}</strong>
            </span>
          </span>
        </button>`;
      }).join('')}
    </div>
  </div>`:'';
  const videoHtml=p.video_url?`<div class="product-video-embed"><iframe src="${esc(p.video_url)}" title="Vídeo demonstrativo de ${esc(p.name)}" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen referrerpolicy="same-origin"></iframe></div>`:'';
  return `<div class="view"><nav class="crumbs" aria-label="Você está em"><a href="/">Início</a><span>/</span><a href="${categoryUrl(category)}">${esc(category.title)}</a><span>/</span><span>${esc(p.name)}</span></nav>
  <div class="product-layout"><div class="product-visual">${artHtml(p,false)}</div><section class="product-summary">
    <div class="product-delivery-pill ${automatic?'is-auto':'is-manual'}">${automatic?'ENTREGA AUTOMÁTICA':'ENTREGA MANUAL'}</div>
    <span class="badge-cat">${esc(category.title)}</span>
    <h1>${esc(p.name)}</h1>
    <div class="card-rating-row"><span class="card-stars" aria-hidden="true">★★★★★</span><span class="card-rating-val">5.0</span></div>
    ${activeDiscount>0?`<div class="card-compare-row"><s class="card-old-price">${money(activeCompare)}</s><span class="card-discount-pill">${activeDiscount}% OFF</span></div>`:''}
    <div class="product-price"><strong>${money(activePrice)}</strong><small>À vista no Pix · cupom aplicado no carrinho</small></div>
    ${variantsHtml}
    ${(minQ>1||maxQ<99)?`<p class="product-qty-limits">Quantidade por pedido: mínima <b>${minQ}</b> · máxima <b>${maxQ}</b></p>`:''}
    <div class="jp-row"><button type="button" class="jp-btn jp-primary" data-buy="${esc(cartActionKey)}">Comprar agora</button><button type="button" class="jp-btn jp-outline" data-add="${esc(cartActionKey)}"><span>Adicionar ao carrinho</span></button></div>
    <div class="product-benefits"><span><img class="benefit-icon mono" src="/static/icon-delivery.png" alt="">Entrega no pedido</span><span><img class="benefit-icon mono" src="/static/icon-support.png" alt="">Chat com suporte</span><span><img class="benefit-icon" src="/static/icon-pix.png" alt="">Pagamento Pix</span></div>
  </section></div>
  <section class="product-section"><h2>Descrição do produto</h2><p class="product-description">${esc(p.description||'Sem descrição cadastrada.')}</p>${videoHtml}</section><section class="product-section"><h2>Informações</h2><ul><li>${automatic?'O arquivo de texto é liberado após a confirmação do pagamento e disponibilidade de estoque.':'A entrega é realizada pelo suporte após a confirmação do pagamento.'}</li><li>Acompanhe sua compra e converse com o suporte na página do pedido.</li>${p.category==='Robux'?'<li>Confirme o destinatário Roblox ao finalizar o pedido.</li>':''}</ul></section><section class="product-section"><h2>Formas de pagamento</h2><img class="payment-icon" src="/static/pix.png" alt=""> Pix</section>${related.length?`<section class="product-related"><h2>Produtos similares</h2><div class="grid">${related.map(cardHtml).join('')}</div></section>`:''}</div>`;
}

/* ---------- eventos ---------- */
document.addEventListener('click', e => {
  const t = e.target;
  const varBtn = t.closest('[data-select-variant]');
  if (varBtn) {
    const pid = Number(varBtn.dataset.productId);
    const vid = Number(varBtn.dataset.selectVariant);
    state.selectedVariants[pid] = vid;
    render();
    return;
  }
  const upsellBtn = t.closest('[data-upsell-add]');
  if (upsellBtn) {
    addItemToCart(upsellBtn.dataset.upsellAdd, 1);
    render();
    return;
  }
  const add = t.closest('[data-add]');
  if (add) {
    const entry = addItemToCart(add.dataset.add, 1);
    if (!entry) return;
    $('#cart-feedback').textContent = `${entry.name} adicionado ao carrinho.`;
    const span = add.querySelector('span');
    if (span) {
      const prev = span.textContent;
      span.textContent = 'Adicionado!';
      clearTimeout(add.feedbackTimer);
      add.feedbackTimer = setTimeout(() => { if (add.isConnected) span.textContent = prev.includes('Adicionar') ? 'Adicionar ao carrinho' : 'add to cart'; }, 1400);
    }
    return;
  }
  const buy = t.closest('[data-buy]');
  if (buy) {
    const entry = addItemToCart(buy.dataset.buy, 1);
    if (!entry) return;
    openCheckoutPage();
    return;
  }
  const open = t.closest('[data-open]');
  if (open) return openDetail(open.dataset.open);
  if (t.closest('[data-close-detail]')) return $('#detail').close();
  const inc = t.closest('[data-inc]'); if (inc) return changeQty(inc.dataset.inc, 1);
  const dec = t.closest('[data-dec]'); if (dec) return changeQty(dec.dataset.dec, -1);
  const rm = t.closest('[data-rm]'); if (rm) { delete state.cart[rm.dataset.rm]; saveCart(); renderCart(); if (currentRoute() === 'checkout') render(); return; }
  if (t.closest('[data-retry]')) return load();
  const dd = t.closest('[data-dd]');
  if (dd) return setDd(dd.dataset.dd);
  if (!t.closest('.dd')) setDd(null);
  if (t.closest('#menu a')) setMenu(false);
  if (t.closest('#burger')) setMenu(!document.body.classList.contains('sidebar-open'));
});
document.addEventListener('change', e => {
  if (e.target.id === 'sort') { state.sort = e.target.value; render(); $('#sort').focus(); }
});
$('#open-cart').addEventListener('click', openCart);
$('#close-cart').addEventListener('click', closeCart);
$('#scrim').addEventListener('click', closeCart);
$('#detail-close').addEventListener('click', () => $('#detail').close());
$('#detail').addEventListener('click', e => { if (e.target === $('#detail')) $('#detail').close(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { if ($('#drawer').classList.contains('open')) closeCart(); setDd(null); setMenu(false); return; }
  if (e.key === 'Tab' && $('#drawer').classList.contains('open')) {
    const f = $$('button:not([disabled]), a[href], [tabindex="0"]', $('#drawer')).filter(x => !x.closest('[hidden]') && x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!$('#drawer').contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  }
});
/* Search palette: catalog data + first-party search preference cookie (no external tracking). */
const SEARCH_COOKIE='nzi-search-prefs';
function readCookieJSON(name) {
  try {
    const raw=document.cookie.split('; ').find(x=>x.startsWith(name+'='))?.slice(name.length+1);
    return raw?JSON.parse(decodeURIComponent(raw)):null;
  } catch { return null; }
}
function canUseSearchCookies() {
  const consent=readCookieJSON('nzi-cookie-preferences');
  return consent ? Boolean(consent.personalization || consent.analytics) : true;
}
function loadSearchPrefs() {
  if(!canUseSearchCookies())return {terms:[],urls:[]};
  const data=readCookieJSON(SEARCH_COOKIE);
  const terms=Array.isArray(data?.terms)?data.terms.filter(t=>typeof t==='string'&&t.trim().length>=2&&t.length<=40).slice(0,5):[];
  const urls=Array.isArray(data?.urls)?data.urls.filter(u=>typeof u==='string'&&/^\/([a-z0-9-]+|produto\/\d+)?$/.test(u)).slice(0,6):[];
  return {terms,urls};
}
function saveSearchPrefs(prefs) {
  if(!canUseSearchCookies()){
    document.cookie=SEARCH_COOKIE+'=; Path=/; Max-Age=0; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');
    return;
  }
  const clean={terms:(prefs.terms||[]).slice(0,5),urls:(prefs.urls||[]).slice(0,6)};
  document.cookie=SEARCH_COOKIE+'='+encodeURIComponent(JSON.stringify(clean))+'; Path=/; Max-Age=2592000; SameSite=Lax'+(location.protocol==='https:'?'; Secure':'');
}
function recordSearchVisit(url,term='') {
  if(!canUseSearchCookies())return;
  const prefs=loadSearchPrefs();
  if(url && /^\/([a-z0-9-]+|produto\/\d+)$/.test(url)){
    prefs.urls=[url,...prefs.urls.filter(u=>u!==url)].slice(0,6);
  }
  const cleanTerm=term.trim().slice(0,40);
  if(cleanTerm.length>=2){
    prefs.terms=[cleanTerm,...prefs.terms.filter(t=>norm(t)!==norm(cleanTerm))].slice(0,5);
  }
  saveSearchPrefs(prefs);
}
window.addEventListener('nzi:consent',e=>{
  if(!e.detail?.personalization && !e.detail?.analytics) saveSearchPrefs({terms:[],urls:[]});
  if(searchDialog.open) renderSmartSearch();
});

const searchDialog=document.createElement('dialog');
searchDialog.className='smart-search';
searchDialog.setAttribute('aria-labelledby','smart-search-title');
searchDialog.innerHTML=`<div class="smart-search-inner"><button class="smart-close" type="button" aria-label="Fechar busca">×</button><p class="smart-eyebrow">NZI STORE</p><h2 id="smart-search-title">Encontre o que procura.</h2><form class="smart-form" role="search"><label class="sr-only" for="smart-query">Buscar produtos ou páginas</label><span aria-hidden="true">⌕</span><input id="smart-query" type="search" placeholder="Buscar produtos ou páginas..." autocomplete="off" maxlength="120"><kbd>ESC</kbd></form><div class="smart-shortcuts"><a href="/">⌂<span>Loja</span></a><button type="button" data-smart-cart>＋<span>Carrinho</span></button><a href="/pedidos">↗<span>Suporte</span></a></div><section class="smart-category-section"><h3>CATEGORIAS EM DESTAQUE</h3><div id="smart-category-banners"></div></section><div id="smart-recent-terms" class="smart-shortcuts" hidden></div><h3>PÁGINAS E PRODUTOS</h3><p id="smart-status" role="status" aria-live="polite"></p><div id="smart-results"></div></div>`;
document.body.append(searchDialog);
const smartQuery=searchDialog.querySelector('#smart-query');
const smartRecentTerms=searchDialog.querySelector('#smart-recent-terms');
function nearWord(a,b) {
  if(Math.abs(a.length-b.length)>1)return false;
  let i=0,j=0,edits=0;
  while(i<a.length&&j<b.length){if(a[i]===b[j]){i++;j++;continue;}if(++edits>1)return false;if(a.length>=b.length)i++;if(b.length>=a.length)j++;}
  return edits+(a.length-i)+(b.length-j)<=1;
}
function smartItems() {
  return [
    {title:'Minha conta',hint:'Entrar ou criar conta',url:'/conta',type:'Página'},
    {title:'Pedidos e suporte',hint:'Compras, entregas e chat',url:'/pedidos',type:'Página'},
    {title:'Loja',hint:'Todas as categorias',url:'/',type:'Página'},
    ...CATEGORIES.map(c=>({title:c.title,hint:'Ver produtos da categoria',url:categoryUrl(c),type:'Categoria'})),
    ...state.products.map(p=>({title:p.name,hint:money(p.price)+' · '+catByName(p.category).title,url:'/produto/'+p.id,type:'Produto',description:p.description}))
  ];
}
function renderSmartSearch() {
  const prefs=loadSearchPrefs();
  const categoryQuery=norm(smartQuery.value.trim());
  searchDialog.querySelector('#smart-category-banners').innerHTML=CATEGORIES.filter(c=>!categoryQuery||norm(c.title).includes(categoryQuery)).map(c=>`<a class="smart-category-banner" href="${categoryUrl(c)}" aria-label="Ver ${esc(c.title)}">${c.image?`<img src="${esc(c.image)}" alt="">`:glyph(c.slug)}<span>${esc(c.title)}</span></a>`).join('');
  if(prefs.terms.length){
    smartRecentTerms.hidden=false;
    smartRecentTerms.innerHTML=prefs.terms.map(t=>`<button type="button" data-recent-term="${esc(t)}">↺<span>${esc(t)}</span></button>`).join('');
  } else {
    smartRecentTerms.hidden=true;
    smartRecentTerms.replaceChildren();
  }
  const query=norm(smartQuery.value.trim()),terms=query.split(/\s+/).filter(Boolean);
  const results=smartItems().map((item,index)=>{
    const title=norm(item.title),text=norm(item.title+' '+item.hint+' '+(item.description||''));
    const words=title.split(/[^a-z0-9]+/).filter(Boolean);
    const matches=terms.every(term=>text.includes(term)||(term.length>=4&&words.some(word=>nearWord(term,word))));
    const recentRank=prefs.urls.indexOf(item.url);
    const recentBoost=recentRank!==-1?(30-recentRank*4):0;
    const termBoost=prefs.terms.some(t=>text.includes(norm(t)))?12:0;
    const baseScore=title===query?100:title.startsWith(query)?70:title.includes(query)?50:20;
    const score=(query?baseScore:0)+recentBoost+termBoost;
    return {...item,index,score,matches,isRecent:recentRank!==-1};
  }).filter(item=>!query||item.matches).sort((a,b)=>(query||a.score!==b.score)?b.score-a.score||a.index-b.index:a.index-b.index).slice(0,14);
  searchDialog.querySelector('#smart-results').innerHTML=results.map(item=>`<a class="smart-result" href="${esc(item.url)}"><span class="smart-result-icon" aria-hidden="true">${item.type==='Produto'?'◇':'↗'}</span><span><strong>${esc(item.title)}</strong><small>${item.isRecent?'Recente · ':''}${esc(item.hint)}</small></span><span class="smart-result-type">${esc(item.type)}</span></a>`).join('');
  searchDialog.querySelector('#smart-status').textContent=state.status==='loading'?'Carregando produtos…':state.status==='error'?'Catálogo indisponível. Você ainda pode acessar as páginas abaixo.':results.length?(query?`${results.length} ${results.length===1?'sugestão encontrada':'sugestões encontradas'}`:'Explore categorias, produtos e sugestões personalizadas'):'Nenhum resultado. Tente outro nome ou uma categoria.';
}
function openSmartSearch() {if(searchDialog.open)return;renderSmartSearch();searchDialog.showModal();document.body.classList.add('smart-search-open');smartQuery.focus();}
searchDialog.querySelector('.smart-close').onclick=()=>searchDialog.close();
searchDialog.addEventListener('close',()=>{document.body.classList.remove('smart-search-open');$('#search').focus();});
searchDialog.addEventListener('click',e=>{
  if(e.target===searchDialog){searchDialog.close();return;}
  const recentBtn=e.target.closest('[data-recent-term]');
  if(recentBtn){smartQuery.value=recentBtn.dataset.recentTerm;renderSmartSearch();smartQuery.focus();return;}
  const link=e.target.closest('.smart-result');
  if(link){recordSearchVisit(link.getAttribute('href'),smartQuery.value);}
});
searchDialog.querySelector('[data-smart-cart]').onclick=()=>{searchDialog.close();openCart();};
smartQuery.addEventListener('input',renderSmartSearch);
searchDialog.querySelector('form').onsubmit=e=>{e.preventDefault();const first=searchDialog.querySelector('.smart-result');if(first){recordSearchVisit(first.getAttribute('href'),smartQuery.value);first.click();}};
searchDialog.addEventListener('keydown',e=>{
  if(!['ArrowDown','ArrowUp'].includes(e.key))return;
  const results=[...searchDialog.querySelectorAll('.smart-result')];if(!results.length)return;
  e.preventDefault();let index=results.indexOf(document.activeElement);index=e.key==='ArrowDown'?Math.min(index+1,results.length-1):Math.max(index-1,0);results[index].focus();
});
$('#search').readOnly=true;
$('#search').setAttribute('aria-haspopup','dialog');
$('#search').addEventListener('click',openSmartSearch);
$('#search').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openSmartSearch();}else if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){smartQuery.value=e.key;openSmartSearch();}});

function checkoutMessage(text) {
  if ($('#checkout-status')) $('#checkout-status').textContent = text;
  if ($('#recipient-status')) $('#recipient-status').textContent = text;
  if ($('#chk-status')) $('#chk-status').textContent = text;
}
$('#checkout').addEventListener('click', () => {
  openCheckoutPage();
});
$('#recipient-close').onclick = () => { $('#recipient-dialog').close(); openCart(); };
$('#recipient-dialog').addEventListener('cancel', event => { event.preventDefault(); $('#recipient-dialog').close(); openCart(); });
async function finishCheckout(payer = null) {
  if (needsRoblox() && (!robloxConfirmed || !robloxUser)) return;
  const button = $('#checkout');
  const chkPayBtn = $('#chk-pay-btn');
  if (button) button.disabled = true;
  if (chkPayBtn) chkPayBtn.disabled = true;
  $('#roblox-confirm').disabled = true;
  checkoutMessage('Criando pedido…');
  try {
    let sessionResponse = await fetch('/api/auth/me', {cache:'no-store'});
    if (sessionResponse.status === 401) {
      sessionResponse = await fetch('/api/auth/refresh', {method:'POST', cache:'no-store', headers:{'Content-Type':'application/json'}, body:'{}'});
    }
    if (sessionResponse.status === 401) {
      checkoutMessage('Entre na sua conta para criar o pedido. Seu carrinho está salvo.');
      $('#recipient-login').hidden = false;
      $('#checkout-login').hidden = false;
      if ($('#chk-login-btn')) $('#chk-login-btn').hidden = false;
      return;
    }
    if (!sessionResponse.ok) throw new Error('Não foi possível verificar sua sessão.');
    const session = await sessionResponse.json();
    const body = {items:cartIds().map(k => {
      const entry = parseCartKey(k);
      return entry.variant_id !== null
        ? {product_id: entry.product_id, variant_id: entry.variant_id, quantity: state.cart[k]}
        : {product_id: entry.product_id, quantity: state.cart[k]};
    }), expected_total:cartTotal(), coupon:activeCoupon, tracking:campaignTracking(),
      ...(payer && payer.email ? {payer_email: payer.email} : {}),
      ...(needsRoblox() ? {roblox_ticket:robloxUser.ticket,roblox_confirmed:robloxConfirmed}:{})};
    const fingerprint = JSON.stringify(body);
    let draft;
    try { draft = JSON.parse(sessionStorage.getItem('nzi-checkout') || 'null'); } catch { draft = null; }
    if (!draft || draft.fingerprint !== fingerprint) {
      draft = {fingerprint, key:crypto.randomUUID()};
      try { sessionStorage.setItem('nzi-checkout', JSON.stringify(draft)); } catch { /* sessão sem armazenamento */ }
    }
    const response = await fetch('/api/orders', {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify({...body,request_key:draft.key})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível criar o pedido.');
    if(payer?.email&&payer?.emailConfirmation&&payer?.termsAccepted===true){try{sessionStorage.setItem('nzi-payer-info',JSON.stringify({...payer,orderId:result.order.id}));}catch{}}
    state.cart = {}; saveCart();
    try { sessionStorage.removeItem('nzi-checkout'); } catch { /* sessão sem armazenamento */ }
    location.href = '/pagamento/' + result.order.id;
  } catch (error) { checkoutMessage(error.message); }
  finally {
    if (button) button.disabled = false;
    if (chkPayBtn) chkPayBtn.disabled = false;
    $('#roblox-confirm').disabled = false;
  }
}
window.addEventListener('hashchange', route);
window.addEventListener('popstate', route);

/* ---------- carga dos produtos ---------- */
function load() {
  state.status = 'loading';
  render(); renderCart();
  return Promise.all(['/api/products','/api/categories','/api/roblox/subcategories'].map(url => fetch(url, {cache:'no-store'}).then(r => { if (!r.ok) throw new Error('http'); return r.json(); })))
    .then(([products, categories, games]) => {
      subcategories=games;
      state.products = Array.isArray(products) ? products : [];
      CATEGORIES = categories.map(category => ({...catBySlug(category.slug),...category}));
      state.status = 'ready'; cleanCart(); renderChrome();
    })
    .catch(() => { state.products = []; state.status = 'error'; })
    .then(() => {
      const h = currentRoute();
      if (SECTIONS.includes(h)) route(); else render();
      renderCart();
      if(searchDialog.open)renderSmartSearch();
    });
}

renderChrome();
renderCart();
route();
load();

$('#roblox-username').addEventListener('input', () => {
  robloxRequest++; robloxUser = null; robloxConfirmed = false;
  $('#roblox-profile').hidden = true;
  $('#roblox-status').textContent = '';
  $('#roblox-search').disabled = false;
});
$('#roblox-form').addEventListener('submit', async event => {
  event.preventDefault();
  const requestId = ++robloxRequest;
  robloxUser = null; robloxConfirmed = false;
  $('#roblox-profile').hidden = true;
  $('#roblox-search').disabled = true;
  $('#roblox-status').textContent = 'Consultando Roblox…';
  try {
    const response = await fetch('/api/roblox/user?username=' + encodeURIComponent($('#roblox-username').value.trim()));
    const result = await response.json();
    if (requestId !== robloxRequest) return;
    if (!response.ok) throw new Error(result.error || 'Não foi possível consultar o Roblox.');
    robloxUser = result;
    $('#roblox-name').textContent = result.displayName;
    $('#roblox-handle').textContent = '@' + result.username;
    $('#roblox-avatar').hidden = !result.avatar;
    if (result.avatar) $('#roblox-avatar').src = result.avatar;
    $('#roblox-profile').hidden = false;
    $('#roblox-confirm').disabled = false;
    $('#roblox-confirm').textContent = 'Confirmar usuario';
    $('#roblox-status').textContent = result.avatar ? 'Confira a conta antes de confirmar.' : 'Avatar indisponível. Confira o username antes de confirmar.';
  } catch (error) {
    if (requestId === robloxRequest) $('#roblox-status').textContent = error.message;
  } finally {
    if (requestId === robloxRequest) $('#roblox-search').disabled = false;
  }
});
$('#roblox-avatar').addEventListener('error', () => { $('#roblox-avatar').hidden = true; });
$('#roblox-confirm').addEventListener('click', () => {
  if (!robloxUser) return;
  robloxConfirmed = true;
  $('#roblox-confirm').textContent = 'Conta confirmada';
  $('#roblox-confirm').disabled = true;
  $('#roblox-status').textContent = 'Conta confirmada.';
  finishCheckout();
});

// Delegation also animates buttons created when changing categories or opening details.
const jellyStates = new WeakMap();
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
function jellyTarget(btn, pressed) {
  if (btn.disabled || reducedMotion.matches) return;
  let state = jellyStates.get(btn);
  if (!state) {
    state = { sx: 1, sy: 1, vx: 0, vy: 0, tx: 1, ty: 1, running: false };
    jellyStates.set(btn, state);
  }
  state.tx = pressed ? 1.16 : 1;
  state.ty = pressed ? .78 : 1;
  if (state.running) return;
  state.running = true;
  let previous = 0;
  function step(now) {
    if (!btn.isConnected || reducedMotion.matches) {
      btn.style.transform = ''; state.running = false; return;
    }
    // Account for elapsed time on screens with different refresh rates.
    const elapsed = previous ? Math.min(now - previous, 50) : 16.67;
    previous = now;
    const dt = elapsed / 16.67;
    state.vx = (state.vx + (state.tx - state.sx) * .28 * dt) * Math.pow(.62, dt);
    state.vy = (state.vy + (state.ty - state.sy) * .28 * dt) * Math.pow(.62, dt);
    state.sx += state.vx * dt; state.sy += state.vy * dt;
    btn.style.transform = `scale(${state.sx}, ${state.sy})`;
    if (Math.abs(state.vx) + Math.abs(state.vy) < .0012 && Math.abs(state.tx - state.sx) + Math.abs(state.ty - state.sy) < .002) {
      state.sx = state.tx; state.sy = state.ty; state.vx = state.vy = 0;
      btn.style.transform = `scale(${state.tx}, ${state.ty})`;
      state.running = false; return;
    }
    requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}
let pressedJelly = null;
function releaseJelly() {
  if (pressedJelly) jellyTarget(pressedJelly, false);
  pressedJelly = null;
}
document.addEventListener('pointerdown', event => {
  const btn = event.target.closest('.jp-btn');
  if (btn && event.button === 0) { releaseJelly(); pressedJelly = btn; jellyTarget(btn, true); }
});
document.addEventListener('pointerup', releaseJelly);
document.addEventListener('pointercancel', releaseJelly);
document.addEventListener('pointerout', event => {
  if (pressedJelly && !pressedJelly.contains(event.relatedTarget)) releaseJelly();
});
window.addEventListener('blur', releaseJelly);
document.addEventListener('keydown', event => {
  const btn = event.target.closest('.jp-btn');
  if (btn && !event.repeat && [' ', 'Enter'].includes(event.key)) { pressedJelly = btn; jellyTarget(btn, true); }
});
document.addEventListener('keyup', event => { if ([' ', 'Enter'].includes(event.key)) releaseJelly(); });

function campaignTracking(){
  try{const preferences=JSON.parse(decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('nzi-cookie-preferences='))?.split('=').slice(1).join('=')||'{}'));if(preferences.version!==2||!preferences.analytics){sessionStorage.removeItem('nzi-campaign');return {};}
  const params=new URLSearchParams(location.search),keys=['src','sck','utm_source','utm_campaign','utm_medium','utm_content','utm_term'];
  const current=Object.fromEntries(keys.filter(k=>params.has(k)).map(k=>[k,params.get(k).slice(0,250)]));
  if(Object.keys(current).length)sessionStorage.setItem('nzi-campaign',JSON.stringify(current));
  return JSON.parse(sessionStorage.getItem('nzi-campaign')||'{}');}catch{return {};}
}
campaignTracking();window.addEventListener('nzi:consent',campaignTracking);

async function recordStoreVisit(){
 try{const prefs=readCookieJSON('nzi-cookie-preferences');if(prefs?.version!==2||!prefs.analytics){sessionStorage.removeItem('nzi-visitor');sessionStorage.removeItem('nzi-visit-day');return;}
 const day=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Sao_Paulo'}).format(new Date());if(sessionStorage.getItem('nzi-visit-day')===day)return;
 let visitor=sessionStorage.getItem('nzi-visitor');if(!visitor){visitor=crypto.randomUUID().replaceAll('-','');sessionStorage.setItem('nzi-visitor',visitor);}
 const session=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());const response=await fetch('/api/analytics/visit',{method:'POST',headers:{'Content-Type':'application/json',...(session.csrf?{'X-CSRF-Token':session.csrf}:{})},body:JSON.stringify({visitor})});if(response.ok&&(await response.json()).recorded)sessionStorage.setItem('nzi-visit-day',day);
 }catch{}
}
recordStoreVisit();window.addEventListener('nzi:consent',recordStoreVisit);

/* ==========================================================================
   Barra Lateral Flutuante de Redes Sociais (#og-social-bar)
   ========================================================================== */
(function () {
  if (window.ogSocialBarInicializado) return;
  window.ogSocialBarInicializado = true;

  const SVG_ICONS = {
    'fa-brands fa-instagram': '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>',
    'fa-brands fa-whatsapp': '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>',
    'fa-brands fa-discord': '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>'
  };

  function ogCriarBarra() {
    if (document.getElementById('og-social-bar')) return;

    const ogLinks = [
      { show: true, link: CONFIG.instagramUrl || 'https://instagram.com/seu-usuario', icon: 'fa-brands fa-instagram', label: 'Instagram', brand: 'instagram' },
      { show: true, link: CONFIG.supportUrl || 'https://wa.me/SEUNUMERO', icon: 'fa-brands fa-whatsapp', label: 'WhatsApp', brand: 'whatsapp' },
      { show: true, link: CONFIG.discordUrl || 'https://discord.gg/SEUSERVIDOR', icon: 'fa-brands fa-discord', label: 'Discord', brand: 'discord' }
    ].filter(Boolean);

    let linksHTML = '';
    ogLinks.forEach(s => {
      if (s.show && s.link.trim()) {
        const svg = SVG_ICONS[s.icon] || '';
        linksHTML +=
          `<a href="${esc(s.link)}" data-brand="${esc(s.brand)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(s.label)}" title="${esc(s.label)}">` +
          `<i class="${esc(s.icon)}">${svg}</i></a>`;
      }
    });

    if (!linksHTML.trim()) return;

    const ogBar = document.createElement('nav');
    ogBar.id = 'og-social-bar';
    ogBar.setAttribute('aria-label', 'Redes sociais');
    ogBar.innerHTML = linksHTML;
    document.body.appendChild(ogBar);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ogCriarBarra);
  } else {
    ogCriarBarra();
  }
})();

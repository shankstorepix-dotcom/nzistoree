'use strict';
/* ==========================================================
   Nzi Store · constelação 3D vermelha de fundo
   - Canvas 2D com projeção em perspectiva (sem dependências externas).
   - O campo gira e se inclina seguindo o cursor; estrelas próximas ao
     cursor se ligam a ele e brilham mais.
   - Puramente cosmético: nenhuma coordenada é enviada ou armazenada.
   - Respeita prefers-reduced-motion e pausa com a aba oculta.
   ========================================================== */
(() => {
  const canvas = document.createElement('canvas');
  canvas.className = 'constellation-bg';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return;

  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const lowPower = (navigator.hardwareConcurrency || 8) <= 4;
  const FOCAL = 520;          // distância focal da câmera virtual
  const DEPTH = 900;          // profundidade do volume de estrelas
  const LINK = 175;           // distância 3D máxima para ligar estrelas
  const CURSOR_LINK = 190;    // raio (px) de ligação com o cursor

  let width = 0, height = 0, dpr = 1, stars = [], frame = 0, last = 0;
  const pointer = { x: 0, y: 0, nx: 0, ny: 0, active: false };
  const view = { yaw: 0, pitch: 0, shiftX: 0, shiftY: 0 };

  /* Sprite de brilho pré-renderizado: muito mais barato que shadowBlur. */
  const glow = document.createElement('canvas');
  glow.width = glow.height = 64;
  const g = glow.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, 'rgba(255,235,238,1)');
  grad.addColorStop(0.18, 'rgba(255,70,90,0.95)');
  grad.addColorStop(0.45, 'rgba(225,29,46,0.35)');
  grad.addColorStop(1, 'rgba(225,29,46,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);

  function populate() {
    const area = width * height;
    const target = Math.round(Math.min(lowPower ? 90 : 150, Math.max(45, area / (lowPower ? 16000 : 10000))));
    const spanX = width * 0.75, spanY = height * 0.75;
    stars = Array.from({ length: target }, () => ({
      x: (Math.random() * 2 - 1) * spanX,
      y: (Math.random() * 2 - 1) * spanY,
      z: (Math.random() * 2 - 1) * DEPTH * 0.5,
      vx: (Math.random() - 0.5) * 0.12,
      vy: (Math.random() - 0.5) * 0.12,
      vz: (Math.random() - 0.5) * 0.12,
      size: 0.6 + Math.random() * 1.4,
      twinkle: Math.random() * Math.PI * 2,
      sx: 0, sy: 0, scale: 0, depth: 0, visible: false
    }));
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, lowPower ? 1 : 1.5);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    populate();
    if (reduced.matches) draw(performance.now(), true);
  }

  function project(now, still) {
    const cy = Math.cos(view.yaw), sy = Math.sin(view.yaw);
    const cp = Math.cos(view.pitch), sp = Math.sin(view.pitch);
    const halfX = width * 0.75, halfY = height * 0.75, halfZ = DEPTH * 0.5;
    const cx = width / 2 + view.shiftX, cyScreen = height / 2 + view.shiftY;
    for (const s of stars) {
      if (!still) {
        s.x += s.vx; s.y += s.vy; s.z += s.vz;
        if (s.x > halfX) s.x = -halfX; else if (s.x < -halfX) s.x = halfX;
        if (s.y > halfY) s.y = -halfY; else if (s.y < -halfY) s.y = halfY;
        if (s.z > halfZ) s.z = -halfZ; else if (s.z < -halfZ) s.z = halfZ;
      }
      // Rotação yaw (eixo Y) e pitch (eixo X).
      const x1 = s.x * cy - s.z * sy;
      const z1 = s.x * sy + s.z * cy;
      const y1 = s.y * cp - z1 * sp;
      const z2 = s.y * sp + z1 * cp;
      const depth = z2 + FOCAL + halfZ;
      s.visible = depth > 40;
      if (!s.visible) continue;
      s.scale = FOCAL / depth;
      s.sx = cx + x1 * s.scale;
      s.sy = cyScreen + y1 * s.scale;
      s.rx = x1; s.ry = y1; s.rz = z2;
      s.depth = Math.max(0, Math.min(1, 1 - (z2 + halfZ) / DEPTH)); // 1 = perto
      s.light = 0.55 + 0.45 * Math.sin(now * 0.0016 + s.twinkle);
    }
  }

  function draw(now, still = false) {
    // Suaviza a câmera em direção ao cursor (com leve rotação automática).
    const auto = still ? 0 : now * 0.00004;
    const targetYaw = pointer.nx * 0.55 + auto;
    const targetPitch = -pointer.ny * 0.35;
    const ease = still ? 1 : 0.045;
    view.yaw += (targetYaw - view.yaw) * ease;
    view.pitch += (targetPitch - view.pitch) * ease;
    view.shiftX += (pointer.nx * -28 - view.shiftX) * ease;
    view.shiftY += (pointer.ny * -18 - view.shiftY) * ease;

    project(now, still);
    ctx.clearRect(0, 0, width, height);
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineWidth = 1;

    // Ligações entre estrelas próximas no espaço 3D.
    const linkSq = LINK * LINK;
    for (let i = 0; i < stars.length; i++) {
      const a = stars[i];
      if (!a.visible) continue;
      for (let j = i + 1; j < stars.length; j++) {
        const b = stars[j];
        if (!b.visible) continue;
        const dx = a.rx - b.rx, dy = a.ry - b.ry, dz = a.rz - b.rz;
        const d2 = dx * dx + dy * dy + dz * dz;
        if (d2 > linkSq) continue;
        const alpha = (1 - Math.sqrt(d2) / LINK) * (0.12 + 0.38 * Math.min(a.depth, b.depth));
        ctx.strokeStyle = `rgba(255,45,66,${alpha.toFixed(3)})`;
        ctx.beginPath();
        ctx.moveTo(a.sx, a.sy);
        ctx.lineTo(b.sx, b.sy);
        ctx.stroke();
      }
    }

    // Ligações com o cursor.
    if (pointer.active && !still) {
      for (const s of stars) {
        if (!s.visible) continue;
        const dx = s.sx - pointer.x, dy = s.sy - pointer.y;
        const dist = Math.hypot(dx, dy);
        if (dist > CURSOR_LINK) continue;
        const k = 1 - dist / CURSOR_LINK;
        s.light = Math.min(1.6, s.light + k * 0.9);
        ctx.strokeStyle = `rgba(255,95,110,${(k * 0.55).toFixed(3)})`;
        ctx.beginPath();
        ctx.moveTo(pointer.x, pointer.y);
        ctx.lineTo(s.sx, s.sy);
        ctx.stroke();
      }
      const halo = 46;
      ctx.globalAlpha = 0.35;
      ctx.drawImage(glow, pointer.x - halo / 2, pointer.y - halo / 2, halo, halo);
      ctx.globalAlpha = 1;
    }

    // Estrelas.
    for (const s of stars) {
      if (!s.visible) continue;
      const r = s.size * s.scale * 9 * (0.6 + s.depth * 0.6);
      ctx.globalAlpha = Math.min(1, (0.25 + 0.75 * s.depth) * s.light);
      ctx.drawImage(glow, s.sx - r / 2, s.sy - r / 2, r, r);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  function loop(now) {
    frame = 0;
    if (document.hidden || reduced.matches) return;
    // Limita a ~60 fps mesmo em telas de 120/144 Hz.
    if (now - last >= 15) { last = now; draw(now); }
    frame = requestAnimationFrame(loop);
  }
  function start() {
    if (!frame && !document.hidden && !reduced.matches) frame = requestAnimationFrame(loop);
    if (reduced.matches) draw(performance.now(), true);
  }
  function stop() { if (frame) cancelAnimationFrame(frame); frame = 0; }

  function track(x, y) {
    pointer.x = x; pointer.y = y; pointer.active = true;
    pointer.nx = (x / width) * 2 - 1;
    pointer.ny = (y / height) * 2 - 1;
  }
  window.addEventListener('pointermove', e => track(e.clientX, e.clientY), { passive: true });
  window.addEventListener('pointerdown', e => track(e.clientX, e.clientY), { passive: true });
  document.addEventListener('pointerleave', () => { pointer.active = false; });
  window.addEventListener('blur', () => { pointer.active = false; });

  let resizeTimer = 0;
  window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(resize, 150); });
  document.addEventListener('visibilitychange', () => (document.hidden ? stop() : start()));
  reduced.addEventListener('change', () => { stop(); start(); });

  resize();
  start();

  /* ---------- Refinos de interface ligados ao cursor ---------- */
  // Spotlight nos cards: só atualiza variáveis CSS do card sob o cursor.
  document.addEventListener('pointermove', e => {
    const card = e.target instanceof Element ? e.target.closest('.card, .tile, .pay-item') : null;
    if (!card) return;
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--mx', `${e.clientX - rect.left}px`);
    card.style.setProperty('--my', `${e.clientY - rect.top}px`);
  }, { passive: true });

  // Revelação suave das seções conforme a rolagem (conteúdo visível sem JS).
  if (!reduced.matches && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    const watch = () => document.querySelectorAll('#app section.block:not(.reveal)').forEach(el => {
      el.classList.add('reveal');
      observer.observe(el);
    });
    const app = document.getElementById('app');
    if (app) new MutationObserver(watch).observe(app, { childList: true });
    watch();
  }
})();

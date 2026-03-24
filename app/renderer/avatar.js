/**
 * avatar.js — Animações do avatar (efeitos de partículas, lip-sync, brilho)
 */

class AvatarController {
  constructor() {
    this.avatarImg  = document.getElementById('avatar-img');
    this.fxCanvas   = document.getElementById('fx-canvas');
    this.mouthCanvas = document.getElementById('mouth-canvas');
    this.fxCtx      = this.fxCanvas.getContext('2d');
    this.mouthCtx   = this.mouthCanvas.getContext('2d');

    this.state = 'idle'; // idle | listening | thinking | speaking
    this.particles = [];
    this.mouthOpen = 0;      // 0.0 – 1.0
    this.mouthTarget = 0;
    this.animFrame = null;
    this.lipSyncData = [];   // array de amplitudes
    this.lipSyncIndex = 0;

    this._resize();
    window.addEventListener('resize', () => this._resize());
    this._loop();
  }

  // ─── Redimensiona canvas ao tamanho da janela ───────────────────────────
  _resize() {
    const W = window.innerWidth;
    const H = window.innerHeight;

    this.fxCanvas.width  = W;
    this.fxCanvas.height = H;

    // Boca: pequeno canvas centralizado sobre a área da boca da personagem
    const mouthW = Math.round(W * 0.12);
    const mouthH = Math.round(mouthW * 0.5);
    this.mouthCanvas.width  = mouthW;
    this.mouthCanvas.height = mouthH;

    this._positionMouthCanvas();
  }

  _positionMouthCanvas() {
    const imgRect = this.avatarImg.getBoundingClientRect();
    const cfg = window._avatarConfig || { mouth_y_offset: 0.38, mouth_x_offset: 0.5 };

    const cx = imgRect.left + imgRect.width * cfg.mouth_x_offset;
    const cy = imgRect.top  + imgRect.height * cfg.mouth_y_offset;

    const mW = this.mouthCanvas.width;
    const mH = this.mouthCanvas.height;

    this.mouthCanvas.style.left = `${Math.round(cx - mW / 2)}px`;
    this.mouthCanvas.style.top  = `${Math.round(cy - mH / 2)}px`;
    this.mouthCanvas.style.position = 'fixed';
  }

  // ─── Loop de animação principal ─────────────────────────────────────────
  _loop() {
    this.animFrame = requestAnimationFrame(() => this._loop());

    const W = this.fxCanvas.width;
    const H = this.fxCanvas.height;
    this.fxCtx.clearRect(0, 0, W, H);

    if (this.state === 'listening') this._drawListeningFx();
    if (this.state === 'speaking')  this._drawSpeakingFx();

    this._updateParticles();
    this._drawParticles();
    this._updateMouth();
    this._drawMouth();
  }

  // ─── Efeito de escuta (ondas azuis) ─────────────────────────────────────
  _drawListeningFx() {
    const ctx = this.fxCtx;
    const W = this.fxCanvas.width;
    const H = this.fxCanvas.height;
    const t = Date.now() / 1000;
    const cx = W / 2;
    const cy = H * 0.72;

    for (let i = 3; i >= 1; i--) {
      const r = 40 + i * 28 + Math.sin(t * 2 + i) * 6;
      const alpha = 0.18 - i * 0.04;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(60, 140, 255, ${alpha})`;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }

  // ─── Efeito de fala (onda rosa/vermelha) ────────────────────────────────
  _drawSpeakingFx() {
    const ctx = this.fxCtx;
    const W = this.fxCanvas.width;
    const H = this.fxCanvas.height;
    const t = Date.now() / 600;
    const amplitude = 6 + this.mouthOpen * 10;

    ctx.beginPath();
    ctx.moveTo(0, H * 0.78);
    for (let x = 0; x <= W; x += 4) {
      const y = H * 0.78 + Math.sin((x / W) * Math.PI * 6 + t) * amplitude;
      ctx.lineTo(x, y);
    }
    ctx.strokeStyle = `rgba(220, 40, 100, 0.35)`;
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // ─── Partículas ─────────────────────────────────────────────────────────
  _spawnParticle(type) {
    const W = window.innerWidth;
    const H = window.innerHeight;
    const colors = type === 'speaking'
      ? ['#e91e63', '#ff4081', '#f06292', '#c2185b']
      : ['#42a5f5', '#64b5f6', '#1e88e5', '#90caf9'];

    this.particles.push({
      x: W * (0.3 + Math.random() * 0.4),
      y: H * (0.5 + Math.random() * 0.3),
      vx: (Math.random() - 0.5) * 1.4,
      vy: -(0.5 + Math.random() * 1.5),
      r: 2 + Math.random() * 4,
      alpha: 0.8,
      color: colors[Math.floor(Math.random() * colors.length)],
    });

    if (this.particles.length > 60) this.particles.shift();
  }

  _updateParticles() {
    const isActive = this.state === 'speaking' || this.state === 'listening';
    if (isActive && Math.random() < 0.25) {
      this._spawnParticle(this.state);
    }

    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.alpha -= 0.015;
      if (p.alpha <= 0) this.particles.splice(i, 1);
    }
  }

  _drawParticles() {
    const ctx = this.fxCtx;
    for (const p of this.particles) {
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.globalAlpha = p.alpha;
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  // ─── Lip-sync (boca animada) ─────────────────────────────────────────────
  _updateMouth() {
    if (this.state === 'speaking' && this.lipSyncData.length > 0) {
      const idx = Math.floor(this.lipSyncIndex) % this.lipSyncData.length;
      this.mouthTarget = this.lipSyncData[idx];
      this.lipSyncIndex += 0.8;
    } else if (this.state === 'listening') {
      // Pequena animação aleatória ao ouvir
      this.mouthTarget = 0.1 + Math.random() * 0.15;
    } else {
      this.mouthTarget = 0;
    }

    // Suavização
    this.mouthOpen += (this.mouthTarget - this.mouthOpen) * 0.25;
  }

  _drawMouth() {
    const ctx = this.mouthCtx;
    const W = this.mouthCanvas.width;
    const H = this.mouthCanvas.height;
    ctx.clearRect(0, 0, W, H);

    if (this.mouthOpen < 0.02) return;

    const cx = W / 2;
    const cy = H / 2;
    const rx = W * 0.42;
    const ry = H * 0.38 * this.mouthOpen;

    // Sombra interior
    ctx.beginPath();
    ctx.ellipse(cx, cy + ry * 0.1, rx, ry + 1, 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(10, 0, 15, 0.7)';
    ctx.fill();

    // Lábio superior
    ctx.beginPath();
    ctx.moveTo(cx - rx, cy);
    ctx.bezierCurveTo(cx - rx * 0.5, cy - ry * 0.9, cx + rx * 0.5, cy - ry * 0.9, cx + rx, cy);
    ctx.strokeStyle = 'rgba(160, 40, 70, 0.9)';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Lábio inferior
    ctx.beginPath();
    ctx.moveTo(cx - rx, cy);
    ctx.bezierCurveTo(cx - rx * 0.5, cy + ry * 1.4, cx + rx * 0.5, cy + ry * 1.4, cx + rx, cy);
    ctx.strokeStyle = 'rgba(160, 40, 70, 0.9)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // ─── API pública ─────────────────────────────────────────────────────────
  setState(state) {
    this.state = state;
    this.avatarImg.className = '';

    if (state === 'speaking')  this.avatarImg.classList.add('speaking');
    if (state === 'listening') this.avatarImg.classList.add('listening');

    if (state !== 'speaking') {
      this.lipSyncData  = [];
      this.lipSyncIndex = 0;
      this.mouthTarget  = 0;
    }
  }

  setLipSync(amplitudes) {
    this.lipSyncData  = amplitudes;
    this.lipSyncIndex = 0;
  }
}

// ─── Remoção de fundo branco (flood-fill a partir das bordas) ──────────────
function removeWhiteBackground(img, tolerance = 28) {
  const canvas = document.createElement('canvas');
  canvas.width  = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);

  const W = canvas.width;
  const H = canvas.height;
  const imageData = ctx.getImageData(0, 0, W, H);
  const data      = imageData.data;
  const visited   = new Uint8Array(W * H);
  const queue     = [];

  const isNearWhite = (i) => {
    return data[i] > (255 - tolerance) &&
           data[i+1] > (255 - tolerance) &&
           data[i+2] > (255 - tolerance);
  };

  // Semeia toda a borda da imagem
  for (let x = 0; x < W; x++) {
    for (const y of [0, H - 1]) {
      const idx = y * W + x;
      if (!visited[idx]) { visited[idx] = 1; queue.push(idx); }
    }
  }
  for (let y = 0; y < H; y++) {
    for (const x of [0, W - 1]) {
      const idx = y * W + x;
      if (!visited[idx]) { visited[idx] = 1; queue.push(idx); }
    }
  }

  // BFS — percorre pixels conectados que sejam brancos
  while (queue.length > 0) {
    const idx = queue.pop();
    const pi  = idx * 4;

    if (!isNearWhite(pi)) continue;

    // Torna o pixel transparente com suavização nas bordas
    const dist = Math.min(
      idx % W, W - 1 - (idx % W),
      Math.floor(idx / W), H - 1 - Math.floor(idx / W)
    );
    data[pi + 3] = dist < 2 ? 0 : 0;  // totalmente transparente

    const x = idx % W;
    const y = Math.floor(idx / W);
    for (const [dx, dy] of [[-1,0],[1,0],[0,-1],[0,1]]) {
      const nx = x + dx, ny = y + dy;
      if (nx >= 0 && nx < W && ny >= 0 && ny < H) {
        const nidx = ny * W + nx;
        if (!visited[nidx]) { visited[nidx] = 1; queue.push(nidx); }
      }
    }
  }

  ctx.putImageData(imageData, 0, 0);
  return canvas.toDataURL('image/png');
}

// ─── Inicialização ──────────────────────────────────────────────────────────
function initAvatar() {
  const img = document.getElementById('avatar-img');
  try {
    const processed = removeWhiteBackground(img);
    img.src = processed;
  } catch (e) {
    // CORS ou outro erro — usa a imagem original
    console.warn('[Avatar] Não foi possível remover fundo:', e);
  }
  window.avatarCtrl = new AvatarController();
}

window.avatarCtrl = null;
const _avatarImg = document.getElementById('avatar-img');
if (_avatarImg.complete && _avatarImg.naturalWidth > 0) {
  initAvatar();
} else {
  _avatarImg.addEventListener('load', initAvatar);
}

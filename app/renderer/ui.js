/**
 * ui.js — Lógica de interface: WebSocket com backend, controles, estado
 */

const WS_URL  = 'ws://localhost:8765/ws';
const RECONNECT_DELAY = 3000;

let ws = null;
let isListening      = false;
let isSpeaking       = false;
let config           = {};
let chatHideTimer    = null;
let resetBubbleTimer = null;   // tracked so openYaraBubble() can cancel it
let twTimer          = null;

// ─── Elementos ──────────────────────────────────────────────────────────────
const btnListen        = document.getElementById('btn-listen');
const btnStop          = document.getElementById('btn-stop');
const statusDot        = document.getElementById('status-dot');
const statusText       = document.getElementById('status-text');
const yaraBubble       = document.getElementById('yara-bubble');
const userBubble       = document.getElementById('user-bubble');
const userMsgEl        = document.getElementById('user-msg');
const typingEl         = document.getElementById('typing-indicator');
const assistantMsgEl   = document.getElementById('assistant-msg');
const btnMinimize      = document.getElementById('btn-minimize');

// ─── Inicialização ──────────────────────────────────────────────────────────
async function init() {
  if (window.__TAURI__) {
    config = await window.__TAURI__.core.invoke('get_config');
    window._avatarConfig = config.avatar;
  }
  connectWS();
  setupControls();
  setupHotkeys();
  initAvatarFlip();
}

// ─── WebSocket ───────────────────────────────────────────────────────────────
function connectWS() {
  setStatus('connecting', 'Conectando...');
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setStatus('idle', 'Pronta');
    console.log('[WS] Conectado ao backend');
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleMessage(msg);
  };

  ws.onerror = (err) => {
    console.error('[WS] Erro:', err);
  };

  ws.onclose = () => {
    setStatus('error', 'Desconectada');
    console.warn('[WS] Conexão encerrada, reconectando...');
    setTimeout(connectWS, RECONNECT_DELAY);
  };
}

function sendWS(type, payload = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, ...payload }));
  }
}

// ─── Mensagens do backend ─────────────────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {
    case 'listening_start':
      setStatus('listening', 'Ouvindo...');
      window.avatarCtrl?.setState('listening');
      isListening = true;
      btnListen.classList.add('active');
      resetBubbleContent();
      break;

    case 'listening_stop':
      setStatus('thinking', 'Pensando...');
      window.avatarCtrl?.setState('thinking');
      isListening = false;
      btnListen.classList.remove('active');
      showTyping();
      break;

    case 'transcript':
      showUserMsg(msg.text);
      break;

    case 'reply_text':
      // informativo — exibição agora é controlada por phrase_start
      break;

    case 'speaking_start':
      setStatus('speaking', 'Falando...');
      window.avatarCtrl?.setState('speaking');
      isSpeaking = true;
      btnStop.classList.remove('hidden');
      break;

    case 'phrase_start':
      showPhrase(msg.text, msg.lip_sync);
      break;

    case 'phrase_end':
      endPhrase();
      break;

    case 'speaking_stop':
      setStatus('idle', 'Pronta');
      window.avatarCtrl?.setState('idle');
      isSpeaking = false;
      btnStop.classList.add('hidden');
      scheduleBubbleHide(7000);
      break;

    case 'model_loading':
      if (!msg.done) {
        setStatus('thinking', `Carregando ${msg.provider}...`);
        window.avatarCtrl?.setState('thinking');
      } else {
        setStatus('idle', 'Pronta');
        window.avatarCtrl?.setState('idle');
      }
      break;

    case 'history_cleared':
      hideBubble(true);
      break;

    case 'error':
      setStatus('error', 'Erro');
      showAssistantMsg(`❌ ${msg.message}`);
      window.avatarCtrl?.setState('idle');
      scheduleBubbleHide(5000);
      break;

    default:
      console.log('[WS] msg desconhecida:', msg);
  }
}

// ─── Controles ────────────────────────────────────────────────────────────
function setupControls() {
  btnListen.addEventListener('click', toggleListen);
  btnStop.addEventListener('click', () => sendWS('stop_speaking'));
  btnMinimize.addEventListener('click', () => window.__TAURI__?.core.invoke('minimize_to_tray'));
  document.getElementById('btn-reset-pos')?.addEventListener('click', () => {
    window.__TAURI__?.core.invoke('reset_position');
  });
  setupDebugPanel();
  setupResize();
}

function setupDebugPanel() {
  const btnToggle   = document.getElementById('btn-debug-toggle');
  const panel       = document.getElementById('debug-panel');
  const thinkInput  = document.getElementById('debug-think-input');
  const speakInput  = document.getElementById('debug-speak-input');
  const btnThink    = document.getElementById('btn-debug-think');
  const btnSpeak    = document.getElementById('btn-debug-speak');

  btnToggle.addEventListener('click', () => {
    panel.classList.toggle('hidden');
  });

  function sendDebugThink() {
    const text = thinkInput.value.trim();
    if (!text) return;
    sendWS('debug_think', { text });
    thinkInput.value = '';
  }

  function sendDebugSpeak() {
    const text = speakInput.value.trim();
    if (!text) return;
    sendWS('debug_speak', { text });
    speakInput.value = '';
  }

  btnThink.addEventListener('click', sendDebugThink);
  btnSpeak.addEventListener('click', sendDebugSpeak);

  thinkInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendDebugThink(); });
  speakInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendDebugSpeak(); });
}

function setupHotkeys() {
  // Eventos emitidos pelo Rust via Tauri
  window.__TAURI__?.event.listen('hotkey-listen', () => toggleListen());
  window.__TAURI__?.event.listen('backend-disconnected', () => setStatus('error', 'Backend offline'));

  // Tecla Escape para parar
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') sendWS('stop_speaking');
  });
}

function toggleListen() {
  if (isSpeaking) {
    sendWS('stop_speaking');
    return;
  }
  if (isListening) {
    sendWS('stop_listening');
  } else {
    sendWS('start_listening');
  }
}

// ─── UI Helpers ──────────────────────────────────────────────────────────
function setStatus(state, text) {
  statusDot.className = state !== 'idle' && state !== 'connecting' ? state : '';
  statusText.textContent = text;
}

// ─── Balões de fala ───────────────────────────────────────────────────────
function openYaraBubble() {
  if (chatHideTimer) { clearTimeout(chatHideTimer); chatHideTimer = null; }
  // Cancel any pending resetBubbleContent so it doesn't clear new text
  if (resetBubbleTimer) { clearTimeout(resetBubbleTimer); resetBubbleTimer = null; }
  yaraBubble.classList.add('bubble-visible');
}

function openUserBubble() {
  userBubble.classList.add('bubble-visible');
}

function hideBubble(immediately = false) {
  if (chatHideTimer) { clearTimeout(chatHideTimer); chatHideTimer = null; }
  if (resetBubbleTimer) { clearTimeout(resetBubbleTimer); resetBubbleTimer = null; }
  stopTypeWriter();
  yaraBubble.classList.remove('bubble-visible');
  userBubble.classList.remove('bubble-visible');
  resetBubbleTimer = setTimeout(() => { resetBubbleContent(); resetBubbleTimer = null; }, immediately ? 0 : 380);
}

function scheduleBubbleHide(ms) {
  chatHideTimer = setTimeout(() => hideBubble(), ms);
}

function resetBubbleContent() {
  userMsgEl.textContent = '';
  userMsgEl.classList.remove('visible');
  typingEl.classList.remove('visible');
  assistantMsgEl.textContent = '';
  assistantMsgEl.classList.remove('visible');
}

function showUserMsg(text) {
  userMsgEl.textContent = 'você › ' + text;
  userMsgEl.classList.add('visible');
  openUserBubble();
}

function showTyping() {
  typingEl.classList.add('visible');
  assistantMsgEl.classList.remove('visible');
  openYaraBubble();
}

function showAssistantMsg(text) {
  typingEl.classList.remove('visible');
  assistantMsgEl.classList.add('visible');
  typeWriter(assistantMsgEl, text);
  openYaraBubble();
}

// Exibe uma frase individual (phrase_start)
function showPhrase(text, lipSync) {
  stopTypeWriter();
  typingEl.classList.remove('visible');
  assistantMsgEl.textContent = '';
  assistantMsgEl.classList.add('visible');
  typeWriter(assistantMsgEl, text);
  if (lipSync && lipSync.length) window.avatarCtrl?.setLipSync(lipSync);
  openYaraBubble();
}

// Esconde o balão entre frases (phrase_end)
function endPhrase() {
  yaraBubble.classList.remove('bubble-visible');
  stopTypeWriter();
}

// ─── Typewriter ───────────────────────────────────────────────────────────
function stopTypeWriter() {
  if (twTimer) { clearInterval(twTimer); twTimer = null; }
  // Remove cursor pendente
  const cursor = assistantMsgEl.querySelector('.tw-cursor');
  if (cursor) cursor.remove();
}

function typeWriter(el, text, speed = 22) {
  stopTypeWriter();
  el.textContent = '';
  const cursor = document.createElement('span');
  cursor.className = 'tw-cursor';
  el.appendChild(cursor);
  let i = 0;
  twTimer = setInterval(() => {
    if (i < text.length) {
      el.insertBefore(document.createTextNode(text[i++]), cursor);
    } else {
      clearInterval(twTimer);
      twTimer = null;
      cursor.remove();
    }
  }, speed);
}

// ─── Resize grip ─────────────────────────────────────────────────────────
function setupResize() {
  const grip = document.getElementById('resize-grip');
  if (!grip || !window.__TAURI__) return;

  let resizing = false;
  let startX, startY, startW, startH;

  grip.addEventListener('mousedown', async (e) => {
    if (e.button !== 0) return;
    resizing = true;
    startX = e.screenX;
    startY = e.screenY;
    const size = await window.__TAURI__.core.invoke('get_window_size');
    startW = size[0];
    startH = size[1];
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!resizing) return;
    window.__TAURI__.core.invoke('resize_window', {
      w: Math.max(180, startW + (e.screenX - startX)),
      h: Math.max(280, startH + (e.screenY - startY)),
    });
  });

  document.addEventListener('mouseup', () => {
    if (!resizing) return;
    resizing = false;
    window.__TAURI__.core.invoke('save_window_size');
  });
}

// ─── Orientação do avatar (vira para o centro da tela) ───────────────────
function updateAvatarFlip(windowX) {
  const screenMidX = window.screen.width / 2;
  const windowMidX = windowX + window.innerWidth / 2;
  document.getElementById('avatar-frame')
    .classList.toggle('flipped', windowMidX > screenMidX);
}

async function initAvatarFlip() {
  if (!window.__TAURI__) return;
  const pos = await window.__TAURI__.core.invoke('get_position');
  updateAvatarFlip(pos[0]);

  // Atualiza flip em tempo real durante drag nativo via OS
  window.__TAURI__.window.getCurrentWindow().onMoved(({ payload: position }) => {
    updateAvatarFlip(position.x / window.devicePixelRatio);
  });
}

// ─── Drag da janela pelo avatar ──────────────────────────────────────────
// Usa startDragging() do Tauri — drag nativo via OS, sem flood de IPC
(function setupDrag() {
  const frame = document.getElementById('avatar-frame');

  frame.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    if (!window.__TAURI__) return;

    window.__TAURI__.core.invoke('start_dragging');

    // Salva posição final ao soltar (mouseup pode não disparar — onMoved cobre o flip)
    document.addEventListener('mouseup', async () => {
      const pos = await window.__TAURI__.core.invoke('get_position').catch(() => null);
      if (pos) window.__TAURI__.core.invoke('save_position', { x: pos[0], y: pos[1] });
    }, { once: true });
  });
})();

// ─── Boot ────────────────────────────────────────────────────────────────
// window.__TAURI__ é injetado pelo Tauri antes de DOMContentLoaded
document.addEventListener('DOMContentLoaded', init);

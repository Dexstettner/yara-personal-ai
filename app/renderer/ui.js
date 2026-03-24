/**
 * ui.js — Lógica de interface: WebSocket com backend, controles, estado
 */

const WS_URL  = 'ws://localhost:8765/ws';
const RECONNECT_DELAY = 3000;

let ws = null;
let isListening = false;
let isSpeaking  = false;
let config      = {};
let chatHideTimer = null;

// ─── Elementos ──────────────────────────────────────────────────────────────
const btnListen     = document.getElementById('btn-listen');
const btnStop       = document.getElementById('btn-stop');
const statusDot     = document.getElementById('status-dot');
const statusText    = document.getElementById('status-text');
const chatBubble    = document.getElementById('chat-bubble');
const bubbleText    = document.getElementById('bubble-text');
const btnMinimize   = document.getElementById('btn-minimize');

// ─── Inicialização ──────────────────────────────────────────────────────────
async function init() {
  if (window.electronAPI) {
    config = await window.electronAPI.getConfig();
    window._avatarConfig = config.avatar;
  }
  connectWS();
  setupControls();
  setupHotkeys();
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
      break;

    case 'listening_stop':
      setStatus('thinking', 'Pensando...');
      window.avatarCtrl?.setState('thinking');
      isListening = false;
      btnListen.classList.remove('active');
      break;

    case 'transcript':
      showBubble(`Você: ${msg.text}`, false);
      break;

    case 'reply_text':
      showBubble(msg.text, true);
      break;

    case 'speaking_start':
      setStatus('speaking', 'Falando...');
      window.avatarCtrl?.setState('speaking');
      isSpeaking = true;
      btnStop.classList.remove('hidden');
      if (msg.lip_sync) window.avatarCtrl?.setLipSync(msg.lip_sync);
      break;

    case 'speaking_stop':
      setStatus('idle', 'Pronta');
      window.avatarCtrl?.setState('idle');
      isSpeaking = false;
      btnStop.classList.add('hidden');
      scheduleBubbleHide(6000);
      break;

    case 'error':
      setStatus('error', 'Erro');
      showBubble(`Erro: ${msg.message}`, false);
      window.avatarCtrl?.setState('idle');
      break;

    default:
      console.log('[WS] msg desconhecida:', msg);
  }
}

// ─── Controles ────────────────────────────────────────────────────────────
function setupControls() {
  btnListen.addEventListener('click', toggleListen);
  btnStop.addEventListener('click', () => sendWS('stop_speaking'));
  btnMinimize.addEventListener('click', () => window.electronAPI?.minimizeToTray());
}

function setupHotkeys() {
  if (window.electronAPI) {
    window.electronAPI.onHotkeyListen(() => toggleListen());
    window.electronAPI.onBackendDisconnected(() => {
      setStatus('error', 'Backend offline');
    });
  }

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

function showBubble(text, isAssistant) {
  if (chatHideTimer) {
    clearTimeout(chatHideTimer);
    chatHideTimer = null;
  }
  bubbleText.textContent = text;
  chatBubble.classList.remove('hidden');
  chatBubble.style.borderColor = isAssistant
    ? 'rgba(180, 40, 100, 0.5)'
    : 'rgba(60, 100, 200, 0.4)';
}

function scheduleBubbleHide(ms) {
  chatHideTimer = setTimeout(() => {
    chatBubble.classList.add('hidden');
  }, ms);
}

// ─── Drag da janela pelo avatar ──────────────────────────────────────────
(function setupDrag() {
  const frame = document.getElementById('avatar-frame');
  let dragging = false;
  let startX, startY, winStartX, winStartY;

  frame.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    startX = e.screenX;
    startY = e.screenY;
    // Posição atual não disponível diretamente; backend Electron salva
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.screenX - startX;
    const dy = e.screenY - startY;
    // Electron não expõe moveTo diretamente no renderer sem IPC extra
    // Usamos CSS transform como fallback visual (limitado)
  });

  document.addEventListener('mouseup', () => { dragging = false; });
})();

// ─── Boot ────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);

const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, screen } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const CONFIG_PATH = path.join(__dirname, '..', 'config.json');
let config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));

let mainWindow = null;
let tray = null;
let backendProcess = null;

function createWindow() {
  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workAreaSize;

  const winW = config.avatar.window_width;
  const winH = config.avatar.window_height;

  const posX = config.avatar.position_x ?? width - winW - 20;
  const posY = config.avatar.position_y ?? height - winH - 20;

  mainWindow = new BrowserWindow({
    width: winW,
    height: winH,
    x: posX,
    y: posY,
    transparent: true,
    frame: false,
    alwaysOnTop: config.avatar.always_on_top,
    resizable: false,
    skipTaskbar: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,   // permite canvas ler imagens locais para remoção de fundo
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.setOpacity(config.avatar.opacity);

  // Permite arrastar a janela clicando na avatar
  mainWindow.on('closed', () => { mainWindow = null; });

  if (process.argv.includes('--dev')) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }
}

function createTray() {
  // Usa ícone padrão se não houver ico
  const iconPath = path.join(__dirname, '..', 'assets', 'icon.png');
  const fallback = path.join(__dirname, '..', 'assets', 'thinking.png');
  const trayIcon = fs.existsSync(iconPath) ? iconPath : fallback;

  tray = new Tray(trayIcon);
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Mostrar / Esconder', click: () => toggleWindow() },
    { type: 'separator' },
    { label: 'Sair', click: () => app.quit() },
  ]);
  tray.setToolTip('AI Assistant');
  tray.setContextMenu(contextMenu);
  tray.on('click', () => toggleWindow());
}

function toggleWindow() {
  if (!mainWindow) return;
  if (mainWindow.isVisible()) {
    mainWindow.hide();
  } else {
    mainWindow.show();
    mainWindow.focus();
  }
}

function startBackend() {
  const backendPath = path.join(__dirname, '..', 'backend', 'main.py');
  backendProcess = spawn('python', [backendPath], {
    cwd: path.join(__dirname, '..'),
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
  });

  backendProcess.stdout.on('data', (data) => {
    console.log('[Backend]', data.toString().trim());
  });

  backendProcess.stderr.on('data', (data) => {
    console.error('[Backend ERR]', data.toString().trim());
  });

  backendProcess.on('close', (code) => {
    console.log(`[Backend] encerrado com código ${code}`);
    if (mainWindow) {
      mainWindow.webContents.send('backend-disconnected');
    }
  });
}

app.whenReady().then(() => {
  createWindow();
  createTray();

  // Quando EXTERNAL_BACKEND=1, o backend já está rodando externamente (ex: Docker).
  // Electron apenas conecta ao WebSocket sem spawnar Python.
  if (!process.env.EXTERNAL_BACKEND) {
    startBackend();
  } else {
    console.log('[Backend] Modo externo — conectando ao backend em execução na porta 8765');
  }

  // Hotkey global para ativar escuta
  const hotkeyListen = config.app.hotkey_listen;
  globalShortcut.register(hotkeyListen, () => {
    if (mainWindow) mainWindow.webContents.send('hotkey-listen');
  });

  // Hotkey para mostrar/esconder
  const hotkeyToggle = config.app.hotkey_toggle;
  globalShortcut.register(hotkeyToggle, () => toggleWindow());

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    if (backendProcess) backendProcess.kill();
    app.quit();
  }
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (backendProcess) backendProcess.kill();
});

// IPC: salvar posição da janela
ipcMain.on('save-position', (event, { x, y }) => {
  config.avatar.position_x = x;
  config.avatar.position_y = y;
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
});

// IPC: obter posição atual da janela
ipcMain.handle('get-position', () => {
  return mainWindow ? mainWindow.getPosition() : [0, 0];
});

// IPC: mover janela (drag pelo avatar)
ipcMain.on('move-window', (event, { x, y }) => {
  if (mainWindow) mainWindow.setPosition(Math.round(x), Math.round(y));
});

// IPC: recarregar config
ipcMain.handle('get-config', () => {
  config = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
  return config;
});

// IPC: minimizar / fechar para tray
ipcMain.on('minimize-to-tray', () => {
  if (mainWindow) mainWindow.hide();
});

// IPC: obter tamanho atual da janela
ipcMain.handle('get-window-size', () => {
  return mainWindow ? mainWindow.getSize() : [400, 700];
});

// IPC: redimensionar janela (drag do resize-grip)
ipcMain.on('resize-window', (_, { w, h }) => {
  if (!mainWindow) return;
  const minW = 180, minH = 280, maxW = 900, maxH = 1400;
  mainWindow.setSize(
    Math.round(Math.max(minW, Math.min(maxW, w))),
    Math.round(Math.max(minH, Math.min(maxH, h)))
  );
});

// IPC: salvar tamanho atual em config.json
ipcMain.on('save-window-size', () => {
  if (!mainWindow) return;
  const [w, h] = mainWindow.getSize();
  config.avatar.window_width  = w;
  config.avatar.window_height = h;
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
});

// IPC: reposicionar janela para canto inferior direito
ipcMain.on('reset-position', () => {
  if (!mainWindow) return;
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  const [w, h] = mainWindow.getSize();
  mainWindow.setPosition(width - w - 20, height - h - 20);
  config.avatar.position_x = width - w - 20;
  config.avatar.position_y = height - h - 20;
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
});

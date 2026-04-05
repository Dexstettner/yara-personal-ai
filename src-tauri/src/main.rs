#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde_json::Value;
use std::sync::Mutex;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, State};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

// ─── App State ───────────────────────────────────────────────────────────────
struct AppState {
    config_path: Mutex<std::path::PathBuf>,
    backend_process: Mutex<Option<std::process::Child>>,
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/// Find the project root by walking up from the exe until config.json is found.
/// Works regardless of CWD (e.g. `cargo tauri dev` runs from src-tauri/).
fn find_project_root() -> std::path::PathBuf {
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().unwrap_or(exe.as_path()).to_path_buf();
        for _ in 0..6 {
            if dir.join("config.json").exists() {
                return dir;
            }
            match dir.parent() {
                Some(p) => dir = p.to_path_buf(),
                None => break,
            }
        }
    }
    std::env::current_dir().unwrap_or_default()
}

fn load_config(path: &std::path::Path) -> Result<Value, String> {
    let data = std::fs::read_to_string(path)
        .map_err(|e| format!("read config: {e}"))?;
    serde_json::from_str(&data)
        .map_err(|e| format!("parse config: {e}"))
}

fn save_config(path: &std::path::Path, cfg: &Value) -> Result<(), String> {
    let data = serde_json::to_string_pretty(cfg)
        .map_err(|e| format!("serialize config: {e}"))?;
    std::fs::write(path, data)
        .map_err(|e| format!("write config: {e}"))
}

/// Convert "ctrl+space" → "Ctrl+Space"
fn fmt_shortcut(raw: &str) -> String {
    raw.split('+')
        .map(|part| {
            let s = part.trim();
            let mut chars = s.chars();
            match chars.next() {
                None => String::new(),
                Some(first) => first.to_uppercase().to_string() + chars.as_str(),
            }
        })
        .collect::<Vec<_>>()
        .join("+")
}

// ─── Tauri Commands ──────────────────────────────────────────────────────────

/// Starts native OS drag-move — no IPC per-frame overhead.
#[tauri::command]
fn start_dragging(app: AppHandle) -> Result<(), String> {
    let win = app.get_webview_window("main").ok_or("window not found")?;
    win.start_dragging().map_err(|e| e.to_string())
}

#[tauri::command]
fn get_config(state: State<AppState>) -> Result<Value, String> {
    let path = state.config_path.lock().unwrap();
    load_config(&path)
}

/// Returns window position in logical (CSS) pixels.
#[tauri::command]
fn get_position(app: AppHandle) -> Result<(f64, f64), String> {
    let win = app.get_webview_window("main").ok_or("window not found")?;
    let phys = win.outer_position().map_err(|e| e.to_string())?;
    let scale = win.scale_factor().map_err(|e| e.to_string())?;
    Ok((phys.x as f64 / scale, phys.y as f64 / scale))
}

/// Moves window; x/y are logical (CSS) pixels from JS screenX/screenY.
#[tauri::command]
fn move_window(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    let win = app.get_webview_window("main").ok_or("window not found")?;
    win.set_position(LogicalPosition::new(x, y))
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn save_position(state: State<AppState>, app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    let path = state.config_path.lock().unwrap().clone();
    let mut cfg = load_config(&path)?;
    cfg["avatar"]["position_x"] = Value::from(x.round() as i64);
    cfg["avatar"]["position_y"] = Value::from(y.round() as i64);
    save_config(&path, &cfg)?;
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.set_position(LogicalPosition::new(x, y));
    }
    Ok(())
}

/// Returns window size in logical pixels.
#[tauri::command]
fn get_window_size(app: AppHandle) -> Result<(u32, u32), String> {
    let win = app.get_webview_window("main").ok_or("window not found")?;
    let phys = win.outer_size().map_err(|e| e.to_string())?;
    let scale = win.scale_factor().map_err(|e| e.to_string())?;
    Ok(((phys.width as f64 / scale) as u32, (phys.height as f64 / scale) as u32))
}

#[tauri::command]
fn resize_window(app: AppHandle, w: u32, h: u32) -> Result<(), String> {
    let win = app.get_webview_window("main").ok_or("window not found")?;
    win.set_size(LogicalSize::new(w as f64, h as f64))
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn save_window_size(state: State<AppState>, app: AppHandle) -> Result<(), String> {
    let path = state.config_path.lock().unwrap().clone();
    let win = app.get_webview_window("main").ok_or("window not found")?;
    let phys = win.outer_size().map_err(|e| e.to_string())?;
    let scale = win.scale_factor().map_err(|e| e.to_string())?;
    let w = (phys.width as f64 / scale) as u32;
    let h = (phys.height as f64 / scale) as u32;
    let mut cfg = load_config(&path)?;
    cfg["avatar"]["window_width"] = Value::from(w);
    cfg["avatar"]["window_height"] = Value::from(h);
    save_config(&path, &cfg)
}

#[tauri::command]
fn minimize_to_tray(app: AppHandle) -> Result<(), String> {
    let win = app.get_webview_window("main").ok_or("window not found")?;
    win.hide().map_err(|e| e.to_string())
}

#[tauri::command]
fn reset_position(app: AppHandle, state: State<AppState>) -> Result<(), String> {
    let win = app.get_webview_window("main").ok_or("window not found")?;
    let scale = win.scale_factor().map_err(|e| e.to_string())?;
    let monitor = win.current_monitor()
        .map_err(|e| e.to_string())?
        .ok_or("no monitor found")?;
    let screen_w = monitor.size().width as f64 / scale;
    let screen_h = monitor.size().height as f64 / scale;
    let phys = win.outer_size().map_err(|e| e.to_string())?;
    let win_w = phys.width as f64 / scale;
    let win_h = phys.height as f64 / scale;
    let x = (screen_w - win_w - 20.0).max(0.0);
    let y = ((screen_h - win_h) / 2.0).max(0.0);
    win.set_position(LogicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    let path = state.config_path.lock().unwrap().clone();
    if let Ok(mut cfg) = load_config(&path) {
        cfg["avatar"]["position_x"] = Value::from(x.round() as i64);
        cfg["avatar"]["position_y"] = Value::from(y.round() as i64);
        let _ = save_config(&path, &cfg);
    }
    Ok(())
}

// ─── Main ─────────────────────────────────────────────────────────────────────
fn main() {
    let project_root = find_project_root();
    let config_path = project_root.join("config.json");
    println!("[Tauri] Raiz do projeto: {:?}", project_root);

    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(AppState {
            config_path: Mutex::new(config_path),
            backend_process: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            start_dragging,
            get_config,
            get_position,
            move_window,
            save_position,
            get_window_size,
            resize_window,
            save_window_size,
            minimize_to_tray,
            reset_position,
        ])
        .setup(|app| {
            // ── Load config ───────────────────────────────────────────────
            let cfg_path = app.state::<AppState>().config_path.lock().unwrap().clone();
            let cfg = load_config(&cfg_path).unwrap_or_default();

            let pos_x = cfg["avatar"]["position_x"].as_f64().unwrap_or(100.0);
            let pos_y = cfg["avatar"]["position_y"].as_f64().unwrap_or(100.0);
            let win_w = cfg["avatar"]["window_width"].as_f64().unwrap_or(400.0);
            let win_h = cfg["avatar"]["window_height"].as_f64().unwrap_or(700.0);
            let hk_listen = cfg["app"]["hotkey_listen"]
                .as_str()
                .map(fmt_shortcut)
                .unwrap_or_else(|| "Ctrl+Space".into());
            let hk_toggle = cfg["app"]["hotkey_toggle"]
                .as_str()
                .map(fmt_shortcut)
                .unwrap_or_else(|| "Ctrl+Shift+H".into());

            // ── Configure main window ─────────────────────────────────────
            // show() first so the HWND is active, then position/size are applied reliably
            let window = app.get_webview_window("main").unwrap();
            window.show()?;
            if let Err(e) = window.set_position(LogicalPosition::new(pos_x, pos_y)) {
                eprintln!("[Tauri] set_position falhou: {e}");
            } else {
                println!("[Tauri] Posição: ({pos_x}, {pos_y})");
            }
            if let Err(e) = window.set_size(LogicalSize::new(win_w, win_h)) {
                eprintln!("[Tauri] set_size falhou: {e}");
            }

            // ── Spawn Python backend ──────────────────────────────────────
            if std::env::var("EXTERNAL_BACKEND").is_err() {
                let root = cfg_path.parent()
                    .map(|p| p.to_path_buf())
                    .unwrap_or_else(find_project_root);
                match std::process::Command::new("python")
                    .arg("backend/main.py")
                    .current_dir(&root)
                    .stdout(std::process::Stdio::inherit())
                    .stderr(std::process::Stdio::inherit())
                    .spawn()
                {
                    Ok(child) => {
                        *app.state::<AppState>().backend_process.lock().unwrap() = Some(child);
                        println!("[Tauri] Python backend iniciado em {:?}", root);
                    }
                    Err(e) => eprintln!("[Tauri] Falha ao iniciar backend: {e}"),
                }
            }

            // ── System tray ───────────────────────────────────────────────
            let show = MenuItem::with_id(app, "show", "Mostrar", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Sair", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &sep, &quit])?;

            TrayIconBuilder::with_id("main-tray")
                .tooltip("Yara AI")
                .icon(tauri::include_image!("icons/32x32.png"))
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(w) = app.get_webview_window("main") {
                            if w.is_visible().unwrap_or(false) {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                    }
                })
                .build(app)?;

            // ── Global shortcuts ──────────────────────────────────────────
            let h_listen = app.handle().clone();
            app.global_shortcut()
                .on_shortcut(hk_listen.as_str(), move |_app, _sc, ev| {
                    if ev.state() == ShortcutState::Pressed {
                        let _ = h_listen.emit("hotkey-listen", ());
                    }
                })?;

            let h_toggle = app.handle().clone();
            app.global_shortcut()
                .on_shortcut(hk_toggle.as_str(), move |_app, _sc, ev| {
                    if ev.state() == ShortcutState::Pressed {
                        if let Some(w) = h_toggle.get_webview_window("main") {
                            if w.is_visible().unwrap_or(false) {
                                let _ = w.hide();
                            } else {
                                let _ = w.show();
                                let _ = w.set_focus();
                            }
                        }
                    }
                })?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(mut child) = app
                    .state::<AppState>()
                    .backend_process
                    .lock()
                    .unwrap()
                    .take()
                {
                    let _ = child.kill();
                }
            }
        });
}

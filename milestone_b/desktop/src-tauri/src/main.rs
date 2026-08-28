// NEXUS native shell (MILESTONE_H_TAURI_PLAN.md §2).
//
// The Rust side is process supervision only: spawn the Python control-plane
// server (`nexus-server`) as a managed sidecar, wait for its loopback port,
// point the WebView at it, and kill it on exit. No control-plane logic lives
// here.
#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent, Url};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const PORT: u16 = 8770;
const POLL_INTERVAL: Duration = Duration::from_millis(300);
const POLL_TRIES: u32 = 60; // ~18 s

struct Sidecar(Mutex<Option<CommandChild>>);

fn port_open(port: u16) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Sidecar(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();

            // per-user event-log DB
            let mut db = app
                .path()
                .app_local_data_dir()
                .expect("no app data dir");
            db.push("events.db");
            if let Some(parent) = db.parent() {
                let _ = std::fs::create_dir_all(parent);
            }

            let (mut rx, child) = app
                .shell()
                .sidecar("nexus-server")
                .expect("nexus-server sidecar missing")
                .args([
                    "--host",
                    "127.0.0.1",
                    "--port",
                    &PORT.to_string(),
                    "--db",
                    db.to_str().expect("non-utf8 db path"),
                ])
                .spawn()
                .expect("failed to spawn nexus-server");

            app.state::<Sidecar>().0.lock().unwrap().replace(child);

            // drain sidecar output into the Tauri log
            tauri::async_runtime::spawn(async move {
                while let Some(ev) = rx.recv().await {
                    match ev {
                        CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                            eprintln!("[nexus-server] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[nexus-server] exited: {:?}", payload);
                        }
                        _ => {}
                    }
                }
            });

            // wait for readiness on a background thread, then navigate the window
            std::thread::spawn(move || {
                for _ in 0..POLL_TRIES {
                    if port_open(PORT) {
                        if let Some(win) = handle.get_webview_window("main") {
                            if let Ok(url) = Url::parse(&format!("http://127.0.0.1:{PORT}")) {
                                let _ = win.navigate(url);
                            }
                        }
                        return;
                    }
                    std::thread::sleep(POLL_INTERVAL);
                }
                eprintln!("[nexus] sidecar not ready after {POLL_TRIES} tries; staying on splash");
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error building the NEXUS shell")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(child) = app_handle.state::<Sidecar>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });
}

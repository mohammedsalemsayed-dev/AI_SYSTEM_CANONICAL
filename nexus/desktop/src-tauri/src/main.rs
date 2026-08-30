// Thin binary entry. All logic lives in lib.rs (Tauri v2 layout: the lib is
// what mobile targets link against; the binary just calls into it).
#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

fn main() {
    nexus_desktop_lib::run()
}

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::WindowUrl;

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            tauri::WindowBuilder::new(app, "main")
                .title("ZigZag Terminal")
                .url(WindowUrl::External("http://localhost:8080".parse().unwrap()))
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

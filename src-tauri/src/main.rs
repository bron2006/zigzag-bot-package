// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::window::WindowUrl; // Правильний шлях до WindowUrl

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            tauri::WindowBuilder::new(app, "main")
                .title("ZigZag Terminal")
                .with_url(WindowUrl::External( // Правильний метод .with_url()
                    "http://localhost:8080".parse().unwrap(),
                ))
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
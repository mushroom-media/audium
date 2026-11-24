//! The audium app: the Svelte frontend (built with `--mode app`) in a Tauri window. It talks to
//! the audium server only over HTTP (see frontend/src/lib/api.ts); the only Rust commands are the
//! app's own updates (src/update.rs). The window has no system title bar: on Windows and Linux
//! the frontend draws its own with the window buttons (frontend/src/lib/components/WindowFrame.svelte,
//! tauri.windows.conf.json, tauri.linux.conf.json); on macOS the page reaches up under the title
//! bar and keeps the system's buttons (tauri.macos.conf.json). It uses the window permissions in
//! capabilities/default.json.

#[cfg(windows)]
mod recover;
#[cfg(desktop)]
mod update;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();

    #[cfg(desktop)]
    let builder = builder
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(update::HowToUpdate(update::Mode::detect()))
        .manage(update::Pending::default())
        .manage(update::Checking::default())
        .invoke_handler(tauri::generate_handler![
            update::update_mode,
            update::update_ready,
            update::update_now,
            update::update_check
        ]);

    // A second start brings the open window to the front instead of a second player.
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
        use tauri::Manager;
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.unminimize();
            let _ = window.show();
            let _ = window.set_focus();
        }
    }));

    // Links to other sites (the repository in Settings > About) open in the system browser.
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_opener::init());

    builder
        // Size and position of the window as they were when it was closed. Not the title bar: that
        // comes from the config (none of the system's), and a saved state of an older version would
        // bring the system title bar back.
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::all()
                        - tauri_plugin_window_state::StateFlags::DECORATIONS,
                )
                .build(),
        )
        .setup(|_app| {
            #[cfg(windows)]
            {
                use tauri::Manager;
                // First: exits the app when an update from last time is installed now.
                update::install_left_over(_app.handle());
                if let Some(window) = _app.get_webview_window("main") {
                    recover::reload_when_renderer_fails(&window);
                }
            }
            #[cfg(desktop)]
            update::watch(_app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running audium")
        .run(|_app, _event| {
            #[cfg(windows)]
            if let tauri::RunEvent::Exit = _event {
                update::install_on_exit(_app);
            }
        });
}

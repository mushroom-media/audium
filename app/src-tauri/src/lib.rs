//! The audium app: the Svelte frontend (built with `--mode app`) in a Tauri window. It talks to
//! the audium server only over HTTP (see frontend/src/lib/api.ts); there is no Rust command the
//! frontend calls. On Windows the window has no system title bar: the frontend draws its own
//! (frontend/src/lib/components/WindowFrame.svelte) and uses the window permissions in
//! capabilities/default.json.

#[cfg(windows)]
mod recover;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();

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

    builder
        // Size and position of the window as they were when it was closed. Not the title bar: that
        // comes from the config (none on Windows), and a saved state of an older version would
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
                if let Some(window) = _app.get_webview_window("main") {
                    recover::reload_when_renderer_fails(&window);
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running audium");
}

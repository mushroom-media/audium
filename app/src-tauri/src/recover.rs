//! A window that stays black after a long idle time.
//!
//! WebView2 runs the page in a renderer process of its own. Windows may end that process while
//! the app sits idle for hours (memory pressure, sleep and resume, a graphics driver reset), or it
//! may hang. WebView2 then reports `ProcessFailed`, but nothing reloads the page: the window shows
//! only its background colour, without a message, until the app is restarted. Here we reload the
//! page (renderer gone or hung) or restart the app (the whole WebView2 browser process gone), and
//! write a line to `%LOCALAPPDATA%\io.github.mushroommedia.audium\logs\webview.log` so it can be
//! told apart from other problems.

use std::io::Write;

use tauri::{Manager, WebviewWindow};
use webview2_com::Microsoft::Web::WebView2::Win32::{
    COREWEBVIEW2_PROCESS_FAILED_KIND, COREWEBVIEW2_PROCESS_FAILED_KIND_BROWSER_PROCESS_EXITED,
    COREWEBVIEW2_PROCESS_FAILED_KIND_FRAME_RENDER_PROCESS_EXITED,
    COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_EXITED,
    COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_UNRESPONSIVE,
};
use webview2_com::ProcessFailedEventHandler;

pub fn reload_when_renderer_fails(window: &WebviewWindow) {
    let app = window.app_handle().clone();
    let _ = window.with_webview(move |webview| unsafe {
        let Ok(core) = webview.controller().CoreWebView2() else {
            return;
        };
        let handler = ProcessFailedEventHandler::create(Box::new(move |sender, args| {
            let (Some(sender), Some(args)) = (sender, args) else {
                return Ok(());
            };
            let mut kind = COREWEBVIEW2_PROCESS_FAILED_KIND::default();
            args.ProcessFailedKind(&mut kind)?;
            log(&app, kind);
            if kind == COREWEBVIEW2_PROCESS_FAILED_KIND_BROWSER_PROCESS_EXITED {
                // This WebView cannot come back; a fresh start can.
                app.restart();
            }
            if kind == COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_EXITED
                || kind == COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_UNRESPONSIVE
                || kind == COREWEBVIEW2_PROCESS_FAILED_KIND_FRAME_RENDER_PROCESS_EXITED
            {
                sender.Reload()?;
            }
            // The GPU and utility processes are restarted by WebView2 itself.
            Ok(())
        }));
        let mut token = Default::default();
        let _ = core.add_ProcessFailed(&handler, &mut token);
    });
}

fn log(app: &tauri::AppHandle, kind: COREWEBVIEW2_PROCESS_FAILED_KIND) {
    let Ok(dir) = app.path().app_log_dir() else {
        return;
    };
    let _ = std::fs::create_dir_all(&dir);
    let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("webview.log")) else {
        return;
    };
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let _ = writeln!(file, "{secs} process_failed kind={}", kind.0);
}

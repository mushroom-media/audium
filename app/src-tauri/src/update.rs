//! Updates of the Windows app, without interrupting anyone.
//!
//! - A few seconds after the start, and every few hours after that, the app asks GitHub whether
//!   there is a newer version (`plugins.updater` in tauri.conf.json; the manifest is published by
//!   .github/workflows/app.yml). A newer installer is downloaded quietly in the background, its
//!   signature checked, and kept in `%LOCALAPPDATA%\io.github.mushroommedia.audium\update`.
//! - When the user closes the app, the installer runs (passive: a small progress bar, no
//!   questions, no admin prompt with the per-user install) and the app does not start again: the
//!   user wanted it closed. The next start is the new version.
//! - Not while Windows shuts down, though: an installer killed half-way would leave a broken
//!   installation. The installer stays on disk instead, and the next start installs it before the
//!   window shows anything, then opens the new version.
//! - The frontend shows a small hint with "restart now" (`update_ready`, `update_now`, the event
//!   `update-ready`; frontend/src/lib/appUpdate.svelte.ts).
//!
//! The app never closes by itself while it is in use. Errors are only written to
//! `logs\update.log`: a missing update is no reason to bother anyone.

use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};
use tauri_plugin_window_state::{AppHandleExt, StateFlags};

/// Not right at the start, which is busy enough (login, first page, playback).
const FIRST_CHECK: Duration = Duration::from_secs(15);
/// The app may stay open for days.
const CHECK_EVERY: Duration = Duration::from_secs(6 * 60 * 60);

/// The release manifest, written last: the installer next to it is complete when it exists.
const MANIFEST: &str = "release.json";
const INSTALLER: &str = "installer.exe";

type Failure = Box<dyn std::error::Error + Send + Sync>;

/// A downloaded and verified update, waiting for the app to close.
#[derive(Default)]
pub struct Pending(Mutex<Option<Ready>>);

struct Ready {
    update: Update,
    bytes: Vec<u8>,
}

/// At the start, before the window shows: install an update that was downloaded but could not be
/// installed when the app was last closed (Windows was shutting down). Returns only when there is
/// nothing to install; otherwise the installer runs and the app exits, and the installer starts
/// the new version.
pub fn install_left_over(app: &AppHandle) {
    let Some(dir) = dir(app) else { return };
    if !dir.join(MANIFEST).exists() {
        // Also clears an installer whose download was cut off.
        let _ = fs::remove_dir_all(&dir);
        return;
    }
    let result = (|| -> Result<(), Failure> {
        let raw: serde_json::Value = serde_json::from_slice(&fs::read(dir.join(MANIFEST))?)?;
        // `None`: this version or a newer one is installed already (installed by hand, say).
        let Some(update) = app.updater()?.restore_update(raw)? else {
            return Ok(());
        };
        let bytes = fs::read(dir.join(INSTALLER))?;
        // Checked again here: the file sat on disk since the download.
        update.verify(&bytes)?;
        // One attempt only: should the installation fail, the next start downloads it afresh
        // instead of running a failing installer on every start.
        let _ = fs::remove_dir_all(&dir);
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.hide();
        }
        log(app, &format!("installing {} at the start", update.version));
        update.restart_after_install(true).install(&bytes)?;
        Ok(())
    })();
    if let Err(err) = result {
        log(app, &format!("left-over update not installed: {err}"));
    }
    let _ = fs::remove_dir_all(&dir);
}

/// Checks for updates in the background, now and then, until one is downloaded.
pub fn watch(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(FIRST_CHECK);
        loop {
            match tauri::async_runtime::block_on(fetch(&app)) {
                Ok(true) => break,
                Ok(false) => {}
                Err(err) => log(&app, &format!("check failed: {err}")),
            }
            std::thread::sleep(CHECK_EVERY);
        }
    });
}

/// Downloads a newer version if there is one. `true` when an update is ready.
async fn fetch(app: &AppHandle) -> Result<bool, Failure> {
    let Some(update) = app.updater()?.check().await? else {
        return Ok(false);
    };
    // `download` checks the signature.
    let bytes = update.download(|_, _| {}, || {}).await?;
    keep(app, &update, &bytes)?;
    let version = update.version.clone();
    log(app, &format!("{version} downloaded"));
    *app.state::<Pending>().0.lock().unwrap() = Some(Ready { update, bytes });
    let _ = app.emit("update-ready", &version);
    Ok(true)
}

/// On disk too, for the next start when Windows shuts down with the app open.
fn keep(app: &AppHandle, update: &Update, bytes: &[u8]) -> Result<(), Failure> {
    let dir = dir(app).ok_or("no data directory")?;
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir)?;
    fs::write(dir.join(INSTALLER), bytes)?;
    let part = dir.join(format!("{MANIFEST}.part"));
    fs::write(&part, serde_json::to_vec(&update.raw_json)?)?;
    fs::rename(part, dir.join(MANIFEST))?;
    Ok(())
}

/// The app is closing (its window is gone): install a waiting update. Not while Windows shuts
/// down; then the next start does it.
pub fn install_on_exit(app: &AppHandle) {
    if shutting_down() {
        return;
    }
    let Some(ready) = app.state::<Pending>().0.lock().unwrap().take() else {
        return;
    };
    if let Some(dir) = dir(app) {
        let _ = fs::remove_dir_all(dir);
    }
    log(app, &format!("installing {} on exit", ready.update.version));
    // Exits the app once the installer runs.
    if let Err(err) = ready.update.restart_after_install(false).install(&ready.bytes) {
        log(app, &format!("install on exit failed: {err}"));
    }
}

/// The version that is ready to install, if any.
#[tauri::command]
pub fn update_ready(app: AppHandle) -> Option<String> {
    app.state::<Pending>().0.lock().unwrap().as_ref().map(|r| r.update.version.clone())
}

/// "Restart now" in the frontend: install the waiting update and start the new version.
#[tauri::command]
pub fn update_now(app: AppHandle) -> Result<(), String> {
    let Some(ready) = app.state::<Pending>().0.lock().unwrap().take() else {
        return Err("no update".into());
    };
    // The window stays where it is; the app exits without closing it.
    let _ = app.save_window_state(StateFlags::all() - StateFlags::DECORATIONS);
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
    if let Some(dir) = dir(&app) {
        let _ = fs::remove_dir_all(dir);
    }
    log(&app, &format!("installing {} now", ready.update.version));
    let result = ready.update.clone().restart_after_install(true).install(&ready.bytes);
    // Only reached when the installer did not start.
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
    }
    let err = result.err().map(|e| e.to_string()).unwrap_or_default();
    log(&app, &format!("install now failed: {err}"));
    *app.state::<Pending>().0.lock().unwrap() = Some(ready);
    Err(err)
}

fn shutting_down() -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetSystemMetrics, SM_SHUTTINGDOWN};
    unsafe { GetSystemMetrics(SM_SHUTTINGDOWN) != 0 }
}

fn dir(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_local_data_dir().ok().map(|d| d.join("update"))
}

fn log(app: &AppHandle, line: &str) {
    let Ok(dir) = app.path().app_log_dir() else {
        return;
    };
    let _ = fs::create_dir_all(&dir);
    let Ok(mut file) = fs::OpenOptions::new().create(true).append(true).open(dir.join("update.log")) else {
        return;
    };
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let _ = writeln!(file, "{secs} {line}");
}

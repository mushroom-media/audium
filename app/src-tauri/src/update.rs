//! Updates of the desktop app, without interrupting anyone.
//!
//! - A few seconds after the start, and every few hours after that, the app asks GitHub whether
//!   there is a newer version (`plugins.updater` in tauri.conf.json; the manifest is published by
//!   .github/workflows/app.yml). A newer version is downloaded quietly in the background and its
//!   signature checked.
//!
//! Windows (`Mode::OnClose`): the installer is kept in
//! `%LOCALAPPDATA%\io.github.mushroommedia.audium\update`.
//! - When the user closes the app, the installer runs (passive: a small progress bar, no
//!   questions, no admin prompt with the per-user install) and the app does not start again: the
//!   user wanted it closed. The next start is the new version.
//! - Not while Windows shuts down, though: an installer killed half-way would leave a broken
//!   installation. The installer stays on disk instead, and the next start installs it before the
//!   window shows anything, then opens the new version.
//!
//! macOS and Linux (`Mode::NextStart`): the new version replaces the app bundle or the AppImage
//! right after the download, which takes a moment and leaves the running app alone (it keeps its
//! files open). The next start is the new version; "restart now" only restarts. This needs no
//! password: where the app may not replace itself (an app in a folder of another user, one run
//! from the disk image, a .deb package), it does not update itself at all (`Mode::Manual`) and
//! Settings > About points to the download page.
//!
//! Everywhere:
//! - The frontend shows a small hint with "restart now" (`update_ready`, `update_now`, the event
//!   `update-ready`; frontend/src/lib/appUpdate.svelte.ts).
//! - Settings > About can also check by hand (`update_check`): the same check and download, with
//!   the download's progress as the event `update-progress`. `update_mode` tells it which of the
//!   above applies.
//!
//! The app never closes by itself while it is in use. Errors are only written to
//! `update.log` in the app's log folder: a missing update is no reason to bother anyone.

#[cfg(windows)]
use std::fs;
use std::io::Write;
#[cfg(windows)]
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use tauri::async_runtime::Mutex as AsyncMutex;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_updater::{Update, UpdaterExt};
#[cfg(windows)]
use tauri_plugin_window_state::{AppHandleExt, StateFlags};

/// Not right at the start, which is busy enough (login, first page, playback).
const FIRST_CHECK: Duration = Duration::from_secs(15);
/// The app may stay open for days.
const CHECK_EVERY: Duration = Duration::from_secs(6 * 60 * 60);

/// The release manifest, written last: the installer next to it is complete when it exists.
#[cfg(windows)]
const MANIFEST: &str = "release.json";
#[cfg(windows)]
const INSTALLER: &str = "installer.exe";

type Failure = Box<dyn std::error::Error + Send + Sync>;

/// How this app updates itself (see the top of this file).
// Windows only ever uses `OnClose`, macOS and Linux the other two.
#[allow(dead_code)]
#[derive(Clone, Copy, PartialEq)]
pub enum Mode {
    OnClose,
    NextStart,
    Manual,
}

impl Mode {
    /// Decided once at the start: where the app lies does not change while it runs.
    pub fn detect() -> Self {
        #[cfg(windows)]
        let mode = Mode::OnClose;
        #[cfg(not(windows))]
        let mode = if replaceable() { Mode::NextStart } else { Mode::Manual };
        mode
    }
}

/// The app bundle (macOS) or the AppImage (Linux) can be replaced by the user running it: the
/// file itself and its folder are writable. The updater would otherwise ask for a password.
#[cfg(not(windows))]
fn replaceable() -> bool {
    use std::path::Path;
    fn writable(path: &Path) -> bool {
        use std::os::unix::ffi::OsStrExt;
        let Ok(path) = std::ffi::CString::new(path.as_os_str().as_bytes()) else {
            return false;
        };
        unsafe { libc::access(path.as_ptr(), libc::W_OK) == 0 }
    }
    // macOS: .../audium.app/Contents/MacOS/audium-app. Not when started from the disk image or
    // from the read-only copy macOS runs of an app that was not moved yet (App Translocation).
    #[cfg(target_os = "macos")]
    let target = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.ancestors().nth(3).map(Path::to_path_buf))
        .filter(|bundle| bundle.extension().is_some_and(|e| e == "app"));
    // Linux: only the AppImage updates itself (its path is in $APPIMAGE). A .deb package belongs
    // to the package manager, which needs root.
    #[cfg(not(target_os = "macos"))]
    let target = std::env::var_os("APPIMAGE").map(std::path::PathBuf::from);
    let Some(target) = target else { return false };
    target.parent().is_some_and(writable) && writable(&target)
}

/// How this app updates itself, decided at the start (`Mode::detect`).
pub struct HowToUpdate(pub Mode);

/// A downloaded and verified update: on Windows waiting for the app to close, on macOS and Linux
/// installed already, for the next start.
#[derive(Default)]
pub struct Pending(Mutex<Option<Ready>>);

struct Ready {
    update: Update,
    #[cfg(windows)]
    bytes: Vec<u8>,
}

/// One check at a time: a check by hand while the background check downloads waits for it
/// instead of downloading the same installer a second time.
#[derive(Default)]
pub struct Checking(AsyncMutex<()>);

/// Windows, at the start, before the window shows: install an update that was downloaded but could not be
/// installed when the app was last closed (Windows was shutting down). Returns only when there is
/// nothing to install; otherwise the installer runs and the app exits, and the installer starts
/// the new version.
#[cfg(windows)]
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
    if app.state::<HowToUpdate>().0 == Mode::Manual {
        return;
    }
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
    let checking = app.state::<Checking>();
    let _one = checking.0.lock().await;
    if ready_version(app).is_some() {
        return Ok(true);
    }
    let Some(update) = app.updater()?.check().await? else {
        return Ok(false);
    };
    // `download` checks the signature. Its progress for Settings > About, a few times a second.
    let mut downloaded: u64 = 0;
    let mut sent: Option<std::time::Instant> = None;
    let bytes = update
        .download(
            |chunk, total| {
                downloaded += chunk as u64;
                if sent.map_or(true, |s| s.elapsed() >= Duration::from_millis(150)) {
                    sent = Some(std::time::Instant::now());
                    let _ = app.emit(
                        "update-progress",
                        serde_json::json!({ "downloaded": downloaded, "total": total }),
                    );
                }
            },
            || {},
        )
        .await?;
    let version = update.version.clone();
    #[cfg(windows)]
    let ready = {
        keep(app, &update, &bytes)?;
        log(app, &format!("{version} downloaded"));
        Ready { update, bytes }
    };
    // Replaces the app bundle or the AppImage; the running app keeps its open files.
    #[cfg(not(windows))]
    let ready = {
        let installing = update.clone();
        tauri::async_runtime::spawn_blocking(move || installing.install(&bytes)).await??;
        log(app, &format!("{version} installed for the next start"));
        Ready { update }
    };
    *app.state::<Pending>().0.lock().unwrap() = Some(ready);
    let _ = app.emit("update-ready", &version);
    Ok(true)
}

/// On disk too, for the next start when Windows shuts down with the app open.
#[cfg(windows)]
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

/// Windows: the app is closing (its window is gone): install a waiting update. Not while Windows
/// shuts down; then the next start does it.
#[cfg(windows)]
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

fn ready_version(app: &AppHandle) -> Option<String> {
    app.state::<Pending>().0.lock().unwrap().as_ref().map(|r| r.update.version.clone())
}

/// How this app updates itself: "on-close" (Windows), "next-start" (macOS, the Linux AppImage)
/// or "manual" (it cannot replace itself; new versions only from the download page).
#[tauri::command]
pub fn update_mode(app: AppHandle) -> &'static str {
    match app.state::<HowToUpdate>().0 {
        Mode::OnClose => "on-close",
        Mode::NextStart => "next-start",
        Mode::Manual => "manual",
    }
}

/// The version that is ready to install (Windows) or installed for the next start, if any.
#[tauri::command]
pub fn update_ready(app: AppHandle) -> Option<String> {
    ready_version(&app)
}

/// "Check for updates" in Settings > About: checks now and downloads a newer version (progress as
/// `update-progress`, then `update-ready`). Returns the version ready to install, or `None` when
/// this already is the newest version.
#[tauri::command]
pub async fn update_check(app: AppHandle) -> Result<Option<String>, String> {
    if app.state::<HowToUpdate>().0 == Mode::Manual {
        return Err("this app does not update itself".into());
    }
    match fetch(&app).await {
        Ok(_) => Ok(ready_version(&app)),
        Err(err) => {
            log(&app, &format!("check by hand failed: {err}"));
            Err(err.to_string())
        }
    }
}

/// "Restart now" in the frontend: install the waiting update and start the new version.
#[cfg(windows)]
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

/// "Restart now" on macOS and Linux: the new version is in place already, so only restart.
#[cfg(not(windows))]
#[tauri::command]
pub fn update_now(app: AppHandle) -> Result<(), String> {
    if app.state::<Pending>().0.lock().unwrap().is_none() {
        return Err("no update".into());
    }
    log(&app, "restarting into the new version");
    app.restart()
}

#[cfg(windows)]
fn shutting_down() -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{GetSystemMetrics, SM_SHUTTINGDOWN};
    unsafe { GetSystemMetrics(SM_SHUTTINGDOWN) != 0 }
}

#[cfg(windows)]
fn dir(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_local_data_dir().ok().map(|d| d.join("update"))
}

fn log(app: &AppHandle, line: &str) {
    let Ok(dir) = app.path().app_log_dir() else {
        return;
    };
    let _ = std::fs::create_dir_all(&dir);
    let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("update.log")) else {
        return;
    };
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let _ = writeln!(file, "{secs} {line}");
}

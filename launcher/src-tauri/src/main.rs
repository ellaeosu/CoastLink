// CoastLink launcher: one window (WebView2) over the existing Python logic, which runs as a hidden sidecar speaking JSON
// lines (coastlink/sidecar.py). No console window: the app is a GUI-subsystem exe and every child process is started with
// CREATE_NO_WINDOW. GPL-3.0-or-later.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use base64::Engine as _;
use sha2::{Digest, Sha256};
use tauri::{Emitter, Manager, State};
use tauri_plugin_window_state::StateFlags;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
/// The release signing key's public half (ed25519, base64). The private half never enters the repository.
const UPDATE_PUBLIC_KEY: &str = include_str!("../../update_pubkey.txt");

#[derive(Default)]
struct Sidecar {
    stdin: Mutex<Option<ChildStdin>>,
    child: Mutex<Option<Child>>,
}

/// The CoastLink folder: COASTLINK_REPO, else the first folder at or above the exe that holds coastlink/engine.py
/// (CoastLink.exe sits in that folder; a development build sits deeper, under launcher/src-tauri/target).
fn repo_dir() -> PathBuf {
    if let Ok(p) = std::env::var("COASTLINK_REPO") {
        return PathBuf::from(p);
    }
    let exe = std::env::current_exe().unwrap_or_default();
    let start = exe.parent().map(Path::to_path_buf).unwrap_or_default();
    let mut d = start.clone();
    for _ in 0..8 {
        if d.join("coastlink").join("engine.py").is_file() {
            return d;
        }
        if !d.pop() {
            break;
        }
    }
    start
}

/// The private Python the installer set up (the embeddable one first, then a virtual environment's).
fn python_path(repo: &Path) -> Option<PathBuf> {
    ["deps/python/python.exe", "deps/python/Scripts/python.exe"]
        .iter()
        .map(|rel| repo.join(rel))
        .find(|p| p.is_file())
}

fn hidden(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

fn start_sidecar(app: &tauri::AppHandle, state: &Sidecar) -> Result<(), String> {
    let repo = repo_dir();
    let py = python_path(&repo).ok_or_else(|| "no_python".to_string())?;
    let mut cmd = Command::new(&py);
    cmd.arg("-u")
        .arg(repo.join("coastlink").join("sidecar.py"))
        .current_dir(&repo)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("COASTLINK_APP_VERSION", env!("CARGO_PKG_VERSION"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = hidden(&mut cmd).spawn().map_err(|e| format!("could not start the CoastLink backend: {e}"))?;
    let stdout = child.stdout.take().ok_or("no backend output")?;
    let stderr = child.stderr.take().ok_or("no backend errors")?;
    let out_app = app.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(l) => {
                    let _ = out_app.emit("sidecar", l);
                }
                Err(_) => break,
            }
        }
        let _ = out_app.emit("sidecar-exit", ());
    });
    let err_app = app.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            let _ = err_app.emit("sidecar-stderr", line);
        }
    });
    *state.stdin.lock().unwrap() = child.stdin.take();
    *state.child.lock().unwrap() = Some(child);
    Ok(())
}

fn stop_sidecar(state: &Sidecar) {
    state.stdin.lock().unwrap().take();
    if let Some(mut c) = state.child.lock().unwrap().take() {
        // closing stdin asks it to finish; a game it started keeps running (it is not tied to this process)
        for _ in 0..20 {
            if matches!(c.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        let _ = c.kill();
    }
}

#[tauri::command]
fn sidecar_send(line: String, state: State<Sidecar>) -> Result<(), String> {
    let mut guard = state.stdin.lock().unwrap();
    let stdin = guard.as_mut().ok_or("the CoastLink backend is not running")?;
    stdin.write_all(line.trim_end().as_bytes()).map_err(|e| e.to_string())?;
    stdin.write_all(b"\n").map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())
}

#[tauri::command]
fn sidecar_restart(app: tauri::AppHandle, state: State<Sidecar>) -> Result<(), String> {
    stop_sidecar(&state);
    start_sidecar(&app, &state)
}

#[tauri::command]
fn app_info() -> serde_json::Value {
    let repo = repo_dir();
    serde_json::json!({
        "version": env!("CARGO_PKG_VERSION"),
        "repo": repo.display().to_string(),
        "exe": std::env::current_exe().map(|p| p.display().to_string()).unwrap_or_default(),
        "python": python_path(&repo).map(|p| p.display().to_string()),
    })
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    let p = PathBuf::from(&path);
    if !p.exists() {
        return Err(format!("{path} does not exist"));
    }
    Command::new("explorer.exe").arg(&p).spawn().map(|_| ()).map_err(|e| e.to_string())
}

/// ed25519 signature check of an update manifest against the built-in release key.
#[tauri::command]
fn verify_manifest(text: String, signature: String) -> Result<bool, String> {
    verify_signature(text.as_bytes(), signature.trim(), UPDATE_PUBLIC_KEY.trim())
}

fn verify_signature(data: &[u8], signature_b64: &str, key_b64: &str) -> Result<bool, String> {
    use ed25519_dalek::{Signature, Verifier, VerifyingKey};
    let b64 = base64::engine::general_purpose::STANDARD;
    let key: [u8; 32] = b64.decode(key_b64).map_err(|e| e.to_string())?.try_into().map_err(|_| "bad public key length")?;
    let key = VerifyingKey::from_bytes(&key).map_err(|e| e.to_string())?;
    let sig = Signature::from_slice(&b64.decode(signature_b64).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    Ok(key.verify(data, &sig).is_ok())
}

const MAX_UPDATE_ARCHIVE: u64 = 160 * 1024 * 1024;

fn read_limited(path: &Path, limit: u64) -> Result<Vec<u8>, String> {
    let file = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    file.take(limit + 1).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    if bytes.len() as u64 > limit {
        return Err("The update file exceeds its allowed size".to_string());
    }
    Ok(bytes)
}

/// Offline ZIPs need the same signed feed as online updates, beside the ZIP.
/// The returned digest is passed to update.apply, which rechecks it before writes.
#[tauri::command]
fn verify_update_file(path: String) -> Result<serde_json::Value, String> {
    verify_update_file_with_key(Path::new(&path), UPDATE_PUBLIC_KEY.trim())
}

fn verify_update_file_with_key(path: &Path, key: &str) -> Result<serde_json::Value, String> {
    let path = std::fs::canonicalize(path).map_err(|e| format!("The update ZIP could not be opened: {e}"))?;
    let parent = path.parent().ok_or("The update ZIP has no parent folder")?;
    let text = read_limited(&parent.join("coastlink-release.json"), 4 * 1024 * 1024)
        .map_err(|_| "For an offline update, put coastlink-release.json and coastlink-release.json.sig from the same release beside the ZIP".to_string())?;
    let signature = read_limited(&parent.join("coastlink-release.json.sig"), 512)
        .map_err(|_| "The offline update's release signature is missing".to_string())?;
    let signature = std::str::from_utf8(&signature).map_err(|_| "The release signature is invalid")?;
    if !verify_signature(&text, signature.trim(), key)? {
        return Err("The release signature is not valid. Nothing was installed".to_string());
    }
    let manifest: serde_json::Value = serde_json::from_slice(&text).map_err(|_| "The signed release feed is invalid")?;
    if manifest.get("product").and_then(|v| v.as_str()) != Some("CoastLink") {
        return Err("The signed release is for a different product".to_string());
    }
    let version = manifest.get("version").and_then(|v| v.as_str()).ok_or("The signed release has no version")?;
    let package = manifest.get("package").ok_or("The signed release has no update package")?;
    let expected = package.get("sha256").and_then(|v| v.as_str()).ok_or("The signed release has no package checksum")?;
    if expected.len() != 64 || !expected.bytes().all(|c| c.is_ascii_hexdigit()) {
        return Err("The signed release checksum is invalid".to_string());
    }
    let size = package.get("size").and_then(|v| v.as_u64()).ok_or("The signed release has no package size")?;
    if size == 0 || size > MAX_UPDATE_ARCHIVE {
        return Err("The signed update exceeds its allowed size".to_string());
    }
    let bytes = read_limited(&path, size)?;
    let got = Sha256::digest(&bytes).iter().map(|b| format!("{b:02x}")).collect::<String>();
    if bytes.len() as u64 != size || got != expected.to_ascii_lowercase() {
        return Err("The update ZIP does not match its signed release checksum. Nothing was installed".to_string());
    }
    Ok(serde_json::json!({"path": path.display().to_string(), "sha256": got, "version": version}))
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut f = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let mut h = Sha256::new();
    let mut buf = vec![0u8; 1 << 20];
    loop {
        let n = f.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(h.finalize().iter().map(|b| format!("{b:02x}")).collect())
}

// ---------------------------------------------------------------- private Python (replaces coastlink/Bootstrap.ps1)
const PY_URL: &str = "https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip";
const PY_SHA: &str = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297";
const PIP_URL: &str = "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl";
const PIP_SHA: &str = "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e";

fn download_checked(app: &tauri::AppHandle, url: &str, file: &Path, sha: &str, what: &str) -> Result<(), String> {
    if file.is_file() && sha256_file(file)? == sha {
        return Ok(());
    }
    let part = file.with_extension("part");
    // Windows' own TLS (Schannel): no bundled certificate store or C crypto library
    let tls = native_tls::TlsConnector::new().map_err(|e| e.to_string())?;
    let agent = ureq::AgentBuilder::new().tls_connector(std::sync::Arc::new(tls)).build();
    let resp = agent.get(url).call().map_err(|e| format!("download of {what} failed: {e}"))?;
    let total: u64 = resp.header("Content-Length").and_then(|v| v.parse().ok()).unwrap_or(0);
    let mut reader = resp.into_reader();
    let mut out = std::fs::File::create(&part).map_err(|e| e.to_string())?;
    let mut got: u64 = 0;
    let mut buf = vec![0u8; 1 << 16];
    let mut last = std::time::Instant::now();
    loop {
        let n = reader.read(&mut buf).map_err(|e| format!("download of {what} failed: {e}"))?;
        if n == 0 {
            break;
        }
        out.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        got += n as u64;
        if last.elapsed().as_millis() > 150 {
            last = std::time::Instant::now();
            let _ = app.emit("bootstrap", serde_json::json!({"stage": what, "done": got, "total": total}));
        }
    }
    drop(out);
    if sha256_file(&part)? != sha {
        let _ = std::fs::remove_file(&part);
        return Err(format!("{what} did not match its expected checksum; nothing was run"));
    }
    std::fs::rename(&part, file).map_err(|e| e.to_string())
}

fn unzip(zip: &Path, into: &Path) -> Result<(), String> {
    let f = std::fs::File::open(zip).map_err(|e| e.to_string())?;
    let mut archive = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| e.to_string())?;
        let rel = entry.enclosed_name().ok_or("unsafe path in archive")?;
        let target = into.join(rel);
        if entry.is_dir() {
            std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
            continue;
        }
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut out = std::fs::File::create(&target).map_err(|e| e.to_string())?;
        std::io::copy(&mut entry, &mut out).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn bootstrap(app: &tauri::AppHandle) -> Result<(), String> {
    let repo = repo_dir();
    let downloads = repo.join("deps").join("downloads");
    let py_dir = repo.join("deps").join("python");
    std::fs::create_dir_all(&downloads).map_err(|e| e.to_string())?;
    let zip = downloads.join("python-3.13.16-embed-amd64.zip");
    download_checked(app, PY_URL, &zip, PY_SHA, "Python")?;
    unzip(&zip, &py_dir)?;
    let pth = std::fs::read_dir(&py_dir)
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .map(|e| e.path())
        .find(|p| p.extension().is_some_and(|x| x == "_pth"))
        .ok_or("Python was unpacked incompletely")?;
    let text = std::fs::read_to_string(&pth).map_err(|e| e.to_string())?;
    let fixed: Vec<String> = text
        .lines()
        .map(|l| if l.trim_start().trim_start_matches('#').trim() == "import site" { "import site".to_string() } else { l.to_string() })
        .collect();
    std::fs::write(&pth, fixed.join("\r\n")).map_err(|e| e.to_string())?;
    let wheel = downloads.join("pip-26.2.1.whl");
    download_checked(app, PIP_URL, &wheel, PIP_SHA, "pip")?;
    let site = py_dir.join("Lib").join("site-packages");
    std::fs::create_dir_all(&site).map_err(|e| e.to_string())?;
    unzip(&wheel, &site)?;
    std::fs::write(
        site.join("coastlink_scriptdir.pth"),
        "import sys, os; a = sys.argv[0] if sys.argv else ''; (a and os.path.isfile(a) and sys.path.insert(0, os.path.dirname(os.path.abspath(a))))",
    )
    .map_err(|e| e.to_string())
}

#[tauri::command]
async fn bootstrap_python(app: tauri::AppHandle) -> Result<(), String> {
    let a = app.clone();
    tauri::async_runtime::spawn_blocking(move || bootstrap(&a)).await.map_err(|e| e.to_string())??;
    let state = app.state::<Sidecar>();
    stop_sidecar(&state);
    start_sidecar(&app, &state)
}

// ---------------------------------------------------------------- self-update: the new exe replaces this one on restart
/// Starts `new_exe --coastlink-swap <this exe> <this pid>` and quits: the new exe waits for this process to end, copies
/// itself over this exe (the old one kept as CoastLink.exe.old for a roll back), and starts it again.
#[tauri::command]
fn self_update(app: tauri::AppHandle, new_exe: String) -> Result<(), String> {
    let me = std::env::current_exe().map_err(|e| e.to_string())?;
    let new_exe = staged_update_path(&repo_dir(), Path::new(&new_exe))?;
    validate_swap_paths(&new_exe, &me)?;
    let mut cmd = Command::new(&new_exe);
    cmd.arg("--coastlink-swap").arg(&me).arg(std::process::id().to_string());
    hidden(&mut cmd).spawn().map_err(|e| e.to_string())?;
    app.exit(0);
    Ok(())
}

fn staged_update_path(repo: &Path, supplied: &Path) -> Result<PathBuf, String> {
    let root = std::fs::canonicalize(repo).map_err(|e| e.to_string())?;
    let expected = std::fs::canonicalize(root.join("CoastLink.exe.new")).map_err(|_| "No launcher update is staged")?;
    let supplied = std::fs::canonicalize(supplied).map_err(|e| e.to_string())?;
    if supplied != expected || expected.parent() != Some(root.as_path()) {
        return Err("Only CoastLink.exe.new inside this installation can finish an update".to_string());
    }
    Ok(expected)
}

fn validate_swap_paths(staged: &Path, target: &Path) -> Result<(), String> {
    if !staged.file_name().is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("CoastLink.exe.new"))
        || !target.file_name().is_some_and(|n| n.to_string_lossy().eq_ignore_ascii_case("CoastLink.exe")) {
        return Err("The launcher update filenames are invalid".to_string());
    }
    let from = std::fs::canonicalize(staged.parent().ok_or("Missing update folder")?).map_err(|e| e.to_string())?;
    let to = std::fs::canonicalize(target.parent().ok_or("Missing launcher folder")?).map_err(|e| e.to_string())?;
    if from != to {
        return Err("The launcher update must stay inside its installation folder".to_string());
    }
    if std::fs::symlink_metadata(target).is_ok_and(|meta| meta.file_type().is_symlink()) {
        return Err("The launcher update target cannot be a symbolic link".to_string());
    }
    Ok(())
}

fn swap_mode(args: &[String]) -> bool {
    if args.len() < 4 || args[1] != "--coastlink-swap" {
        return false;
    }
    let target = PathBuf::from(&args[2]);
    let me = std::env::current_exe().unwrap_or_default();
    let pid = match args[3].parse::<u32>() {
        Ok(pid) if pid > 0 && pid != std::process::id() => pid.to_string(),
        _ => return true,
    };
    if validate_swap_paths(&me, &target).is_err() {
        return true;
    }
    // wait for the old launcher to end (its exe stays locked while it runs)
    for _ in 0..200 {
        let out = hidden(Command::new("tasklist").args(["/FI", &format!("PID eq {pid}"), "/NH"])).output();
        if out.map(|o| !String::from_utf8_lossy(&o.stdout).contains(&pid)).unwrap_or(true) {
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    let old = target.with_extension("exe.old");
    let _ = std::fs::remove_file(&old);
    for _ in 0..50 {
        if std::fs::rename(&target, &old).is_ok() || !target.exists() {
            if std::fs::copy(&me, &target).is_ok() {
                let _ = Command::new(&target).spawn();
                return true;
            }
            let _ = std::fs::rename(&old, &target);
        }
        std::thread::sleep(std::time::Duration::from_millis(200));
    }
    let _ = Command::new(&target).spawn(); // could not replace it: start the old one again
    true
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if swap_mode(&args) {
        return;
    }
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().with_state_flags(StateFlags::all() & !StateFlags::VISIBLE).build())
        .plugin(tauri_plugin_dialog::init())
        .manage(Sidecar::default())
        .setup(|app| {
            let handle = app.handle().clone();
            let state = app.state::<Sidecar>();
            if let Err(e) = start_sidecar(&handle, &state) {
                eprintln!("sidecar: {e}");
            }
            Ok(())
        })
        .on_page_load(|webview, payload| {
            if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                let _ = webview.window().show();
            }
        })
        .invoke_handler(tauri::generate_handler![
            sidecar_send,
            sidecar_restart,
            app_info,
            open_path,
            verify_manifest,
            verify_update_file,
            bootstrap_python,
            self_update
        ])
        .build(tauri::generate_context!())
        .expect("CoastLink could not start")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                stop_sidecar(&app.state::<Sidecar>());
            }
        });
}

#[cfg(test)]
mod update_tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT: AtomicU64 = AtomicU64::new(0);

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let unique = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
            let path = std::env::temp_dir().join(format!("coastlink-update-test-{}-{unique}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            if self.0.starts_with(std::env::temp_dir())
                && self.0.file_name().unwrap().to_string_lossy().starts_with("coastlink-update-test-") {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
    }

    fn signed_fixture(folder: &Path, package: &[u8]) -> (PathBuf, String) {
        // Deterministic test key only; unrelated to the production signing key.
        let key = SigningKey::from_bytes(&[7; 32]);
        let public = base64::engine::general_purpose::STANDARD.encode(key.verifying_key().as_bytes());
        let archive = folder.join("CoastLink-0.6.1-update.zip");
        std::fs::write(&archive, package).unwrap();
        let digest = Sha256::digest(package).iter().map(|b| format!("{b:02x}")).collect::<String>();
        let text = serde_json::to_vec(&serde_json::json!({"product":"CoastLink","version":"0.6.1",
            "package":{"name":"CoastLink-0.6.1-update.zip","sha256":digest,"size":package.len()}})).unwrap();
        let signature = base64::engine::general_purpose::STANDARD.encode(key.sign(&text).to_bytes());
        std::fs::write(folder.join("coastlink-release.json"), text).unwrap();
        std::fs::write(folder.join("coastlink-release.json.sig"), signature).unwrap();
        (archive, public)
    }

    #[test]
    fn offline_package_needs_signed_feed_and_matching_hash() {
        let dir = Fixture::new();
        let (archive, key) = signed_fixture(&dir.0, b"signed archive bytes");
        let result = verify_update_file_with_key(&archive, &key).unwrap();
        assert_eq!(result["version"], "0.6.1");
        std::fs::write(&archive, b"changed archive bytes").unwrap();
        assert!(verify_update_file_with_key(&archive, &key).is_err());
    }

    #[test]
    fn offline_feed_tampering_and_wrong_key_are_rejected() {
        let dir = Fixture::new();
        let (archive, key) = signed_fixture(&dir.0, b"archive bytes");
        let wrong = base64::engine::general_purpose::STANDARD.encode(SigningKey::from_bytes(&[8; 32]).verifying_key().as_bytes());
        assert!(verify_update_file_with_key(&archive, &wrong).is_err());
        std::fs::write(dir.0.join("coastlink-release.json"), b"{\"product\":\"CoastLink\"}").unwrap();
        assert!(verify_update_file_with_key(&archive, &key).is_err());
    }

    #[test]
    fn offline_file_without_release_proof_is_rejected() {
        let dir = Fixture::new();
        let archive = dir.0.join("update.zip");
        std::fs::write(&archive, b"archive bytes").unwrap();
        assert!(verify_update_file_with_key(&archive, UPDATE_PUBLIC_KEY.trim()).unwrap_err().contains("beside the ZIP"));
    }

    #[test]
    fn bounded_reads_reject_oversized_files() {
        let dir = Fixture::new();
        let path = dir.0.join("oversized");
        std::fs::write(&path, b"12345").unwrap();
        assert!(read_limited(&path, 4).is_err());
    }

    #[test]
    fn staged_swap_stays_within_installation_and_uses_fixed_names() {
        let dir = Fixture::new();
        let stage = dir.0.join("CoastLink.exe.new");
        let target = dir.0.join("CoastLink.exe");
        std::fs::write(&stage, b"MZ test").unwrap();
        assert!(staged_update_path(&dir.0, &stage).is_ok());
        assert!(validate_swap_paths(&stage, &target).is_ok());
        let other = dir.0.join("other.exe");
        std::fs::write(&other, b"MZ other").unwrap();
        assert!(staged_update_path(&dir.0, &other).is_err());
        assert!(validate_swap_paths(&stage, &other).is_err());
        let outside = Fixture::new();
        assert!(validate_swap_paths(&stage, &outside.0.join("CoastLink.exe")).is_err());
    }
}

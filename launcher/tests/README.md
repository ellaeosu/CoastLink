# Launcher checks

Install Node.js and Playwright, with an Edge installation or a Playwright Chromium
runtime configured in harness.cjs. Run `node controllers.cjs` and `node screens.cjs`.
These run headlessly with mocked backend calls; no native game or desktop window
is opened. Screenshots/results go to the system temporary directory, or the folder
set by COASTLINK_TEST_OUTPUT.

Python backend checks: from coastlink/, run `python -m unittest discover`.
Rust updater checks: from launcher/src-tauri/, run `cargo test --bin coastlink`.
Actual controllers, audio output and online play need separate hardware tests.

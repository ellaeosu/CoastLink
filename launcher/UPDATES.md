# Publishing launcher updates

The release repository is recorded in `launcher/update_source.json` as
`{"repo": "owner/CoastLink"}`. Fresh installations use this public default.
Custom settings in `config/update.json` take precedence and are not replaced by
an update. Keep signing keys outside the project.

Build the launcher first, then create a release:

```text
cargo build --release
python launcher/release.py --key <private-key-file> --github-repo owner/CoastLink --runtime-source work/rb2 --out <release-folder>
```

Run Cargo in `launcher/src-tauri`; run the Python command from the project root,
using the actual path to the runtime sources. The `--base-url` option can name a
different HTTPS download base instead of `--github-repo`. The packager refuses
an unset or placeholder download address.

Upload all generated assets to the matching `v<version>` GitHub release: the
fresh-install ZIP, update ZIP, `coastlink-release.json`, its `.sig`, and the runtime
source ZIP. The modified runtime's corresponding GPL source must accompany its
binary. The private signing key is never included in any package.

The app verifies the feed's Ed25519 signature before downloading an online
update, then checks the archive SHA-256 before extraction. It checks allowed
paths and each file's hash before replacing anything, saves backups, and stages
the launcher executable for replacement on restart. The updater never touches
game data, keys, saves, settings or shader caches.

For an offline update, download the update ZIP and both feed files from the same
release into one folder. Choose the ZIP in **Install update file**. The app
verifies the adjacent signed feed and checks the selected ZIP against it before
installing; a checksum list inside a ZIP is not an authenticity signature.

## Creating a local release before hosting is ready

Use `--offline` instead of a repository or download base:

```text
python launcher/release.py --offline --key <private-key-file> --runtime-source work/rb2 --out <release-folder>
```

This creates the same signed update ZIP, feed, signature, fresh-install ZIP and
runtime source archive. The signed feed explicitly says `offline: true` and its
`package.url` is empty. The launcher can verify and install it from the adjacent
files; it is not an online update feed. No placeholder GitHub address is signed.
Once hosting is available, rerun the packager with the real `--github-repo` or
`--base-url` and upload those regenerated assets.

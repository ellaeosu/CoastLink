"""Make a CoastLink release: the full zip (fresh install or upgrade in place), the update zip the app installs, the signed
release feed (coastlink-release.json + .sig), and the GPL source of the shipped runtime.

  python launcher/release.py --key <ed25519 private key file> [--base-url https://github.com/<owner>/<repo>/releases/download/v<version>/]
                             [--runtime-source <folder with host/ build_host.py ...>] [--out <folder>] [--notes "line" ...]
                             [--offline]

Build CoastLink.exe first (cargo build --release in launcher/src-tauri). The private key never enters the repository.
Upload the full ZIP, update ZIP, feed, feed signature, and runtime source ZIP to the release; the app finds coastlink-release.json at
https://github.com/<owner>/<repo>/releases/latest/download/coastlink-release.json. GPL-3.0-or-later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.parse
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "coastlink"))
import update_apply  # noqa: E402

TARGET = REPO / "launcher" / "src-tauri" / "target" / "release"
SKIP_DIRS = {".git", "build", "deps", "config", "saves", "plan", "__pycache__", "target", "node_modules", ".github"}
LEGACY = {"Play CoastLink.cmd", "Install CoastLink.cmd", "Live Counter.cmd", "Clean old CoastLink.cmd", "coastlink/CoastLink.ps1",
          "coastlink/Settings.ps1", "coastlink/LiveCounter.ps1", "coastlink/Bootstrap.ps1", "coastlink/Cleanup.ps1",
          "coastlink/PACKAGE.sha256.json", "coastlink/UPDATE.sha256.json"}
BINARY_OK = ("coastlink/runtime_patch/",)
NEVER = {".nsp", ".xci", ".nca", ".nso", ".nro", ".elf", ".arc", ".keys", ".key", ".pem", ".p12", ".pfx", ".sav", ".obj", ".pdb", ".lib", ".part", ".pyc"}
NEVER |= update_apply.engine.GAME_EXTENSIONS


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def release_base_url(base_url: str, github_repo: str, version: str, *, offline=False) -> str:
    if offline:
        if base_url or github_repo:
            raise ValueError("Choose --offline or a remote release address, not both.")
        return ""
    if not base_url:
        if not update_apply.REPO_NAME.fullmatch(github_repo):
            raise ValueError("Set --base-url or --github-repo owner/name before signing a public release.")
        base_url = f"https://github.com/{github_repo}/releases/download/v{version}/"
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The release download base must be an https:// URL without credentials, query or fragment.")
    if "/OWNER/REPO/" in base_url:
        raise ValueError("Replace OWNER/REPO with the release repository before signing.")
    return base_url.rstrip("/") + "/"


def release_feed(version: str, notes: list, package_name: str, data: bytes, base_url: str) -> dict:
    return {"product": "CoastLink", "version": version, "notes": notes, "offline": not bool(base_url),
            "package": {"name": package_name, "url": base_url + package_name if base_url else "",
                        "sha256": sha(data), "size": len(data)}}


def tracked() -> list[str]:
    """The upstream files git tracks (read from .git/index, so git itself is not needed)."""
    data = (REPO / ".git" / "index").read_bytes()
    assert data[:4] == b"DIRC" and int.from_bytes(data[4:8], "big") in (2, 3)
    count, pos, names = int.from_bytes(data[8:12], "big"), 12, []
    for _ in range(count):
        fixed = 64 if int.from_bytes(data[pos + 60:pos + 62], "big") & 0x4000 else 62     # (v3 extended flags: 2 more bytes)
        end = data.index(b"\0", pos + fixed)
        names.append(data[pos + fixed:end].decode("utf-8"))
        pos += ((end - pos + 8) // 8) * 8                                                   # NUL-padded to a multiple of 8
    return names


def repo_files() -> dict[str, bytes]:
    files = {}
    candidates = {REPO / name for name in tracked()} | {REPO / "SOURCE.json", REPO / "START HERE.txt"}
    candidates |= {p for folder in ("coastlink", "launcher") for p in (REPO / folder).rglob("*")}
    for path in sorted(candidates):
        rel = path.relative_to(REPO)
        if not path.is_file() or any(part in SKIP_DIRS for part in rel.parts):
            continue
        name = rel.as_posix()
        if name in LEGACY or path.suffix.lower() in NEVER or name.endswith((".exe.new", ".exe.old")) or path.name == ".env" or path.name.startswith(".env."):
            continue
        if path.suffix.lower() in (".exe", ".dll") and not name.startswith(BINARY_OK):
            continue
        files[name] = path.read_bytes()
    files["CoastLink.exe"] = (TARGET / "coastlink.exe").read_bytes()
    files["WebView2Loader.dll"] = (TARGET / "WebView2Loader.dll").read_bytes()
    return files


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("--key", required=True, type=Path)
    cli.add_argument("--base-url", default="")
    cli.add_argument("--github-repo", default="", help="release owner/name; generates the versioned GitHub download URL")
    cli.add_argument("--offline", action="store_true", help="make a signed local-install release with no remote download URL")
    cli.add_argument("--runtime-source", type=Path)
    cli.add_argument("--out", type=Path, default=REPO.parent / "release")
    cli.add_argument("--notes", nargs="*", default=[])
    args = cli.parse_args()
    source = json.loads((REPO / "SOURCE.json").read_text(encoding="utf-8"))
    version = source["version"]
    release_repo = args.github_repo if args.offline else args.github_repo or update_apply.load_config(REPO)["repo"]
    base = release_base_url(args.base_url, release_repo, version, offline=args.offline)
    if (REPO / "coastlink" / "runtime_patch" / "ssbu_native_rb.exe").is_file() and not args.runtime_source:
        raise ValueError("--runtime-source is required when publishing CoastLink's modified runtime (the GPL corresponding source must accompany it).")
    conf = json.loads((REPO / "launcher" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert conf["version"] == version.split("-")[0], f"tauri.conf.json {conf['version']} != SOURCE.json {version}"
    args.out.mkdir(parents=True, exist_ok=True)
    files = repo_files()

    # the update zip: CoastLink's own files only (update_apply.canonical decides), with their checksums
    update_names = sorted(n for n in files if n in update_apply.TOP_FILES or n.startswith(update_apply.PREFIXES))
    for name in update_names:
        update_apply.canonical(name)
    manifest = {"product": "CoastLink", "version": version, "upstream_commit": source["upstream_commit"],
                "files": {n: sha(files[n]) for n in update_names}}
    update_zip = args.out / f"CoastLink-{version}-update.zip"
    with zipfile.ZipFile(update_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in update_names:
            archive.writestr(name, files[name])
        archive.writestr(update_apply.MANIFEST, json.dumps(manifest, indent=2) + "\n")
    update_apply.read_archive(update_zip)                       # the app's own checks pass

    # the full zip: everything for a fresh install, under CoastLink/
    full_zip = args.out / f"CoastLink-{version}.zip"
    with zipfile.ZipFile(full_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(files):
            archive.writestr("CoastLink/" + name, files[name])
    with zipfile.ZipFile(full_zip) as archive:
        assert archive.testzip() is None
        for required in ("CoastLink.exe", "WebView2Loader.dll", "LICENSE", "SOURCE.json", "coastlink/sidecar.py", "coastlink/engine.py",
                         "launcher/ui/index.html", "launcher/src-tauri/src/main.rs", "scripts/install.py"):
            assert "CoastLink/" + required in archive.namelist(), required

    # the signed feed
    data = update_zip.read_bytes()
    feed = release_feed(version, args.notes, update_zip.name, data, base)
    feed_path = args.out / "coastlink-release.json"
    feed_path.write_text(json.dumps(feed, indent=2) + "\n", encoding="utf-8")
    signer = TARGET / "coastlink-sign.exe"
    signature = subprocess.check_output([str(signer), "sign", str(args.key), str(feed_path)], text=True).strip()
    (args.out / "coastlink-release.json.sig").write_text(signature + "\n", encoding="ascii")
    public = (REPO / "launcher" / "update_pubkey.txt").read_text().strip()
    assert subprocess.check_output([str(signer), "verify", public, str(feed_path), signature], text=True).strip() == "valid"

    out = {"version": version, "full_zip": str(full_zip), "full_bytes": full_zip.stat().st_size, "update_zip": str(update_zip),
           "update_files": len(update_names), "feed": str(feed_path), "offline": args.offline}
    if args.runtime_source:                                     # GPL: the complete source of the shipped ssbu_native_rb.exe
        rs = args.runtime_source
        runtime = json.loads((REPO / "coastlink" / "runtime_patch" / "SOURCE.json").read_text(encoding="utf-8-sig"))
        tag = runtime["runtime_commit"].rsplit("-", 1)[-1]
        source_zip = args.out / f"CoastLink-Runtime-{tag}-Source.zip"
        with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(REPO / "LICENSE", "LICENSE")
            for path in sorted((rs / "host").rglob("*")):
                if path.is_file() and path.suffix.lower() not in (".obj", ".o", ".exe", ".pdb", ".lib"):
                    archive.write(path, "host/" + path.relative_to(rs / "host").as_posix())
            for name in ("build_host.py", "pair.py", "exercise.py", "dependencies.json"):
                if (rs / name).is_file():
                    archive.write(rs / name, name)
            archive.writestr("README.txt", f"CoastLink runtime {tag}: upstream ssbu-recomp {runtime['runtime_commit'].split('+')[0]} with the CoastLink changes\n"
                             "(search the sources for \"CoastLink\"). Build: python build_host.py --dll ssbu_game_r1.dll --out ssbu_native_rb.exe\n"
                             "(Zig, see build_host.py). GPL-3.0-or-later.\n")
        out["runtime_source"] = str(source_zip)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

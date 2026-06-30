#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


def list_manifest_paths(manifests_dir: Path) -> list[Path]:
    return sorted(path for path in manifests_dir.glob("*.json") if path.is_file())


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    required = ["app-id", "source"]
    for key in required:
        if key not in data:
            raise ValueError(f"{path}: missing required field {key!r}")

    if not isinstance(data["source"], dict):
        raise ValueError(f"{path}: field 'source' must be an object")

    return data


def github_api_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "slophub",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def resolve_github_release_asset(manifest_path: Path, source: dict[str, Any]) -> dict[str, Any]:
    repository = source.get("repository")
    asset_pattern = source.get("asset")
    release = source.get("release", "latest")

    if not repository or not asset_pattern:
        raise ValueError(
            f"{manifest_path}: github-release-asset source requires 'repository' and 'asset'"
        )

    if release == "latest":
        api_url = f"https://api.github.com/repos/{repository}/releases/latest"
    else:
        api_url = f"https://api.github.com/repos/{repository}/releases/tags/{release}"

    payload = github_api_json(api_url)
    assets = payload.get("assets", [])
    matches = [asset for asset in assets if fnmatch.fnmatch(asset.get("name", ""), asset_pattern)]

    if not matches:
        raise ValueError(f"{manifest_path}: no release asset matched pattern {asset_pattern!r}")
    if len(matches) > 1:
        names = ", ".join(asset["name"] for asset in matches)
        raise ValueError(f"{manifest_path}: asset pattern {asset_pattern!r} matched multiple assets: {names}")

    asset = matches[0]
    digest = asset.get("digest", "")
    sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else source.get("sha256")
    if not sha256:
        raise ValueError(f"{manifest_path}: could not determine sha256 for asset {asset['name']}")

    return {
        "asset_name": asset["name"],
        "bundle_url": asset["browser_download_url"],
        "bundle_sha256": sha256,
        "release_name": payload.get("name") or payload.get("tag_name") or "",
        "release_tag": payload.get("tag_name") or "",
        "release_url": payload.get("html_url") or "",
        "published_at": payload.get("published_at") or "",
        "repository": repository,
    }


def resolve_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    source = manifest["source"]
    source_type = source.get("type")

    if source_type != "github-release-asset":
        raise ValueError(f"{manifest_path}: unsupported source type {source_type!r}")

    resolved_source = resolve_github_release_asset(manifest_path, source)
    icon_url = manifest.get("icon-url") or ""

    return {
        "manifest_path": str(manifest_path),
        "app_id": manifest["app-id"],
        "branch": manifest.get("branch", "stable"),
        "title": manifest.get("title", manifest["app-id"]),
        "description": manifest.get("description", ""),
        "icon_url": icon_url,
        "homepage": manifest.get("homepage", ""),
        "source": resolved_source,
    }


def resolve_all(manifests_dir: Path) -> list[dict[str, Any]]:
    manifest_paths = list_manifest_paths(manifests_dir)
    if not manifest_paths:
        raise ValueError(f"no package manifests found in {manifests_dir}")
    return [resolve_manifest(path) for path in manifest_paths]


def write_json(data: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "slophub"})
    with urllib.request.urlopen(request) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_resolve(args: argparse.Namespace) -> int:
    packages = resolve_all(Path(args.manifests_dir))
    write_json(packages, Path(args.output))
    return 0


def command_import(args: argparse.Namespace) -> int:
    with Path(args.input).open("r", encoding="utf-8") as handle:
        packages = json.load(handle)

    repo_dir = Path(args.repo_dir)
    download_dir = Path(args.download_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    if not (repo_dir / "config").exists():
        run(["ostree", "init", f"--repo={repo_dir}", "--mode=archive-z2"])

    for package in packages:
        bundle_name = package["source"]["asset_name"]
        bundle_path = download_dir / bundle_name
        download_file(package["source"]["bundle_url"], bundle_path)
        actual_sha256 = sha256_file(bundle_path)
        expected_sha256 = package["source"]["bundle_sha256"]
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"{bundle_name}: sha256 mismatch, expected {expected_sha256}, got {actual_sha256}"
            )

        command = [
            "flatpak",
            "build-import-bundle",
            str(repo_dir),
            str(bundle_path),
            "--no-update-summary",
        ]
        if args.gpg_sign:
            command.append(f"--gpg-sign={args.gpg_sign}")
        run(command)

    return 0


def env_default(name: str, fallback: str = "") -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        return fallback
    return value


def repo_urls() -> tuple[str, str]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repository:
        owner, repo = repository.split("/", 1)
        base = f"https://{owner}.github.io/{repo}/"
    else:
        base = "https://example.invalid/"
    homepage = env_default("SLOPHUB_REPO_HOMEPAGE", base)
    repo_url = env_default("SLOPHUB_REPO_URL", f"{base}repo/")
    return homepage, repo_url


def maybe_line(name: str, value: str) -> str:
    if not value:
        return ""
    return f"{name}={value}\n"


def render_flatpakrepo(public_dir: Path, packages: list[dict[str, Any]]) -> None:
    remote_name = env_default("SLOPHUB_REMOTE_NAME", "slophub")
    repo_title = env_default("SLOPHUB_REPO_TITLE", "Slophub")
    repo_comment = env_default("SLOPHUB_REPO_COMMENT", "Flatpak remote published by Slophub.")
    repo_description = env_default(
        "SLOPHUB_REPO_DESCRIPTION",
        "Flatpak remote that republishes selected upstream Flatpak bundles.",
    )
    collection_id = env_default("SLOPHUB_COLLECTION_ID")
    default_branch = env_default("SLOPHUB_BRANCH", packages[0]["branch"] if packages else "stable")
    gpg_key_base64 = os.environ["SLOPHUB_GPG_KEY_BASE64"]
    homepage, repo_url = repo_urls()
    icon_url = env_default("SLOPHUB_ICON_URL", packages[0]["icon_url"] if packages else "")

    content = [
        "[Flatpak Repo]\n",
        f"Title={repo_title}\n",
        f"Url={repo_url}\n",
        f"Homepage={homepage}\n",
        f"Comment={repo_comment}\n",
        f"Description={repo_description}\n",
        maybe_line("Icon", icon_url),
        f"DefaultBranch={default_branch}\n",
        f"GPGKey={gpg_key_base64}\n",
        maybe_line("DeployCollectionID", collection_id),
    ]
    (public_dir / f"{remote_name}.flatpakrepo").write_text("".join(content), encoding="utf-8")


def render_flatpakrefs(public_dir: Path, packages: list[dict[str, Any]]) -> None:
    remote_name = env_default("SLOPHUB_REMOTE_NAME", "slophub")
    runtime_repo = env_default(
        "SLOPHUB_RUNTIME_REPO", "https://dl.flathub.org/repo/flathub.flatpakrepo"
    )
    gpg_key_base64 = os.environ["SLOPHUB_GPG_KEY_BASE64"]
    _, repo_url = repo_urls()

    for package in packages:
        content = [
            "[Flatpak Ref]\n",
            f"Name={package['app_id']}\n",
            f"Branch={package['branch']}\n",
            f"Title={package['title']}\n",
            f"Url={repo_url}\n",
            "IsRuntime=false\n",
            f"RuntimeRepo={runtime_repo}\n",
            f"SuggestRemoteName={remote_name}\n",
            maybe_line("Description", package["description"]),
            maybe_line("Icon", package["icon_url"]),
            f"GPGKey={gpg_key_base64}\n",
        ]
        (public_dir / f"{package['app_id']}.flatpakref").write_text("".join(content), encoding="utf-8")


def render_catalog(public_dir: Path, packages: list[dict[str, Any]]) -> None:
    remote_name = env_default("SLOPHUB_REMOTE_NAME", "slophub")
    repo_title = env_default("SLOPHUB_REPO_TITLE", "Slophub")
    repo_description = env_default(
        "SLOPHUB_REPO_DESCRIPTION",
        "Flatpak remote that republishes selected upstream Flatpak bundles.",
    )
    homepage, repo_url = repo_urls()

    catalog = {
        "remote": {
            "name": remote_name,
            "title": repo_title,
            "description": repo_description,
            "homepage_url": homepage,
            "repo_url": repo_url,
            "flatpakrepo_url": f"{homepage}{remote_name}.flatpakrepo",
        },
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "apps": [],
    }

    for package in packages:
        catalog["apps"].append(
            {
                "app_id": package["app_id"],
                "branch": package["branch"],
                "title": package["title"],
                "description": package["description"],
                "homepage_url": package["homepage"],
                "icon_url": package["icon_url"],
                "flatpakref_url": f"{homepage}{package['app_id']}.flatpakref",
                "release": {
                    "name": package["source"]["release_name"],
                    "tag": package["source"]["release_tag"],
                    "published_at": package["source"]["published_at"],
                    "url": package["source"]["release_url"],
                },
                "bundle": {
                    "asset_name": package["source"]["asset_name"],
                    "download_url": package["source"]["bundle_url"],
                    "sha256": package["source"]["bundle_sha256"],
                },
            }
        )

    write_json(catalog, public_dir / "apps.json")


def command_render_metadata(args: argparse.Namespace) -> int:
    with Path(args.input).open("r", encoding="utf-8") as handle:
        packages = json.load(handle)

    public_dir = Path(args.public_dir)
    public_dir.mkdir(parents=True, exist_ok=True)
    render_flatpakrepo(public_dir, packages)
    render_flatpakrefs(public_dir, packages)
    render_catalog(public_dir, packages)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--manifests-dir", default="manifests")
    resolve_parser.add_argument("--output", required=True)
    resolve_parser.set_defaults(func=command_resolve)

    import_parser = subparsers.add_parser("import-bundles")
    import_parser.add_argument("--input", required=True)
    import_parser.add_argument("--download-dir", required=True)
    import_parser.add_argument("--repo-dir", required=True)
    import_parser.add_argument("--gpg-sign")
    import_parser.set_defaults(func=command_import)

    render_parser = subparsers.add_parser("render-metadata")
    render_parser.add_argument("--input", required=True)
    render_parser.add_argument("--public-dir", default="public")
    render_parser.set_defaults(func=command_render_metadata)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise

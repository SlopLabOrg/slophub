#!/usr/bin/env python3

from __future__ import annotations

import argparse
import configparser
from datetime import UTC, datetime
import fnmatch
import gzip
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
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

    screenshots = []
    for entry in manifest.get("screenshots", []):
        if isinstance(entry, str):
            screenshots.append({"url": entry, "caption": manifest.get("title", manifest["app-id"])})
        elif isinstance(entry, dict) and entry.get("url"):
            screenshots.append(
                {
                    "url": entry["url"],
                    "caption": entry.get("caption", manifest.get("title", manifest["app-id"])),
                }
            )
        else:
            raise ValueError(f"{manifest_path}: invalid screenshot entry {entry!r}")

    return {
        "manifest_path": str(manifest_path),
        "app_id": manifest["app-id"],
        "branch": manifest.get("branch", "stable"),
        "title": manifest.get("title", manifest["app-id"]),
        "description": manifest.get("description", ""),
        "icon_url": icon_url,
        "homepage": manifest.get("homepage", ""),
        "screenshots": screenshots,
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


def capture(command: list[str]) -> str:
    return subprocess.check_output(command, text=True)


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


def ensure_png_icon(source_path: Path, destination_path: Path, size: int) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower()
    if suffix == ".png":
        from PIL import Image

        with Image.open(source_path) as image:
            image = image.convert("RGBA")
            image.thumbnail((size, size))
            image.save(destination_path, format="PNG")
        return

    if suffix == ".svg":
        try:
            import cairosvg
        except ImportError as exc:
            raise RuntimeError(
                "cairosvg is required to rasterize SVG icons for AppStream metadata"
            ) from exc

        cairosvg.svg2png(
            url=str(source_path),
            write_to=str(destination_path),
            output_width=size,
            output_height=size,
        )
        return

    raise ValueError(f"unsupported icon format for AppStream rasterization: {source_path}")


def find_imported_ref(repo_dir: Path, app_id: str, branch: str) -> str:
    refs = capture(["ostree", "refs", f"--repo={repo_dir}"]).splitlines()
    suffix = f"/{branch}"
    prefix = f"app/{app_id}/"
    matches = [ref for ref in refs if ref.startswith(prefix) and ref.endswith(suffix)]
    if not matches:
        raise ValueError(f"could not find imported ref for {app_id} branch {branch}")
    if len(matches) > 1:
        raise ValueError(f"multiple refs found for {app_id} branch {branch}: {', '.join(matches)}")
    return matches[0]


def repo_cat(repo_dir: Path, ref: str, path: str) -> bytes:
    return subprocess.check_output(["ostree", "cat", f"--repo={repo_dir}", ref, path])


def repo_has_path(repo_dir: Path, ref: str, path: str) -> bool:
    result = subprocess.run(
        ["ostree", "ls", f"--repo={repo_dir}", ref, path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def first_existing_path(repo_dir: Path, ref: str, candidates: list[str]) -> str:
    for candidate in candidates:
        if repo_has_path(repo_dir, ref, candidate):
            return candidate
    raise ValueError(f"none of the candidate paths exist for {ref}: {', '.join(candidates)}")


def parse_flatpak_metadata(repo_dir: Path, ref: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(repo_cat(repo_dir, ref, "/metadata").decode("utf-8"))
    return parser


def build_component_xml(
    repo_dir: Path,
    ref: str,
    package: dict[str, Any],
    icons_root: Path,
) -> ET.Element:
    metainfo_path = first_existing_path(
        repo_dir,
        ref,
        [
            f"/files/share/metainfo/{package['app_id']}.metainfo.xml",
            f"/export/share/metainfo/{package['app_id']}.metainfo.xml",
        ],
    )
    component = ET.fromstring(repo_cat(repo_dir, ref, metainfo_path))
    metadata = parse_flatpak_metadata(repo_dir, ref)

    icon_candidates = [
        f"/files/share/icons/hicolor/128x128/apps/{package['app_id']}.png",
        f"/files/share/icons/hicolor/scalable/apps/{package['app_id']}.svg",
        f"/export/share/icons/hicolor/128x128/apps/{package['app_id']}.png",
        f"/export/share/icons/hicolor/scalable/apps/{package['app_id']}.svg",
    ]
    icon_path = first_existing_path(repo_dir, ref, icon_candidates)
    icon_source_path = icons_root / Path(icon_path).name
    icon_source_path.parent.mkdir(parents=True, exist_ok=True)
    icon_source_path.write_bytes(repo_cat(repo_dir, ref, icon_path))

    for size in (64, 128):
        ensure_png_icon(
            icon_source_path,
            icons_root / str(size) / f"{package['app_id']}.png",
            size,
        )

    for existing_icon in list(component.findall("icon")):
        if existing_icon.attrib.get("type") == "cached":
            component.remove(existing_icon)

    cached_64 = ET.Element("icon", {"type": "cached", "width": "64", "height": "64"})
    cached_64.text = f"{package['app_id']}.png"
    cached_128 = ET.Element("icon", {"type": "cached", "width": "128", "height": "128"})
    cached_128.text = f"{package['app_id']}.png"
    component.insert(0, cached_128)
    component.insert(0, cached_64)

    if not any(icon.attrib.get("type") == "stock" for icon in component.findall("icon")):
        stock = ET.Element("icon", {"type": "stock"})
        stock.text = package["app_id"]
        component.insert(0, stock)

    existing_bundle = component.find("bundle")
    if existing_bundle is None:
        bundle_attrs = {"type": "flatpak"}
        runtime = metadata.get("Application", "runtime", fallback="")
        sdk = metadata.get("Application", "sdk", fallback="")
        if runtime:
            bundle_attrs["runtime"] = runtime
        if sdk:
            bundle_attrs["sdk"] = sdk
        bundle = ET.Element("bundle", bundle_attrs)
        bundle.text = ref
        component.append(bundle)

    if package["screenshots"]:
        screenshots_node = component.find("screenshots")
        if screenshots_node is None:
            screenshots_node = ET.SubElement(component, "screenshots")

        existing_sources = {
            image.text or ""
            for screenshot in screenshots_node.findall("screenshot")
            for image in screenshot.findall("image")
        }

        is_first = len(screenshots_node.findall("screenshot")) == 0
        for screenshot_data in package["screenshots"]:
            screenshot_url = screenshot_data["url"]
            if screenshot_url in existing_sources:
                continue
            attrs = {"type": "default"} if is_first else {}
            screenshot = ET.SubElement(screenshots_node, "screenshot", attrs)
            image = ET.SubElement(screenshot, "image", {"type": "source"})
            image.text = screenshot_url
            caption = ET.SubElement(screenshot, "caption")
            caption.text = screenshot_data["caption"]
            is_first = False

    return component


def write_appstream_catalog(path: Path, components: list[ET.Element]) -> None:
    root = ET.Element("components", {"version": "0.8", "origin": "flatpak"})
    for component in components:
        root.append(component)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def commit_directory_to_repo(
    repo_dir: Path,
    branch: str,
    source_dir: Path,
    subject: str,
    gpg_sign: str | None,
) -> None:
    command = [
        "ostree",
        "commit",
        f"--repo={repo_dir}",
        f"--branch={branch}",
        "--tree",
        f"dir={source_dir}",
        "--subject",
        subject,
    ]
    if gpg_sign:
        command.extend(["--gpg-sign", gpg_sign])
    run(command)


def generate_appstream(repo_dir: Path, packages: list[dict[str, Any]], gpg_sign: str | None) -> None:
    refs_by_arch: dict[str, list[tuple[dict[str, Any], str]]] = {}
    for package in packages:
        ref = find_imported_ref(repo_dir, package["app_id"], package["branch"])
        parts = ref.split("/")
        if len(parts) != 4:
            raise ValueError(f"unexpected ref format: {ref}")
        arch = parts[2]
        refs_by_arch.setdefault(arch, []).append((package, ref))

    temp_root = repo_dir.parent / ".slophub-appstream"
    if temp_root.exists():
        subprocess.run(["rm", "-rf", str(temp_root)], check=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    for arch, entries in refs_by_arch.items():
        icons_source_root = temp_root / arch / "icon-sources"
        icons_cache_root = temp_root / arch / "icons"
        components = []
        for package, ref in entries:
            components.append(build_component_xml(repo_dir, ref, package, icons_source_root))

        appstream2_root = temp_root / arch / "appstream2"
        appstream_root = temp_root / arch / "appstream"
        (appstream2_root / "icons").mkdir(parents=True, exist_ok=True)
        (appstream_root / "icons").mkdir(parents=True, exist_ok=True)

        write_appstream_catalog(appstream2_root / "appstream.xml", components)
        xml_bytes = (appstream2_root / "appstream.xml").read_bytes()
        with gzip.open(appstream_root / "appstream.xml.gz", "wb") as handle:
            handle.write(xml_bytes)

        for size in (64, 128):
            source_size_dir = icons_source_root / str(size)
            if source_size_dir.exists():
                for target_root in (appstream2_root, appstream_root):
                    target_dir = target_root / "icons" / f"{size}x{size}"
                    target_dir.mkdir(parents=True, exist_ok=True)
                    for icon_path in source_size_dir.glob("*.png"):
                        destination = target_dir / icon_path.name
                        destination.write_bytes(icon_path.read_bytes())

        commit_directory_to_repo(
            repo_dir,
            f"appstream2/{arch}",
            appstream2_root,
            f"Update appstream2 for {arch}",
            gpg_sign,
        )
        commit_directory_to_repo(
            repo_dir,
            f"appstream/{arch}",
            appstream_root,
            f"Update appstream for {arch}",
            gpg_sign,
        )


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

    generate_appstream(repo_dir, packages, args.gpg_sign)
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

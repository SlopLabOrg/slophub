# Slophub

This repository is used to make Flatpak apps available through the `Slophub` remote.

If you want your app to be available here, the requirement is simple: your project must publish a `.flatpak` file in a GitHub release.

## How to add your app

1. Create a `manifests/<APP_ID>.json` file.
2. Point that file to your project's GitHub release.
3. Commit and push.
4. CI will download the `.flatpak`, import it into the `Slophub` remote, and publish an `<APP_ID>.flatpakref`.

## Manifest format

Example:

```json
{
  "app-id": "dev.parquetta.Parquetta",
  "branch": "master",
  "title": "Parquetta",
  "description": "Preview and query Parquet files with DuckDB.",
  "homepage": "https://github.com/ogregorio/parquetta",
  "icon-url": "https://raw.githubusercontent.com/ogregorio/parquetta/main/Parquetta.svg",
  "screenshots": [
    {
      "url": "https://raw.githubusercontent.com/ogregorio/parquetta/main/assets/Screenshot.png",
      "caption": "Parquetta previewing a Parquet file"
    }
  ],
  "source": {
    "type": "github-release-asset",
    "repository": "ogregorio/parquetta",
    "release": "latest",
    "asset": "parquetta-*.flatpak"
  }
}
```

## Fields

- `app-id`: Flatpak app ID.
- `branch`: branch published inside the bundle. It must match the actual branch in the `.flatpak`.
- `title`: display name.
- `description`: short app description.
- `homepage`: project page.
- `icon-url`: public icon URL.
- `screenshots`: optional list of screenshot objects with `url` and optional `caption` to inject into AppStream metadata.
- `source.type`: currently the supported value is `github-release-asset`.
- `source.repository`: GitHub repository in `owner/repo` format.
- `source.release`: `latest` or a specific tag.
- `source.asset`: asset name, with glob support, as long as it resolves to a single `.flatpak`.

## What Slophub publishes

For each configured app, the repository publishes:

- `repo/` containing the app in the remote
- `slophub.flatpakrepo`
- `<APP_ID>.flatpakref`
- `apps.json` with metadata for the published apps
- AppStream metadata intended for software centers such as GNOME Software

## How users install apps

```bash
flatpak remote-add --if-not-exists slophub https://<owner>.github.io/<repo>/repo/
flatpak install slophub <APP_ID>
```

## GNOME Software

To add the remote in GNOME Software, open:

```text
https://<owner>.github.io/<repo>/slophub.flatpakrepo
```

To install a specific app directly in GNOME Software, open:

```text
https://<owner>.github.io/<repo>/<APP_ID>.flatpakref
```

`Slophub` also publishes AppStream metadata for the imported apps so software centers can index them more reliably.

## JSON catalog

The public catalog is available at:

```text
https://<owner>.github.io/<repo>/apps.json
```

It includes:

- remote metadata
- published app list
- `.flatpakref` URL for each app
- upstream release metadata
- imported bundle URL and `sha256`

## Updates

`Slophub` checks for new releases periodically. When the upstream `.flatpak` changes, the remote is updated and users receive the new version through `flatpak update`.

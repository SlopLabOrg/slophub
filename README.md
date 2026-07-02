# Slophub

Slophub republishes Flatpak apps through the `slophub` remote.

If you want your app to be available here, your project must publish a `.flatpak` file in a GitHub release.

## Add an app

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
  "categories": ["Development", "Database"],
  "homepage": "https://github.com/ogregorio/parquetta",
  "icon-path": "Parquetta.svg",
  "metainfo-path": "packaging/dev.parquetta.Parquetta.metainfo.xml",
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
- `categories`: optional list of app categories. These values are also published in `apps.json` and merged into the generated AppStream metadata.
- `homepage`: project page.
- `icon-path`: required path to the upstream icon file inside the source repository. Slophub fetches this file from the resolved release tag and uses it for AppStream icons and the catalog icon URL.
- `metainfo-path`: required path to the upstream AppStream metainfo file inside the source repository. Slophub fetches this file from the resolved release tag when generating AppStream metadata.
- `icon-url`: optional public icon URL override for the catalog.
- `screenshots`: optional list of screenshot objects with `url` and optional `caption` to inject into AppStream metadata.
- `source.type`: currently the supported value is `github-release-asset`.
- `source.repository`: GitHub repository in `owner/repo` format.
- `source.release`: `latest` or a specific tag.
- `source.asset`: asset name, with glob support, as long as it resolves to a single `.flatpak`.

## Categories

Use `categories` as a JSON array with one or more of these values:

- `Audio`
- `AudioVideo`
- `Database`
- `Development`
- `Education`
- `Game`
- `Graphics`
- `IDE`
- `Network`
- `Office`
- `Science`
- `Settings`
- `Spreadsheet`
- `System`
- `Utility`
- `Video`

For each configured app, Slophub publishes:

- `repo/` containing the app in the remote
- `slophub.flatpakrepo`
- `<APP_ID>.flatpakref`
- `apps.json` with metadata for the published apps
- AppStream metadata intended for software centers such as GNOME Software

## Add the Slophub remote

```bash
flatpak remote-add --if-not-exists slophub https://dl.sloplab.org/repo/
```

## GNOME Software

To add the remote in GNOME Software, open:

```text
https://dl.sloplab.org/slophub.flatpakrepo
```

## Install an app

```bash
flatpak install slophub <APP_ID>
```

To install a specific app directly in GNOME Software, open:

```text
https://dl.sloplab.org/<APP_ID>.flatpakref
```

`Slophub` also publishes AppStream metadata for the imported apps so software centers can index them more reliably.

## JSON catalog

The public catalog is available at:

```text
https://dl.sloplab.org/apps.json
```

It includes:

- remote metadata
- published app list
- app categories
- `.flatpakref` URL for each app
- upstream release metadata
- imported bundle URL and `sha256`

## Updates

`Slophub` checks for new releases periodically. When the upstream `.flatpak` changes, the remote is updated and users receive the new version through `flatpak update`.

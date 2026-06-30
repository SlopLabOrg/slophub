# Slophub

GitHub repository template for hosting a Flatpak repository named `Slophub` with GitHub Actions and GitHub Pages.

The structure follows the flow described in the official Flatpak documentation for hosting OSTree repositories: build the repository with `flatpak-builder`, update it with `flatpak build-update-repo`, sign it with GPG, and publish the static artifacts over HTTP.

Official reference:

- https://docs.flatpak.org/en/latest/hosting-a-repository.html

## What this repository provides

- validation workflow for pull requests
- build and publish workflow for GitHub Pages
- automatic generation of:
  - `slophub.flatpakrepo`
  - `<APP_ID>.flatpakref`
  - `repo/` with the OSTree contents
  - `index.html` for installation

## Structure

```text
.github/workflows/
  build-and-publish.yml
  validate-manifest.yml
manifests/
  README.md
scripts/
  render-flatpak-metadata.sh
```

## How to use

1. Add the Flatpak manifest under `manifests/`.
2. Configure GitHub Pages to use `GitHub Actions` as the source.
3. Create the repository variables below in `Settings > Secrets and variables > Actions > Variables`.
4. Create the GPG secrets in `Settings > Secrets and variables > Actions > Secrets`.
5. Push to the `main` branch.

## Repository variables

Required:

- `SLOPHUB_APP_ID`  
  Example: `io.github.youruser.YourApp`
- `SLOPHUB_MANIFEST_PATH`  
  Example: `manifests/io.github.youruser.YourApp.yml`
- `SLOPHUB_GPG_KEY_ID`  
  Example: `ABCDEF0123456789`

Optional:

- `SLOPHUB_BRANCH`  
  Default: `stable`
- `SLOPHUB_COLLECTION_ID`  
  Example: `io.github.youruser.Slophub`
- `SLOPHUB_REMOTE_NAME`  
  Default: `slophub`
- `SLOPHUB_REPO_TITLE`  
  Default: `Slophub`
- `SLOPHUB_REPO_COMMENT`
- `SLOPHUB_REPO_DESCRIPTION`
- `SLOPHUB_REPO_HOMEPAGE`
- `SLOPHUB_REPO_URL`
- `SLOPHUB_RUNTIME_REPO`  
  Default: `https://dl.flathub.org/repo/flathub.flatpakrepo`
- `SLOPHUB_ICON_URL`
- `SLOPHUB_DESCRIPTION`

## Required secrets

- `SLOPHUB_GPG_PRIVATE_KEY`  
  ASCII-armored private key used to sign the repository.
- `SLOPHUB_GPG_PASSPHRASE`  
  Passphrase for the private key.

## Generating the GPG key

Local example:

```bash
gpg --full-generate-key
gpg --list-secret-keys --keyid-format=long
gpg --armor --export-secret-keys ABCDEF0123456789
```

Use the output of the last command as the value of `SLOPHUB_GPG_PRIVATE_KEY`.

## Published output

After deployment, GitHub Pages will publish:

- `https://<owner>.github.io/<repo>/slophub.flatpakrepo`
- `https://<owner>.github.io/<repo>/<APP_ID>.flatpakref`
- `https://<owner>.github.io/<repo>/repo/`

## Repository installation

```bash
flatpak remote-add --if-not-exists slophub https://<owner>.github.io/<repo>/repo/
```

## App installation

```bash
flatpak install slophub <APP_ID>
```

## Notes

- The validation workflow uses `--stop-at=modules` to catch manifest errors early without publishing anything.
- Deployment uses the `ghcr.io/flathub-infra/flatpak-github-actions:gnome-48` image, which already includes a suitable Flatpak toolchain for CI.
- The app manifest is not included here because it depends on the package you want to distribute.

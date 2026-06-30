#!/usr/bin/env bash

set -euo pipefail

repo_name="${GITHUB_REPOSITORY##*/}"
repo_owner="${GITHUB_REPOSITORY%%/*}"

remote_name="${SLOPHUB_REMOTE_NAME:-slophub}"
app_id="${SLOPHUB_APP_ID:?SLOPHUB_APP_ID is required}"
branch="${SLOPHUB_BRANCH:-stable}"
repo_title="${SLOPHUB_REPO_TITLE:-Slophub}"
repo_comment="${SLOPHUB_REPO_COMMENT:-Slophub Flatpak repository}"
repo_description="${SLOPHUB_REPO_DESCRIPTION:-Flatpak repository published with GitHub Actions and GitHub Pages.}"
repo_homepage="${SLOPHUB_REPO_HOMEPAGE:-https://${repo_owner}.github.io/${repo_name}/}"
repo_url="${SLOPHUB_REPO_URL:-https://${repo_owner}.github.io/${repo_name}/repo/}"
runtime_repo="${SLOPHUB_RUNTIME_REPO:-https://dl.flathub.org/repo/flathub.flatpakrepo}"
icon_url="${SLOPHUB_ICON_URL:-https://${repo_owner}.github.io/${repo_name}/icon.png}"
description="${SLOPHUB_DESCRIPTION:-Flatpak package distributed by Slophub.}"
gpg_key_base64="${SLOPHUB_GPG_KEY_BASE64:?SLOPHUB_GPG_KEY_BASE64 is required}"
collection_id="${SLOPHUB_COLLECTION_ID:-}"

mkdir -p public

cat > "public/${remote_name}.flatpakrepo" <<EOF
[Flatpak Repo]
Title=${repo_title}
Url=${repo_url}
Homepage=${repo_homepage}
Comment=${repo_comment}
Description=${repo_description}
Icon=${icon_url}
DefaultBranch=${branch}
GPGKey=${gpg_key_base64}
EOF

if [ -n "${collection_id}" ]; then
  printf 'DeployCollectionID=%s\n' "${collection_id}" >> "public/${remote_name}.flatpakrepo"
fi

cat > "public/${app_id}.flatpakref" <<EOF
[Flatpak Ref]
Name=${app_id}
Branch=${branch}
Title=${repo_title}
Url=${repo_url}
IsRuntime=false
RuntimeRepo=${runtime_repo}
SuggestRemoteName=${remote_name}
Description=${description}
Icon=${icon_url}
GPGKey=${gpg_key_base64}
EOF

cat > public/index.html <<EOF
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${repo_title}</title>
    <style>
      :root {
        color-scheme: light dark;
        font-family: Inter, system-ui, sans-serif;
      }
      body {
        margin: 0;
        padding: 32px;
        line-height: 1.5;
      }
      main {
        max-width: 720px;
      }
      pre {
        overflow: auto;
        padding: 16px;
        border: 1px solid #8884;
      }
      a {
        word-break: break-word;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>${repo_title}</h1>
      <p>${repo_description}</p>
      <p><a href="./${remote_name}.flatpakrepo">Download ${remote_name}.flatpakrepo</a></p>
      <p><a href="./${app_id}.flatpakref">Download ${app_id}.flatpakref</a></p>
      <pre>flatpak remote-add --if-not-exists ${remote_name} ${repo_url}
flatpak install ${remote_name} ${app_id}</pre>
    </main>
  </body>
</html>
EOF

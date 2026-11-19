# Signed Android releases and updates

## One-time signing setup (required before the first public release)

Create a dedicated Android upload/release keystore and keep a secure offline backup.
Never commit the keystore or passwords to this repository.

Add these GitHub Actions repository secrets:

- `ANDROID_KEYSTORE_BASE64`: base64-encoded complete JKS/PKCS12 keystore file
- `ANDROID_KEYSTORE_PASSWORD`: keystore password
- `ANDROID_KEY_ALIAS`: key alias
- `ANDROID_KEY_PASSWORD`: private-key password

The workflow uses the same key for every release. Losing or replacing it prevents in-place updates for users who installed an APK signed by the old key.

## Build behavior

- Pull requests and ordinary branch builds can produce unsigned inspection APKs if signing secrets are not configured.
- A version tag such as `v1.0.1` requires all signing secrets and a verifiably signed APK. It then publishes `molido-agro-ai.apk` and `latest.json` as a GitHub Release.
- Never distribute an unsigned APK as a production update.

## Android update limitation

Android does not allow a normal sideloaded app to silently install its own APK. An updater can check releases, download and verify the package, then invoke Android's package installer; the user must approve installation (and allow this source if not already allowed). Fully unattended installation requires a managed/device-owner deployment or an app-store managed update channel.

The release manifest is designed for the in-app updater. Each release must increment `versionCode`; do not reuse a version code.


## Existing keystore location

The setup script uses `$HOME/.config/molido-agro-signing/molido-release.p12` by default. If the existing release keystore is stored elsewhere, pass its exact path without moving or replacing it:

```bash
MOLIDO_KEYSTORE_PATH="/absolute/path/to/existing-release.p12" bash scripts/setup-android-signing.sh
```

The script validates the selected file before changing any GitHub secret. It never creates a replacement key unless `--new-key` is explicitly requested, and it refuses to overwrite an existing file.

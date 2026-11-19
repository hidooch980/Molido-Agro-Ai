#!/usr/bin/env bash
set -Eeuo pipefail

REPO="hidooch980/Molido-Agro-Ai"
ALIAS="molido-release"
KEY_DIR="${HOME}/.config/molido-agro-signing"
KEYSTORE="${MOLIDO_KEYSTORE_PATH:-${KEY_DIR}/molido-release.p12}"
MODE="${1:-}"

command -v keytool >/dev/null 2>&1 || { echo "ERROR: keytool missing. Install an OpenJDK package in Termux."; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "ERROR: GitHub CLI (gh) missing."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: Sign in first with: gh auth login"; exit 1; }

mkdir -p "$(dirname "$KEYSTORE")"
if [[ "$(dirname "$KEYSTORE")" == "$KEY_DIR" ]]; then chmod 700 "$KEY_DIR"; fi

if [[ "$MODE" == "--new-key" ]]; then
  if [[ -e "$KEYSTORE" ]]; then
    echo "ERROR: Refusing to overwrite existing keystore: $KEYSTORE"
    echo "Back it up and move it yourself before explicitly creating a replacement."
    exit 1
  fi
  echo "WARNING: A new signing identity is permanent. Existing APKs signed with another key cannot be updated with this key."
  read -r -p "Type CREATE-NEW-KEY to confirm: " CONFIRM
  [[ "$CONFIRM" == "CREATE-NEW-KEY" ]] || { echo "Cancelled."; exit 1; }
  read -rsp "Choose a strong keystore password (12+ characters): " PASS
  echo
  [[ ${#PASS} -ge 12 ]] || { unset PASS; echo "ERROR: Password must be at least 12 characters."; exit 1; }
  keytool -genkeypair -noprompt -v -storetype PKCS12 \
    -keystore "$KEYSTORE" -storepass "$PASS" -keypass "$PASS" \
    -alias "$ALIAS" -keyalg RSA -keysize 3072 -validity 10000 \
    -dname "CN=Molido Agro AI, OU=Android, O=Molido, L=Tehran, ST=Tehran, C=IR"
else
  [[ -s "$KEYSTORE" ]] || {
    echo "ERROR: Keystore not found: $KEYSTORE"
    echo "If this is the first signing identity, run this script with --new-key."
    exit 1
  }
  read -rsp "Enter the EXISTING keystore password: " PASS
  echo
fi

if ! keytool -list -storetype PKCS12 -keystore "$KEYSTORE" -storepass "$PASS" -alias "$ALIAS" >/dev/null 2>&1; then
  unset PASS
  echo "ERROR: Keystore/password/alias validation failed. No GitHub secrets were changed."
  exit 1
fi

# Verify the private-key password too; for PKCS12 Android signing it must match the store password.
CSR="$KEY_DIR/.molido-signing-check.csr"
if ! keytool -certreq -storetype PKCS12 -keystore "$KEYSTORE" -storepass "$PASS" \
  -keypass "$PASS" -alias "$ALIAS" -file "$CSR" >/dev/null 2>&1; then
  rm -f "$CSR"
  unset PASS
  echo "ERROR: Private key could not be unlocked. No GitHub secrets were changed."
  exit 1
fi
rm -f "$CSR"
chmod 600 "$KEYSTORE"

TMP="$(mktemp -d "$KEY_DIR/secrets.XXXXXX")"
chmod 700 "$TMP"
cleanup() { rm -rf "$TMP"; unset PASS; }
trap cleanup EXIT

base64 "$KEYSTORE" | tr -d '\r\n' > "$TMP/keystore.b64"
printf '%s' "$PASS" > "$TMP/storepass"
printf '%s' "$ALIAS" > "$TMP/alias"
printf '%s' "$PASS" > "$TMP/keypass"
chmod 600 "$TMP"/*

echo "Keystore and private key validated locally."
gh secret set ANDROID_KEYSTORE_BASE64 --repo "$REPO" < "$TMP/keystore.b64"
gh secret set ANDROID_KEYSTORE_PASSWORD --repo "$REPO" < "$TMP/storepass"
gh secret set ANDROID_KEY_ALIAS --repo "$REPO" < "$TMP/alias"
gh secret set ANDROID_KEY_PASSWORD --repo "$REPO" < "$TMP/keypass"

echo "Configured secret names (values are never displayed):"
gh secret list --repo "$REPO"

echo "Starting Android CI on foundation/android-release-foundation..."
gh workflow run release-build.yml --repo "$REPO" --ref foundation/android-release-foundation
echo "Submitted. Check: https://github.com/$REPO/actions"

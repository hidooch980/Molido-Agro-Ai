#!/usr/bin/env bash
set -Eeuo pipefail

REPO="hidooch980/Molido-Agro-Ai"
ALIAS="molido-release"
KEY_DIR="${HOME}/.config/molido-agro-signing"
KEYSTORE="${MOLIDO_KEYSTORE_PATH:-${KEY_DIR}/molido-release.p12}"
PASSWORD_FILE="${KEY_DIR}/molido-release-password.txt"
MODE="${1:-}"
AUTO="${2:-}"

command -v keytool >/dev/null 2>&1 || { echo "ERROR: keytool missing."; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "ERROR: GitHub CLI (gh) missing."; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "ERROR: OpenSSL missing."; exit 1; }
command -v base64 >/dev/null 2>&1 || { echo "ERROR: base64 missing."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "ERROR: GitHub CLI authentication required."; exit 1; }

mkdir -p "$KEY_DIR" "$(dirname "$KEYSTORE")"
chmod 700 "$KEY_DIR"

if [[ "$MODE" == "--new-key" ]]; then
  [[ "$AUTO" == "--yes" ]] || { echo "ERROR: Use --new-key --yes to explicitly confirm a new signing identity."; exit 1; }
  if [[ -e "$KEYSTORE" || -e "$PASSWORD_FILE" ]]; then
    echo "ERROR: A keystore or password file already exists. Refusing to overwrite either."
    exit 1
  fi

  # Generate a high-entropy password locally; never print it.
  PASS="$(openssl rand -hex 32)"
  (umask 077; printf '%s' "$PASS" > "$PASSWORD_FILE")
  chmod 600 "$PASSWORD_FILE"

  if ! keytool -genkeypair -noprompt -storetype PKCS12 \
    -keystore "$KEYSTORE" -storepass "$PASS" -keypass "$PASS" \
    -alias "$ALIAS" -keyalg RSA -keysize 3072 -validity 10000 \
    -dname "CN=Molido Agro AI, OU=Android, O=Molido, L=Tehran, ST=Tehran, C=IR" \
    >/dev/null; then
    rm -f "$KEYSTORE" "$PASSWORD_FILE"
    unset PASS
    echo "ERROR: Key generation failed; partial files removed."
    exit 1
  fi
else
  [[ -s "$KEYSTORE" && -s "$PASSWORD_FILE" ]] || {
    echo "ERROR: Existing keystore/password file pair not found."
    exit 1
  }
  PASS="$(cat "$PASSWORD_FILE")"
fi

if ! keytool -list -storetype PKCS12 -keystore "$KEYSTORE" -storepass "$PASS" -alias "$ALIAS" >/dev/null 2>&1; then
  unset PASS
  echo "ERROR: Keystore/password/alias validation failed. GitHub secrets unchanged."
  exit 1
fi

CSR="$KEY_DIR/.molido-signing-check.csr"
if ! keytool -certreq -storetype PKCS12 -keystore "$KEYSTORE" -storepass "$PASS" \
  -keypass "$PASS" -alias "$ALIAS" -file "$CSR" >/dev/null 2>&1; then
  rm -f "$CSR"
  unset PASS
  echo "ERROR: Private key could not be unlocked. GitHub secrets unchanged."
  exit 1
fi
rm -f "$CSR"
chmod 600 "$KEYSTORE" "$PASSWORD_FILE"

TMP="$(mktemp -d "$KEY_DIR/secrets.XXXXXX")"
chmod 700 "$TMP"
cleanup() { rm -rf "$TMP"; unset PASS; }
trap cleanup EXIT

base64 "$KEYSTORE" | tr -d '\r\n' > "$TMP/keystore.b64"
printf '%s' "$PASS" > "$TMP/storepass"
printf '%s' "$ALIAS" > "$TMP/alias"
printf '%s' "$PASS" > "$TMP/keypass"
chmod 600 "$TMP"/*

echo "Local PKCS12 keystore and private key validated."
gh secret set ANDROID_KEYSTORE_BASE64 --repo "$REPO" < "$TMP/keystore.b64"
gh secret set ANDROID_KEYSTORE_PASSWORD --repo "$REPO" < "$TMP/storepass"
gh secret set ANDROID_KEY_ALIAS --repo "$REPO" < "$TMP/alias"
gh secret set ANDROID_KEY_PASSWORD --repo "$REPO" < "$TMP/keypass"

echo "Configured GitHub secret names (values are not displayed):"
gh secret list --repo "$REPO"

echo "Dispatching Android CI on $GITHUB_REF_NAME..."
gh workflow run release-build.yml --repo "$REPO" --ref "${GITHUB_REF_NAME:-foundation/android-release-foundation}"
echo "Workflow dispatched. Monitor https://github.com/$REPO/actions"

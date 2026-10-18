#!/usr/bin/env bash
# Encrypt teacher playbooks for the public site.
#
#   ./utils/encrypt-playbooks.sh                 # every playbook in private/teach-src/
#   ./utils/encrypt-playbooks.sh unit5-cicd-iac  # just one
#
# Plaintext sources live in private/teach-src/ (git-ignored, never committed).
# The encrypted copies are written to docs/teach-5t27uuv8/ and are what gets
# committed and published. Each opens only after the password is typed.
#
# Password: taken from STATICRYPT_PASSWORD if set, otherwise asked for (twice).
# Use the SAME password every time, or older pages stay on the old one.
# The salt in .staticrypt.json is not secret; keep it so "Remember me" keeps
# working across pages and re-encryptions.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/private/teach-src"
OUT="$ROOT/docs/teach-5t27uuv8"
STATICRYPT="staticrypt@3.5.4"

# Local preview link: private/teach-src/playbook -> the shared CSS/JS.
[ -e "$SRC/playbook" ] || ln -s ../../docs/teach-5t27uuv8/playbook "$SRC/playbook"

command -v npx >/dev/null || { echo "npx not found: install Node.js first." >&2; exit 1; }

files=()
if [ "$#" -gt 0 ]; then
  for name in "$@"; do files+=("$SRC/${name%.html}.html"); done
else
  for f in "$SRC"/*.html; do [ -e "$f" ] && files+=("$f"); done
fi
[ "${#files[@]}" -gt 0 ] || { echo "No playbooks found in $SRC" >&2; exit 1; }
for f in "${files[@]}"; do [ -f "$f" ] || { echo "Missing: $f" >&2; exit 1; }; done

if [ -z "${STATICRYPT_PASSWORD:-}" ]; then
  read -rsp "Playbook password: " STATICRYPT_PASSWORD; echo
  read -rsp "Repeat password:   " again; echo
  [ "$STATICRYPT_PASSWORD" = "$again" ] || { echo "Passwords differ." >&2; exit 1; }
fi
# Short passwords are easier to brute-force offline (the encrypted pages are
# public), so they need an explicit opt-in: ALLOW_SHORT_PASSWORD=1.
short=()
if [ "${#STATICRYPT_PASSWORD}" -lt 14 ]; then
  if [ "${ALLOW_SHORT_PASSWORD:-0}" = "1" ]; then
    echo "Warning: password under 14 characters (ALLOW_SHORT_PASSWORD=1)." >&2
    short=(--short)
  else
    echo "Use at least 14 characters, or set ALLOW_SHORT_PASSWORD=1 to accept a shorter one." >&2; exit 1
  fi
fi
export STATICRYPT_PASSWORD

# StaticCrypt prefixes "./" to the config path, so paths must be relative to ROOT.
cd "$ROOT"
rel=()
for f in "${files[@]}"; do rel+=("${f#"$ROOT"/}"); done
npx --yes "$STATICRYPT" "${rel[@]}" ${short[@]+"${short[@]}"} \
  --directory "${OUT#"$ROOT"/}" \
  --config .staticrypt.json \
  --remember 30 \
  --template-title "DSO303 Teaching Area" \
  --template-instructions "Teacher access only." \
  --template-button "Open" \
  --template-placeholder "Password" \
  --template-error "Wrong password." \
  --template-remember "Remember this device for 30 days" \
  --template-color-primary "#1d4ed8" \
  --template-color-secondary "#000000"

# Never publish plaintext: every output must be a StaticCrypt page.
for f in "${files[@]}"; do
  out="$OUT/$(basename "$f")"
  grep -q "staticrypt" "$out" || { echo "Not encrypted: $out" >&2; exit 1; }
  echo "Encrypted: ${out#"$ROOT"/}"
done

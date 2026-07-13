#!/bin/zsh -f
set -euo pipefail

readonly -a forbidden_git_environment=(
  GIT_DIR
  GIT_WORK_TREE
  GIT_INDEX_FILE
  GIT_OBJECT_DIRECTORY
  GIT_ALTERNATE_OBJECT_DIRECTORIES
  GIT_COMMON_DIR
  GIT_CONFIG
  GIT_CONFIG_GLOBAL
  GIT_CONFIG_SYSTEM
  GIT_CONFIG_COUNT
  GIT_CEILING_DIRECTORIES
  GIT_CONFIG_PARAMETERS
  GIT_NAMESPACE
  GIT_REPLACE_REF_BASE
  GIT_SHALLOW_FILE
)
for git_setting in "${forbidden_git_environment[@]}"; do
  if (( ${+parameters[$git_setting]} )); then
    print -u2 -- "Refusing release with repository-redirecting environment: $git_setting"
    exit 1
  fi
done
for git_setting in ${(k)parameters}; do
  case "$git_setting" in
    GIT_CONFIG_KEY_*|GIT_CONFIG_VALUE_*)
      print -u2 -- "Refusing release with repository-redirecting environment: $git_setting"
      exit 1
      ;;
  esac
done
readonly -a forbidden_network_environment=(
  ALL_PROXY
  all_proxy
  HTTP_PROXY
  http_proxy
  HTTPS_PROXY
  https_proxy
  NO_PROXY
  no_proxy
  CURL_CA_BUNDLE
  curl_ca_bundle
  REQUESTS_CA_BUNDLE
  requests_ca_bundle
  SSL_CERT_DIR
  ssl_cert_dir
  SSL_CERT_FILE
  ssl_cert_file
)
for network_setting in "${forbidden_network_environment[@]}"; do
  if (( ${+parameters[$network_setting]} )); then
    print -u2 -- "Refusing release with proxy or custom-CA environment: $network_setting"
    exit 1
  fi
done
export GIT_NO_REPLACE_OBJECTS=1

readonly safe_path="/usr/bin:/bin:/usr/sbin:/sbin"
export PATH="$safe_path"
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP PYTHONINSPECT

readonly python_bin="/usr/bin/python3"
if [[ ! -x "$python_bin" || -L "$python_bin" ]] \
    || ! "$python_bin" -I -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
  print -u2 -- "The root-owned macOS Python 3.9 or newer is required for the release gate."
  exit 1
fi

usage() {
  print -u2 -- "Usage: scripts/release_testflight.sh --archive-only|--upload"
  exit 2
}

mode=${1:-}
if [[ "$mode" != "--archive-only" && "$mode" != "--upload" ]]; then
  usage
fi

repo_root=$(/bin/realpath "$(/usr/bin/dirname "$0")/..")
cd "$repo_root"

trusted_git=(
  /usr/bin/env -i
  "PATH=/usr/bin:/bin"
  "HOME=/var/empty"
  "XDG_CONFIG_HOME=/var/empty"
  "GIT_CONFIG_NOSYSTEM=1"
  "GIT_CONFIG_GLOBAL=/dev/null"
  "LC_ALL=C"
  "GIT_NO_REPLACE_OBJECTS=1"
  "GIT_ATTR_NOSYSTEM=1"
  "GIT_OPTIONAL_LOCKS=0"
  /usr/bin/git
)
repo_top=$("${trusted_git[@]}" -C "$repo_root" rev-parse --show-toplevel)
repo_top=$(/bin/realpath "$repo_top")
if [[ "$repo_top" != "$repo_root" ]]; then
  print -u2 -- "Refusing release outside the canonical XJie_IOS repository root."
  exit 1
fi
common_dir=$("${trusted_git[@]}" -C "$repo_root" rev-parse --path-format=absolute --git-common-dir)
if [[ ! -d "$common_dir" || -L "$common_dir" ]]; then
  print -u2 -- "Refusing release with an invalid Git common directory."
  exit 1
fi
common_dir=$(/bin/realpath "$common_dir")
unsafe_git_config=""
if unsafe_git_config=$("${trusted_git[@]}" -C "$repo_root" config --local --get-regexp \
    '^(core\.(attributesfile|fsmonitor|ignorestat|trustctime|checkstat|worktree)|extensions\.worktreeconfig|filter\.|diff\.|include\.|url\.)'); then
  :
else
  git_config_status=$?
  if (( git_config_status != 1 )); then
    print -u2 -- "Unable to audit local Git configuration."
    exit 1
  fi
fi
if [[ -n "$unsafe_git_config" ]]; then
  print -u2 -- "Refusing release with unsafe local Git configuration."
  exit 1
fi
if [[ -e "$common_dir/info/attributes" || -L "$common_dir/info/attributes" ]]; then
  print -u2 -- "Refusing release with repository-local attributes override."
  exit 1
fi
replace_refs=$("${trusted_git[@]}" -C "$repo_root" for-each-ref --format='%(refname)' refs/replace)
if [[ -n "$replace_refs" ]]; then
  print -u2 -- "Refusing release with local Git replace refs: ${replace_refs//$'\n'/, }"
  exit 1
fi
release_lock_dir="$common_dir/xjie-testflight-release.lock"
if ! /bin/mkdir -- "$release_lock_dir"; then
  print -u2 -- "Another TestFlight release is active (lock: $release_lock_dir)."
  exit 1
fi
release_lock_acquired=true
entitlements=""
candidate_parent=""
candidate_repo=""
distribution_parent=""
ipa_snapshot_parent=""
export_path=""
typeset -a altool_auth_args

cleanup_release() {
  local exit_status=$?
  local cleanup_failed=0
  if [[ -n "$entitlements" && -e "$entitlements" ]]; then
    /bin/unlink "$entitlements" || cleanup_failed=1
  fi
  if [[ -n "$candidate_parent" && -d "$candidate_parent" ]]; then
    /bin/chmod -R u+w "$candidate_parent" >/dev/null 2>&1 || cleanup_failed=1
    /bin/rm -rf -- "$candidate_parent" || cleanup_failed=1
  fi
  if [[ -n "$distribution_parent" && -d "$distribution_parent" ]]; then
    /bin/chmod -R u+w "$distribution_parent" >/dev/null 2>&1 || cleanup_failed=1
    /bin/rm -rf -- "$distribution_parent" || cleanup_failed=1
  fi
  if [[ -n "$ipa_snapshot_parent" && -d "$ipa_snapshot_parent" ]]; then
    /bin/chmod -R u+w "$ipa_snapshot_parent" >/dev/null 2>&1 || cleanup_failed=1
    /bin/rm -rf -- "$ipa_snapshot_parent" || cleanup_failed=1
  fi
  if [[ -n "$export_path" && -d "$export_path" ]]; then
    /bin/chmod -R u+w "$export_path" >/dev/null 2>&1 || cleanup_failed=1
    /bin/rm -rf -- "$export_path" || cleanup_failed=1
  fi
  if [[ "$release_lock_acquired" == "true" && -d "$release_lock_dir" ]]; then
    /bin/rmdir -- "$release_lock_dir" || cleanup_failed=1
  fi
  if (( exit_status == 0 && cleanup_failed != 0 )); then
    print -u2 -- "Release cleanup failed; inspect the lock and temporary entitlement file."
    return 1
  fi
  return "$exit_status"
}
trap 'cleanup_release' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

for setting in \
  XCODE_XCCONFIG_FILE \
  SWIFT_ACTIVE_COMPILATION_CONDITIONS \
  OTHER_SWIFT_FLAGS \
  GCC_PREPROCESSOR_DEFINITIONS \
  ENABLE_TESTABILITY \
  INFOPLIST_FILE \
  CODE_SIGN_ENTITLEMENTS \
  PRODUCT_BUNDLE_IDENTIFIER \
  API_BASE_URL
do
  if (( ${+parameters[$setting]} )); then
    print -u2 -- "Refusing release with injected Xcode build setting: $setting"
    exit 1
  fi
done

validate_auth_metadata() {
  local auth_kind=$1
  local first=$2
  local second=$3
  "$python_bin" -I -c '
import re
import sys
import uuid

kind, first, second = sys.argv[1:]
for value in (first, second):
    if not value or len(value) > 254 or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SystemExit("invalid authentication metadata")
if kind == "api":
    if re.fullmatch(r"[A-Za-z0-9]{8,64}", first) is None:
        raise SystemExit("invalid App Store Connect API key ID")
    try:
        uuid.UUID(second)
    except ValueError as exc:
        raise SystemExit("invalid App Store Connect API issuer ID") from exc
elif kind == "keychain":
    if "@" not in first or first.startswith("@") or first.endswith("@"):
        raise SystemExit("invalid App Store Connect username")
    if len(second.strip()) < 2 or second != second.strip():
        raise SystemExit("invalid App Store Connect keychain item")
else:
    raise SystemExit("unknown authentication metadata type")
' "$auth_kind" "$first" "$second"
}

configure_upload_authentication() {
  local api_fields=0
  local keychain_fields=0
  (( ${+parameters[XJIE_ASC_API_KEY_ID]} )) && (( api_fields += 1 ))
  (( ${+parameters[XJIE_ASC_API_ISSUER_ID]} )) && (( api_fields += 1 ))
  (( ${+parameters[XJIE_ASC_USERNAME]} )) && (( keychain_fields += 1 ))
  (( ${+parameters[XJIE_ASC_PASSWORD_KEYCHAIN_ITEM]} )) && (( keychain_fields += 1 ))

  if (( api_fields > 0 && keychain_fields > 0 )); then
    print -u2 -- "Refusing mixed App Store Connect authentication metadata."
    exit 1
  fi
  if (( api_fields == 2 )); then
    validate_auth_metadata api "$XJIE_ASC_API_KEY_ID" "$XJIE_ASC_API_ISSUER_ID"
    altool_auth_args=(
      --api-key "$XJIE_ASC_API_KEY_ID"
      --api-issuer "$XJIE_ASC_API_ISSUER_ID"
    )
    return
  fi
  if (( keychain_fields == 2 )); then
    validate_auth_metadata keychain "$XJIE_ASC_USERNAME" "$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"
    altool_auth_args=(
      --username "$XJIE_ASC_USERNAME"
      --password "@keychain:$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"
    )
    return
  fi
  print -u2 -- "Upload requires one complete App Store Connect authentication method."
  exit 1
}

if [[ "$mode" == "--upload" ]]; then
  configure_upload_authentication
fi

readonly pinned_developer_dir="/Applications/Xcode.app/Contents/Developer"
developer_dir=$(/bin/realpath "${DEVELOPER_DIR:-$pinned_developer_dir}")
if [[ "$developer_dir" != "$pinned_developer_dir" ]]; then
  print -u2 -- "Refusing unpinned DEVELOPER_DIR: $developer_dir"
  exit 1
fi
xcodebuild_bin="$developer_dir/usr/bin/xcodebuild"
if [[ ! -x "$xcodebuild_bin" || -L "$xcodebuild_bin" ]]; then
  print -u2 -- "Trusted xcodebuild is missing: $xcodebuild_bin"
  exit 1
fi
readonly pinned_xcode_identity=$'Xcode 26.3\nBuild version 17C529'
if [[ "$("$xcodebuild_bin" -version)" != "$pinned_xcode_identity" ]]; then
  print -u2 -- "Refusing an Xcode toolchain other than Xcode 26.3 (17C529)."
  exit 1
fi

tmp_parent=$(/bin/realpath /tmp)
if [[ ! -d "$tmp_parent" || -L "$tmp_parent" ]]; then
  print -u2 -- "Canonical temporary directory is unavailable."
  exit 1
fi

xcode_env=(
  /usr/bin/env -i
  "HOME=$HOME"
  "PATH=$safe_path"
  "TMPDIR=$tmp_parent"
  "LANG=${LANG:-en_US.UTF-8}"
  "DEVELOPER_DIR=$developer_dir"
)

"$python_bin" -I tools/run_regression_gate.py assert-release

release_head=$("${trusted_git[@]}" -C "$repo_root" rev-parse HEAD)
release_tree=$("${trusted_git[@]}" -C "$repo_root" rev-parse 'HEAD^{tree}')
candidate_parent=$(/usr/bin/mktemp -d "$tmp_parent/xjie-release-candidate.XXXXXX")
candidate_repo="$candidate_parent/repository"
"${trusted_git[@]}" -C "$repo_root" clone --no-local --no-checkout --no-tags \
  "$repo_root" "$candidate_repo"
"${trusted_git[@]}" -C "$candidate_repo" checkout --detach --quiet "$release_head"
"${trusted_git[@]}" -C "$candidate_repo" remote remove origin

verify_candidate_snapshot() {
  [[ "$("${trusted_git[@]}" -C "$candidate_repo" rev-parse HEAD)" == "$release_head" ]]
  [[ "$("${trusted_git[@]}" -C "$candidate_repo" rev-parse 'HEAD^{tree}')" == "$release_tree" ]]
  [[ -z "$("${trusted_git[@]}" -C "$candidate_repo" status --porcelain=v1 --untracked-files=all)" ]]
  [[ -z "$("${trusted_git[@]}" -C "$candidate_repo" for-each-ref --format='%(refname)' refs/replace)" ]]
}
verify_candidate_snapshot
/bin/chmod -R a-w "$candidate_repo"
verify_candidate_snapshot

project="$candidate_repo/Xjie/Xjie.xcodeproj"
scheme="Xjie"
export_options="$candidate_repo/scripts/ExportOptions-TestFlight.plist"
[[ -f "$export_options" && ! -L "$export_options" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :destination' "$export_options")" == "export" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :method' "$export_options")" == "app-store-connect" ]]
[[ "$(/usr/libexec/PlistBuddy -c 'Print :teamID' "$export_options")" == "52BRF299Y7" ]]
[[ "$(/usr/bin/plutil -extract manageAppVersionAndBuildNumber raw -o - "$export_options")" == "false" ]]
settings=$("${xcode_env[@]}" "$xcodebuild_bin" \
  -project "$project" \
  -scheme "$scheme" \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -showBuildSettings \
  -json)
printf '%s' "$settings" \
  | "$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" \
      --release-build-settings-stdin

setting_value() {
  local key=$1
  printf '%s' "$settings" | "$python_bin" -I -c '
import json
import sys

payload = json.load(sys.stdin)
matches = [
    item for item in payload
    if item.get("target") == "Xjie"
    and item.get("buildSettings", {}).get("PRODUCT_BUNDLE_IDENTIFIER") == "com.xjie.app"
]
if len(matches) != 1:
    raise SystemExit(f"expected one Xjie application target, found {len(matches)}")
value = matches[0]["buildSettings"].get(sys.argv[1], "")
print("" if value is None else value)
' "$key"
}

version=$(setting_value MARKETING_VERSION)
build=$(setting_value CURRENT_PROJECT_VERSION)
testability=$(setting_value ENABLE_TESTABILITY)
swift_conditions=$(setting_value SWIFT_ACTIVE_COMPILATION_CONDITIONS)

if [[ -z "$version" || -z "$build" ]]; then
  print -u2 -- "Unable to resolve MARKETING_VERSION/CURRENT_PROJECT_VERSION."
  exit 1
fi
if ! "$python_bin" -I -c 'import re, sys; raise SystemExit(0 if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", sys.argv[1]) else 1)' "$version"; then
  print -u2 -- "Refusing invalid MARKETING_VERSION; expected Apple numeric segments such as 1, 1.0, or 1.0.2."
  exit 1
fi
if ! "$python_bin" -I -c 'import re, sys; raise SystemExit(0 if re.fullmatch(r"[1-9][0-9]*", sys.argv[1]) else 1)' "$build"; then
  print -u2 -- "Refusing invalid CURRENT_PROJECT_VERSION; expected a positive integer."
  exit 1
fi
[[ "$testability" == "NO" ]]
[[ "$swift_conditions" != *DEBUG* ]]

archive_root="$repo_root/Xjie"
if [[ ! -d "$archive_root" || -L "$archive_root" \
    || "$(/bin/realpath "$archive_root")" != "$archive_root" ]]; then
  print -u2 -- "Canonical Xjie project directory is unavailable."
  exit 1
fi
archive_parent_path="$archive_root/build"
if [[ -e "$archive_parent_path" || -L "$archive_parent_path" ]]; then
  if [[ ! -d "$archive_parent_path" || -L "$archive_parent_path" ]]; then
    print -u2 -- "Refusing a non-directory or symlinked archive parent."
    exit 1
  fi
else
  /bin/mkdir -- "$archive_parent_path"
fi
archive_parent=$(/bin/realpath "$archive_parent_path")
if [[ "$archive_parent" != "$archive_parent_path" ]]; then
  print -u2 -- "Refusing a symlinked or redirected archive parent."
  exit 1
fi

require_canonical_direct_child() {
  local canonical_parent=$1
  local candidate=$2
  local label=$3
  local candidate_parent
  local candidate_name
  candidate_parent=$(/bin/realpath "$(/usr/bin/dirname "$candidate")")
  candidate_name=$(/usr/bin/basename "$candidate")
  if [[ "$candidate_parent" != "$canonical_parent" \
      || -z "$candidate_name" \
      || "$candidate_name" == "." \
      || "$candidate_name" == ".." \
      || "$candidate" != "$canonical_parent/$candidate_name" ]]; then
    print -u2 -- "Refusing $label outside its canonical parent."
    exit 1
  fi
}

sha256_file() {
  "$python_bin" -I -c '
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
' "$1"
}

archive="$archive_parent/Xjie-TestFlight-${version}-${build}.xcarchive"
require_canonical_direct_child "$archive_parent" "$archive" "archive path"
export_path=$(/usr/bin/mktemp -d "$tmp_parent/xjie-testflight-export.XXXXXX")
require_canonical_direct_child "$tmp_parent" "$export_path" "export path"
if [[ ! -d "$export_path" || -L "$export_path" \
    || "$(/bin/realpath "$export_path")" != "$export_path" \
    || "$(/usr/bin/stat -f '%u' "$export_path")" != "$(/usr/bin/id -u)" ]]; then
  print -u2 -- "Unable to create a private canonical TestFlight export directory."
  exit 1
fi
/bin/chmod 700 "$export_path"
/bin/rm -rf -- "$archive"

verify_candidate_snapshot
"${xcode_env[@]}" "$xcodebuild_bin" \
  -project "$project" \
  -scheme "$scheme" \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$archive" \
  clean archive \
  -allowProvisioningUpdates
verify_candidate_snapshot

application_path=$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:ApplicationPath' "$archive/Info.plist")
archive_bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :ApplicationProperties:CFBundleIdentifier' "$archive/Info.plist")
if [[ "$application_path" != "Applications/Xjie.app" || "$archive_bundle_id" != "com.xjie.app" ]]; then
  print -u2 -- "Archive application identity is unexpected."
  exit 1
fi
app="$archive/Products/$application_path"
app_count=$(/usr/bin/find "$archive/Products/Applications" -mindepth 1 -maxdepth 1 -type d -name '*.app' | /usr/bin/wc -l | /usr/bin/tr -d ' ')
[[ "$app_count" == "1" && -d "$app" && ! -L "$app" ]]

info="$app/Info.plist"
bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$info")
archive_version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$info")
archive_build=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$info")
api_base=$(/usr/libexec/PlistBuddy -c 'Print :API_BASE_URL' "$info")
health_read=$(/usr/libexec/PlistBuddy -c 'Print :NSHealthShareUsageDescription' "$info")
health_write=$(/usr/libexec/PlistBuddy -c 'Print :NSHealthUpdateUsageDescription' "$info")

[[ "$bundle_id" == "com.xjie.app" ]]
[[ "$archive_version" == "$version" ]]
[[ "$archive_build" == "$build" ]]
[[ "$api_base" == "https://www.jianjieaitech.com" ]]
[[ -n "$health_read" && -n "$health_write" ]]

/usr/bin/codesign --verify --deep --strict "$app"
entitlements=$(/usr/bin/mktemp "$tmp_parent/xjie-release-entitlements.XXXXXX")
[[ -f "$entitlements" && ! -L "$entitlements" ]]
/usr/bin/codesign -d --entitlements :- "$app" > "$entitlements" 2>/dev/null
[[ "$(/usr/bin/plutil -extract com.apple.developer.healthkit raw -o - "$entitlements")" == "true" ]]
[[ "$(/usr/bin/plutil -extract com.apple.developer.healthkit.background-delivery raw -o - "$entitlements")" == "true" ]]

forbidden_count=$(/usr/bin/find "$app" -type f \( \
  -name '.env' -o -name '*.pem' -o -name '*.key' -o -name '*.sqlite' -o -name '*.db' \
\) | wc -l | tr -d ' ')
if [[ "$forbidden_count" != "0" ]]; then
  print -u2 -- "Release bundle contains forbidden sensitive/runtime files."
  exit 1
fi
"$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" "$app"
archive_cdhash=$(/usr/bin/codesign -d --verbose=4 "$app" 2>&1 \
  | /usr/bin/sed -n 's/^CDHash=//p' \
  | /usr/bin/head -n 1)
if ! "$python_bin" -I -c 'import re, sys; raise SystemExit(0 if re.fullmatch(r"[0-9a-fA-F]{40,64}", sys.argv[1]) else 1)' "$archive_cdhash"; then
  print -u2 -- "Unable to bind the signed archive to its code-directory hash."
  exit 1
fi

echo "Archive verified: $archive ($bundle_id $archive_version($archive_build))"

# Close the archive-time race: source, branch tip and exact-SHA remote CI must
# still match after Xcode finishes the signed archive.
"$python_bin" -I tools/run_regression_gate.py assert-release

verify_candidate_snapshot
/usr/bin/codesign --verify --deep --strict "$app"
current_cdhash=$(/usr/bin/codesign -d --verbose=4 "$app" 2>&1 \
  | /usr/bin/sed -n 's/^CDHash=//p' \
  | /usr/bin/head -n 1)
if [[ "$current_cdhash" != "$archive_cdhash" ]]; then
  print -u2 -- "Archive changed after verification; refusing export/upload."
  exit 1
fi
"$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" "$app"
"${xcode_env[@]}" "$xcodebuild_bin" \
  -exportArchive \
  -archivePath "$archive" \
  -exportOptionsPlist "$export_options" \
  -exportPath "$export_path" \
  -allowProvisioningUpdates

if [[ ! -d "$export_path" || -L "$export_path" \
    || "$(/bin/realpath "$export_path")" != "$export_path" \
    || "$(/usr/bin/stat -f '%u' "$export_path")" != "$(/usr/bin/id -u)" \
    || "$(/usr/bin/stat -f '%Lp' "$export_path")" != "700" ]]; then
  print -u2 -- "TestFlight export path is not a canonical real directory."
  exit 1
fi
ipa_candidates=("$export_path"/*.ipa(N))
if (( ${#ipa_candidates[@]} != 1 )); then
  print -u2 -- "Expected exactly one locally exported IPA; found ${#ipa_candidates[@]}."
  exit 1
fi
exported_ipa=${ipa_candidates[1]}
if [[ ! -f "$exported_ipa" || -L "$exported_ipa" ]]; then
  print -u2 -- "The locally exported IPA must be a regular non-symlink file."
  exit 1
fi

# Move release work away from Xcode's predictable export path. Hash the source
# around the copy and establish the immutable comparison baseline before any
# scan or extraction; later release checks use only this random snapshot.
ipa_snapshot_parent=$(/usr/bin/mktemp -d "$tmp_parent/xjie-ipa-snapshot.XXXXXX")
if [[ ! -d "$ipa_snapshot_parent" || -L "$ipa_snapshot_parent" \
    || "$(/bin/realpath "$ipa_snapshot_parent")" != "$ipa_snapshot_parent" ]]; then
  print -u2 -- "Unable to create a canonical IPA snapshot directory."
  exit 1
fi
/bin/chmod 700 "$ipa_snapshot_parent"
ipa="$ipa_snapshot_parent/Xjie-${version}-${build}.ipa"
require_canonical_direct_child "$ipa_snapshot_parent" "$ipa" "IPA snapshot path"
exported_ipa_sha256_before=$(sha256_file "$exported_ipa")
/bin/cp -p -- "$exported_ipa" "$ipa"
if [[ ! -f "$ipa" || -L "$ipa" \
    || "$(/usr/bin/stat -f '%l' "$ipa")" != "1" ]]; then
  print -u2 -- "The IPA snapshot must be a regular single-link file."
  exit 1
fi
/bin/chmod 400 "$ipa"
exported_ipa_sha256_after=$(sha256_file "$exported_ipa")
ipa_sha256=$(sha256_file "$ipa")
if [[ "$exported_ipa_sha256_before" != "$exported_ipa_sha256_after" \
    || "$exported_ipa_sha256_after" != "$ipa_sha256" ]]; then
  print -u2 -- "The exported IPA changed while creating its release snapshot."
  exit 1
fi

# Validate every regular member before extraction: path identity, file type,
# archive expansion bounds, sensitive filenames and private-key content.
"$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"
if [[ "$(sha256_file "$ipa")" != "$ipa_sha256" ]]; then
  print -u2 -- "The IPA snapshot changed during container validation."
  exit 1
fi

distribution_parent=$(/usr/bin/mktemp -d "$tmp_parent/xjie-distribution-inspection.XXXXXX")
if [[ ! -d "$distribution_parent" || -L "$distribution_parent" \
    || "$(/bin/realpath "$distribution_parent")" != "$distribution_parent" ]]; then
  print -u2 -- "Unable to create a canonical IPA inspection directory."
  exit 1
fi
/usr/bin/ditto -x -k "$ipa" "$distribution_parent"
if [[ "$(sha256_file "$ipa")" != "$ipa_sha256" ]]; then
  print -u2 -- "The IPA snapshot changed during extraction."
  exit 1
fi
distribution_payload="$distribution_parent/Payload"
if [[ ! -d "$distribution_payload" || -L "$distribution_payload" ]]; then
  print -u2 -- "Exported IPA is missing a real Payload directory."
  exit 1
fi
distribution_apps=("$distribution_payload"/*.app(N))
if (( ${#distribution_apps[@]} != 1 )); then
  print -u2 -- "Expected exactly one application in the exported IPA Payload."
  exit 1
fi
distribution_app=${distribution_apps[1]}
if [[ ! -d "$distribution_app" || -L "$distribution_app" ]]; then
  print -u2 -- "Exported IPA application must be a real non-symlink directory."
  exit 1
fi

"$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" "$distribution_app"
distribution_info="$distribution_app/Info.plist"
distribution_bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$distribution_info")
distribution_version=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$distribution_info")
distribution_build=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$distribution_info")
distribution_api_base=$(/usr/libexec/PlistBuddy -c 'Print :API_BASE_URL' "$distribution_info")
distribution_executable_name=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$distribution_info")
distribution_platform=$(/usr/libexec/PlistBuddy -c 'Print :DTPlatformName' "$distribution_info")
distribution_sdk=$(/usr/libexec/PlistBuddy -c 'Print :DTSDKName' "$distribution_info")
distribution_supported_platform=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleSupportedPlatforms:0' "$distribution_info")
[[ "$distribution_bundle_id" == "com.xjie.app" ]]
[[ "$distribution_version" == "$version" ]]
[[ "$distribution_build" == "$build" ]]
[[ "$distribution_api_base" == "https://www.jianjieaitech.com" ]]
[[ "$distribution_platform" == "iphoneos" ]]
[[ "$distribution_sdk" == iphoneos* ]]
[[ "$distribution_supported_platform" == "iPhoneOS" ]]
if /usr/libexec/PlistBuddy -c 'Print :CFBundleSupportedPlatforms:1' "$distribution_info" >/dev/null 2>&1; then
  print -u2 -- "Exported IPA declares more than the iPhoneOS device platform."
  exit 1
fi
distribution_executable="$distribution_app/$distribution_executable_name"
[[ -f "$distribution_executable" && ! -L "$distribution_executable" && -x "$distribution_executable" ]]
[[ "$(/usr/bin/lipo -archs "$distribution_executable")" == "arm64" ]]
otool_payload=$(/usr/bin/otool -l "$distribution_executable")
printf '%s' "$otool_payload" | "$python_bin" -I -c '
import sys

lines = sys.stdin.read().splitlines()
platforms = []
for index, line in enumerate(lines):
    if line.strip() != "cmd LC_BUILD_VERSION":
        continue
    for candidate in lines[index + 1:index + 12]:
        stripped = candidate.strip()
        if stripped.startswith("Load command "):
            break
        if stripped.startswith("platform "):
            platforms.append(int(stripped.split()[1]))
            break
if not platforms or set(platforms) != {2}:
    raise SystemExit(f"expected only iOS device LC_BUILD_VERSION platform 2, found {platforms}")
'

/usr/bin/codesign --verify --deep --strict "$distribution_app"
distribution_entitlements="$distribution_parent/distribution-entitlements.plist"
/usr/bin/codesign -d --entitlements :- "$distribution_app" > "$distribution_entitlements" 2>/dev/null
[[ "$(/usr/bin/plutil -extract com.apple.developer.healthkit raw -o - "$distribution_entitlements")" == "true" ]]
[[ "$(/usr/bin/plutil -extract com.apple.developer.healthkit.background-delivery raw -o - "$distribution_entitlements")" == "true" ]]
[[ "$(/usr/bin/plutil -extract application-identifier raw -o - "$distribution_entitlements")" == "52BRF299Y7.com.xjie.app" ]]
[[ "$(/usr/bin/plutil -extract com.apple.developer.team-identifier raw -o - "$distribution_entitlements")" == "52BRF299Y7" ]]
[[ "$(/usr/bin/plutil -extract get-task-allow raw -o - "$distribution_entitlements")" == "false" ]]
[[ "$(/usr/bin/plutil -extract beta-reports-active raw -o - "$distribution_entitlements")" == "true" ]]

embedded_profile="$distribution_app/embedded.mobileprovision"
if [[ ! -f "$embedded_profile" || -L "$embedded_profile" ]]; then
  print -u2 -- "Exported IPA is missing a regular embedded provisioning profile."
  exit 1
fi
profile_plist="$distribution_parent/embedded-profile.plist"
profile_cms_status=$(/usr/bin/security cms -D -h 0 -n -i "$embedded_profile" 2>&1)
printf '%s' "$profile_cms_status" \
  | "$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" --cms-status-stdin
/usr/bin/security cms -D -i "$embedded_profile" > "$profile_plist"
signing_certificates_dir="$distribution_parent/signing-certificates"
/bin/mkdir -- "$signing_certificates_dir"
(
  cd "$signing_certificates_dir"
  /usr/bin/codesign -d --extract-certificates "$distribution_app" >/dev/null 2>&1
)
leaf_signing_certificate="$signing_certificates_dir/codesign0"
if [[ ! -f "$leaf_signing_certificate" || -L "$leaf_signing_certificate" \
    || ! -s "$leaf_signing_certificate" ]]; then
  print -u2 -- "Unable to extract the distribution leaf signing certificate."
  exit 1
fi
"$python_bin" -I -c '
import datetime as dt
import plistlib
import re
import sys

with open(sys.argv[1], "rb") as handle:
    profile = plistlib.load(handle)
with open(sys.argv[2], "rb") as handle:
    signed = plistlib.load(handle)
with open(sys.argv[3], "rb") as handle:
    leaf_certificate = handle.read()

team = "52BRF299Y7"
application_identifier = f"{team}.com.xjie.app"
entitlements = profile.get("Entitlements")
if not isinstance(entitlements, dict):
    raise SystemExit("embedded provisioning profile has no entitlements")
if profile.get("TeamIdentifier") != [team]:
    raise SystemExit("embedded provisioning profile team is unexpected")
if profile.get("ApplicationIdentifierPrefix") != [team]:
    raise SystemExit("embedded provisioning application prefix is unexpected")
if "iOS" not in profile.get("Platform", []):
    raise SystemExit("embedded provisioning profile is not for iOS")
if profile.get("ProvisionedDevices") is not None or profile.get("ProvisionsAllDevices") is True:
    raise SystemExit("embedded provisioning profile is not App Store distribution")
if not isinstance(profile.get("Name"), str) or not profile["Name"].strip():
    raise SystemExit("embedded provisioning profile has no identity name")
if re.fullmatch(r"[0-9a-fA-F-]{36}", str(profile.get("UUID", ""))) is None:
    raise SystemExit("embedded provisioning profile UUID is invalid")
developer_certificates = profile.get("DeveloperCertificates")
if not isinstance(developer_certificates, list) or not developer_certificates \
        or any(not isinstance(item, bytes) or not item for item in developer_certificates):
    raise SystemExit("embedded provisioning profile has invalid DeveloperCertificates")
if leaf_certificate not in developer_certificates:
    raise SystemExit("actual distribution signing certificate is not authorized by the profile")
expiration = profile.get("ExpirationDate")
if not isinstance(expiration, dt.datetime) or expiration <= dt.datetime.utcnow():
    raise SystemExit("embedded provisioning profile is expired")

required = {
    "application-identifier": application_identifier,
    "com.apple.developer.team-identifier": team,
    "com.apple.developer.healthkit": True,
    "com.apple.developer.healthkit.background-delivery": True,
    "get-task-allow": False,
    "beta-reports-active": True,
}
for key, expected in required.items():
    if entitlements.get(key) != expected or signed.get(key) != expected:
        raise SystemExit(f"distribution identity mismatch for {key}")
' "$profile_plist" "$distribution_entitlements" "$leaf_signing_certificate"

code_directory_hash() {
  /usr/bin/codesign -d --verbose=4 "$1" 2>&1 \
    | /usr/bin/sed -n 's/^CDHash=//p' \
    | /usr/bin/head -n 1
}

distribution_cdhash=$(code_directory_hash "$distribution_app")
if ! "$python_bin" -I -c 'import re, sys; raise SystemExit(0 if re.fullmatch(r"[0-9a-fA-F]{64}", sys.argv[1]) else 1)' "$ipa_sha256" \
    || ! "$python_bin" -I -c 'import re, sys; raise SystemExit(0 if re.fullmatch(r"[0-9a-fA-F]{40,64}", sys.argv[1]) else 1)' "$distribution_cdhash"; then
  print -u2 -- "Unable to bind the locally exported distribution IPA."
  exit 1
fi

recheck_distribution_identity() {
  verify_candidate_snapshot
  /usr/bin/codesign --verify --deep --strict "$distribution_app"
  "$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"
  "$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" "$distribution_app"
  current_ipa_sha256=$(sha256_file "$ipa")
  current_distribution_cdhash=$(code_directory_hash "$distribution_app")
  if [[ "$current_ipa_sha256" != "$ipa_sha256" \
      || "$current_distribution_cdhash" != "$distribution_cdhash" ]]; then
    print -u2 -- "The verified distribution IPA changed before release."
    exit 1
  fi
}

echo "Distribution IPA verified: $ipa ($distribution_bundle_id $distribution_version($distribution_build) sha256=$ipa_sha256 cdhash=$distribution_cdhash)"
recheck_distribution_identity

# Revalidate exact HEAD, remote CI, protections and sign-offs after the actual
# distribution bytes (not only the development-signed archive) are known.
"$python_bin" -I tools/run_regression_gate.py assert-release

if [[ "$mode" == "--archive-only" ]]; then
  echo "Archive and local distribution export completed without upload."
  exit 0
fi

recheck_distribution_identity
altool_path=$("${xcode_env[@]}" /usr/bin/xcrun --find altool)
if [[ "$altool_path" != "$developer_dir/usr/bin/altool" || ! -x "$altool_path" ]]; then
  print -u2 -- "Pinned Xcode altool is unavailable."
  exit 1
fi
altool_real=$(/bin/realpath "$altool_path")
case "$altool_real" in
  /Applications/Xcode.app/Contents/SharedFrameworks/ContentDelivery.framework/Versions/*/Resources/altoolShim) ;;
  *)
    print -u2 -- "Refusing an altool outside the pinned Xcode bundle."
    exit 1
    ;;
esac

# Run from HOME so altool finds only its documented private-key locations or
# Keychain item. Credential secrets are never passed through this script.
(
  cd "$HOME"
  "${xcode_env[@]}" /usr/bin/xcrun altool \
    --upload-app \
    -f "$ipa" \
    "${altool_auth_args[@]}" \
    --output-format json
)

echo "TestFlight upload completed for the verified IPA $version($build) sha256=$ipa_sha256 cdhash=$distribution_cdhash."

#!/bin/zsh
set -euo pipefail

usage() {
  echo "Usage: scripts/release_testflight.sh --archive-only|--upload" >&2
  exit 2
}

mode=${1:-}
if [[ "$mode" != "--archive-only" && "$mode" != "--upload" ]]; then
  usage
fi

repo_root=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo_root"

python3 tools/run_regression_gate.py assert-release

project="Xjie/Xjie.xcodeproj"
scheme="Xjie"
settings=$(xcodebuild -project "$project" -scheme "$scheme" -configuration Release -showBuildSettings)
version=$(printf '%s\n' "$settings" | awk -F ' = ' '/MARKETING_VERSION = / {print $2; exit}')
build=$(printf '%s\n' "$settings" | awk -F ' = ' '/CURRENT_PROJECT_VERSION = / {print $2; exit}')

if [[ -z "$version" || -z "$build" ]]; then
  echo "Unable to resolve MARKETING_VERSION/CURRENT_PROJECT_VERSION." >&2
  exit 1
fi

archive="Xjie/build/Xjie-TestFlight-${version}-${build}.xcarchive"
rm -rf "$archive"

xcodebuild \
  -project "$project" \
  -scheme "$scheme" \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$archive" \
  clean archive \
  -allowProvisioningUpdates

app=$(find "$archive/Products/Applications" -maxdepth 1 -type d -name '*.app' -print -quit)
if [[ -z "$app" ]]; then
  echo "Archive contains no application bundle." >&2
  exit 1
fi

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
[[ "$api_base" == https://* ]]
[[ -n "$health_read" && -n "$health_write" ]]

codesign --verify --deep --strict "$app"
entitlements="/tmp/xjie-release-entitlements-${build}.plist"
codesign -d --entitlements :- "$app" > "$entitlements" 2>/dev/null
[[ "$(plutil -extract com.apple.developer.healthkit raw -o - "$entitlements")" == "true" ]]
[[ "$(plutil -extract com.apple.developer.healthkit.background-delivery raw -o - "$entitlements")" == "true" ]]

forbidden_count=$(find "$app" -type f \( \
  -name '.env' -o -name '*.pem' -o -name '*.key' -o -name '*.sqlite' -o -name '*.db' \
\) | wc -l | tr -d ' ')
if [[ "$forbidden_count" != "0" ]]; then
  echo "Release bundle contains forbidden sensitive/runtime files." >&2
  exit 1
fi

echo "Archive verified: $archive ($bundle_id $archive_version($archive_build))"

if [[ "$mode" == "--archive-only" ]]; then
  exit 0
fi

export_options="Xjie/build/ExportOptions.plist"
if [[ ! -f "$export_options" ]]; then
  echo "Missing local export options: $export_options" >&2
  exit 1
fi

export_path="/tmp/xjie-testflight-${version}-${build}"
rm -rf "$export_path"
xcodebuild \
  -exportArchive \
  -archivePath "$archive" \
  -exportOptionsPlist "$export_options" \
  -exportPath "$export_path" \
  -allowProvisioningUpdates

echo "TestFlight export/upload completed for $version($build)."

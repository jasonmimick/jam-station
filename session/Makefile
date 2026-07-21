# Session — build & run without opening Xcode (docs/DESIGN-session.md)
APP = dist/Session.app
SIM = iPhone 17 Pro
PHONE = 922C681A-FA77-51B5-A08C-441FFA0CDADD   # Jason's iPhone ("analog")
IPAD  = 46662E56-D69F-57CE-8968-CD611C13F9E7   # Jason's iPad ("CompactDisc")
BUNDLE = run.jam-station.session.ios

MINI = jason@jasons-mac-mini
MINI_SSH = ssh -o IdentitiesOnly=yes -i ~/.ssh/id_euler

.PHONY: mac run clean ios-sim ios-phone ios-ipad mac-release

# Build the UNIVERSAL Mac app, zip it, and ship it to the station's
# /session/download (the zip lives in the brain's music volume on the mini —
# docker cp, same road the CD ripper uses). Verify by re-downloading.
mac-release:
	swift build -c release --arch arm64 --arch x86_64
	rm -rf dist/release && mkdir -p dist/release/Session.app/Contents/MacOS dist/release/Session.app/Contents/Resources
	cp .build/apple/Products/Release/SessionMac dist/release/Session.app/Contents/MacOS/Session
	cp Resources/Info.plist dist/release/Session.app/Contents/Info.plist
	cp Resources/Session.icns dist/release/Session.app/Contents/Resources/Session.icns
	codesign --force --sign - dist/release/Session.app
	cd dist/release && zip -qry ../Session-mac.zip Session.app
	scp -o IdentitiesOnly=yes -i ~/.ssh/id_euler dist/Session-mac.zip $(MINI):/tmp/Session-mac.zip
	$(MINI_SSH) $(MINI) 'PATH=$$PATH:/usr/local/bin:/opt/homebrew/bin; docker exec slab-jam-brain mkdir -p /music/_downloads && docker cp /tmp/Session-mac.zip slab-jam-brain:/music/_downloads/Session-mac.zip && rm /tmp/Session-mac.zip'
	@echo "verifying the live download…"
	@curl -s -o /dev/null -w "  /session/download -> %{http_code} · %{size_download} bytes\n" https://jam-station.runslab.run/session/download

# build + run the iOS app in the Simulator on this Mac (the fast loop)
ios-sim:
	cd ios && xcodegen generate -q && xcodebuild -project SessioniOS.xcodeproj \
	  -scheme Session -destination 'platform=iOS Simulator,name=$(SIM)' \
	  -derivedDataPath build build | tail -1
	xcrun simctl boot "$(SIM)" 2>/dev/null || true
	open -a Simulator
	xcrun simctl install "$(SIM)" ios/build/Build/Products/Debug-iphonesimulator/Session.app
	xcrun simctl launch "$(SIM)" $(BUNDLE)

# Device installs build against the GENERIC iOS destination — xcodebuild's
# per-device discovery flakes when the phone naps, and a `| tail` pipe once
# masked a failed build so devicectl kept re-installing a stale bundle.
# Fail loudly, then verify with the device's own app listing.
ios-build:
	cd ios && xcodegen generate -q && xcodebuild -project SessioniOS.xcodeproj \
	  -scheme Session -destination 'generic/platform=iOS' \
	  -allowProvisioningUpdates -derivedDataPath build -quiet build

ios-phone: ios-build
	xcrun devicectl device install app --device $(PHONE) \
	  ios/build/Build/Products/Debug-iphoneos/Session.app | grep -E "App installed" \
	  || (echo "INSTALL FAILED — is the phone unlocked / plugged in?" && false)
	@xcrun devicectl device info apps --device $(PHONE) | grep -i "^Session " || true

ios-ipad: ios-build
	xcrun devicectl device install app --device $(IPAD) \
	  ios/build/Build/Products/Debug-iphoneos/Session.app | grep -E "App installed" \
	  || (echo "INSTALL FAILED — is the iPad unlocked / plugged in?" && false)
	@xcrun devicectl device info apps --device $(IPAD) | grep -i "^Session " || true

mac:
	swift build -c release
	rm -rf dist
	mkdir -p $(APP)/Contents/MacOS
	cp .build/release/SessionMac $(APP)/Contents/MacOS/Session
	cp Resources/Info.plist $(APP)/Contents/Info.plist
	mkdir -p $(APP)/Contents/Resources
	cp Resources/Session.icns $(APP)/Contents/Resources/Session.icns
	codesign --force --sign - $(APP)

run: mac
	open $(APP)

clean:
	rm -rf .build dist

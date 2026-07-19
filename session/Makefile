# Session — build & run without opening Xcode (docs/DESIGN-session.md)
APP = dist/Session.app
SIM = iPhone 17 Pro
PHONE = 922C681A-FA77-51B5-A08C-441FFA0CDADD   # Jason's iPhone ("analog")
IPAD  = 46662E56-D69F-57CE-8968-CD611C13F9E7   # Jason's iPad ("CompactDisc")
BUNDLE = run.jam-station.session.ios

.PHONY: mac run clean ios-sim ios-phone ios-ipad

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

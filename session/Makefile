# Session — build & run without opening Xcode (docs/DESIGN-session.md)
APP = dist/Session.app
SIM = iPhone 17 Pro
PHONE = 922C681A-FA77-51B5-A08C-441FFA0CDADD   # Jason's iPhone ("analog")
BUNDLE = run.jam-station.session.ios

.PHONY: mac run clean ios-sim ios-phone

# build + run the iOS app in the Simulator on this Mac (the fast loop)
ios-sim:
	cd ios && xcodegen generate -q && xcodebuild -project SessioniOS.xcodeproj \
	  -scheme Session -destination 'platform=iOS Simulator,name=$(SIM)' \
	  -derivedDataPath build build | tail -1
	xcrun simctl boot "$(SIM)" 2>/dev/null || true
	open -a Simulator
	xcrun simctl install "$(SIM)" ios/build/Build/Products/Debug-iphonesimulator/Session.app
	xcrun simctl launch "$(SIM)" $(BUNDLE)

# build + install onto the real iPhone (must be plugged in / on wifi-pairing)
ios-phone:
	cd ios && xcodegen generate -q && xcodebuild -project SessioniOS.xcodeproj \
	  -scheme Session -destination 'platform=iOS,id=$(PHONE)' \
	  -destination-timeout 120 -allowProvisioningUpdates \
	  -derivedDataPath build build | tail -1
	xcrun devicectl device install app --device $(PHONE) \
	  ios/build/Build/Products/Debug-iphoneos/Session.app | tail -1

mac:
	swift build -c release
	rm -rf dist
	mkdir -p $(APP)/Contents/MacOS
	cp .build/release/SessionMac $(APP)/Contents/MacOS/Session
	cp Resources/Info.plist $(APP)/Contents/Info.plist
	codesign --force --sign - $(APP)

run: mac
	open $(APP)

clean:
	rm -rf .build dist

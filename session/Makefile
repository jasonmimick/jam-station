# Session — build & run without opening Xcode (docs/DESIGN-session.md)
APP = dist/Session.app

.PHONY: mac run clean

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

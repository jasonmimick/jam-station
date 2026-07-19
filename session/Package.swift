// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Session",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "SessionCore"),
        .executableTarget(name: "SessionMac", dependencies: ["SessionCore"]),
    ]
)

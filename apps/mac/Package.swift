// swift-tools-version:6.0
// AnyAssistant for the Mac: the menu bar app that installs and runs the server.
// Built into AnyAssistant.app and a .dmg by build.sh.
import PackageDescription

let package = Package(
    name: "AnyAssistant",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "AnyAssistant", path: "Sources/AnyAssistant")
    ],
    swiftLanguageModes: [.v6]
)

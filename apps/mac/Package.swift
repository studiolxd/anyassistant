// swift-tools-version:6.0
// AnyAssistant for the Mac: the menu bar app that installs and runs the server.
// Built into AnyAssistant.app and a .dmg by build.sh. Sparkle: its updates (AppUpdates.swift).
import PackageDescription

let package = Package(
    name: "AnyAssistant",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", from: "2.6.0")
    ],
    targets: [
        .executableTarget(
            name: "AnyAssistant",
            dependencies: [.product(name: "Sparkle", package: "Sparkle")],
            path: "Sources/AnyAssistant",
            linkerSettings: [.unsafeFlags(["-Xlinker", "-rpath", "-Xlinker", "@executable_path/../Frameworks"])]  // Sparkle.framework, in the app
        )
    ],
    swiftLanguageModes: [.v6]
)

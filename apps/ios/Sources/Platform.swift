// What differs between the iPhone/iPad and the Mac app (which builds these same files: the
// face, the microphone, the camera and the link, apps/mac/Sources/AnyAssistant/Client).

import SwiftUI

#if canImport(UIKit)
import UIKit
typealias PlatformImage = UIImage

extension Image {
    init(platform image: PlatformImage) { self.init(uiImage: image) }
}
#else
import AppKit
typealias PlatformImage = NSImage

extension Image {
    init(platform image: PlatformImage) { self.init(nsImage: image) }
}
#endif

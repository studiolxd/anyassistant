// The front camera, for «¿qué ves?» and «lee esto» (the plugin «eyes» on the Mac): while it's
// awake, a frame about once a second goes to the Mac; asleep, the camera is off. When the Mac
// asks for a photo, it takes one at full resolution. Only if the Mac has «eyes» on, and the app
// is in front (iOS doesn't allow the camera in the background).

import AVFoundation
import CoreImage
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif

/// Its state is touched only on its queue (the frames' delegate is called there; the photo's goes there).
final class Camera: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, AVCapturePhotoCaptureDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    private let video = AVCaptureVideoDataOutput()
    private let still = AVCapturePhotoOutput()
    private let queue = DispatchQueue(label: "camera")
    private let context = CIContext()
    private var configured = false
    private var lastFrame = Date.distantPast
    private var photos: [Int64: @Sendable (Data) -> Void] = [:]
    private var latest: Data?  // the last frame, for a photo that fails
    /// A frame, as JPEG (about once a second while on).
    var onFrame: (@Sendable (Data) -> Void)?

    var running: Bool { session.isRunning }

    func start() {
        queue.async { [self] in
            guard AVCaptureDevice.authorizationStatus(for: .video) != .denied, configure() else { return }
            orient()
            if !session.isRunning { session.startRunning() }
        }
    }

    func stop() {
        queue.async { [self] in if session.isRunning { session.stopRunning() } }
    }

    /// A photo at full resolution (nil: no camera).
    func photo(_ done: @escaping @Sendable (Data?) -> Void) {
        queue.async { [self] in
            guard configure() else { return done(nil) }
            orient()
            let wasRunning = session.isRunning
            if !wasRunning { session.startRunning() }
            let shoot: @Sendable () -> Void = { [self] in
                let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
                photos[settings.uniqueID] = { data in
                    done(data)
                    if !wasRunning { self.queue.async { self.session.stopRunning() } }
                }
                still.capturePhoto(with: settings, delegate: self)
            }
            // Just switched on, the camera isn't ready (its photo comes out empty): a moment first.
            if wasRunning { shoot() } else { queue.asyncAfter(deadline: .now() + 0.8, execute: shoot) }
        }
    }

    private func configure() -> Bool {
        if configured { return true }
        // The front camera (a Mac's has no side: whichever it has).
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front)
                ?? AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device) else { return false }
        session.beginConfiguration()
        #if os(iOS)
        session.automaticallyConfiguresApplicationAudioSession = false  // the audio is Audio's: don't touch it
        #endif
        session.sessionPreset = .photo
        if session.canAddInput(input) { session.addInput(input) }
        video.alwaysDiscardsLateVideoFrames = true
        video.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(video) { session.addOutput(video) }
        if session.canAddOutput(still) { session.addOutput(still) }
        // What goes to the Mac is never mirrored (the LLM reads text in it; it is told its left
        // is the user's right); only the preview on the screen is a mirror.
        for output in [video, still] as [AVCaptureOutput] {
            if let connection = output.connection(with: .video), connection.isVideoMirroringSupported {
                connection.automaticallyAdjustsVideoMirroring = false
                connection.isVideoMirrored = false
            }
        }
        session.commitConfiguration()
        configured = true
        return true
    }

    /// Upright, as the screen is held (a Mac's camera always is).
    private func orient() {
        #if os(iOS)
        let orientation: AVCaptureVideoOrientation
        switch Camera.interface {
        case .landscapeLeft: orientation = .landscapeLeft
        case .landscapeRight: orientation = .landscapeRight
        case .portraitUpsideDown: orientation = .portraitUpsideDown
        default: orientation = .portrait
        }
        for output in [video, still] as [AVCaptureOutput] {
            if let connection = output.connection(with: .video), connection.isVideoOrientationSupported {
                connection.videoOrientation = orientation
            }
        }
        #endif
    }

    #if os(iOS)
    /// The screen's orientation (kept from the main thread).
    static var interface = UIInterfaceOrientation.portrait
    #endif

    func captureOutput(_ output: AVCaptureOutput, didOutput buffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard Date().timeIntervalSince(lastFrame) >= 1, let pixels = CMSampleBufferGetImageBuffer(buffer) else { return }
        lastFrame = Date()
        var image = CIImage(cvPixelBuffer: pixels)
        let side = max(image.extent.width, image.extent.height)
        if side > 960 { image = image.transformed(by: CGAffineTransform(scaleX: 960 / side, y: 960 / side)) }
        guard let space = CGColorSpace(name: CGColorSpace.sRGB),
              let jpeg = context.jpegRepresentation(of: image, colorSpace: space,
                                                    options: [kCGImageDestinationLossyCompressionQuality as CIImageRepresentationOption: 0.7])
        else { return }
        latest = jpeg
        onFrame?(jpeg)
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        let taken = error == nil ? photo.fileDataRepresentation() : nil
        let id = photo.resolvedSettings.uniqueID
        queue.async { [self] in
            let done = photos.removeValue(forKey: id)
            done?(taken?.isEmpty == false ? taken! : (latest ?? Data()))  // failed: the last frame
        }
    }
}

/// The camera live, for «muestra la cámara» (a mirror: the front camera as you see yourself).
#if os(iOS)
final class PreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }

    func orient() {
        guard let connection = preview.connection, connection.isVideoOrientationSupported else { return }
        switch Camera.interface {
        case .landscapeLeft: connection.videoOrientation = .landscapeLeft
        case .landscapeRight: connection.videoOrientation = .landscapeRight
        case .portraitUpsideDown: connection.videoOrientation = .portraitUpsideDown
        default: connection.videoOrientation = .portrait
        }
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        orient()
    }
}
#else
final class PreviewView: NSView {
    let preview = AVCaptureVideoPreviewLayer()

    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer = preview
    }

    required init?(coder: NSCoder) { fatalError("not from a nib") }
}
#endif

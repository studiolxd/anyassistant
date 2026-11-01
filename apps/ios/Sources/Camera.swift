// The front camera, for «¿qué ves?» and «lee esto» (the plugin «eyes» on the Mac): while it's
// awake, a frame about once a second goes to the Mac; asleep, the camera is off. When the Mac
// asks for a photo, it takes one at full resolution. Only if the Mac has «eyes» on, and the app
// is in front (iOS doesn't allow the camera in the background).

import AVFoundation
import CoreImage
import UIKit

final class Camera: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, AVCapturePhotoCaptureDelegate {
    private let session = AVCaptureSession()
    private let video = AVCaptureVideoDataOutput()
    private let still = AVCapturePhotoOutput()
    private let queue = DispatchQueue(label: "camera")
    private let context = CIContext()
    private var configured = false
    private var lastFrame = Date.distantPast
    private var photos: [Int64: (Data) -> Void] = [:]
    /// A frame, as JPEG (about once a second while on).
    var onFrame: ((Data) -> Void)?

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
    func photo(_ done: @escaping (Data?) -> Void) {
        queue.async { [self] in
            guard configure() else { return done(nil) }
            orient()
            let wasRunning = session.isRunning
            if !wasRunning { session.startRunning() }
            let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
            photos[settings.uniqueID] = { data in
                done(data)
                if !wasRunning { self.queue.async { self.session.stopRunning() } }
            }
            still.capturePhoto(with: settings, delegate: self)
        }
    }

    private func configure() -> Bool {
        if configured { return true }
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front),
              let input = try? AVCaptureDeviceInput(device: device) else { return false }
        session.beginConfiguration()
        session.automaticallyConfiguresApplicationAudioSession = false  // the audio is Audio's: don't touch it
        session.sessionPreset = .photo
        if session.canAddInput(input) { session.addInput(input) }
        video.alwaysDiscardsLateVideoFrames = true
        video.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(video) { session.addOutput(video) }
        if session.canAddOutput(still) { session.addOutput(still) }
        session.commitConfiguration()
        configured = true
        return true
    }

    /// Upright, as the screen is held.
    private func orient() {
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
    }

    /// The screen's orientation (kept from the main thread).
    static var interface = UIInterfaceOrientation.portrait

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
        onFrame?(jpeg)
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        let done = photos.removeValue(forKey: photo.resolvedSettings.uniqueID)
        done?(photo.fileDataRepresentation() ?? Data())
    }
}

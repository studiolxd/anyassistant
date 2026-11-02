// «Escanear código»: the QR that «Conectar otro dispositivo» shows on the server, read with the
// camera; it says where the server is and its code, so nothing is typed (Mac.Invitation). With
// VisionKit's scanner where it exists (iOS 16 or later, on devices that support it: it highlights
// the code); else AVFoundation's, which every iPhone and iPad with iOS 15 has (the iPhone 7 too).

import AVFoundation
import SwiftUI
import VisionKit

struct ScanView: View {
    let found: (Mac.Invitation) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var denied = false

    var body: some View {
        NavigationView {
            Group {
                if denied {
                    Text(T("Allow the camera in Settings to scan the code."))
                        .multilineTextAlignment(.center).foregroundColor(.secondary).padding(32)
                } else if visionKit {
                    if #available(iOS 16.0, *) { VisionScanner(found: read) }
                } else {
                    CameraScanner(found: read, denied: $denied)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.black.ignoresSafeArea())
            .navigationTitle(T("Scan the code"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(T("Cancel")) { dismiss() } }
            }
        }
        .navigationViewStyle(.stack)
    }

    /// VisionKit's scanner, where this iPhone or iPad has it (and the camera is allowed already;
    /// else AVFoundation's asks for it).
    var visionKit: Bool {
        if #available(iOS 16.0, *) {
            return DataScannerViewController.isSupported && DataScannerViewController.isAvailable
        }
        return false
    }

    /// A QR that isn't the server's is ignored: it keeps scanning.
    func read(_ text: String) {
        guard let url = URL(string: text), let invitation = Mac.Invitation(url) else { return }
        found(invitation)
        dismiss()
    }
}

@available(iOS 16.0, *)
struct VisionScanner: UIViewControllerRepresentable {
    let found: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])],
                                                qualityLevel: .balanced, recognizesMultipleItems: false,
                                                isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {
        if !scanner.isScanning { try? scanner.startScanning() }
    }

    func makeCoordinator() -> Coordinator { Coordinator(found: found) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let found: (String) -> Void
        init(found: @escaping (String) -> Void) { self.found = found }

        func dataScanner(_ scanner: DataScannerViewController, didAdd added: [RecognizedItem], allItems: [RecognizedItem]) {
            for item in added {
                if case .barcode(let code) = item, let text = code.payloadStringValue { found(text) }
            }
        }
    }
}

/// AVFoundation's: the back camera, reading QR codes.
struct CameraScanner: UIViewControllerRepresentable {
    let found: (String) -> Void
    @Binding var denied: Bool

    func makeUIViewController(context: Context) -> ScannerController {
        let controller = ScannerController()
        controller.found = found
        controller.denied = { denied = true }
        return controller
    }

    func updateUIViewController(_ controller: ScannerController, context: Context) {}
}

final class ScannerController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    var found: ((String) -> Void)?
    var denied: (() -> Void)?
    private let session = AVCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        AVCaptureDevice.requestAccess(for: .video) { allowed in
            DispatchQueue.main.async { allowed ? self.configure() : self.denied?() }
        }
    }

    private func configure() {
        guard let camera = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: camera),
              session.canAddInput(input) else { return }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.qr]
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        preview = layer
        DispatchQueue.global(qos: .userInitiated).async { self.session.startRunning() }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        if session.isRunning { DispatchQueue.global(qos: .userInitiated).async { self.session.stopRunning() } }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
        for object in objects {
            if let code = object as? AVMetadataMachineReadableCodeObject, let text = code.stringValue { found?(text) }
        }
    }
}

import Foundation
import Vision
import AppKit
import PDFKit

// Local-only helper: JSON OCR observations, or a single PDF page render.
// OCR boxes use top-left normalized coordinates in the input image.
do {
    let args = Array(CommandLine.arguments.dropFirst())
    if args.first == "render", args.count == 5,
       let number = Int(args[2]), let dpi = Double(args[3]), dpi > 0,
       let doc = PDFDocument(url: URL(fileURLWithPath: args[1])),
       number >= 1, number <= doc.pageCount, let page = doc.page(at: number - 1) {
        let bounds = page.bounds(for: .mediaBox)
        let scale = dpi / 72
        let width = Int(ceil(bounds.width * scale)), height = Int(ceil(bounds.height * scale))
        guard width > 0, height > 0, width * height <= 100_000_000,
              let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                  bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw NSError(domain: "plate", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid render size"])
        }
        ctx.setFillColor(CGColor(gray: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        ctx.scaleBy(x: scale, y: scale)
        page.draw(with: .mediaBox, to: ctx)
        guard let cg = ctx.makeImage(), let data = NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]) else {
            throw NSError(domain: "plate", code: 2)
        }
        try data.write(to: URL(fileURLWithPath: args[4]), options: .withoutOverwriting)
        print("{\"rendered\":true}")
    } else if args.first == "ocr", args.count == 2 {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["en-US", "zh-Hant", "zh-Hans"]
        request.usesLanguageCorrection = false
        try VNImageRequestHandler(url: URL(fileURLWithPath: args[1])).perform([request])
        let rows: [[String: Any]] = (request.results ?? []).compactMap { item in
            guard let candidate = item.topCandidates(1).first else { return nil }
            let box = item.boundingBox
            return ["text": candidate.string, "confidence": candidate.confidence,
                    "box": [box.minX, 1 - box.maxY, box.width, box.height]]
        }
        let json = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
        print(String(data: json, encoding: .utf8)!)
    } else {
        fputs("Usage: plate_ocr ocr IMAGE | render PDF PAGE DPI OUTPUT.png\n", stderr)
        exit(2)
    }
} catch {
    fputs("\(error)\n", stderr); exit(1)
}

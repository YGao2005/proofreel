import AppKit
import Vision

guard CommandLine.arguments.count == 2, let image = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("usage: vm-ocr <png>\n".data(using: .utf8)!)
    exit(2)
}
// Vision misreads small text on a screen with 1x pixels ("Try" as "Iry"). It reads a copy at twice the size well,
// in the same time. Its boxes are fractions of the image, so the pixel math below stays the same.
func doubled(_ image: CGImage) -> CGImage {
    guard image.width < 2000, let context = CGContext(data: nil, width: image.width * 2, height: image.height * 2,
        bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return image }
    context.interpolationQuality = .high
    context.draw(image, in: CGRect(x: 0, y: 0, width: image.width * 2, height: image.height * 2))
    return context.makeImage() ?? image
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
try VNImageRequestHandler(cgImage: doubled(cg)).perform([request])
let width = Double(cg.width), height = Double(cg.height)
let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
    guard let text = observation.topCandidates(1).first?.string else { return nil }
    let box = observation.boundingBox
    return ["text": text, "x": Int(box.minX * width), "y": Int((1 - box.maxY) * height),
            "w": Int(box.width * width), "h": Int(box.height * height)]
}
print(String(data: try JSONSerialization.data(withJSONObject: lines), encoding: .utf8)!)

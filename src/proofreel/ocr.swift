import AppKit
import Vision

guard CommandLine.arguments.count == 2, let image = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("usage: vm-ocr <png>\n".data(using: .utf8)!)
    exit(2)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
try VNImageRequestHandler(cgImage: cg).perform([request])
let width = Double(cg.width), height = Double(cg.height)
let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
    guard let text = observation.topCandidates(1).first?.string else { return nil }
    let box = observation.boundingBox
    return ["text": text, "x": Int(box.minX * width), "y": Int((1 - box.maxY) * height),
            "w": Int(box.width * width), "h": Int(box.height * height)]
}
print(String(data: try JSONSerialization.data(withJSONObject: lines), encoding: .utf8)!)

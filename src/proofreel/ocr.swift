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
func pixels(_ box: CGRect, _ text: String) -> [String: Any] {
    ["text": text, "x": Int(box.minX * width), "y": Int((1 - box.maxY) * height),
     "w": Int(box.width * width), "h": Int(box.height * height)]
}
let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let text = candidate.string
    var words: [[String: Any]] = []
    var index = text.startIndex
    while let start = text[index...].firstIndex(where: { !$0.isWhitespace }) {
        let end = text[start...].firstIndex(where: { $0.isWhitespace }) ?? text.endIndex
        if let box = try? candidate.boundingBox(for: start..<end)?.boundingBox {
            words.append(pixels(box, String(text[start..<end])))
        }
        index = end
    }
    var line = pixels(observation.boundingBox, text)
    line["words"] = words
    return line
}
print(String(data: try JSONSerialization.data(withJSONObject: lines), encoding: .utf8)!)

import AppKit
import ApplicationServices

var appName: String?
var maxDepth = 60
var budget = 4000
var args = CommandLine.arguments.dropFirst().makeIterator()
while let arg = args.next() {
    switch arg {
    case "--app": appName = args.next()
    case "--front": appName = nil
    case "--depth": maxDepth = Int(args.next() ?? "") ?? maxDepth
    default:
        FileHandle.standardError.write("usage: proofreel-ax [--app <name>|--front] [--depth N]\n".data(using: .utf8)!)
        exit(2)
    }
}

func fail(_ message: String, _ code: Int32) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(code)
}

guard AXIsProcessTrusted() else {
    fail("This process has no Accessibility permission. Grant it to the process that starts it (over SSH: /usr/libexec/sshd-keygen-wrapper).", 3)
}

func attribute(_ element: AXUIElement, _ name: String) -> AnyObject? {
    var value: AnyObject?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}

func text(_ value: AnyObject?, limit: Int = 200) -> String? {
    guard let string = value as? String, !string.isEmpty else { return nil }
    return string.count > limit ? String(string.prefix(limit)) + "…" : string
}

func plain(_ value: AnyObject?) -> Any? {
    if let string = text(value) { return string }
    if let number = value as? NSNumber { return number }
    if let url = value as? URL { return url.absoluteString }
    return nil
}

func frame(_ element: AXUIElement) -> [Double]? {
    var point = CGPoint.zero, size = CGSize.zero
    guard let position = attribute(element, kAXPositionAttribute), let extent = attribute(element, kAXSizeAttribute),
          CFGetTypeID(position) == AXValueGetTypeID(), CFGetTypeID(extent) == AXValueGetTypeID(),
          AXValueGetValue(position as! AXValue, .cgPoint, &point), AXValueGetValue(extent as! AXValue, .cgSize, &size)
    else { return nil }
    return [point.x, point.y, size.width, size.height].map { (Double($0) * 10).rounded() / 10 }
}

func node(_ element: AXUIElement, _ depth: Int) -> [String: Any] {
    budget -= 1
    var out: [String: Any] = ["role": attribute(element, kAXRoleAttribute) as? String ?? "?"]
    out["subrole"] = text(attribute(element, kAXSubroleAttribute))
    out["title"] = text(attribute(element, kAXTitleAttribute))
    out["description"] = text(attribute(element, kAXDescriptionAttribute))
    out["id"] = text(attribute(element, kAXIdentifierAttribute))
    out["value"] = plain(attribute(element, kAXValueAttribute))
    if let titled = attribute(element, kAXTitleUIElementAttribute), CFGetTypeID(titled) == AXUIElementGetTypeID() {
        let label = titled as! AXUIElement
        out["label"] = text(attribute(label, kAXValueAttribute)) ?? text(attribute(label, kAXTitleAttribute))
    }
    out["enabled"] = attribute(element, kAXEnabledAttribute) as? Bool
    out["focused"] = (attribute(element, kAXFocusedAttribute) as? Bool) == true ? true : nil
    out["frame"] = frame(element)
    let children = attribute(element, kAXChildrenAttribute) as? [AXUIElement] ?? []
    if depth < maxDepth && budget > 0 && !children.isEmpty {
        out["children"] = children.prefix(budget).map { node($0, depth + 1) }
    }
    return out
}

func match(_ app: NSRunningApplication, _ name: String) -> Bool {
    let want = name.lowercased()
    return app.localizedName?.lowercased() == want || app.bundleIdentifier?.lowercased() == want
}

let apps = NSWorkspace.shared.runningApplications
let found = appName.map { name in
    apps.first { match($0, name) } ?? apps.first { $0.localizedName?.lowercased().contains(name.lowercased()) == true }
} ?? NSWorkspace.shared.frontmostApplication
guard let pid = found?.processIdentifier else { fail(appName.map { "No running app named \($0)." } ?? "No app is in front.", 4) }

let app = AXUIElementCreateApplication(pid)
AXUIElementSetMessagingTimeout(app, 3)
let windows = attribute(app, kAXWindowsAttribute) as? [AXUIElement] ?? []
let display = CGDisplayBounds(CGMainDisplayID())
let result: [String: Any] = [
    "app": NSRunningApplication(processIdentifier: pid)?.localizedName ?? "",
    "pid": pid,
    "screen": ["w": display.width, "h": display.height],
    "windows": windows.map { node($0, 0) },
]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write("\n".data(using: .utf8)!)

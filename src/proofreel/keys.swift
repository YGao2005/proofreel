// Post modifier key presses in a macOS guest, as a hardware keyboard does. A VNC server cannot send Fn, and the
// presses of a tap must keep their timing, so each command runs as one process in the guest.
//   keys hold <modifier> <seconds> | keys tap <modifier> <count> <press ms> <gap ms> | keys down|up <modifier>
import CoreGraphics
import Foundation

// WHY: a real keyboard also sets the device bit of the left or right key, and some apps read it.
let modifiers: [String: (CGKeyCode, CGEventFlags)] = [
    "fn": (63, .maskSecondaryFn),
    "option": (58, [.maskAlternate, CGEventFlags(rawValue: 0x20)]),
    "roption": (61, [.maskAlternate, CGEventFlags(rawValue: 0x40)]),
    "command": (55, [.maskCommand, CGEventFlags(rawValue: 0x8)]),
    "rcommand": (54, [.maskCommand, CGEventFlags(rawValue: 0x10)]),
    "control": (59, [.maskControl, CGEventFlags(rawValue: 0x1)]),
    "rcontrol": (62, [.maskControl, CGEventFlags(rawValue: 0x2000)]),
    "shift": (56, [.maskShift, CGEventFlags(rawValue: 0x2)]),
    "rshift": (60, [.maskShift, CGEventFlags(rawValue: 0x4)]),
]
let source = CGEventSource(stateID: .hidSystemState)

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(2)
}

func post(_ name: String, down: Bool) {
    guard let (code, mask) = modifiers[name] else {
        fail("Unknown modifier \(name). Use one of: \(modifiers.keys.sorted().joined(separator: ", ")).")
    }
    guard let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down) else {
        fail("macOS made no key event for \(name).")
    }
    event.type = .flagsChanged
    event.flags = down ? mask.union(.maskNonCoalesced) : .maskNonCoalesced
    event.post(tap: .cghidEventTap)
}

func pause(_ milliseconds: Double) {
    usleep(UInt32(max(0, milliseconds) * 1000))
}

// WHY: without the permission, macOS drops posted events with no error.
guard CGPreflightPostEventAccess() else {
    fail("The guest drops posted keys: give /usr/libexec/sshd-keygen-wrapper the Accessibility permission.")
}
let args = Array(CommandLine.arguments.dropFirst())
func number(_ index: Int) -> Double {
    guard index < args.count, let value = Double(args[index]) else { fail("Usage: keys hold|tap|down|up <modifier> ...") }
    return value
}

switch args.first {
case "hold" where args.count == 3:
    post(args[1], down: true)
    pause(number(2) * 1000)
    post(args[1], down: false)
case "tap" where args.count == 5:
    for index in 0..<Int(number(2)) {
        if index > 0 { pause(number(4)) }
        post(args[1], down: true)
        pause(number(3))
        post(args[1], down: false)
    }
case "down" where args.count == 2: post(args[1], down: true)
case "up" where args.count == 2: post(args[1], down: false)
default: fail("Usage: keys hold|tap|down|up <modifier> ...")
}

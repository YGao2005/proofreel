import CoreAudio
import Foundation

let system = AudioObjectID(kAudioObjectSystemObject)

func address(_ selector: AudioObjectPropertySelector) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
}

func read<T: BitwiseCopyable>(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector, _ initial: T) -> T {
    var value = initial, size = UInt32(MemoryLayout<T>.size), where_ = address(selector)
    AudioObjectGetPropertyData(id, &where_, 0, nil, &size, &value)
    return value
}

func text(_ id: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String {
    var value: Unmanaged<CFString>?, size = UInt32(MemoryLayout<CFString?>.size), where_ = address(selector)
    guard AudioObjectGetPropertyData(id, &where_, 0, nil, &size, &value) == noErr, let value else { return "" }
    return value.takeRetainedValue() as String
}

func fourcc(_ value: UInt32) -> String {
    String(bytes: [24, 16, 8, 0].map { UInt8((value >> $0) & 0xff) }, encoding: .ascii) ?? "\(value)"
}

func devices() -> [AudioObjectID] {
    var where_ = address(kAudioHardwarePropertyDevices), size: UInt32 = 0
    AudioObjectGetPropertyDataSize(system, &where_, 0, nil, &size)
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / 4)
    AudioObjectGetPropertyData(system, &where_, 0, nil, &size, &ids)
    return ids
}

func rate(_ id: AudioObjectID) -> Double { read(id, kAudioDevicePropertyNominalSampleRate, 0.0) }

func defaultInput() -> AudioObjectID { read(system, kAudioHardwarePropertyDefaultInputDevice, AudioObjectID(0)) }

func fail(_ message: String) -> Never {
    print(message)
    exit(1)
}

let args = Array(CommandLine.arguments.dropFirst())
switch args.first {
case "set-default-input":
    guard let id = devices().first(where: { text($0, kAudioDevicePropertyDeviceUID) == args[1] }) else { fail("no device \(args[1])") }
    var value = id, where_ = address(kAudioHardwarePropertyDefaultInputDevice)
    exit(AudioObjectSetPropertyData(system, &where_, 0, nil, 4, &value) == noErr ? 0 : 1)
case "check":
    let callRate = Double(args[1]) ?? 24000
    let id = defaultInput()
    guard id != 0 else { fail("No default input device.") }
    let name = text(id, kAudioObjectPropertyName), transport = read(id, kAudioDevicePropertyTransportType, UInt32(0))
    let idle = rate(id)
    var proc: AudioDeviceIOProcID?
    guard AudioDeviceCreateIOProcIDWithBlock(&proc, id, nil, { _, _, _, _, _ in }) == noErr, let proc,
          AudioDeviceStart(id, proc) == noErr else { fail("Input on \(name) did not start.") }
    var during = idle
    for _ in 0..<40 where during == idle {
        usleep(50_000)
        during = rate(id)
    }
    AudioDeviceStop(id, proc)
    AudioDeviceDestroyIOProcID(id, proc)
    var after = during
    for _ in 0..<80 where after != idle {
        usleep(50_000)
        after = rate(id)
    }
    let summary = "Default input \(name): transport \(fourcc(transport)), \(Int(idle)) Hz idle, \(Int(during)) Hz with input on, \(Int(after)) Hz after."
    let ok = transport == kAudioDeviceTransportTypeBluetooth && idle == 48000 && during == callRate && after == 48000
    if !ok { fail(summary) }
    print(summary)
default:
    fail("usage: probe set-default-input <uid> | check <call rate>")
}

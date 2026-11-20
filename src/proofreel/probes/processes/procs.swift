import Darwin
import Foundation

let env = ProcessInfo.processInfo.environment
let app = env["PROOFREEL_APP"] ?? ""
let interval = Double(env["INTERVAL"] ?? "") ?? 1
let me = getpid()
let top = 3, topMin = 10.0, topNames = 16

struct Key: Hashable { let pid: Int32, start: UInt64 }
struct Proc { let parent: Int32, responsible: Int32, name: String, comm: String, path: String, cpu: Double, memory: Double }

// WHY: an app's XPC services (such as WebKit's web content) are children of launchd; macOS names the app responsible.
let responsible: (Int32) -> Int32 = {
    guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "responsibility_get_pid_responsible_for_pid") else { return { $0 } }
    return unsafeBitCast(symbol, to: (@convention(c) (Int32) -> Int32).self)
}()

let tick: Double = {
    var base = mach_timebase_info_data_t()
    mach_timebase_info(&base)
    return Double(base.numer) / Double(base.denom) / 1e9
}()

func text<T>(_ tuple: T) -> String {
    withUnsafeBytes(of: tuple) { bytes in String(decoding: bytes.prefix { $0 != 0 }, as: UTF8.self) }
}

func usage(_ pid: Int32) -> (cpu: Double, memory: Double)? {
    var info = rusage_info_v0()
    let done = withUnsafeMutablePointer(to: &info) {
        $0.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { proc_pid_rusage(pid, RUSAGE_INFO_V0, $0) }
    }
    if done == 0 {
        return (Double(info.ri_user_time + info.ri_system_time) * tick, Double(info.ri_phys_footprint))
    }
    var task = proc_taskinfo()
    let size = Int32(MemoryLayout<proc_taskinfo>.size)
    guard proc_pidinfo(pid, PROC_PIDTASKINFO, 0, &task, size) == size else { return nil }
    return (Double(task.pti_total_user + task.pti_total_system) * tick, Double(task.pti_resident_size))
}

func processes() -> [Key: Proc] {
    var pids = [Int32](repeating: 0, count: Int(proc_listallpids(nil, 0)) + 64)
    let count = Int(proc_listallpids(&pids, Int32(pids.count * MemoryLayout<Int32>.size)))
    var found = [Key: Proc]()
    var path = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
    for pid in pids.prefix(max(0, count)) where pid > 0 {
        var info = proc_bsdinfo()
        let size = Int32(MemoryLayout<proc_bsdinfo>.size)
        guard proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size, let used = usage(pid) else { continue }
        let length = proc_pidpath(pid, &path, UInt32(path.count))
        let comm = text(info.pbi_comm), name = text(info.pbi_name)
        found[Key(pid: pid, start: info.pbi_start_tvsec * 1_000_000 + info.pbi_start_tvusec)] = Proc(
            parent: Int32(info.pbi_ppid), responsible: responsible(pid), name: name.isEmpty ? comm : name, comm: comm,
            path: length > 0 ? String(cString: path) : "", cpu: used.cpu, memory: used.memory)
    }
    return found
}

var bundleIDs = [String: String]()

func bundle(_ path: String) -> String? {
    guard let end = path.range(of: ".app/") else { return nil }
    return String(path[..<end.lowerBound]) + ".app"
}

func named(_ proc: Proc) -> Bool {
    if app.isEmpty { return false }
    if [proc.name, proc.comm, (proc.path as NSString).lastPathComponent].contains(app) { return true }
    guard let root = bundle(proc.path) else { return false }
    if ((root as NSString).lastPathComponent as NSString).deletingPathExtension == app { return true }
    if bundleIDs[root] == nil { bundleIDs[root] = Bundle(path: root)?.bundleIdentifier ?? "" }
    return bundleIDs[root] == app
}

func appTree(_ found: [Key: Proc]) -> Set<Key> {
    var children = [Int32: [Key]]()
    for (key, proc) in found { children[proc.parent, default: []].append(key) }
    var todo = found.filter { named($0.value) }.map(\.key)
    let roots = Set(todo.compactMap { bundle(found[$0]!.path) }), pids = Set(todo.map(\.pid))
    todo += found.filter { pids.contains($0.value.responsible) || bundle($0.value.path).map(roots.contains) ?? false }.map(\.key)
    var seen = Set<Key>()
    while let key = todo.popLast() {
        if seen.insert(key).inserted { todo += children[key.pid] ?? [] }
    }
    return seen
}

func cpuTicks() -> (busy: Double, all: Double) {
    var load = host_cpu_load_info()
    var count = mach_msg_type_number_t(MemoryLayout<host_cpu_load_info>.size / MemoryLayout<integer_t>.size)
    _ = withUnsafeMutablePointer(to: &load) {
        $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { host_statistics(mach_host_self(), HOST_CPU_LOAD_INFO, $0, &count) }
    }
    let ticks = [load.cpu_ticks.0, load.cpu_ticks.1, load.cpu_ticks.2, load.cpu_ticks.3].map(Double.init)
    return (ticks[0] + ticks[1] + ticks[3], ticks.reduce(0, +))
}

func memoryInUse() -> Double {
    var stats = vm_statistics64()
    var count = mach_msg_type_number_t(MemoryLayout<vm_statistics64>.size / MemoryLayout<integer_t>.size)
    _ = withUnsafeMutablePointer(to: &stats) {
        $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) { host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count) }
    }
    let pages = Double(stats.internal_page_count) - Double(stats.purgeable_count) + Double(stats.wire_count) + Double(stats.compressor_page_count)
    return pages * Double(vm_kernel_page_size) / 1_048_576
}

func now() -> Double { Double(clock_gettime_nsec_np(CLOCK_UPTIME_RAW)) / 1e9 }

func say(_ line: String) {
    FileHandle.standardOutput.write(Data((line + "\n").utf8))
}

func quote(_ text: String) -> String {
    let data = try? JSONSerialization.data(withJSONObject: text, options: [.fragmentsAllowed, .withoutEscapingSlashes])
    return data.flatMap { String(data: $0, encoding: .utf8) } ?? "\"?\""
}

var names = Set<String>()

func measures(_ lines: [(String, Double)], _ t: Double) {
    for (m, v) in lines {
        if m.hasPrefix("cpu/top/") {
            if !names.contains(m) && names.count >= topNames { continue }
            names.insert(m)
        }
        say(String(format: "{\"m\":%@,\"v\":%.2f,\"t\":%.4f}", quote(m), v, t))
    }
}

say(#"{"ready":true}"#)
say(#"{"meta":{"app":\#(quote(app.isEmpty ? "none: give start --app" : app)),"cores":\#(ProcessInfo.processInfo.activeProcessorCount)}}"#)
var before: [Key: Proc]? = nil, then = 0.0, ticks = (busy: 0.0, all: 0.0), running: Bool? = nil
while true {
    let found = processes(), load = cpuTicks(), at = now()
    let tree = appTree(found)
    var lines = [(String, Double)]()
    var used = [Key: Double]()
    if let before {
        for (key, proc) in found where key.pid != me {
            used[key] = (proc.cpu - (before[key]?.cpu ?? 0)) / (at - then) * 100
        }
    }
    if !tree.isEmpty {
        if before != nil { lines.append(("cpu/app", tree.reduce(0) { $0 + (used[$1] ?? 0) })) }
        lines += [("mem/app", tree.reduce(0) { $0 + found[$1]!.memory } / 1_048_576), ("app/procs", Double(tree.count))]
    }
    if before != nil {
        var others = [String: Double]()
        for (key, cpu) in used where !tree.contains(key) { others[found[key]!.name, default: 0] += cpu }
        lines.append(("cpu/other", others.values.reduce(0, +)))
        lines += others.filter { $0.value >= topMin }.sorted { $0.value > $1.value }.prefix(top).map { ("cpu/top/\($0.key)", $0.value) }
        lines.append(("cpu/system", (load.busy - ticks.busy) / max(1, load.all - ticks.all) * 100))
    }
    measures(lines + [("mem/system", memoryInUse())], at)
    if !app.isEmpty, let running, running != !tree.isEmpty {
        say(String(format: "{\"m\":\"%@\",\"t\":%.4f}", tree.isEmpty ? "app/exit" : "app/start", at))
    }
    (before, then, ticks, running) = (found, at, load, !tree.isEmpty)
    Thread.sleep(forTimeInterval: interval)
}

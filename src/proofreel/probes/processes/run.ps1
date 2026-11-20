$ErrorActionPreference = 'Stop'
try {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading;

public static class Procs {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct Entry { public uint size, usage, pid; public IntPtr heap; public uint module, threads, parent; public int priority; public uint flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string exe; }
    [StructLayout(LayoutKind.Sequential)]
    struct Counters { public uint size, faults; public UIntPtr peak, working, a, b, c, d, pagefile, peakPagefile, priv; }
    [StructLayout(LayoutKind.Sequential)]
    struct Memory { public uint size, load; public ulong total, avail, pageTotal, pageAvail, virtTotal, virtAvail, extended; }

    [DllImport("kernel32")] static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
    [DllImport("kernel32", CharSet = CharSet.Unicode)] static extern bool Process32FirstW(IntPtr snap, ref Entry entry);
    [DllImport("kernel32", CharSet = CharSet.Unicode)] static extern bool Process32NextW(IntPtr snap, ref Entry entry);
    [DllImport("kernel32")] static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32")] static extern bool GetProcessTimes(IntPtr process, out long created, out long ended, out long kernel, out long user);
    [DllImport("kernel32")] static extern bool K32GetProcessMemoryInfo(IntPtr process, out Counters counters, uint size);
    [DllImport("kernel32")] static extern bool GetSystemTimes(out long idle, out long kernel, out long user);
    [DllImport("kernel32")] static extern bool GlobalMemoryStatusEx(ref Memory memory);

    class Proc { public uint Parent; public string Name; public double Cpu, Mem; }

    static Dictionary<Tuple<uint, long>, Proc> Read() {
        var found = new Dictionary<Tuple<uint, long>, Proc>();
        var snap = CreateToolhelp32Snapshot(2, 0);
        var entry = new Entry { size = (uint)Marshal.SizeOf(typeof(Entry)) };
        for (var more = Process32FirstW(snap, ref entry); more; more = Process32NextW(snap, ref entry)) {
            var handle = OpenProcess(0x1000, false, entry.pid);
            if (handle == IntPtr.Zero) continue;
            long created, ended, kernel, user;
            Counters counters;
            if (GetProcessTimes(handle, out created, out ended, out kernel, out user)) {
                var mem = K32GetProcessMemoryInfo(handle, out counters, (uint)Marshal.SizeOf(typeof(Counters))) ? (double)counters.priv.ToUInt64() : 0;
                var name = entry.exe.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ? entry.exe.Substring(0, entry.exe.Length - 4) : entry.exe;
                found[Tuple.Create(entry.pid, created)] = new Proc { Parent = entry.parent, Name = name, Cpu = (kernel + user) / 1e7, Mem = mem };
            }
            CloseHandle(handle);
        }
        CloseHandle(snap);
        return found;
    }

    static HashSet<Tuple<uint, long>> Tree(Dictionary<Tuple<uint, long>, Proc> found, string app) {
        var seen = new HashSet<Tuple<uint, long>>();
        if (app == "") return seen;
        var children = found.Keys.ToLookup(k => found[k].Parent);
        var todo = new Stack<Tuple<uint, long>>(found.Keys.Where(k => string.Equals(found[k].Name, app, StringComparison.OrdinalIgnoreCase)));
        while (todo.Count > 0) {
            var key = todo.Pop();
            if (!seen.Add(key)) continue;
            foreach (var child in children[key.Item1]) if (child.Item2 >= key.Item2) todo.Push(child);
        }
        return seen;
    }

    static string Quote(string text) {
        return "\"" + string.Concat(text.Select(c => c == '"' || c == '\\' ? "\\" + c : c < ' ' ? string.Format("\\u{0:x4}", (int)c) : c.ToString())) + "\"";
    }

    static void Say(string line) { Console.Out.WriteLine(line); Console.Out.Flush(); }

    public static void Run(string app, double interval) {
        app = app.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) ? app.Substring(0, app.Length - 4) : app;
        var me = (uint)Process.GetCurrentProcess().Id;
        var clock = Stopwatch.StartNew();
        var names = new HashSet<string>();
        Dictionary<Tuple<uint, long>, Proc> before = null;
        long busy0 = 0, all0 = 0;
        double then = 0;
        bool? running = null;
        var dot = System.Globalization.CultureInfo.InvariantCulture;
        Say("{\"ready\":true}");
        Say("{\"meta\":{\"app\":" + Quote(app == "" ? "none: give start --app" : app) + ",\"cores\":" + Environment.ProcessorCount + "}}");
        while (true) {
            var found = Read();
            var at = clock.Elapsed.TotalSeconds;
            long idle, kernel, user;
            GetSystemTimes(out idle, out kernel, out user);
            var memory = new Memory { size = (uint)Marshal.SizeOf(typeof(Memory)) };
            GlobalMemoryStatusEx(ref memory);
            var tree = Tree(found, app);
            var lines = new List<KeyValuePair<string, double>>();
            Action<string, double> add = (m, v) => lines.Add(new KeyValuePair<string, double>(m, v));
            var used = new Dictionary<Tuple<uint, long>, double>();
            if (before != null)
                foreach (var pair in found)
                    if (pair.Key.Item1 != me && pair.Key.Item1 != 0)
                        used[pair.Key] = (pair.Value.Cpu - (before.ContainsKey(pair.Key) ? before[pair.Key].Cpu : 0)) / (at - then) * 100;
            if (tree.Count > 0) {
                if (before != null) add("cpu/app", tree.Sum(k => used.ContainsKey(k) ? used[k] : 0));
                add("mem/app", tree.Sum(k => found[k].Mem) / 1048576);
                add("app/procs", tree.Count);
            }
            if (before != null) {
                var others = used.Where(p => !tree.Contains(p.Key)).GroupBy(p => found[p.Key].Name).ToDictionary(g => g.Key, g => g.Sum(p => p.Value));
                add("cpu/other", others.Values.Sum());
                foreach (var top in others.Where(p => p.Value >= 10).OrderByDescending(p => p.Value).Take(3)) add("cpu/top/" + top.Key, top.Value);
                add("cpu/system", 100.0 * ((kernel + user - idle) - busy0) / Math.Max(1, (kernel + user) - all0));
            }
            add("mem/system", (memory.total - memory.avail) / 1048576.0);
            foreach (var line in lines) {
                if (line.Key.StartsWith("cpu/top/")) {
                    if (!names.Contains(line.Key) && names.Count >= 16) continue;
                    names.Add(line.Key);
                }
                Say(string.Format(dot, "{{\"m\":{0},\"v\":{1:0.##},\"t\":{2:0.####}}}", Quote(line.Key), line.Value, at));
            }
            if (app != "" && running.HasValue && running.Value != tree.Count > 0)
                Say(string.Format(dot, "{{\"m\":\"{0}\",\"t\":{1:0.####}}}", tree.Count > 0 ? "app/start" : "app/exit", at));
            before = found; then = at; busy0 = kernel + user - idle; all0 = kernel + user; running = tree.Count > 0;
            Thread.Sleep(TimeSpan.FromSeconds(interval));
        }
    }
}
'@
} catch {
    Write-Output ('{"unavailable": "Add-Type failed: ' + ($_.Exception.Message -replace '["\\\r\n]', ' ') + '"}')
    exit 0
}
$interval = 1.0
if ($env:INTERVAL) { $interval = [double]::Parse($env:INTERVAL, [Globalization.CultureInfo]::InvariantCulture) }
[Procs]::Run([string]$env:PROOFREEL_APP, $interval)

import Foundation
import UserNotifications

let debugOn = ProcessInfo.processInfo.environment["NOTIFY_DEBUG"] != nil
let logURL = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent(".claude/notify-debug.log")
func log(_ s: String, force: Bool = false) {
    guard debugOn || force else { return }
    let line = "\(Date()) \(s)\n"
    FileHandle.standardError.write(line.data(using: .utf8)!)
    if let d = line.data(using: .utf8) {
        if let fh = try? FileHandle(forWritingTo: logURL) {
            fh.seekToEndOfFile(); fh.write(d); try? fh.close()
        } else { try? d.write(to: logURL) }
    }
}

// ---- payload: JSON file, JSON argv, "Title|Body", or plain text ----
var title = "Claude Code", subtitle = "", body = "Finished", soundName = "default"

func apply(_ raw: String) {
    let s = raw.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !s.isEmpty else { return }
    if s.hasPrefix("{"), let d = s.data(using: .utf8),
       let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] {
        title    = (o["title"]    as? String) ?? title
        subtitle = (o["subtitle"] as? String) ?? subtitle
        body     = (o["body"]     as? String) ?? body
        soundName = (o["sound"]   as? String) ?? soundName
        return
    }
    let parts = s.components(separatedBy: "|")
    if parts.count > 2 { title = parts[0]; subtitle = parts[1]; body = parts.dropFirst(2).joined(separator: "|") }
    else if parts.count > 1 { title = parts[0]; body = parts[1] }
    else { body = s }
}

let args = Array(CommandLine.arguments.dropFirst())
if !args.isEmpty {
    apply(args.joined(separator: " "))
} else if let raw = try? String(contentsOf: FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent(".claude/.notify-msg"), encoding: .utf8) {
    apply(raw)
}

let center = UNUserNotificationCenter.current()
var granted = false, authErr: Error?
let sem = DispatchSemaphore(value: 0)
center.requestAuthorization(options: [.alert, .sound]) { ok, err in granted = ok; authErr = err; sem.signal() }
_ = sem.wait(timeout: .now() + 30)
log("authorized=\(granted) error=\(authErr.map { String(describing: $0) } ?? "none")", force: authErr != nil)

let content = UNMutableNotificationContent()
content.title = title
if !subtitle.isEmpty { content.subtitle = subtitle }
content.body = body
switch soundName.lowercased() {
case "none", "": content.sound = nil
case "default":  content.sound = .default
default:         content.sound = UNNotificationSound(named: UNNotificationSoundName(soundName))
}

var addErr: Error?
let sem2 = DispatchSemaphore(value: 0)
center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)) { err in
    addErr = err; sem2.signal()
}
_ = sem2.wait(timeout: .now() + 15)
log("posted title=\"\(title)\" sub=\"\(subtitle)\" body=\"\(body)\" sound=\(soundName) error=\(addErr.map { String(describing: $0) } ?? "none")", force: addErr != nil)
Thread.sleep(forTimeInterval: 0.4)
exit(addErr == nil ? 0 : 3)

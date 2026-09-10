import AppKit
import Foundation
let output = URL(fileURLWithPath: CommandLine.arguments[1])
FileManager.default.createFile(atPath: output.path, contents:nil)
let file = try FileHandle(forWritingTo:output)
let end = Date().addingTimeInterval(Double(CommandLine.arguments[2]) ?? 600)
while Date()<end {
 if let app=NSWorkspace.shared.frontmostApplication {
  let row:[String:Any] = ["time":Date().timeIntervalSince1970,"pid":Int(app.processIdentifier),"bundle":app.bundleIdentifier ?? "", "name":app.localizedName ?? ""]
  let data=try JSONSerialization.data(withJSONObject:row,options:[.sortedKeys]);file.write(data);file.write(Data([10]))
 }
 Thread.sleep(forTimeInterval:0.05)
}
try file.close()

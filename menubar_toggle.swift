import Cocoa

class App: NSObject, NSApplicationDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    var timer: Timer?
    let base = NSHomeDirectory() + "/EmailForwarder"
    var port = 9876

    func applicationDidFinishLaunching(_ n: Notification) {
        if let d = try? Data(contentsOf: URL(fileURLWithPath: base + "/config.json")),
           let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
           let p = j["dashboard_port"] as? Int { port = p }

        let menu = NSMenu()
        let t = NSMenuItem(title: "Toggle", action: #selector(toggle), keyEquivalent: "")
        t.target = self; menu.addItem(t)
        menu.addItem(.separator())
        let s = NSMenuItem(title: "", action: nil, keyEquivalent: ""); s.tag = 1; menu.addItem(s)
        let c = NSMenuItem(title: "", action: nil, keyEquivalent: ""); c.tag = 2; menu.addItem(c)
        menu.addItem(.separator())
        let log = NSMenuItem(title: "Open Log", action: #selector(openLog), keyEquivalent: "l")
        log.target = self; menu.addItem(log)
        let q = NSMenuItem(title: "Quit Menu Icon", action: #selector(doQuit), keyEquivalent: "q")
        q.target = self; menu.addItem(q)
        item.menu = menu

        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    func state() -> (Bool, Int, String) {
        guard let d = try? Data(contentsOf: URL(fileURLWithPath: base + "/state.json")),
              let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any]
        else { return (true, 0, "\u{2014}") }
        return (j["enabled"] as? Bool ?? true,
                j["forwarded_count"] as? Int ?? 0,
                j["last_check"] as? String ?? "\u{2014}")
    }

    func refresh() {
        let (on, n, last) = state()
        item.button?.title = on ? "\u{2709}\u{FE0E}" : "\u{2709}\u{FE0E} \u{23F8}"
        item.menu?.item(withTag: 1)?.title = "Forwarded: \(n)"
        item.menu?.item(withTag: 2)?.title = "Checked: \(last)"
        item.menu?.items.first?.title = on ? "\u{23F8}  Pause" : "\u{25B6}\u{FE0F}  Resume"
    }

    @objc func toggle() {
        var req = URLRequest(url: URL(string: "http://localhost:\(port)/toggle")!)
        req.httpMethod = "POST"
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.async { self?.refresh() }
        }.resume()
    }

    @objc func openLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: base + "/forwarder.log"))
    }

    @objc func doQuit() { NSApp.terminate(nil) }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let d = App()
app.delegate = d
app.run()

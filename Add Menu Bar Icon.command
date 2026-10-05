#!/bin/bash
# Adds the menu bar toggle icon to an existing EmailForwarder install.
# No sign-in, no setup — just compiles and starts the icon.

set -u

APP_DIR="$HOME/EmailForwarder"
LABEL="com.moritz.emailforwarder.menubar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

die()  { printf '\n\033[31m%s\033[0m\n\n' "$*"; printf 'Press return to close.'; read -r _; exit 1; }

clear
echo "=== Adding menu bar icon ==="
echo

[ -d "$APP_DIR" ] || die "EmailForwarder not found at $APP_DIR — run the full installer first."

command -v swiftc >/dev/null 2>&1 || die "swiftc not found. Install Xcode Command Line Tools: xcode-select --install"

cat > "$APP_DIR/menubar_toggle.swift" <<'SWIFT_EOF'
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
        let icon = on ? "\u{2709}\u{FE0E}" : "\u{2709}\u{FE0E}\u{23F8}"
        let attr = NSAttributedString(string: icon, attributes: [
            .font: NSFont.systemFont(ofSize: 18)
        ])
        item.button?.attributedTitle = attr
        item.menu?.item(withTag: 1)?.title = "Forwarded: \(n)"
        item.menu?.item(withTag: 2)?.title = "Checked: \(last)"
        item.menu?.items.first?.title = on ? "\u{23F8}  Pause" : "\u{25B6}\u{FE0F}  Resume"
    }

    @objc func toggle() {
        var req = URLRequest(url: URL(string: "http://localhost:\(port)/toggle")!)
        req.httpMethod = "POST"
        req.setValue("1", forHTTPHeaderField: "X-Forwarder")
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
SWIFT_EOF

echo "  Compiling..."
ERR="$(swiftc -O -o "$APP_DIR/menubar_toggle" "$APP_DIR/menubar_toggle.swift" -framework Cocoa 2>&1)"
[ $? -eq 0 ] || die "Compile failed: $ERR"
echo "  Compiled."

# Stop old instance if running
launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1
for _ in 1 2 3 4 5; do
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 1
done

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/menubar_toggle</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/dev/null</string>
  <key>StandardErrorPath</key><string>/dev/null</string>
</dict>
</plist>
PLIST_EOF

BOOT_ERR="$(launchctl bootstrap "$DOMAIN" "$PLIST" 2>&1)"
if [ $? -ne 0 ]; then
  BOOT_ERR="$(launchctl load -w "$PLIST" 2>&1)"
  [ $? -eq 0 ] || die "Could not start: $BOOT_ERR"
fi

echo
echo "  Done — look for the envelope (✉) in your menu bar."
echo "  Click it to pause/resume the forwarder."
echo
printf 'Press return to close.'
read -r _

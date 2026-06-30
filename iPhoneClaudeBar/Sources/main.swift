import Cocoa
import ServiceManagement

// iPhone & Claude — a menu-bar app showing the iPhone's battery next to a live pixel "bloom"
// loader whose color reflects Claude Code's state, plus the current status text.
//
//   GET http://127.0.0.1:4040/battery -> { phone: { level, charging, present, stale, source } }
//   GET http://127.0.0.1:4040/status  -> { state, label, tool, project }
//
// No Mac battery (macOS shows that natively). The creature is drawn procedurally — no GIFs.

let SERVER = "http://127.0.0.1:4040"
let POLL_SECONDS = 2.0
let ANIM_FPS = 30.0

// State -> bloom color (RGB 0-255), matching the pixloader variants the user supplied.
let COL_CODING = (CGFloat(222), CGFloat(115), CGFloat(86))   // #DE7356  working / thinking
let COL_ALERT  = (CGFloat(242), CGFloat(242), CGFloat(4))    // #F2F204  waiting / permission
let COL_DONE   = (CGFloat(4),   CGFloat(242), CGFloat(11))   // #04F20B  finished turn
let COL_IDLE   = (CGFloat(110), CGFloat(110), CGFloat(122))  // calm gray for idle / offline

// ── Pixel "bloom" loader, ported from the supplied canvas script ──────────────────────────────
// A fixed ring of pixels pulses outward: each cell's alpha = a distance-based floor plus a
// sin² ripple driven by time and radius, giving the breathing bloom.
enum Bloom {
    static let offsets: [(Int, Int)] = [
        (-1,-1),(0,-1),(1,-1),(-2,-1),(2,-1),(-2,0),(-1,0),(0,0),(1,0),(2,0),
        (-2,1),(-1,1),(0,1),(1,1),(2,1),(-1,-2),(0,-2),(1,-2),(2,-2),(-2,-2),
        (-1,2),(0,2),(1,2),(2,2),(-2,2),(0,-3),(1,-3),(-1,-3),(2,-3),(-2,-3),
        (3,-2),(3,-1),(3,0),(3,1),(3,2),(2,3),(1,3),(0,3),(-1,3),(-2,3),
        (-3,2),(-3,1),(-3,0),(-3,-1),(-3,-2),(0,-4),(1,-4),(-1,-4),(2,-4),(-2,-4),
        (3,-3),(4,-2),(4,-1),(4,0),(4,1),(4,2),(3,3),(2,4),(1,4),(0,4),
        (-1,4),(-2,4),(-3,3),(-4,2),(-4,1),(-4,0),(-4,-1),(-4,-2),(-3,-3),
    ]

    static func image(time: Double, rgb: (CGFloat, CGFloat, CGFloat), height: CGFloat) -> NSImage {
        let cell = max(1, (height / 9).rounded(.down))
        let box = cell * 9
        let center = box / 2
        let img = NSImage(size: NSSize(width: box, height: box))
        img.lockFocus()
        NSGraphicsContext.current?.imageInterpolation = .none
        for (c, i) in offsets {
            let u = (Double(c * c + i * i)).squareRoot()
            let base: Double = u < 2.5 ? 0.4 : (u < 3.5 ? 0.2 : 0.06)
            let s = max(0.0, sin(0.0016 * time - 0.28 * u))
            let alpha = min(1.0, base + 0.65 * s * s)
            NSColor(srgbRed: rgb.0 / 255, green: rgb.1 / 255, blue: rgb.2 / 255, alpha: CGFloat(alpha)).setFill()
            let x = (center + CGFloat(c) * cell).rounded()
            let y = (center + CGFloat(i) * cell).rounded()
            NSBezierPath(rect: NSRect(x: x, y: y, width: cell, height: cell)).fill()
        }
        img.unlockFocus()
        img.isTemplate = false
        return img
    }
}

// ── Pixel "brew" loader (coffee cup + rising steam) — the idle animation ──────────────────────
// Ported from the supplied script. Its art color (#1a1a18) is near-black, so we render it as a
// template (white masked by the script's per-pixel alphas) and let the menu bar tint it to a
// visible foreground color.
enum Brew {
    static func image(time a: Double, barHeight: CGFloat) -> NSImage {
        let ncell: CGFloat = 4
        let padX: CGFloat = 1                   // horizontal breathing room
        let minX: CGFloat = -3, maxX: CGFloat = 5
        // Frame the box SYMMETRICALLY around the cup's center (yJS 1.5) so the cup lands on the
        // menu-bar text line. Steam rises above; equal empty rows below balance it.
        let frameTop: CGFloat = -4              // steam clipped above this
        let frameBottom: CGFloat = 7            // empty rows below -> cup centered (center of -4..7 = 1.5)
        let cols = Int(maxX - minX) + 1
        let rows = Int(frameBottom - frameTop) + 1
        let box = NSSize(width: (CGFloat(cols) + 2 * padX) * ncell, height: CGFloat(rows) * ncell)
        let img = NSImage(size: box)
        img.lockFocus()
        NSGraphicsContext.current?.imageInterpolation = .none

        func cell(_ x: CGFloat, _ y: CGFloat, _ alpha: Double) {
            if y < frameTop { return }
            NSColor(white: 1, alpha: CGFloat(min(1, max(0, alpha)))).setFill()
            let px = (((x - minX) + padX) * ncell).rounded()
            let py = ((frameBottom - y) * ncell).rounded()   // flip: steam (negative y) rises up
            NSBezierPath(rect: NSRect(x: px, y: py, width: ncell, height: ncell)).fill()
        }

        // Cup: body, rim, bottom, handle (static alphas).
        for y in 0...3 { for x in -3...3 { cell(CGFloat(x), CGFloat(y), 0.62) } }
        for x in -3...3 { cell(CGFloat(x), -1, 0.72) }
        for x in -2...2 { cell(CGFloat(x), 4, 0.65) }
        for (x, y) in [(4,0),(5,0),(5,1),(5,2),(5,3),(5,4),(4,4),(4,1),(4,3)] {
            cell(CGFloat(x), CGFloat(y), 0.58)
        }

        // Three wavering steam columns rising from the cup.
        let i = 7.0
        let columns: [(x: Double, speed: Double, ph: Double)] = [
            (-1.5, 0.00075, 0.0), (0.0, 0.0007, 2.2), (1.5, 0.0008, 4.4),
        ]
        for col in columns {
            let M = a * col.speed + col.ph
            let f = (sin(M) + 1) / 2
            let d = Int((f * i).rounded())
            if d < 0 { continue }
            for e in 0...d {
                let aa = Double(e) / i
                let u = 1.5 * sin(1.2 * M + aa * Double.pi * 1.8)
                let s = (1 - aa) * 0.48 * f
                if s <= 0.03 { continue }
                cell(CGFloat(col.x + u), CGFloat(-2 - e), s)
                if e > 0 {                                  // bridge horizontal gaps between puffs
                    let f2 = 1.5 * sin(1.2 * M + (aa - 1 / i) * Double.pi * 1.8)
                    if abs((u - f2).rounded()) > 1 {
                        cell(CGFloat(col.x + (u + f2) / 2), CGFloat(-2 - e), 0.65 * s)
                    }
                }
            }
        }
        img.unlockFocus()
        img.isTemplate = true
        // Use near-full bar height; the cup is centered in the box, so it aligns with the text line.
        let h = (barHeight - 2).rounded()
        img.size = NSSize(width: (h * box.width / box.height).rounded(), height: h)
        return img
    }
}

// ── Lucide "zap" (classic polygon), white template — the charging marker ──────────────────────
func lucideZap(height: CGFloat) -> NSImage {
    let pts: [(CGFloat, CGFloat)] = [(13,2),(3,14),(12,14),(11,22),(21,10),(12,10),(13,2)]
    let s = height / 24.0
    let img = NSImage(size: NSSize(width: (24 * s).rounded(), height: height))
    img.lockFocus()
    let p = NSBezierPath()
    for (i, pt) in pts.enumerated() {
        let q = NSPoint(x: pt.0 * s, y: (24 - pt.1) * s)
        if i == 0 { p.move(to: q) } else { p.line(to: q) }
    }
    p.close()
    NSColor.white.setFill(); p.fill()
    img.unlockFocus()
    img.isTemplate = true
    return img
}

// ── Sliding toggle switch for menu rows (ported from m1ckc3s/claude-status-bar) ───────────────
// NSSwitch can't show its accent inside a menu's vibrant window, so the track + knob are drawn as
// layers and the "on" color is filled explicitly; the knob slides on a spring.
final class ToggleView: NSView {
    static let w: CGFloat = 33, h: CGFloat = 16
    private let track = CALayer()
    private let knob = CALayer()
    private var lastToggle = Date.distantPast
    private var hovered = false
    var isOn: Bool { didSet { updateState(animated: true) } }
    var onToggle: ((Bool) -> Void)?

    init(isOn: Bool) {
        self.isOn = isOn
        super.init(frame: NSRect(x: 0, y: 0, width: ToggleView.w, height: ToggleView.h))
        layer = CALayer(); wantsLayer = true
        track.frame = bounds; track.cornerRadius = bounds.height / 2
        layer?.addSublayer(track)
        let kh = bounds.height - 4, kw = kh + 3
        knob.bounds = CGRect(x: 0, y: 0, width: kw, height: kh)
        knob.cornerRadius = kh / 2
        knob.backgroundColor = NSColor.white.cgColor
        layer?.addSublayer(knob)
        updateState(animated: false)
    }
    required init?(coder: NSCoder) { fatalError() }
    override var intrinsicContentSize: NSSize { NSSize(width: ToggleView.w, height: ToggleView.h) }

    private func knobCenter() -> CGPoint {
        let kw = knob.bounds.width
        return CGPoint(x: isOn ? bounds.width - kw / 2 - 2 : kw / 2 + 2, y: bounds.height / 2)
    }
    private func trackColor() -> CGColor {
        if isOn {
            let accent = NSColor.controlAccentColor
            return (hovered ? (accent.blended(withFraction: 0.10, of: .white) ?? accent) : accent).cgColor
        }
        let dark = effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        let base: CGFloat = dark ? 1.0 : 0.0
        let alpha: CGFloat = (dark ? 0.30 : 0.34) + (hovered ? 0.10 : 0)
        return NSColor(white: base, alpha: alpha).cgColor
    }
    private func updateState(animated: Bool) {
        let toColor = trackColor(), toPos = knobCenter()
        CATransaction.begin(); CATransaction.setDisableActions(true)
        if animated {
            let spring = CASpringAnimation(keyPath: "position")
            spring.fromValue = NSValue(point: knob.presentation()?.position ?? knob.position)
            spring.toValue = NSValue(point: toPos)
            spring.damping = 16; spring.stiffness = 260; spring.mass = 1; spring.initialVelocity = 0
            spring.duration = spring.settlingDuration
            knob.add(spring, forKey: "position")
            let col = CABasicAnimation(keyPath: "backgroundColor")
            col.fromValue = track.presentation()?.backgroundColor ?? track.backgroundColor
            col.toValue = toColor; col.duration = 0.2
            track.add(col, forKey: "backgroundColor")
        }
        knob.position = toPos; track.backgroundColor = toColor
        CATransaction.commit()
    }
    override func viewDidChangeEffectiveAppearance() { super.viewDidChangeEffectiveAppearance(); updateState(animated: false) }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect], owner: self))
    }
    override func mouseEntered(with event: NSEvent) { hovered = true; updateState(animated: false) }
    override func mouseExited(with event: NSEvent) { hovered = false; updateState(animated: false) }
    override func mouseDown(with event: NSEvent) {
        guard Date().timeIntervalSince(lastToggle) > 0.1 else { return }
        lastToggle = Date(); isOn.toggle(); onToggle?(isOn)
    }
}

// ── Parsed state ──────────────────────────────────────────────────────────────────────────────
struct Phone { var level: Int; var charging: Bool; var present: Bool; var stale: Bool; var source: String? }
struct Claude { var state: String; var label: String?; var tool: String?; var project: String?; var startedAt: Double }

// ── Controller ────────────────────────────────────────────────────────────────────────────────
final class Controller: NSObject, NSMenuDelegate {
    let phoneItem  = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let claudeItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

    let barH = NSStatusBar.system.thickness
    lazy var zapIcon: NSImage = lucideZap(height: (barH * 0.62).rounded())
    lazy var phoneIcon: NSImage? = {
        let img = NSImage(systemSymbolName: "iphone", accessibilityDescription: "iPhone")
        img?.isTemplate = true
        return img
    }()

    var bloomColor = COL_IDLE
    var idleMode = true                          // idle/offline -> brew loader; else -> bloom
    let started = Date()
    var pollTimer: Timer?
    var animTimer: Timer?

    var phone: Phone?
    var claude: Claude?
    var reachable = false

    var lastState: String?                       // for one-shot sound on transition
    var soundOn = UserDefaults.standard.object(forKey: "soundOn") as? Bool ?? true
    var showTimer = UserDefaults.standard.object(forKey: "showTimer") as? Bool ?? true

    var baseLabel = "—"                          // status text without the elapsed timer
    var claudeStartedAt = 0.0                    // unix start of the current busy run (0 = not busy)
    var lastTitleSec = -1

    func start() {
        phoneItem.menu = makeMenu()
        claudeItem.menu = makeMenu()
        phoneItem.button?.imagePosition = .imageLeft
        phoneItem.button?.image = phoneIcon
        phoneItem.button?.title = " …"
        claudeItem.button?.imagePosition = .imageLeft
        renderClaude()

        let p = Timer(timeInterval: POLL_SECONDS, repeats: true) { [weak self] _ in self?.poll() }
        RunLoop.main.add(p, forMode: .common); pollTimer = p; poll()
        let a = Timer(timeInterval: 1.0 / ANIM_FPS, repeats: true) { [weak self] _ in self?.animTick() }
        RunLoop.main.add(a, forMode: .common); animTimer = a
    }

    // ── networking ──
    func poll() {
        fetch("/battery") { [weak self] obj in
            guard let self = self else { return }
            if let obj = obj {
                self.reachable = true
                if let p = obj["phone"] as? [String: Any] {
                    self.phone = Phone(level: p["level"] as? Int ?? 0,
                                       charging: p["charging"] as? Bool ?? false,
                                       present: p["present"] as? Bool ?? false,
                                       stale: p["stale"] as? Bool ?? false,
                                       source: p["source"] as? String)
                } else { self.phone = nil }
            } else { self.reachable = false }
            DispatchQueue.main.async { self.renderPhone() }
        }
        fetch("/status") { [weak self] obj in
            guard let self = self else { return }
            if let obj = obj {
                self.claude = Claude(state: (obj["state"] as? String ?? "idle").lowercased(),
                                     label: obj["label"] as? String,
                                     tool: obj["tool"] as? String,
                                     project: obj["project"] as? String,
                                     startedAt: (obj["startedAt"] as? Double) ?? Double(obj["startedAt"] as? Int ?? 0))
            } else { self.claude = nil }
            DispatchQueue.main.async { self.renderClaude() }
        }
    }

    func fetch(_ path: String, _ done: @escaping ([String: Any]?) -> Void) {
        guard let url = URL(string: SERVER + path) else { return done(nil) }
        var req = URLRequest(url: url); req.timeoutInterval = 4
        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data = data,
                  let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            else { return done(nil) }
            done(obj)
        }.resume()
    }

    // ── rendering ──
    func renderPhone() {
        guard let b = phoneItem.button else { return }
        if !reachable {
            b.image = phoneIcon; b.title = " 4040?"
        } else if let p = phone, p.present {
            b.image = p.charging ? zapIcon : phoneIcon   // charging glyph replaces the phone
            b.title = " \(p.level)%"
        } else {
            b.image = phoneIcon; b.title = " —"
        }
    }

    func renderClaude() {
        let st = reachable ? (claude?.state ?? "idle") : "offline"
        switch st {
        case "thinking", "tool":      bloomColor = COL_CODING; idleMode = false
        case "waiting", "permission": bloomColor = COL_ALERT;  idleMode = false
        case "done":                  bloomColor = COL_DONE;   idleMode = false
        default:                      idleMode = true                 // idle / offline -> brew
        }
        // One-shot sound when the state transitions into "done" or "needs you".
        if st != lastState {
            if st == "done" { play("Glass") }
            else if st == "waiting" || st == "permission" { play("Ping") }
            lastState = st
        }
        baseLabel = reachable ? (claude?.label ?? claude?.state.capitalized ?? "—") : "offline"
        claudeStartedAt = reachable ? (claude?.startedAt ?? 0) : 0
        applyClaudeTitle()
    }

    func applyClaudeTitle() {
        var t = baseLabel
        if showTimer, claudeStartedAt > 0 {
            let e = Int(Date().timeIntervalSince1970 - claudeStartedAt)
            if e >= 0 { t += "  " + fmtElapsed(e) }
        }
        claudeItem.button?.title = " " + t
    }

    func fmtElapsed(_ s: Int) -> String {
        if s >= 3600 { return String(format: "%d:%02d:%02d", s / 3600, (s % 3600) / 60, s % 60) }
        if s >= 60 { return String(format: "%d:%02d", s / 60, s % 60) }
        return "\(s)s"
    }

    func play(_ name: String) {
        guard soundOn else { return }
        NSSound(named: NSSound.Name(name))?.play()
    }

    // Launch at login via SMAppService (macOS 13+). Registers this app bundle as a login item.
    var loginEnabled: Bool {
        if #available(macOS 13.0, *) { return SMAppService.mainApp.status == .enabled }
        return false
    }
    func setLogin(_ on: Bool) {
        if #available(macOS 13.0, *) {
            do { on ? try SMAppService.mainApp.register() : try SMAppService.mainApp.unregister() }
            catch { NSLog("login item error: \(error)") }
        }
    }

    func animTick() {
        let t = Date().timeIntervalSince(started) * 1000
        let h = (barH - 1).rounded()
        claudeItem.button?.image = idleMode
            ? Brew.image(time: t, barHeight: barH)
            : Bloom.image(time: t, rgb: bloomColor, height: h)

        // Advance the elapsed timer once per second while a run is active.
        if showTimer, claudeStartedAt > 0 {
            let sec = Int(Date().timeIntervalSince1970)
            if sec != lastTitleSec { lastTitleSec = sec; applyClaudeTitle() }
        }
    }

    // ── menu ──
    func makeMenu() -> NSMenu {
        let m = NSMenu(); m.delegate = self; m.autoenablesItems = false; return m
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()

        menu.addItem(header("iPhone"))
        if !reachable { menu.addItem(info("Server unreachable")) }
        else if let p = phone, p.present {
            var s = "\(p.level)%"
            if p.charging { s += " · charging" }
            if p.stale { s += " · stale" }
            if let src = p.source { s += " · \(src)" }
            menu.addItem(info(s))
        } else { menu.addItem(info("Unreachable")) }

        menu.addItem(header("Claude"))
        if let c = claude, reachable {
            var s = c.label ?? c.state.capitalized
            if c.state == "tool", let t = c.tool { s += " · \(t)" }
            if claudeStartedAt > 0 {
                let e = Int(Date().timeIntervalSince1970 - claudeStartedAt)
                if e >= 0 { s += " · \(fmtElapsed(e))" }
            }
            menu.addItem(info(s))
            if let proj = c.project, !proj.isEmpty { menu.addItem(info(proj)) }
        } else { menu.addItem(info("Offline")) }

        menu.addItem(header("Settings"))
        menu.addItem(toggleRow(title: "Show timer", isOn: showTimer) { [weak self] on in
            self?.showTimer = on
            UserDefaults.standard.set(on, forKey: "showTimer")
            self?.applyClaudeTitle()
        })
        menu.addItem(toggleRow(title: "Play sounds", isOn: soundOn) { [weak self] on in
            self?.soundOn = on
            UserDefaults.standard.set(on, forKey: "soundOn")
            if on { self?.play("Glass") }
        })
        if #available(macOS 13.0, *) {
            menu.addItem(toggleRow(title: "Start at login", isOn: loginEnabled) { [weak self] on in
                self?.setLogin(on)
            })
        }

        menu.addItem(.separator())
        menu.addItem(action("Open dashboard", #selector(openDashboard)))
        menu.addItem(action("Refresh now", #selector(refreshNow)))
        menu.addItem(.separator())
        let q = action("Quit", #selector(quit)); q.keyEquivalent = "q"; menu.addItem(q)
    }

    func header(_ title: String) -> NSMenuItem {
        if #available(macOS 14.0, *) { return NSMenuItem.sectionHeader(title: title) }
        let it = NSMenuItem(title: title, action: nil, keyEquivalent: ""); it.isEnabled = false; return it
    }

    func toggleRow(title: String, isOn: Bool, onToggle: @escaping (Bool) -> Void) -> NSMenuItem {
        let width: CGFloat = 250, height: CGFloat = 24, leftInset: CGFloat = 14, rightInset: CGFloat = 12
        let row = NSView(frame: NSRect(x: 0, y: 0, width: width, height: height))
        row.autoresizingMask = [.width]
        let label = NSTextField(labelWithString: title)
        label.font = NSFont.menuFont(ofSize: 0)
        label.sizeToFit()
        label.setFrameOrigin(NSPoint(x: leftInset, y: (height - label.frame.height) / 2))
        label.autoresizingMask = [.maxXMargin]
        row.addSubview(label)
        let toggle = ToggleView(isOn: isOn)
        toggle.onToggle = onToggle
        toggle.setFrameOrigin(NSPoint(x: width - toggle.frame.width - rightInset, y: (height - toggle.frame.height) / 2))
        toggle.autoresizingMask = [.minXMargin]
        row.addSubview(toggle)
        let item = NSMenuItem(); item.view = row; return item
    }

    func info(_ t: String) -> NSMenuItem {
        let it = NSMenuItem(title: t, action: nil, keyEquivalent: ""); it.isEnabled = false; return it
    }
    func action(_ t: String, _ sel: Selector) -> NSMenuItem {
        let it = NSMenuItem(title: t, action: sel, keyEquivalent: ""); it.target = self; it.isEnabled = true; return it
    }

    @objc func openDashboard() { if let u = URL(string: SERVER + "/battery") { NSWorkspace.shared.open(u) } }
    @objc func refreshNow() { poll() }
    @objc func quit() { NSApp.terminate(nil) }
}

// ── entry point ──
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = Controller()
controller.start()
app.run()

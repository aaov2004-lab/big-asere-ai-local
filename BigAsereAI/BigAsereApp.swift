import AppKit
import WebKit
import Foundation

// Big Asere AI — ventana nativa creada a partir de codigo fuente local en Xcode.
// El servicio Python y Ollama solo trabajan sobre el loopback 127.0.0.1.
@MainActor
final class BigAsereApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var backend: Process?
    private var localOrigin: String?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let rect = NSRect(x: 0, y: 0, width: 1260, height: 810)
        window = NSWindow(contentRect: rect,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Big Asere AI"
        window.minSize = NSSize(width: 850, height: 570)
        window.center()
        window.delegate = self
        window.setFrameAutosaveName("BigAsereAIWindow")
        window.backgroundColor = NSColor(calibratedRed: 0.05, green: 0.06, blue: 0.09, alpha: 1)

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()   // Cookies de sesion en memoria.
        webView = WKWebView(frame: rect, configuration: config)
        webView.uiDelegate = self
        webView.navigationDelegate = self
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        showStatus("Iniciando la IA local…")
        launchBackend()
    }

    private func showStatus(_ message: String) {
        let safe = message.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        let page = """
        <!doctype html><html lang="es"><head><meta charset="UTF-8"></head>
        <body style="margin:0;background:#0c0e15;display:grid;place-items:center;height:100vh;font-family:-apple-system,sans-serif;color:#f1f2f5">
        <div style="text-align:center;max-width:560px;padding:24px"><div style="font-weight:800;font-size:36px;color:#e23744;margin-bottom:18px">BA ✦</div>
        <div style="font-size:16px">\(safe)</div><div style="font-size:12px;color:#9296a5;margin-top:20px">Big Asere AI · Privada en tu Mac</div></div></body></html>
        """
        webView.loadHTMLString(page, baseURL: nil)
    }

    private func launchBackend() {
        guard let resources = Bundle.main.resourceURL else {
            showStatus("No se encuentran los recursos de la aplicación.")
            return
        }
        let script = resources.appendingPathComponent("server.py")
        guard FileManager.default.fileExists(atPath: script.path) else {
            showStatus("Falta server.py. Verifica que los recursos estén incluidos en el proyecto Xcode.")
            return
        }
        let pythonPaths = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        guard let python = pythonPaths.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            showStatus("Falta Python 3. Instala Python y vuelve a abrir la app. Ollama no ha sido modificado.")
            return
        }
        let task = Process()
        task.executableURL = URL(fileURLWithPath: python)
        task.arguments = ["-u", script.path]
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env.removeValue(forKey: "BIGASERE_OLLAMA_URL")
        task.environment = env
        let stdout = Pipe()
        let stderr = Pipe()
        task.standardOutput = stdout
        task.standardError = stderr
        backend = task
        do { try task.run() } catch {
            showStatus("No se pudo iniciar el servidor local: \(error.localizedDescription)")
            return
        }
        // El servidor imprime READY <puerto> <token> en el primer renglon.
        // Se lee sin bloquear el hilo principal de la interfaz.
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let pipe = stdout.fileHandleForReading
            var line = Data()
            while line.count < 256 {
                let byte = pipe.readData(ofLength: 1)
                if byte.isEmpty || byte[0] == 10 { break }
                line.append(byte)
            }
            let value = String(data: line, encoding: .utf8) ?? ""
            let parts = value.split(separator: " ").map(String.init)
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }
                if parts.count == 3, parts[0] == "READY",
                    let port = Int(parts[1]), (1...65535).contains(port),
                    parts[2].count > 20,
                    let url = URL(string: "http://127.0.0.1:\(port)/launch?token=\(parts[2])") {
                    self.localOrigin = "http://127.0.0.1:\(port)"
                    self.webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
                } else {
                    self.showStatus("El servidor local no pudo iniciar. Comprueba Python 3 y vuelve a ejecutar la app desde Xcode para ver el error.")
                }
            }
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        // Se permiten la pantalla interna de inicio (about:blank) y las URLs del mismo servidor.
        if url.scheme == "about" || "\(url.scheme ?? "")://\(url.host ?? ""):\(url.port ?? 0)" == localOrigin {
            decisionHandler(.allow)
            return
        }
        // Nunca se cargan sitios remotos dentro de la app.
        if navigationAction.navigationType == .linkActivated, ["http", "https"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = "Big Asere AI"
        alert.informativeText = message
        alert.addButton(withTitle: "Aceptar")
        alert.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = "Big Asere AI · Confirmación"
        alert.informativeText = message
        alert.addButton(withTitle: "Continuar")
        alert.addButton(withTitle: "Cancelar")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.messageText = "Big Asere AI"
        alert.informativeText = prompt
        alert.addButton(withTitle: "Guardar")
        alert.addButton(withTitle: "Cancelar")
        let field = NSTextField(string: defaultText ?? "")
        field.frame = NSRect(x: 0, y: 0, width: 340, height: 24)
        alert.accessoryView = field
        completionHandler(alert.runModal() == .alertFirstButtonReturn ? field.stringValue : nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        if let task = backend, task.isRunning { task.terminate() }
    }
}

// Punto de entrada explícito; necesario en Xcode 26.2 con comprobación
// de aislamiento del actor principal. No ejecuta acciones sobre Big Asere.
@main
struct BigAsereMain {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = BigAsereApp()
        app.delegate = delegate
        app.run()
    }
}

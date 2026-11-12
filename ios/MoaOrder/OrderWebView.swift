import SwiftUI
import WebKit

final class BrowserState: ObservableObject {
    weak var webView: WKWebView?
    @Published var message: String?
    @Published var download: SharedDownload?

    func whenIdle(_ action: @escaping () -> Void) {
        guard let webView else { action(); return }
        webView.evaluateJavaScript("typeof busy === 'function' && busy()") { result, _ in
            if result as? Bool == true { self.message = "녹음이나 분석이 끝난 뒤 다시 시도해 주세요." }
            else { action() }
        }
    }
    func reloadWhenIdle() { whenIdle { self.webView?.reload() } }
}

struct OrderWebView: UIViewRepresentable {
    let url: URL
    let state: BrowserState
    func makeCoordinator() -> Coordinator { Coordinator(origin: url, state: state) }
    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator; view.uiDelegate = context.coordinator
        view.allowsBackForwardNavigationGestures = false
        view.isOpaque = false
        view.backgroundColor = UIColor(red: 0.96, green: 0.97, blue: 0.95, alpha: 1)
        state.webView = view
        view.load(URLRequest(url: url))
        return view
    }
    func updateUIView(_ view: WKWebView, context: Context) {}
    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.stopLoading(); view.navigationDelegate = nil; view.uiDelegate = nil
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        let origin: URL
        let state: BrowserState
        private var downloads: [ObjectIdentifier: URL] = [:]
        init(origin: URL, state: BrowserState) { self.origin = origin; self.state = state }
        func sameOrigin(_ url: URL?) -> Bool {
            guard let url else { return false }
            return url.scheme == "https" && url.host?.lowercased() == origin.host?.lowercased() && (url.port ?? 443) == (origin.port ?? 443)
        }
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if sameOrigin(navigationAction.request.url) {
                decisionHandler(navigationAction.shouldPerformDownload ? .download : .allow)
            } else {
                if navigationAction.navigationType == .linkActivated, let url = navigationAction.request.url,
                   ["https", "http"].contains(url.scheme ?? "") { UIApplication.shared.open(url) }
                decisionHandler(.cancel)
            }
        }
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = navigationAction.request.url, ["https", "http"].contains(url.scheme ?? "") {
                if sameOrigin(url) { webView.load(navigationAction.request) }
                else { UIApplication.shared.open(url) }
            }
            return nil
        }
        func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            let allowed = type == .microphone && frame.isMainFrame && origin.protocol == "https"
                && origin.host.lowercased() == self.origin.host?.lowercased()
                && (origin.port == 0 ? 443 : origin.port) == (self.origin.port ?? 443)
            decisionHandler(allowed ? .prompt : .deny)
        }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            if (error as NSError).code != NSURLErrorCancelled { state.message = "서버에 연결하지 못했어요. 주소, 인터넷 연결, 인증서 신뢰 설정을 확인해 주세요." }
        }
        func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            guard sameOrigin(navigationResponse.response.url) else { decisionHandler(.cancel); return }
            let attachment = (navigationResponse.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")?.lowercased().hasPrefix("attachment") == true
            decisionHandler(attachment || !navigationResponse.canShowMIMEType ? .download : .allow)
        }
        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
            guard sameOrigin(response.url) else { completionHandler(nil); return }
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let destination = folder.appendingPathComponent("order-result.json")
                downloads[ObjectIdentifier(download)] = destination; completionHandler(destination)
            } catch { state.message = "주문 파일을 저장하지 못했어요."; completionHandler(nil) }
        }
        func downloadDidFinish(_ download: WKDownload) {
            if let url = downloads.removeValue(forKey: ObjectIdentifier(download)) { state.download = SharedDownload(url: url) }
        }
        func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
            if let url = downloads.removeValue(forKey: ObjectIdentifier(download)) { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
            state.message = "다운로드에 실패했어요. 다시 시도해 주세요."
        }
    }
}

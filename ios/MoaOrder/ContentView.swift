import SwiftUI
import WebKit

struct ContentView: View {
    @AppStorage("serverOrigin") private var serverOrigin = ""
    @State private var link = ""
    @State private var launchURL: URL?
    @State private var error = ""
    @StateObject private var browser = BrowserState()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            Group {
                if let url = launchURL {
                    OrderWebView(url: url, state: browser)
                        .toolbar {
                            ToolbarItem(placement: .navigationBarLeading) {
                                Button("연결 설정") { changeConnection() }
                            }
                            ToolbarItem(placement: .navigationBarTrailing) {
                                Button { browser.reloadWhenIdle() } label: { Image(systemName: "arrow.clockwise") }
                                    .accessibilityLabel("새로고침")
                            }
                        }
                } else {
                    Form {
                        Section {
                            Label("가는 동안, 주문을 모아요", systemImage: "bubble.left.and.bubble.right.fill")
                                .font(.headline)
                            Text("매장 선택 → 녹음 → 사람별 최종 주문을 확인하세요.")
                        }
                        Section("모아오더 접속 링크") {
                            SecureField("https://…/#key=…", text: $link)
                                .textInputAutocapitalization(.never).autocorrectionDisabled()
                                .keyboardType(.URL)
                            Button("연결하기") { connect() }
                            if !error.isEmpty { Text(error).foregroundStyle(.red) }
                        }
                        Section {
                            Text("현재 버전은 연결된 서버에서 음성을 분석합니다. iPhone 단독 분석은 포함하지 않습니다.")
                            Text("녹음 중에는 이 앱을 화면에 열어 두세요. 다른 앱으로 이동하면 녹음을 종료하고 저장을 시도합니다.")
                        }
                    }
                }
            }
            .navigationTitle("모아오더")
            .navigationBarTitleDisplayMode(.inline)
            .tint(Color(red: 0.09, green: 0.36, blue: 0.28))
            .alert("확인해 주세요", isPresented: Binding(get: { browser.message != nil }, set: { if !$0 { browser.message = nil } })) {
                Button("확인", role: .cancel) { browser.message = nil }
            } message: { Text(browser.message ?? "") }
            .sheet(item: $browser.download) { item in ShareFile(url: item.url) }
        }
        .onAppear {
            if launchURL == nil, let saved = URL(string: serverOrigin), saved.scheme == "https", saved.host != nil {
                launchURL = saved
            }
        }
        .onChange(of: scenePhase) { phase in
            UIApplication.shared.isIdleTimerDisabled = phase == .active && launchURL != nil
            if phase == .background {
                browser.webView?.evaluateJavaScript("if (typeof phase !== 'undefined' && phase === 'recording') stopRecording();", completionHandler: nil)
            }
        }
        .onChange(of: launchURL) { value in UIApplication.shared.isIdleTimerDisabled = value != nil }
    }

    private func connect() {
        guard var components = URLComponents(string: link.trimmingCharacters(in: .whitespacesAndNewlines)),
              components.scheme == "https", let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil else {
            error = "HTTPS로 시작하는 서버 접속 링크를 입력해 주세요."; return
        }
        components.path = "/"; components.query = nil
        guard let url = components.url else { error = "접속 링크를 확인해 주세요."; return }
        components.fragment = nil
        // Save only the server address; the key stays in memory until web pairing.
        serverOrigin = components.url!.absoluteString
        error = ""; link = ""; launchURL = url
    }

    private func changeConnection() {
        browser.whenIdle {
            launchURL = nil; serverOrigin = ""; browser.webView = nil
        }
    }
}

struct SharedDownload: Identifiable {
    let id = UUID()
    let url: URL
}

struct ShareFile: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        controller.completionWithItemsHandler = { _, _, _, _ in try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        return controller
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

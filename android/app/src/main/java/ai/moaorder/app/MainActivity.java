package ai.moaorder.app;

import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.os.Environment;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.webkit.*;
import android.widget.*;
import java.io.OutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.*;

/** Server-connected client. Model weights and inference stay on the GPU server. */
public final class MainActivity extends Activity {
    private static final String HOME = "https://udder-purify-retract.ngrok-free.dev/";
    private static final String HOST = "udder-purify-retract.ngrok-free.dev";
    private static final int MIC = 101, LOCATION = 102, PICK_AUDIO = 103, SAVE_FILE = 104;
    private WebView web;
    private ProgressBar progress;
    private LinearLayout errorPanel;
    private PermissionRequest microphone;
    private GeolocationPermissions.Callback locationCallback;
    private String locationOrigin;
    private ValueCallback<Uri[]> fileCallback;
    private byte[] pendingDownload;

    private boolean trusted(String url) {
        if (url == null) return false;
        Uri u = Uri.parse(url);
        return "https".equals(u.getScheme()) && HOST.equals(u.getHost())
            && (u.getPort() == -1 || u.getPort() == 443) && u.getUserInfo() == null;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (android.os.Build.VERSION.SDK_INT >= 27) getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.WHITE);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(-1, -1));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        root.addView(progress, new FrameLayout.LayoutParams(-1, 8, Gravity.TOP));
        errorPanel = new LinearLayout(this);
        errorPanel.setOrientation(LinearLayout.VERTICAL);
        errorPanel.setGravity(Gravity.CENTER);
        errorPanel.setPadding(48, 48, 48, 48);
        errorPanel.setBackgroundColor(Color.WHITE);
        TextView message = new TextView(this);
        message.setText("모아오더에 연결할 수 없어요\n인터넷 연결과 서버 상태를 확인해 주세요.");
        message.setTextSize(18); message.setGravity(Gravity.CENTER); message.setTextColor(Color.rgb(0,44,95));
        errorPanel.addView(message);
        Button retry = new Button(this); retry.setText("다시 연결"); retry.setOnClickListener(v -> loadHome());
        errorPanel.addView(retry);
        root.addView(errorPanel, new FrameLayout.LayoutParams(-1,-1));
        errorPanel.setVisibility(View.GONE);
        setContentView(root);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true); // Android document picker audio streams.
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setGeolocationEnabled(true);
        settings.setSupportMultipleWindows(false);
        settings.setSafeBrowsingEnabled(true);
        settings.setUserAgentString(settings.getUserAgentString() + " MoaOrder/1.0");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.addJavascriptInterface(new Downloads(), "MoaDownloads");
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                // Tunnel interstitials must not replace CSS/JS/API responses in WebView.
                if (!trusted(r.getUrl().toString()) || !"GET".equals(r.getMethod())) return null;
                try {
                    HttpURLConnection c = (HttpURLConnection)new URL(r.getUrl().toString()).openConnection();
                    c.setConnectTimeout(20000); c.setReadTimeout(30000); c.setInstanceFollowRedirects(false);
                    for(Map.Entry<String,String> h:r.getRequestHeaders().entrySet()) {
                        if(!h.getKey().equalsIgnoreCase("Accept-Encoding")) c.setRequestProperty(h.getKey(),h.getValue());
                    }
                    c.setRequestProperty("Accept-Encoding","identity");
                    c.setRequestProperty("ngrok-skip-browser-warning","true");
                    String cookie=CookieManager.getInstance().getCookie(r.getUrl().toString());
                    if(cookie!=null)c.setRequestProperty("Cookie",cookie);
                    int status=c.getResponseCode();
                    Map<String,String> headers=new HashMap<>();
                    for(Map.Entry<String,List<String>> h:c.getHeaderFields().entrySet()) {
                        if(h.getKey()==null)continue;
                        if(h.getKey().equalsIgnoreCase("Set-Cookie")) {
                            for(String value:h.getValue())CookieManager.getInstance().setCookie(r.getUrl().toString(),value);
                        } else headers.put(h.getKey(),String.join(", ",h.getValue()));
                    }
                    String type=c.getContentType();
                    String mime=type==null?"application/octet-stream":type.split(";")[0];
                    InputStream stream=status>=400?c.getErrorStream():c.getInputStream();
                    return new WebResourceResponse(mime,"UTF-8",status,c.getResponseMessage()==null?"Response":c.getResponseMessage(),headers,stream);
                } catch(Exception e) { return null; }
            }
            @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                String url = r.getUrl().toString();
                if (trusted(url)) return false;
                if (r.isForMainFrame() && r.hasGesture() && ("https".equals(r.getUrl().getScheme()) || "http".equals(r.getUrl().getScheme()))) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, r.getUrl())); } catch (Exception e) { toast("링크를 열 수 없어요."); }
                }
                return true;
            }
            @Override public void onPageStarted(WebView v, String url, android.graphics.Bitmap icon) { progress.setVisibility(View.VISIBLE); }
            @Override public void onPageFinished(WebView v, String url) {
                progress.setVisibility(View.GONE);
                CookieManager.getInstance().flush();
                if (!trusted(url)) return;
                v.evaluateJavascript("document.getElementById('installGuide')?.remove()", null);
                // The web app exports result JSON and recordings via blob URLs.
                v.evaluateJavascript("(function(){if(window.moaDownloadHook)return;window.moaDownloadHook=true;document.addEventListener('click',async function(e){var a=e.target.closest&&e.target.closest('a');if(!a||!a.href.startsWith('blob:'))return;e.preventDefault();try{var b=await(await fetch(a.href)).blob();if(b.size>32*1024*1024){alert('저장 가능한 파일 크기를 초과했어요.');return;}var r=new FileReader();r.onload=function(){MoaDownloads.save(r.result,a.download||'moaorder-result',b.type||'application/octet-stream');};r.readAsDataURL(b);}catch(err){alert('파일을 저장할 수 없어요.');}},true);})()", null);
            }
            @Override public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) { if(r.isForMainFrame()) showError(); }
            @Override public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse e) { if(r.isForMainFrame() && e.getStatusCode()>=400) showError(); }
            @Override public void onReceivedSslError(WebView v, SslErrorHandler h, SslError e) { h.cancel(); showError(); }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView v, int value) { progress.setProgress(value); }
            @Override public void onPermissionRequest(PermissionRequest r) {
                runOnUiThread(() -> {
                    if (!trusted(r.getOrigin().toString()) || !trusted(web.getUrl()) || !Arrays.asList(r.getResources()).contains(PermissionRequest.RESOURCE_AUDIO_CAPTURE)) { r.deny(); return; }
                    if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED) {
                        r.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                    } else {
                        if (microphone!=null) microphone.deny();
                        microphone=r; requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, MIC);
                    }
                });
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest r) { if(microphone==r) microphone=null; }
            @Override public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                if(!trusted(origin) || !trusted(web.getUrl())) { callback.invoke(origin,false,false); return; }
                if(checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)==PackageManager.PERMISSION_GRANTED) { callback.invoke(origin,true,false); return; }
                if(locationCallback!=null) locationCallback.invoke(locationOrigin,false,false);
                locationCallback=callback; locationOrigin=origin;
                requestPermissions(new String[]{Manifest.permission.ACCESS_COARSE_LOCATION,Manifest.permission.ACCESS_FINE_LOCATION},LOCATION);
            }
            @Override public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if(!trusted(v.getUrl())) { callback.onReceiveValue(null); return true; }
                if(fileCallback!=null) fileCallback.onReceiveValue(null);
                fileCallback=callback;
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("audio/*").addCategory(Intent.CATEGORY_OPENABLE);
                try { startActivityForResult(pick,PICK_AUDIO); } catch(Exception e) { fileCallback.onReceiveValue(null);fileCallback=null;toast("파일 선택기를 열 수 없어요."); }
                return true;
            }
        });
        web.setDownloadListener((url, agent, disposition, mime, length) -> {
            if(!trusted(url) || !trusted(web.getUrl())) return;
            try {
                DownloadManager.Request r=new DownloadManager.Request(Uri.parse(url));
                String cookies=CookieManager.getInstance().getCookie(url);
                if(cookies!=null) r.addRequestHeader("Cookie",cookies);
                r.addRequestHeader("ngrok-skip-browser-warning","true");
                r.setMimeType(mime);r.setTitle("모아오더 파일");
                r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS,URLUtil.guessFileName(url,disposition,mime));
                r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                ((DownloadManager)getSystemService(DOWNLOAD_SERVICE)).enqueue(r);
                toast("다운로드를 시작했어요.");
            } catch(Exception e) { toast("파일을 다운로드할 수 없어요."); }
        });
        // Do not restore arbitrary navigation or embed an access key in the APK.
        loadHome();
    }
    private void loadHome() { errorPanel.setVisibility(View.GONE); progress.setVisibility(View.VISIBLE); web.loadUrl(HOME,Collections.singletonMap("ngrok-skip-browser-warning","true")); }
    private void showError() { progress.setVisibility(View.GONE);errorPanel.setVisibility(View.VISIBLE); }
    private void toast(String s) { Toast.makeText(this,s,Toast.LENGTH_LONG).show(); }
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(code,permissions,results);
        if(code==MIC && microphone!=null) {
            if(results.length>0 && results[0]==PackageManager.PERMISSION_GRANTED && trusted(web.getUrl())) microphone.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            else { microphone.deny(); toast("녹음하려면 마이크 권한을 허용해 주세요. 파일 업로드는 계속 사용할 수 있어요."); }
            microphone=null;
        }
        if(code==LOCATION && locationCallback!=null) {
            locationCallback.invoke(locationOrigin,checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)==PackageManager.PERMISSION_GRANTED,false);
            locationCallback=null;
        }
    }
    public final class Downloads {
        @JavascriptInterface public void save(String data,String name,String mime) {
            if(data==null || data.length()>46*1024*1024 || !data.startsWith("data:")) return;
            runOnUiThread(() -> {
                if(!trusted(web.getUrl()) || pendingDownload!=null) return;
                try {
                    int comma=data.indexOf(',');if(comma<0)return;
                    pendingDownload=Base64.decode(data.substring(comma+1),Base64.DEFAULT);
                    if(pendingDownload.length>32*1024*1024) {pendingDownload=null;return;}
                    String safeName=name==null?"moaorder-result":name.replaceAll("[^가-힣a-zA-Z0-9._-]","_");
                    Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                        .setType(mime!=null && mime.contains("/")?mime:"application/octet-stream").putExtra(Intent.EXTRA_TITLE,safeName);
                    startActivityForResult(intent,SAVE_FILE);
                } catch(Exception e) {pendingDownload=null;toast("저장할 수 없어요.");}
            });
        }
    }
    @Override protected void onActivityResult(int code,int result,Intent data) {
        super.onActivityResult(code,result,data);
        if(code==PICK_AUDIO && fileCallback!=null) {
            Uri uri=result==RESULT_OK && data!=null?data.getData():null;
            fileCallback.onReceiveValue(uri!=null && "content".equals(uri.getScheme())?new Uri[]{uri}:null);fileCallback=null;
        }
        if(code==SAVE_FILE) {
            byte[] bytes=pendingDownload;pendingDownload=null;
            if(result==RESULT_OK && data!=null && data.getData()!=null && bytes!=null) {
                try(OutputStream out=getContentResolver().openOutputStream(data.getData())) { if(out!=null) {out.write(bytes);toast("저장했어요.");} }
                catch(Exception e) {toast("저장하지 못했어요.");}
            }
        }
    }
    @Override public void onBackPressed() { if(errorPanel.getVisibility()==View.VISIBLE) {super.onBackPressed();} else if(web.canGoBack())web.goBack();else super.onBackPressed(); }
    @Override protected void onDestroy() {
        if(microphone!=null)microphone.deny();
        if(fileCallback!=null)fileCallback.onReceiveValue(null);
        if(locationCallback!=null)locationCallback.invoke(locationOrigin,false,false);
        web.removeJavascriptInterface("MoaDownloads");web.destroy();super.onDestroy();
    }
}

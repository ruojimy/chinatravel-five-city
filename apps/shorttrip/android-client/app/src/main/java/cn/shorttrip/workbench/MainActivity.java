package cn.shorttrip.workbench;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.print.PrintManager;
import android.text.InputType;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.CookieManager;
import android.webkit.WebMessage;
import android.webkit.WebMessagePort;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** Thin client: all planning and data live on the shared ShortTrip server (GaussDB + accounts). */
public final class MainActivity extends Activity {
    private static final int SAVE_JSON = 2;
    private static final String TAG = "ShortTrip";
    private static final String SERVER = "server_url";
    private static final String PAGE = "page";
    private FrameLayout content;
    private WebView web;
    private WebMessagePort port;
    private Uri origin;
    private byte[] pendingExport;

    @Override
    protected void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        getWindow().setStatusBarColor(Color.WHITE);
        getWindow().setNavigationBarColor(Color.WHITE);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                | (Build.VERSION.SDK_INT >= 26 ? View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR : 0));
        content = new FrameLayout(this);
        content.setBackgroundColor(Color.WHITE);
        if (Build.VERSION.SDK_INT >= 35) {
            content.setOnApplyWindowInsetsListener((view, insets) -> {
                android.graphics.Insets safe = insets.getInsets(WindowInsets.Type.systemBars()
                        | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                view.setPadding(safe.left, safe.top, safe.right, safe.bottom);
                return insets;
            });
        }
        setContentView(content);
        start();
    }

    private SharedPreferences settings() {
        return getSharedPreferences("shorttrip", Context.MODE_PRIVATE);
    }

    private String serverUrl() {
        String saved = settings().getString(SERVER, "");
        return saved.isEmpty() ? BuildConfig.DEFAULT_SERVER : saved;
    }

    private void start() {
        String server = serverUrl();
        if (server.isEmpty()) {
            showStatus("请先填写 ShortTrip 服务器地址。", true);
            openServerSettings();
            return;
        }
        open(server);
    }

    private void showStatus(String message, boolean actions) {
        closeWeb();
        content.removeAllViews();
        LinearLayout status = new LinearLayout(this);
        status.setOrientation(LinearLayout.VERTICAL);
        status.setGravity(Gravity.CENTER);
        status.setPadding(dp(28), dp(28), dp(28), dp(28));
        TextView label = new TextView(this);
        label.setText(message);
        label.setTextSize(16);
        label.setGravity(Gravity.CENTER);
        label.setPadding(0, 0, 0, dp(16));
        status.addView(label);
        if (actions) {
            Button retry = new Button(this);
            retry.setText("重试");
            retry.setOnClickListener(view -> start());
            status.addView(retry);
            Button server = new Button(this);
            server.setText("服务器设置");
            server.setOnClickListener(view -> openServerSettings());
            status.addView(server);
        }
        content.addView(status, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
    }

    private void open(String server) {
        closeWeb();
        origin = Uri.parse(server);
        web = new WebView(this);
        web.setBackgroundColor(Color.WHITE);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setUserAgentString(web.getSettings().getUserAgentString()
                + " ShortTripAndroid/" + BuildConfig.VERSION_NAME);
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (!request.isForMainFrame() || local(uri)) {
                    return false;
                }
                if ("https".equalsIgnoreCase(uri.getScheme()) || "http".equalsIgnoreCase(uri.getScheme())) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, uri));
                    } catch (ActivityNotFoundException error) {
                        toast("没有可打开此链接的浏览器");
                    }
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (view == web && local(Uri.parse(url))) {
                    content.removeView(content.findViewWithTag("connecting"));
                    attachMessagePort(view);
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && view == web) {
                    showStatus("连不上服务器 " + server + "\n请确认电脑上的 ShortTrip 服务已启动，且手机和电脑在同一网络。", true);
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse error) {
                if (request.isForMainFrame() && view == web && error.getStatusCode() >= 500) {
                    showStatus("服务器暂时出错（" + error.getStatusCode() + "）。请稍后重试。", true);
                }
            }

            @Override
            public void doUpdateVisitedHistory(WebView view, String url, boolean reload) {
                rememberPage(Uri.parse(url));
            }
        });
        content.removeAllViews();
        content.addView(web, new FrameLayout.LayoutParams(-1, -1));
        // Covers the blank WebView until the first page arrives (a LAN timeout can take ~30 s).
        LinearLayout connecting = new LinearLayout(this);
        connecting.setTag("connecting");
        connecting.setOrientation(LinearLayout.VERTICAL);
        connecting.setGravity(Gravity.CENTER);
        connecting.setBackgroundColor(Color.WHITE);
        connecting.addView(new android.widget.ProgressBar(this));
        TextView label = new TextView(this);
        label.setText("正在连接 " + server + " …");
        label.setPadding(dp(24), dp(16), dp(24), 0);
        label.setGravity(Gravity.CENTER);
        connecting.addView(label);
        content.addView(connecting, new FrameLayout.LayoutParams(-1, -1));
        web.loadUrl(server + settings().getString(PAGE, "/?new=1"));
    }

    private boolean local(Uri uri) {
        return origin != null && uri.getScheme() != null
                && uri.getScheme().equalsIgnoreCase(origin.getScheme())
                && uri.getHost() != null && uri.getHost().equalsIgnoreCase(origin.getHost())
                && uri.getPort() == origin.getPort();
    }

    private void attachMessagePort(WebView view) {
        if (port != null) port.close();
        WebMessagePort[] channel = view.createWebMessageChannel();
        port = channel[0];
        port.setWebMessageCallback(new WebMessagePort.WebMessageCallback() {
            @Override
            public void onMessage(WebMessagePort sender, WebMessage message) {
                if (sender != port || web != view) return;
                String data = message.getData();
                if (data == null || data.length() > 8_000_000) return;
                try {
                    JSONObject request = new JSONObject(data);
                    switch (request.getString("action")) {
                        case "settings":
                            openServerSettings();
                            break;
                        case "export":
                            exportJson(request.getString("name"), request.getString("text"));
                            break;
                        case "print":
                            PrintManager printer = (PrintManager) getSystemService(Context.PRINT_SERVICE);
                            printer.print("ShortTrip 行程", view.createPrintDocumentAdapter("ShortTrip 行程"), null);
                            break;
                        default:
                            break;
                    }
                } catch (JSONException error) {
                    Log.w(TAG, "Invalid Workbench message");
                }
            }
        });
        view.postWebMessage(new WebMessage("shorttrip-android", new WebMessagePort[]{channel[1]}),
                Uri.parse(origin.getScheme() + "://" + origin.getAuthority()));
    }

    private void openServerSettings() {
        LinearLayout fields = new LinearLayout(this);
        fields.setOrientation(LinearLayout.VERTICAL);
        fields.setPadding(dp(24), dp(8), dp(24), 0);
        EditText address = new EditText(this);
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setSingleLine(true);
        address.setHint("http://192.168.1.10:8790");
        address.setText(serverUrl());
        fields.addView(address);
        new AlertDialog.Builder(this)
                .setTitle("ShortTrip 服务器")
                .setMessage("填写电脑上 ShortTrip 服务启动时显示的“手机/局域网访问”地址。账号和行程保存在服务器的数据库里。")
                .setView(fields)
                .setNegativeButton("取消", null)
                .setPositiveButton("保存并连接", (dialog, which) -> {
                    String value = address.getText().toString().trim();
                    while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
                    Uri parsed = Uri.parse(value);
                    if (!("http".equals(parsed.getScheme()) || "https".equals(parsed.getScheme()))
                            || parsed.getHost() == null) {
                        toast("地址需以 http:// 或 https:// 开头");
                        return;
                    }
                    String changed = parsed.getScheme() + "://" + parsed.getAuthority();
                    boolean other = !changed.equals(serverUrl());
                    SharedPreferences.Editor edit = settings().edit().putString(SERVER, changed);
                    if (other) edit.remove(PAGE);
                    edit.apply();
                    open(changed);
                })
                .show();
    }

    private void exportJson(String filename, String json) {
        if (pendingExport != null) return;
        pendingExport = json.getBytes(StandardCharsets.UTF_8);
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.setType("application/json");
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.putExtra(Intent.EXTRA_TITLE, filename.replaceAll("[^A-Za-z0-9_.-]", "_"));
        try {
            startActivityForResult(intent, SAVE_JSON);
        } catch (ActivityNotFoundException error) {
            pendingExport = null;
            toast("系统未提供文件保存界面");
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != SAVE_JSON) return;
        byte[] export = pendingExport;
        pendingExport = null;
        if (result != RESULT_OK || export == null || data == null || data.getData() == null) return;
        try (OutputStream output = getContentResolver().openOutputStream(data.getData(), "wt")) {
            if (output == null) throw new IOException("No output");
            output.write(export);
            toast("已保存行程 JSON");
        } catch (IOException | SecurityException error) {
            toast("无法保存行程 JSON");
        }
    }

    private void rememberPage(Uri page) {
        if (!local(page)) return;
        String path = page.getPath();
        if ("/".equals(path) || "/index.html".equals(path)) {
            String query = page.getEncodedQuery();
            settings().edit().putString(PAGE, "/" + (query == null ? "" : "?" + query)).apply();
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        closeWeb();
        super.onDestroy();
    }

    private void closeWeb() {
        if (port != null) {
            port.close();
            port = null;
        }
        if (web != null) {
            content.removeView(web);
            web.destroy();
            web = null;
        }
    }

    private int dp(int size) {
        return (int) (size * getResources().getDisplayMetrics().density + 0.5f);
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }
}

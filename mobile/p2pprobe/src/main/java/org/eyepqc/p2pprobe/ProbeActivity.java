package org.eyepqc.p2pprobe;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** Isolated synthetic probe, no JavaScript bridge, USB, credentials or production protocol. */
public final class ProbeActivity extends Activity {
    private WebView web;
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        web=new WebView(this);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,android.webkit.WebResourceRequest request){return true;}
        });
        setContentView(web);
        // A fixed bundled page; do not load remote pages or add a native JS bridge.
        try(java.io.InputStream input=getAssets().open("probe.html")){
            java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();
            byte[] buffer=new byte[4096];int n;
            while((n=input.read(buffer))!=-1)bytes.write(buffer,0,n);
            web.loadDataWithBaseURL("https://p2p-probe.invalid/",new String(bytes.toByteArray(),java.nio.charset.StandardCharsets.UTF_8),"text/html","UTF-8",null);
        }catch(java.io.IOException error){throw new IllegalStateException("bundled probe unavailable",error);}
    }
    @Override protected void onDestroy(){if(web!=null){web.destroy();web=null;}super.onDestroy();}
}

package org.eyepqc.mobile;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.concurrent.atomic.AtomicReference;

/** Foreground viewer. Credentials remain memory-only; leaving the screen closes the session. */
public final class MainActivity extends Activity {
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final AtomicReference<Bitmap> pending=new AtomicReference<>();
    private PairingConfig config;
    private TextView configSummary;
    private TextView status;
    private ImageView image;
    private StreamClient client;
    private Bitmap displayed;
    private volatile long generation;
    private long rendered,started;
    private final Runnable render=new Runnable(){public void run(){
        Bitmap next=pending.getAndSet(null);
        if(next!=null){Bitmap old=displayed;displayed=next;image.setImageBitmap(next);if(old!=null)old.recycle();if(rendered==0)started=System.nanoTime();rendered++;}
    }};
    private final Runnable monitor=new Runnable(){public void run(){
        if(client!=null)client.checkTimeout();ui.postDelayed(this,1000);
    }};
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE,WindowManager.LayoutParams.FLAG_SECURE);
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);layout.setPadding(16,16,16,16);
        layout.setOnApplyWindowInsetsListener((view,insets)->{view.setPadding(16+insets.getSystemWindowInsetLeft(),16+insets.getSystemWindowInsetTop(),16+insets.getSystemWindowInsetRight(),16+insets.getSystemWindowInsetBottom());return insets;});
        configSummary=new TextView(this);configSummary.setText("尚未导入连接配置");layout.addView(configSummary);
        button(layout,"导入连接配置 JSON",()->{Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"application/json","text/plain","application/octet-stream"}).addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(intent,1);});
        button(layout,"连接",this::connect);
        LinearLayout controls=new LinearLayout(this);layout.addView(controls);button(controls,"停止",()->{if(client!=null)client.stop();});button(controls,"换钥",()->{if(client!=null)client.rekey();});button(controls,"关闭",this::disconnect);
        status=new TextView(this);status.setText("导入可信 PC 生成的 JSON，然后点击连接");layout.addView(status);
        image=new ImageView(this);image.setAdjustViewBounds(true);image.setScaleType(ImageView.ScaleType.FIT_CENTER);layout.addView(image,new LinearLayout.LayoutParams(-1,0,1));setContentView(layout);
    }
    private void button(LinearLayout layout,String label,Runnable task){Button b=new Button(this);b.setText(label);b.setOnClickListener(v->task.run());layout.addView(b);}
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);if(request!=1||result!=RESULT_OK||data==null||data.getData()==null)return;
        try(InputStream in=getContentResolver().openInputStream(data.getData());ByteArrayOutputStream out=new ByteArrayOutputStream()){
            if(in==null)throw new IllegalArgumentException("file");byte[] buf=new byte[1024];int n;
            while((n=in.read(buf))!=-1){if(out.size()+n>PairingConfig.MAX_BYTES)throw new IllegalArgumentException("configuration size");out.write(buf,0,n);}
            config=PairingConfig.parse(out.toByteArray());configSummary.setText("已导入："+config.endpoint);status.setText("配置已校验，点击连接即可");
        }catch(Exception e){config=null;configSummary.setText("尚未导入有效配置");status.setText("JSON 配置无效或超过8 KiB，请从可信 PC 重新导出");}
    }
    private void connect(){
        disconnect();final long active=generation;
        try{
            if(config==null)throw new IllegalArgumentException("missing configuration");
            rendered=0;started=0;
            client=new StreamClient(config.publicKey,config.pin,new StreamClient.Listener(){
                public void status(String message){ui.post(()->{if(active==generation)status.setText(message+(message.startsWith("已认证 /")&&rendered>1?" / 显示 "+String.format(java.util.Locale.ROOT,"%.1f",(rendered-1)/Math.max(0.001,(System.nanoTime()-started)/1e9))+" fps":""));});}
                public void reset(){
                    synchronized(pending){if(active!=generation)return;ui.removeCallbacks(render);Bitmap b=pending.getAndSet(null);if(b!=null)b.recycle();}
                    ui.post(()->{if(active==generation)clearDisplay();});
                }
                public void frame(byte[] jpeg){
                    if(active!=generation)return;
                    BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(jpeg,0,jpeg.length,bounds);
                    if(bounds.outWidth<1||bounds.outHeight<1||bounds.outWidth>4096||bounds.outHeight>4096||((long)bounds.outWidth*bounds.outHeight)>4194304)throw new IllegalArgumentException("JPEG dimensions");
                    Bitmap bitmap=BitmapFactory.decodeByteArray(jpeg,0,jpeg.length);if(bitmap==null)throw new IllegalArgumentException("JPEG decode");
                    synchronized(pending){if(active!=generation){bitmap.recycle();return;}Bitmap old=pending.getAndSet(bitmap);if(old!=null)old.recycle();ui.removeCallbacks(render);ui.post(render);}
                }
            });
            client.connect(config.endpoint,config.token);
        }catch(Exception e){status.setText("请先导入有效的连接配置 JSON");}
    }
    private void disconnect(){
        synchronized(pending){generation++;if(client!=null){client.close();client=null;}ui.removeCallbacks(render);Bitmap b=pending.getAndSet(null);if(b!=null)b.recycle();}
        clearDisplay();if(status!=null)status.setText("已关闭");
    }
    private void clearDisplay(){if(image!=null)image.setImageDrawable(null);if(displayed!=null){displayed.recycle();displayed=null;}rendered=0;started=0;}
    @Override protected void onResume(){super.onResume();ui.post(monitor);}
    @Override protected void onPause(){super.onPause();ui.removeCallbacks(monitor);disconnect();}
}

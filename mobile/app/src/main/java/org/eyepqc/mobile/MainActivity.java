package org.eyepqc.mobile;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
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
    private EditText endpoint,token,pin;
    private TextView status;
    private ImageView image;
    private byte[] publicKey;
    private StreamClient client;
    private Bitmap displayed;
    private volatile long generation;
    private long rendered,started;
    private final Runnable render=new Runnable(){public void run(){
        Bitmap next=pending.getAndSet(null);
        if(next!=null){Bitmap old=displayed;displayed=next;image.setImageBitmap(next);if(old!=null)old.recycle();rendered++;}
    }};
    private final Runnable monitor=new Runnable(){public void run(){
        if(client!=null)client.checkTimeout();ui.postDelayed(this,1000);
    }};
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE,WindowManager.LayoutParams.FLAG_SECURE);
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);layout.setPadding(16,16,16,16);
        layout.setOnApplyWindowInsetsListener((view,insets)->{view.setPadding(16+insets.getSystemWindowInsetLeft(),16+insets.getSystemWindowInsetTop(),16+insets.getSystemWindowInsetRight(),16+insets.getSystemWindowInsetBottom());return insets;});
        endpoint=field(layout,"ws://PC局域网或VPN地址:8765/stream",false);
        token=field(layout,"PC访问令牌",true);pin=field(layout,"可信板卡公钥 SHA-256（64位hex）",false);
        button(layout,"选择板卡公钥文件（800字节）",()->{Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("application/octet-stream").addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(intent,1);});
        button(layout,"连接",this::connect);
        LinearLayout controls=new LinearLayout(this);layout.addView(controls);button(controls,"停止",()->{if(client!=null)client.stop();});button(controls,"换钥",()->{if(client!=null)client.rekey();});button(controls,"关闭",this::disconnect);
        status=new TextView(this);status.setText("选择公钥并输入可信指纹；录像/后台播放未启用");layout.addView(status);
        image=new ImageView(this);image.setAdjustViewBounds(true);image.setScaleType(ImageView.ScaleType.FIT_CENTER);layout.addView(image,new LinearLayout.LayoutParams(-1,0,1));setContentView(layout);
    }
    private EditText field(LinearLayout layout,String hint,boolean secret){EditText e=new EditText(this);e.setHint(hint);e.setSingleLine(true);e.setSaveEnabled(false);e.setInputType(secret?InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);layout.addView(e);return e;}
    private void button(LinearLayout layout,String label,Runnable task){Button b=new Button(this);b.setText(label);b.setOnClickListener(v->task.run());layout.addView(b);}
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);if(request!=1||result!=RESULT_OK||data==null)return;
        try(InputStream in=getContentResolver().openInputStream(data.getData());ByteArrayOutputStream out=new ByteArrayOutputStream()){
            if(in==null)throw new IllegalArgumentException("file");byte[] buf=new byte[801];int n;
            while((n=in.read(buf))!=-1){out.write(buf,0,n);if(out.size()>800)throw new IllegalArgumentException("key length");}
            if(out.size()!=800)throw new IllegalArgumentException("key length");publicKey=out.toByteArray();status.setText("公钥已载入；请独立确认指纹");
        }catch(Exception e){publicKey=null;status.setText("公钥文件必须恰好800字节");}
    }
    private void connect(){
        disconnect();final long active=generation;
        try{
            if(publicKey==null)throw new IllegalArgumentException("missing key");
            final byte[] pinned=Protocol.hex(pin.getText().toString().trim());rendered=0;started=System.nanoTime();
            client=new StreamClient(publicKey,pinned,new StreamClient.Listener(){
                public void status(String message){ui.post(()->{if(active==generation)status.setText(message+" / 显示 "+String.format(java.util.Locale.ROOT,"%.1f",rendered/Math.max(0.001,(System.nanoTime()-started)/1e9))+" fps");});}
                public void frame(byte[] jpeg){
                    if(active!=generation)return;
                    BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(jpeg,0,jpeg.length,bounds);
                    if(bounds.outWidth<1||bounds.outHeight<1||bounds.outWidth>4096||bounds.outHeight>4096||((long)bounds.outWidth*bounds.outHeight)>4194304)throw new IllegalArgumentException("JPEG dimensions");
                    Bitmap bitmap=BitmapFactory.decodeByteArray(jpeg,0,jpeg.length);if(bitmap==null)throw new IllegalArgumentException("JPEG decode");
                    synchronized(pending){if(active!=generation){bitmap.recycle();return;}Bitmap old=pending.getAndSet(bitmap);if(old!=null)old.recycle();ui.removeCallbacks(render);ui.post(render);}
                }
            });
            client.connect(endpoint.getText().toString().trim(),token.getText().toString());
        }catch(Exception e){status.setText("连接参数无效；检查800字节公钥、64位指纹及访问令牌");}
    }
    private void disconnect(){
        synchronized(pending){generation++;if(client!=null){client.close();client=null;}ui.removeCallbacks(render);Bitmap b=pending.getAndSet(null);if(b!=null)b.recycle();}
        if(image!=null)image.setImageDrawable(null);if(displayed!=null){displayed.recycle();displayed=null;}if(status!=null)status.setText("已关闭");
    }
    @Override protected void onResume(){super.onResume();ui.post(monitor);}
    @Override protected void onPause(){super.onPause();ui.removeCallbacks(monitor);disconnect();}
}

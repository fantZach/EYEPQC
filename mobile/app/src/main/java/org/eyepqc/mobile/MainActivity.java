package org.eyepqc.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.text.InputType;
import android.widget.EditText;
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
    private EditText serverAddress,username,password;
    private PairingClient pairingClient;
    private AlertDialog takeoverDialog;
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
        serverAddress=new EditText(this);serverAddress.setHint("可信服务器 wss://地址:端口/stream");serverAddress.setSingleLine(true);serverAddress.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);serverAddress.setText("wss://124.70.38.245:8765/stream");layout.addView(serverAddress);
        configSummary=new TextView(this);configSummary.setText("登录后自动获取并校验配对配置");layout.addView(configSummary);
        button(layout,"手动导入 JSON（备用/确认身份变更）",()->{Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"application/json","text/plain","application/octet-stream"}).addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(intent,1);});
        username=new EditText(this);username.setHint("账号（v2 WSS）");username.setSingleLine(true);username.setSaveEnabled(false);username.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_NO);layout.addView(username);
        password=new EditText(this);password.setHint("密码（仅本次进程）");password.setSingleLine(true);password.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);password.setSaveEnabled(false);password.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_NO);layout.addView(password);
        button(layout,"登录并连接",this::connect);
        LinearLayout controls=new LinearLayout(this);layout.addView(controls);button(controls,"停止",()->{if(pairingClient!=null)disconnect();else if(client!=null)client.stop();});button(controls,"换钥",()->{if(client!=null)client.rekey();});button(controls,"关闭",this::disconnect);
        status=new TextView(this);status.setText("确认服务地址，输入账号密码；无需选择 JSON 文件");layout.addView(status);
        image=new ImageView(this);image.setAdjustViewBounds(true);image.setScaleType(ImageView.ScaleType.FIT_CENTER);layout.addView(image,new LinearLayout.LayoutParams(-1,0,1));setContentView(layout);
        String savedConfig=getPreferences(MODE_PRIVATE).getString("account_pairing",null);
        if(savedConfig!=null){try{PairingConfig restored=PairingConfig.parse(savedConfig.getBytes(java.nio.charset.StandardCharsets.UTF_8));if(restored.version!=2)throw new IllegalArgumentException("saved profile");config=restored;serverAddress.setText(config.endpoint);configSummary.setText("已保存板卡身份；登录时校验更新");}catch(Exception error){getPreferences(MODE_PRIVATE).edit().remove("account_pairing").apply();}}
    }
    private void button(LinearLayout layout,String label,Runnable task){Button b=new Button(this);b.setText(label);b.setOnClickListener(v->task.run());layout.addView(b);}
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);if(request!=1||result!=RESULT_OK||data==null||data.getData()==null)return;
        try(InputStream in=getContentResolver().openInputStream(data.getData());ByteArrayOutputStream out=new ByteArrayOutputStream()){
            if(in==null)throw new IllegalArgumentException("file");byte[] buf=new byte[1024];int n;
            while((n=in.read(buf))!=-1){if(out.size()+n>PairingConfig.MAX_BYTES)throw new IllegalArgumentException("configuration size");out.write(buf,0,n);}
            byte[] json=out.toByteArray();PairingConfig selected=PairingConfig.parse(json);disconnect();config=selected;serverAddress.setText(config.endpoint);remember(json);configSummary.setText((config.version==2?"账号 / 临时 KEM：":"v1 开发兼容：")+config.endpoint);status.setText(config.version==2?"可信配置已导入，输入账号密码后连接":"v1 开发兼容配置已校验，点击连接");
        }catch(Exception e){status.setText("JSON 配置无效或超过8 KiB；原有可信身份保持不变");}
    }
    private void connect(){connect(false);}
    private void connect(boolean takeover){
        disconnect();final long active=generation;
        try{
            String endpoint=serverAddress.getText().toString().trim();
            String user=username.getText().toString(),secret=password.getText().toString();
            if(config!=null&&config.version==1&&config.endpoint.equals(endpoint)){stream(active,takeover,user,secret);return;}
            status.setText("验证账号并获取配对配置");
            pairingClient=new PairingClient();
            String remembered=getPreferences(MODE_PRIVATE).getString("pairing:"+endpoint,null);
            byte[] previousPin=remembered!=null?PairingConfig.fromServer(remembered.getBytes(java.nio.charset.StandardCharsets.UTF_8),endpoint,null).pin:
                config!=null&&config.version==2&&config.endpoint.equals(endpoint)?config.pin.clone():null;
            pairingClient.fetch(endpoint,user,secret,previousPin,new PairingClient.Listener(){
                public void received(PairingConfig received,byte[] json){ui.post(()->{
                    if(active!=generation)return;
                    pairingClient.close();pairingClient=null;config=received;remember(json);
                    configSummary.setText("已自动配对 / 临时 KEM："+config.endpoint);
                    try{stream(active,takeover,user,secret);}catch(Exception error){disconnect();status.setText("连接准备失败，请检查账号及配对配置");}
                });}
                public void failed(String message){ui.post(()->{if(active!=generation)return;disconnect();status.setText(message);});}
            });
        }catch(Exception e){disconnect();status.setText("请检查可信 WSS 地址和账号密码");}
    }
    private void remember(byte[] json){
        if(config.version==2){String text=new String(json,java.nio.charset.StandardCharsets.UTF_8);getPreferences(MODE_PRIVATE).edit().putString("account_pairing",text).putString("pairing:"+config.endpoint,text).apply();}
    }
    private void stream(long active,boolean takeover,String user,String secret)throws Exception {
            rendered=0;started=0;
            client=new StreamClient(config.publicKey,config.pin,new StreamClient.Listener(){
                public void takeoverRequired(){ui.post(()->{if(active!=generation||config.version!=2)return;takeoverDialog=new AlertDialog.Builder(MainActivity.this).setTitle("账号正在另一设备观看").setMessage("接管会关闭该设备的视频连接。是否接管？").setNegativeButton("取消",(dialog,which)->{}).setPositiveButton("确认接管",(dialog,which)->connect(true)).show();});}
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
            },config.version==2);
            if(config.version==2)client.connectAccount(config.endpoint,user,secret,takeover);
            else client.connect(config.endpoint,config.token);
    }
    private void disconnect(){
        if(takeoverDialog!=null){takeoverDialog.dismiss();takeoverDialog=null;}
        synchronized(pending){generation++;if(client!=null){client.close();client=null;}ui.removeCallbacks(render);Bitmap b=pending.getAndSet(null);if(b!=null)b.recycle();}
        if(pairingClient!=null){pairingClient.close();pairingClient=null;}
        clearDisplay();if(status!=null)status.setText("已关闭");
    }
    private void clearDisplay(){if(image!=null)image.setImageDrawable(null);if(displayed!=null){displayed.recycle();displayed=null;}rendered=0;started=0;}
    @Override protected void onResume(){super.onResume();ui.post(monitor);}
    @Override protected void onPause(){super.onPause();ui.removeCallbacks(monitor);disconnect();}
}

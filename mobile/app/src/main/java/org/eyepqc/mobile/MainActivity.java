package org.eyepqc.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.res.Configuration;
import android.graphics.drawable.GradientDrawable;
import android.text.method.PasswordTransformationMethod;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.ImageButton;
import android.widget.FrameLayout;
import android.widget.ScrollView;
import android.widget.ProgressBar;
import android.widget.TextView;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.concurrent.atomic.AtomicReference;

/** Foreground viewer. Credentials remain memory-only; leaving the screen closes the session. */
public final class MainActivity extends Activity {
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final AtomicReference<Bitmap> pending=new AtomicReference<>();
    private final ViewerState state=new ViewerState();
    private PairingConfig config;
    private EditText serverAddress,username,password;
    private PairingClient pairingClient;
    private AlertDialog takeoverDialog,exitDialog;
    private TextView configSummary,status,badge,fps,frames,dropped,playerInfo,emptyTitle;
    private View loginCard,advanced,emptyPlayer,liveBadge,normalPanel,actionBar;
    private Button primary,rekey,importConfig,passwordVisibility,fullscreenStop;
    private ImageButton fullscreenButton;
    private FrameLayout root,player,videoSlot,fullscreenHost;
    private ScrollView scroll;
    private ProgressBar progress;
    private boolean fullscreen,passwordVisible;
    private volatile boolean acceptFrames;
    private ImageView image;
    private StreamClient client;
    private Bitmap displayed;
    private volatile long generation;
    private volatile long videoEpoch;
    private long rendered,started;
    private final Runnable render=new Runnable(){public void run(){
        Bitmap next=pending.getAndSet(null);
        if(next!=null){
            if(!acceptFrames){next.recycle();return;}
            Bitmap old=displayed;displayed=next;image.setImageBitmap(next);if(old!=null)old.recycle();
            boolean first=rendered==0;
            if(first){started=System.nanoTime();emptyPlayer.setVisibility(View.GONE);liveBadge.setVisibility(View.VISIBLE);status.setText("画面已认证，正在实时播放");}
            rendered++;if(first)updateBadge();
        }
    }};
    private final Runnable monitor=new Runnable(){public void run(){
        if(client!=null)client.checkTimeout();ui.postDelayed(this,1000);
    }};
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);getWindow().setFlags(WindowManager.LayoutParams.FLAG_SECURE,WindowManager.LayoutParams.FLAG_SECURE);
        setContentView(R.layout.activity_main);
        root=findViewById(R.id.root);scroll=findViewById(R.id.scroll);player=findViewById(R.id.player);videoSlot=findViewById(R.id.video_slot);fullscreenHost=findViewById(R.id.fullscreen_host);
        normalPanel=findViewById(R.id.normal_panel);actionBar=findViewById(R.id.action_bar);
        serverAddress=findViewById(R.id.server);username=findViewById(R.id.username);password=findViewById(R.id.password);
        configSummary=findViewById(R.id.config_summary);status=findViewById(R.id.status);badge=findViewById(R.id.state_badge);fps=findViewById(R.id.fps);frames=findViewById(R.id.frames);dropped=findViewById(R.id.dropped);playerInfo=findViewById(R.id.player_info);emptyTitle=findViewById(R.id.empty_title);
        loginCard=findViewById(R.id.login_card);advanced=findViewById(R.id.advanced);emptyPlayer=findViewById(R.id.empty_player);liveBadge=findViewById(R.id.live_badge);image=findViewById(R.id.image);progress=findViewById(R.id.progress);
        primary=findViewById(R.id.primary);rekey=findViewById(R.id.rekey);importConfig=findViewById(R.id.import_config);passwordVisibility=findViewById(R.id.password_visibility);fullscreenButton=findViewById(R.id.fullscreen);fullscreenStop=findViewById(R.id.fullscreen_stop);
        root.setOnApplyWindowInsetsListener((view,insets)->{int pad=dp(20);scroll.setPadding(pad+insets.getSystemWindowInsetLeft(),pad+insets.getSystemWindowInsetTop(),pad+insets.getSystemWindowInsetRight(),dp(8));actionBar.setPadding(pad+insets.getSystemWindowInsetLeft(),dp(12),pad+insets.getSystemWindowInsetRight(),dp(12)+insets.getSystemWindowInsetBottom());return insets;});
        player.addOnLayoutChangeListener((view,l,t,r,b,ol,ot,or,ob)->{if(!fullscreen&&r-l>0){int height=(r-l)*3/4;if(view.getLayoutParams().height!=height){view.getLayoutParams().height=height;view.requestLayout();}}});
        primary.setOnClickListener(v->primaryAction());rekey.setOnClickListener(v->requestRekey());fullscreenStop.setOnClickListener(v->primaryAction());fullscreenButton.setOnClickListener(v->setFullscreen(!fullscreen));
        findViewById(R.id.settings).setOnClickListener(v->{advanced.setVisibility(advanced.getVisibility()==View.VISIBLE?View.GONE:View.VISIBLE);});
        passwordVisibility.setOnClickListener(v->showPassword(!passwordVisible));
        password.setOnEditorActionListener((v,action,event)->{if(action==EditorInfo.IME_ACTION_GO){if(state.canConnect())connect();return true;}return false;});
        importConfig.setOnClickListener(v->{if(!state.canConnect())return;Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES,new String[]{"application/json","text/plain","application/octet-stream"}).addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(intent,1);});
        String savedConfig=getPreferences(MODE_PRIVATE).getString("account_pairing",null);
        if(savedConfig!=null){try{PairingConfig restored=PairingConfig.parse(savedConfig.getBytes(java.nio.charset.StandardCharsets.UTF_8));if(restored.version!=2)throw new IllegalArgumentException("saved profile");config=restored;serverAddress.setText(config.endpoint);updateSummary();}catch(Exception error){getPreferences(MODE_PRIVATE).edit().remove("account_pairing").apply();}}
        if(serverAddress.length()==0)advanced.setVisibility(View.VISIBLE);
        updateControls();
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if(Build.VERSION.SDK_INT>=33)getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,this::handleBack);
    }
    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private void showPassword(boolean visible){passwordVisible=visible;password.setTransformationMethod(visible?null:PasswordTransformationMethod.getInstance());password.setSelection(password.length());passwordVisibility.setText(visible?"隐藏":"显示");passwordVisibility.setContentDescription(visible?"隐藏密码":"显示密码");}
    private void hideKeyboard(){showPassword(false);View focus=getCurrentFocus();if(focus!=null){((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(focus.getWindowToken(),0);focus.clearFocus();}}
    private void updateSummary(){if(config!=null)configSummary.setText((config.version==2?"已记住板卡身份 · ":"v1 开发兼容 · ")+Protocol.hex(config.pin).substring(0,16)+"…\n身份变更时需可信手动导入确认");}
    private void primaryAction(){
        if(state.canConnect()){connect();return;}
        if(state.busy()){disconnect();status.setText("已取消连接，可重新尝试");return;}
        if(state.stop()&&client!=null){acceptFrames=false;clearDisplay();status.setText("正在停止视频并清理会话…");updateControls();client.stop();}
    }
    private void requestRekey(){if(client==null||!state.rekey())return;acceptFrames=false;clearDisplay();status.setText("正在协商新密钥，旧画面已清除");updateControls();client.rekey();}
    private void updateControls(){
        boolean editable=state.canConnect();serverAddress.setEnabled(editable);username.setEnabled(editable);password.setEnabled(editable);passwordVisibility.setEnabled(editable);importConfig.setEnabled(editable);
        boolean compact=state.phase()==ViewerState.Phase.LIVE||state.phase()==ViewerState.Phase.REKEYING||state.phase()==ViewerState.Phase.STOPPING;
        loginCard.setVisibility(compact?View.GONE:View.VISIBLE);rekey.setEnabled(state.canRekey());primary.setEnabled(state.phase()!=ViewerState.Phase.STOPPING);
        primary.setText(state.phase()==ViewerState.Phase.LIVE?"停止播放":state.busy()?"取消连接":state.phase()==ViewerState.Phase.STOPPING?"正在停止…":state.phase()==ViewerState.Phase.ERROR?"重新连接":"连接并观看");
        progress.setVisibility(state.busy()||state.phase()==ViewerState.Phase.STOPPING?View.VISIBLE:View.GONE);
        fullscreenStop.setVisibility(fullscreen&&state.active()?View.VISIBLE:View.GONE);fullscreenStop.setText(state.busy()?"取消连接":"停止播放");fullscreenStop.setEnabled(state.phase()!=ViewerState.Phase.STOPPING);
        fullscreenButton.setEnabled(state.phase()==ViewerState.Phase.LIVE||state.phase()==ViewerState.Phase.REKEYING);fullscreenButton.setAlpha(fullscreenButton.isEnabled()?1f:.4f);
        if(state.phase()==ViewerState.Phase.LIVE||state.phase()==ViewerState.Phase.REKEYING)getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        emptyTitle.setText(state.busy()?"正在建立安全会话":state.phase()==ViewerState.Phase.ERROR?"连接暂不可用":"等待视频");updateBadge();
    }
    private void updateBadge(){
        int text=R.color.muted,background=R.color.page;String label="等待连接";
        if(state.phase()==ViewerState.Phase.LIVE){label=rendered>0?"● 实时播放":"会话已认证";text=R.color.success;background=R.color.success_soft;}
        else if(state.busy()||state.phase()==ViewerState.Phase.STOPPING){label=state.phase()==ViewerState.Phase.REKEYING?"正在换钥":state.phase()==ViewerState.Phase.STOPPING?"正在停止":"正在连接";text=R.color.warning;background=R.color.warning_soft;}
        else if(state.phase()==ViewerState.Phase.ERROR){label="需要重试";text=R.color.danger;background=R.color.danger_soft;}
        if(!label.contentEquals(badge.getText()))badge.setText(label);
        badge.setTextColor(getColor(text));GradientDrawable shape=new GradientDrawable();shape.setColor(getColor(background));shape.setCornerRadius(dp(8));badge.setBackground(shape);
    }
    private void setFullscreen(boolean enabled){
        if(fullscreen==enabled)return;hideKeyboard();fullscreen=enabled;
        ((ViewGroup)player.getParent()).removeView(player);
        (enabled?fullscreenHost:videoSlot).addView(player,new FrameLayout.LayoutParams(-1,enabled?-1:Math.max(dp(180),videoSlot.getWidth()*3/4)));
        normalPanel.setVisibility(enabled?View.GONE:View.VISIBLE);fullscreenHost.setVisibility(enabled?View.VISIBLE:View.GONE);
        fullscreenButton.setImageResource(enabled?R.drawable.ic_fullscreen_exit:R.drawable.ic_fullscreen);fullscreenButton.setContentDescription(enabled?"退出全屏":"全屏预览");
        getWindow().getDecorView().setSystemUiVisibility(enabled?View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY:View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        root.requestApplyInsets();updateControls();
    }
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);if(request!=1||result!=RESULT_OK||data==null||data.getData()==null)return;
        try(InputStream in=getContentResolver().openInputStream(data.getData());ByteArrayOutputStream out=new ByteArrayOutputStream()){
            if(in==null)throw new IllegalArgumentException("file");byte[] buf=new byte[1024];int n;
            while((n=in.read(buf))!=-1){if(out.size()+n>PairingConfig.MAX_BYTES)throw new IllegalArgumentException("configuration size");out.write(buf,0,n);}
            byte[] json=out.toByteArray();PairingConfig selected=PairingConfig.parse(json);disconnect();config=selected;serverAddress.setText(config.endpoint);remember(json);updateSummary();status.setText(config.version==2?"可信身份已导入，输入账号密码后连接":"v1 开发兼容配置已导入");
        }catch(Exception e){status.setText("JSON 配置无效或超过8 KiB；原有可信身份保持不变");}
    }
    private void connect(){connect(false);}
    private void connect(boolean takeover){
        if(!state.canConnect())return;
        serverAddress.setError(null);username.setError(null);password.setError(null);
        boolean legacy=config!=null&&config.version==1&&config.endpoint.equals(serverAddress.getText().toString().trim());
        try{String endpoint=serverAddress.getText().toString().trim();StreamClient.validateEndpoint(endpoint);if(!legacy&&!endpoint.startsWith("wss://"))throw new IllegalArgumentException("WSS required");}
        catch(Exception error){advanced.setVisibility(View.VISIBLE);serverAddress.setError("请输入可信 wss://地址:端口/stream");serverAddress.requestFocus();return;}
        if(!legacy&&username.getText().toString().isEmpty()){username.setError("请输入账号");username.requestFocus();return;}
        if(!legacy&&password.length()==0){password.setError("请输入密码");password.requestFocus();return;}
        disconnect();state.connect();updateControls();hideKeyboard();final long active=generation;
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
                    updateSummary();
                    try{stream(active,takeover,user,secret);}catch(Exception error){connectionFailed("连接准备失败，请检查账号及配对配置");}
                });}
                public void failed(String message){ui.post(()->{if(active==generation)connectionFailed(message);});}
            });
        }catch(Exception e){connectionFailed("请检查可信 WSS 地址和账号密码");}
    }
    private void remember(byte[] json){
        if(config.version==2){String text=new String(json,java.nio.charset.StandardCharsets.UTF_8);getPreferences(MODE_PRIVATE).edit().putString("account_pairing",text).putString("pairing:"+config.endpoint,text).apply();}
    }
    private void stream(long active,boolean takeover,String user,String secret)throws Exception {
            rendered=0;started=0;
            client=new StreamClient(config.publicKey,config.pin,new StreamClient.Listener(){
                public void takeoverRequired(){ui.post(()->{if(active!=generation||config.version!=2)return;takeoverDialog=new AlertDialog.Builder(MainActivity.this).setTitle("账号正在另一设备观看").setMessage("接管会关闭该设备的视频连接。是否接管？").setNegativeButton("取消",(dialog,which)->{}).setPositiveButton("确认接管",(dialog,which)->connect(true)).show();});}
                public void state(StreamClient.State event){ui.post(()->{
                    if(active!=generation||!state.client(event))return;acceptFrames=state.phase()==ViewerState.Phase.LIVE;
                    if(event==StreamClient.State.STOPPED){clearDisplay();setFullscreen(false);}
                    if(event==StreamClient.State.FAILED){acceptFrames=false;clearDisplay();setFullscreen(false);}
                    if(event==StreamClient.State.STREAMING)status.setText("身份和会话密钥已确认，等待画面");
                    updateControls();
                });}
                public void statistics(long received,long missing){ui.post(()->{
                    if(active!=generation||state.phase()!=ViewerState.Phase.LIVE)return;
                    frames.setText(Long.toString(received));dropped.setText(Long.toString(missing));
                    String rate=rendered>1?String.format(java.util.Locale.ROOT,"%.1f",(rendered-1)/Math.max(.001,(System.nanoTime()-started)/1e9)):"—";
                    fps.setText(rate);if(displayed!=null)playerInfo.setText(displayed.getWidth()+" × "+displayed.getHeight()+"  ·  "+rate+" fps");
                });}
                public void status(String message){ui.post(()->{
                    if(active!=generation||message.startsWith("已认证 /"))return;
                    if(state.phase()==ViewerState.Phase.STOPPING&&!message.equals("已停止"))return;
                    status.setText(friendly(message));
                });}
                public void reset(){
                    synchronized(pending){if(active!=generation)return;acceptFrames=false;videoEpoch++;ui.removeCallbacks(render);Bitmap b=pending.getAndSet(null);if(b!=null)b.recycle();}
                    ui.post(()->{if(active==generation)clearDisplay();});
                }
                public void frame(byte[] jpeg){
                    if(active!=generation||!acceptFrames)return;final long frameEpoch=videoEpoch;
                    BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(jpeg,0,jpeg.length,bounds);
                    if(bounds.outWidth<1||bounds.outHeight<1||bounds.outWidth>4096||bounds.outHeight>4096||((long)bounds.outWidth*bounds.outHeight)>4194304)throw new IllegalArgumentException("JPEG dimensions");
                    Bitmap bitmap=BitmapFactory.decodeByteArray(jpeg,0,jpeg.length);if(bitmap==null)throw new IllegalArgumentException("JPEG decode");
                    synchronized(pending){if(active!=generation||frameEpoch!=videoEpoch||!acceptFrames){bitmap.recycle();return;}Bitmap old=pending.getAndSet(bitmap);if(old!=null)old.recycle();ui.removeCallbacks(render);ui.post(render);}
                }
            },config.version==2);
            if(config.version==2)client.connectAccount(config.endpoint,user,secret,takeover);
            else client.connect(config.endpoint,config.token);
    }
    private void disconnect(){
        if(takeoverDialog!=null){takeoverDialog.dismiss();takeoverDialog=null;}
        if(exitDialog!=null){exitDialog.dismiss();exitDialog=null;}
        synchronized(pending){generation++;acceptFrames=false;if(client!=null){client.close();client=null;}ui.removeCallbacks(render);Bitmap b=pending.getAndSet(null);if(b!=null)b.recycle();}
        if(pairingClient!=null){pairingClient.close();pairingClient=null;}
        state.idle();clearDisplay();setFullscreen(false);updateControls();status.setText("已断开连接，可再次观看");
    }
    private void connectionFailed(String message){disconnect();state.error();updateControls();status.setText(friendly(message));}
    private String friendly(String message){
        if(message.contains("HTTP 401"))return "账号或密码不正确，请重新输入";
        if(message.contains("HTTP 409"))return "账号正在另一设备观看，请确认是否接管";
        if(message.contains("HTTP 429"))return "登录请求较频繁，请稍后再试";
        if(message.contains("HTTP 503"))return "服务暂不可用，请检查 PC 和板卡状态";
        if(message.equals("连接中"))return "正在建立加密网络连接…";
        if(message.equals("验证板卡中"))return "正在验证板卡身份并协商密钥…";
        if(message.equals("重新协商密钥"))return "正在更换会话密钥，旧画面已清除";
        if(message.equals("已停止"))return "视频已停止，点击连接即可再次观看";
        return message;
    }
    private void clearDisplay(){
        synchronized(pending){videoEpoch++;ui.removeCallbacks(render);Bitmap queued=pending.getAndSet(null);if(queued!=null)queued.recycle();}
        if(image!=null)image.setImageDrawable(null);if(displayed!=null){displayed.recycle();displayed=null;}rendered=0;started=0;
        if(emptyPlayer!=null){emptyPlayer.setVisibility(View.VISIBLE);liveBadge.setVisibility(View.GONE);fps.setText("—");frames.setText("—");dropped.setText("—");playerInfo.setText("ML-KEM · AES-GCM");}
    }
    @Override public void onConfigurationChanged(Configuration configuration){super.onConfigurationChanged(configuration);root.requestApplyInsets();}
    @Override public void onBackPressed(){handleBack();}
    private void handleBack(){
        if(fullscreen){setFullscreen(false);return;}
        if(state.active()){if(exitDialog==null)exitDialog=new AlertDialog.Builder(this).setTitle("离开实时监看？").setMessage("连接会断开，当前画面和会话密钥会清理。").setNegativeButton("继续观看",(dialog,which)->exitDialog=null).setPositiveButton("断开并离开",(dialog,which)->finish()).setOnCancelListener(dialog->exitDialog=null).show();return;}
        finish();
    }
    @Override protected void onResume(){super.onResume();ui.post(monitor);}
    @Override protected void onPause(){super.onPause();ui.removeCallbacks(monitor);disconnect();showPassword(false);}
}

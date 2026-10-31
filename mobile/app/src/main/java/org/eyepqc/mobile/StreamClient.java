package org.eyepqc.mobile;

import java.net.InetAddress;
import java.net.URI;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import okhttp3.OkHttpClient;
import okhttp3.Credentials;
import java.nio.charset.StandardCharsets;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/** One viewer, bounded worker queue, no secret/plaintext logging. */
public final class StreamClient implements AutoCloseable {
    // Leave 15 seconds to refresh before the board's strict 1800-second key expiry.
    static final long ROTATION_MILLIS=TimeUnit.SECONDS.toMillis(1785);
    public enum State { CONNECTING, VERIFYING, STREAMING, REKEYING, STOPPED, FAILED }
    public interface Listener {
        void frame(byte[] jpeg); void status(String message);
        default void state(State state) {} default void statistics(long frames,long dropped) {}
        default void reset() {} default void takeoverRequired() {}
    }
    private final ThreadPoolExecutor worker=new ThreadPoolExecutor(1,1,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(512));
    private final AtomicBoolean closed=new AtomicBoolean();
    private final AtomicBoolean timerPending=new AtomicBoolean();
    private final OkHttpClient http=new OkHttpClient.Builder().followRedirects(false).followSslRedirects(false).pingInterval(10,TimeUnit.SECONDS).connectTimeout(10,TimeUnit.SECONDS).build();
    private final Session session;
    private final boolean ephemeral;
    private java.util.Timer rotation;
    private final Listener listener;
    private volatile WebSocket socket;
    private volatile long handshakeStarted;
    private volatile long businessExpires;
    private long lastStatus;
    private long lastHelloSent;
    private int helloRetries;
    public StreamClient(byte[] pk,byte[] pin,Listener callback) throws Exception {this(pk,pin,callback,false);}
    public StreamClient(byte[] pk,byte[] pin,Listener callback,boolean ephemeral) throws Exception { this.ephemeral=ephemeral;listener=callback;session=new Session(pk,pin,jpeg->{try{callback.frame(jpeg);}finally{Session.wipe(jpeg);}},ephemeral); }
    public static void validateEndpoint(String endpoint) throws Exception {
        URI uri=new URI(endpoint);
        if(uri.getHost()==null||uri.getUserInfo()!=null||uri.getFragment()!=null||!"/stream".equals(uri.getPath())||uri.getQuery()!=null)throw new IllegalArgumentException("endpoint must be ws[s]://address:port/stream");
        if("wss".equals(uri.getScheme()))return;
        if(!"ws".equals(uri.getScheme()))throw new IllegalArgumentException("WebSocket URL required");
        String host=uri.getHost();
        // Plain WS is only for explicit local/VPN numeric addresses, never public DNS.
        if(!host.matches("[0-9.]+")&&!host.contains(":"))throw new IllegalArgumentException("ws requires a local/VPN numeric address; use wss for DNS");
        InetAddress addr=InetAddress.getByName(host);byte[] b=addr.getAddress();
        boolean vpn=b.length==4&&(b[0]&255)==100&&(b[1]&255)>=64&&(b[1]&255)<=127;
        boolean ula=b.length==16&&((b[0]&254)==252);
        if(!addr.isLoopbackAddress()&&!addr.isSiteLocalAddress()&&!addr.isLinkLocalAddress()&&!vpn&&!ula)throw new IllegalArgumentException("public endpoints require wss");
    }
    public void connect(String endpoint,String token){
        if(token==null||token.isEmpty()||token.length()>512||token.indexOf('\r')>=0||token.indexOf('\n')>=0)throw new IllegalArgumentException("invalid access token");
        connectAuthorized(endpoint,"Bearer "+token,false);
    }
    static String accountAuthorization(String endpoint,String username,String password)throws Exception{
        validateEndpoint(endpoint);if(!endpoint.startsWith("wss://"))throw new IllegalArgumentException("login requires WSS");
        if(username.isEmpty()||username.length()>128||username.indexOf(':')>=0||password.isEmpty()||password.length()>1024)throw new IllegalArgumentException("credentials");
        for(char c:(username+password).toCharArray())if(Character.isISOControl(c))throw new IllegalArgumentException("credentials");
        return Credentials.basic(username,password,StandardCharsets.UTF_8);
    }
    public void connectAccount(String endpoint,String username,String password,boolean takeover)throws Exception{
        if(!ephemeral)throw new IllegalStateException("account login requires suite2");
        connectAuthorized(endpoint,accountAuthorization(endpoint,username,password),takeover);
    }
    private void connectAuthorized(String endpoint,String authorization,boolean takeover){
        submit(()->{
            validateEndpoint(endpoint);
            listener.state(State.CONNECTING);listener.status("连接中");handshakeStarted=System.nanoTime();
            socket=http.newWebSocket(new Request.Builder().url(endpoint+(takeover?"?takeover=1":"")).header("Authorization",authorization).build(),new WebSocketListener(){
                @Override public void onOpen(WebSocket ws,Response response){submit(()->{startHandshake();listener.state(State.VERIFYING);listener.status("验证板卡中");});}
                @Override public void onMessage(WebSocket ws,ByteString bytes){
                    if(bytes.size()>1459||bytes.size()<4){fail("非法记录长度");return;}
                    byte[] record=bytes.toByteArray();submit(()->{
                        if(businessExpired()){fail("业务密钥已到期，请重新连接");return;}
                        int before=session.phase();
                        for(byte[] reply:session.receive(record))send(reply);
                        if(before!=session.phase()&&session.streaming())listener.state(State.STREAMING);
                        if(ephemeral&&before!=session.phase()){if(session.streaming()){businessExpires=System.nanoTime()+TimeUnit.MINUTES.toNanos(30);scheduleRotation(ROTATION_MILLIS);}else handshakeStarted=System.nanoTime();}
                        if(session.streaming()){handshakeStarted=0;long now=System.nanoTime();if(now-lastStatus>TimeUnit.SECONDS.toNanos(1)){lastStatus=now;listener.statistics(session.completeFrames,session.droppedFrames);listener.status("已认证 / 帧 "+session.completeFrames+" / 丢帧 "+session.droppedFrames);}}
                    });
                }
                @Override public void onMessage(WebSocket ws,String text){fail("拒绝文本消息");}
                @Override public void onFailure(WebSocket ws,Throwable error,Response response){boolean conflict=response!=null&&response.code()==409;fail(response==null?ConnectionMessages.transport(error):("服务拒绝连接 HTTP "+response.code()));if(conflict)listener.takeoverRequired();}
                @Override public void onClosing(WebSocket ws,int code,String reason){ws.close(code,null);fail(code==4409?"账号已由另一设备接管，请手动连接":"连接已关闭");}
                @Override public void onClosed(WebSocket ws,int code,String reason){fail("连接已关闭");}
            });
        });
    }
    private void startHandshake()throws Exception{handshakeStarted=lastHelloSent=System.nanoTime();helloRetries=0;send(session.start());}
    public void rekey(){submit(()->{if(businessExpired()){fail("业务密钥已到期，请重新连接");return;}cancelRotation();send(session.rekey());businessExpires=0;listener.reset();startHandshake();listener.state(State.REKEYING);listener.status("重新协商密钥");});}
    private boolean businessExpired(){long deadline=businessExpires;return deadline!=0&&System.nanoTime()-deadline>=0;}
    synchronized void scheduleRotation(long delayMillis){cancelRotation();if(closed.get())return;rotation=new java.util.Timer("eyepqc-rotation",true);rotation.schedule(new java.util.TimerTask(){public void run(){rekey();}},delayMillis);}
    private synchronized void cancelRotation(){if(rotation!=null){rotation.cancel();rotation=null;}}
    public void stop(){submit(()->{if(session.streaming())send(session.stop());shutdown(false);listener.state(State.STOPPED);listener.status("已停止");});}
    public void checkTimeout(){
        if(businessExpired()){fail("业务密钥已到期，请重新连接");return;}
        if(closed.get()||handshakeStarted==0||!timerPending.compareAndSet(false,true))return;
        submit(()->{try{
            long since=handshakeStarted,now=System.nanoTime();if(since==0)return;
            if(now-since>TimeUnit.SECONDS.toNanos(15)){fail("握手超时，请重新连接");return;}
            if(session.waitingAck()&&helloRetries<2&&now-lastHelloSent>=TimeUnit.SECONDS.toNanos(3)){
                send(session.retryHello());helloRetries++;lastHelloSent=now;
            }
        }finally{timerPending.set(false);}});
    }
    private void send(byte[] record){WebSocket ws=socket;if(ws==null||ws.queueSize()>65536||!ws.send(ByteString.of(record)))throw new IllegalStateException("send queue unavailable");}
    private interface Task {void run() throws Exception;}
    private void submit(Task task){
        if(closed.get())return;
        try{worker.execute(()->{if(closed.get())return;try{task.run();}catch(Exception error){fail("认证或协议失败，请重新连接");}});}
        catch(RejectedExecutionException error){fail("接收队列已满，请重新连接");}
    }
    private void fail(String message){if(!closed.get()){listener.state(State.FAILED);listener.status(message);}close();}
    @Override public void close(){shutdown(true);}
    private void shutdown(boolean abort){
        if(!closed.compareAndSet(false,true))return;
        businessExpires=0;
        cancelRotation();
        WebSocket ws=socket;if(ws!=null){ws.close(1000,null);if(abort)ws.cancel();}
        worker.getQueue().clear();
        // Serialize wiping after any in-flight crypto/decode operation.
        try{worker.execute(()->{session.close();listener.reset();});}catch(RejectedExecutionException ignored){}
        worker.shutdown();http.dispatcher().executorService().shutdown();http.connectionPool().evictAll();
    }
}

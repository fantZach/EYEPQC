package org.eyepqc.mobile;

import java.net.InetAddress;
import java.net.URI;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/** One viewer, bounded worker queue, no secret/plaintext logging. */
public final class StreamClient implements AutoCloseable {
    public interface Listener { void frame(byte[] jpeg); void status(String message); }
    private final ThreadPoolExecutor worker=new ThreadPoolExecutor(1,1,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(512));
    private final AtomicBoolean closed=new AtomicBoolean();
    private final OkHttpClient http=new OkHttpClient.Builder().pingInterval(10,TimeUnit.SECONDS).connectTimeout(10,TimeUnit.SECONDS).build();
    private final Session session;
    private final Listener listener;
    private volatile WebSocket socket;
    private volatile long handshakeStarted;
    private long lastStatus;
    public StreamClient(byte[] pk,byte[] pin,Listener callback) throws Exception { listener=callback;session=new Session(pk,pin,jpeg->{try{callback.frame(jpeg);}finally{Session.wipe(jpeg);}}); }
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
        submit(()->{
            validateEndpoint(endpoint);
            if(token.isEmpty()||token.length()>512||token.indexOf('\r')>=0||token.indexOf('\n')>=0)throw new IllegalArgumentException("invalid access token");
            listener.status("连接中");handshakeStarted=System.nanoTime();
            socket=http.newWebSocket(new Request.Builder().url(endpoint).header("Authorization","Bearer "+token).build(),new WebSocketListener(){
                @Override public void onOpen(WebSocket ws,Response response){submit(()->{handshakeStarted=System.nanoTime();send(session.start());listener.status("验证板卡中");});}
                @Override public void onMessage(WebSocket ws,ByteString bytes){
                    if(bytes.size()>1459||bytes.size()<4){fail("非法记录长度");return;}
                    byte[] record=bytes.toByteArray();submit(()->{
                        for(byte[] reply:session.receive(record))send(reply);
                        if(session.streaming()){handshakeStarted=0;long now=System.nanoTime();if(now-lastStatus>TimeUnit.SECONDS.toNanos(1)){lastStatus=now;listener.status("已认证 / 帧 "+session.completeFrames+" / 丢帧 "+session.droppedFrames);}}
                    });
                }
                @Override public void onMessage(WebSocket ws,String text){fail("拒绝文本消息");}
                @Override public void onFailure(WebSocket ws,Throwable error,Response response){fail(response==null?"连接失败":("服务拒绝连接 HTTP "+response.code()));}
                @Override public void onClosing(WebSocket ws,int code,String reason){ws.close(code,null);fail("连接已关闭");}
                @Override public void onClosed(WebSocket ws,int code,String reason){fail("连接已关闭");}
            });
        });
    }
    public void rekey(){submit(()->{send(session.rekey());send(session.start());handshakeStarted=System.nanoTime();listener.status("重新协商密钥");});}
    public void stop(){submit(()->{if(session.streaming())send(session.stop());shutdown(false);listener.status("已停止");});}
    public void checkTimeout(){long since=handshakeStarted;if(since!=0&&System.nanoTime()-since>TimeUnit.SECONDS.toNanos(15))fail("握手超时，请重新连接");}
    private void send(byte[] record){WebSocket ws=socket;if(ws==null||ws.queueSize()>65536||!ws.send(ByteString.of(record)))throw new IllegalStateException("send queue unavailable");}
    private interface Task {void run() throws Exception;}
    private void submit(Task task){
        if(closed.get())return;
        try{worker.execute(()->{if(closed.get())return;try{task.run();}catch(Exception error){fail("认证或协议失败，请重新连接");}});}
        catch(RejectedExecutionException error){fail("接收队列已满，请重新连接");}
    }
    private void fail(String message){if(!closed.get())listener.status(message);close();}
    @Override public void close(){shutdown(true);}
    private void shutdown(boolean abort){
        if(!closed.compareAndSet(false,true))return;
        WebSocket ws=socket;if(ws!=null){ws.close(1000,null);if(abort)ws.cancel();}
        worker.getQueue().clear();
        // Serialize wiping after any in-flight crypto/decode operation.
        try{worker.execute(session::close);}catch(RejectedExecutionException ignored){}
        worker.shutdown();http.dispatcher().executorService().shutdown();http.connectionPool().evictAll();
    }
}

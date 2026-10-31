package org.eyepqc.mobile;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;
import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.ResponseBody;

/** One authenticated HTTPS fetch; never follows redirects or touches the board session. */
public final class PairingClient implements AutoCloseable {
    public interface Listener { void received(PairingConfig config,byte[] json); void failed(String message); }
    private final OkHttpClient http=new OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
        .connectTimeout(10,TimeUnit.SECONDS).callTimeout(15,TimeUnit.SECONDS).build();
    public void fetch(String endpoint,String username,String password,byte[] previousPin,Listener listener)throws Exception {
        String authorization=StreamClient.accountAuthorization(endpoint,username,password);
        java.net.URI uri=new java.net.URI(endpoint);
        if(uri.getPort()==0||uri.getPort()>65535)throw new IllegalArgumentException("server port");
        String url="https://"+endpoint.substring(6,endpoint.length()-7)+"/pairing.json";
        http.newCall(new Request.Builder().url(url).header("Authorization",authorization).build()).enqueue(new Callback(){
            public void onFailure(Call call,IOException error){listener.failed(ConnectionMessages.transport(error));}
            public void onResponse(Call call,Response response){
                try(Response close=response){
                    if(response.code()!=200){listener.failed(response.code()==401?"账号或密码错误":"配置获取被拒绝 HTTP "+response.code());return;}
                    ResponseBody body=response.body();
                    if(body==null||body.contentLength()>PairingConfig.MAX_BYTES)throw new IOException("configuration size");
                    byte[] json;
                    try(InputStream in=body.byteStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                        byte[] buffer=new byte[1024];int count;
                        while((count=in.read(buffer))!=-1){if(out.size()+count>PairingConfig.MAX_BYTES)throw new IOException("configuration size");out.write(buffer,0,count);}
                        json=out.toByteArray();
                    }
                    listener.received(PairingConfig.fromServer(json,endpoint,previousPin),json);
                }catch(Exception error){listener.failed("配对配置无效或板卡身份已变化；请核对后可信手动导入");}
            }
        });
    }
    @Override public void close(){http.dispatcher().cancelAll();http.dispatcher().executorService().shutdown();http.connectionPool().evictAll();}
}

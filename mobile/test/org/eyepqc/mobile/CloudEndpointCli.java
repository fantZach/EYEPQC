package org.eyepqc.mobile;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Synthetic loopback TLS/HTTP failure adapter; credentials and identity are public fixtures. */
public final class CloudEndpointCli {
    public static void main(String[] args)throws Exception{
        if(args.length!=3)throw new IllegalArgumentException("endpoint expected-status explicit-takeover");
        CountDownLatch failed=new CountDownLatch(1),reset=new CountDownLatch(1),confirmation=new CountDownLatch(1);
        AtomicInteger confirmations=new AtomicInteger();byte[] key=new byte[800];
        try(StreamClient client=new StreamClient(key,Protocol.sha(key),new StreamClient.Listener(){
            public void frame(byte[] jpeg){throw new AssertionError("unexpected video");}
            public void status(String message){if(message.equals(args[1])||(args[1].equals("TLS")&&message.startsWith("TLS 证书校验失败")))failed.countDown();}
            public void reset(){reset.countDown();}
            public void takeoverRequired(){confirmations.incrementAndGet();confirmation.countDown();}
        },true)){
            client.connectAccount(args[0],"public-fixture-user","public-fixture-password",Boolean.parseBoolean(args[2]));
            if(!failed.await(8,TimeUnit.SECONDS)||!reset.await(2,TimeUnit.SECONDS))throw new AssertionError("failure did not close/reset");
            boolean conflict=args[1].equals("服务拒绝连接 HTTP 409");
            if(confirmation.await(conflict?2000:200,TimeUnit.MILLISECONDS)!=conflict||confirmations.get()!=(conflict?1:0))throw new AssertionError("unexpected takeover confirmation");
        }
        System.out.println("CLOUD_ENDPOINT_OK");
    }
}

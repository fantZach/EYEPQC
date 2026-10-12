package org.eyepqc.mobile;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Actual OkHttp transport smoke adapter: compares a public fixture hash, never prints a frame. */
public final class NetworkCli {
    public static void main(String[] args)throws Exception {
        if(args.length!=5&&args.length!=6)throw new IllegalArgumentException("NetworkCli <public-key path> <pin> <ws endpoint> <test token> <fixture JPEG sha256> [rekey]");
        final boolean rekey=args.length==6&&args[5].equals("rekey");
        final boolean stop=args.length==6&&args[5].equals("stop");
        if(args.length==6&&!rekey&&!stop)throw new IllegalArgumentException("unknown test mode");
        CountDownLatch done=new CountDownLatch(1);AtomicBoolean success=new AtomicBoolean();
        AtomicBoolean requested=new AtomicBoolean(),rotating=new AtomicBoolean();AtomicReference<StreamClient> owner=new AtomicReference<>();
        try(StreamClient client=new StreamClient(Files.readAllBytes(Paths.get(args[0])),Protocol.hex(args[1]),new StreamClient.Listener(){
            public void status(String message){if(message.equals("重新协商密钥"))rotating.set(true);if(stop&&message.equals("已停止")){success.set(true);done.countDown();}}
            public void frame(byte[] jpeg){
                try{
                    if((stop||rekey&&!rotating.get())&&requested.get())return;
                    if(!Protocol.hex(Protocol.sha(jpeg)).equals(args[4])){done.countDown();return;}
                    if(stop){if(requested.compareAndSet(false,true))owner.get().stop();}
                    else if(!rekey||rotating.get()){success.set(true);done.countDown();}
                    else if(requested.compareAndSet(false,true))owner.get().rekey();
                }catch(Exception ignored){done.countDown();}
            }
        })){
            owner.set(client);
            client.connect(args[2],args[3]);
            if(!done.await(20,TimeUnit.SECONDS)||!success.get())throw new AssertionError("authenticated fixture not received");
            System.out.println(stop?"ANDROID_NETWORK_STOP_OK":rekey?"ANDROID_NETWORK_REKEY_OK":"ANDROID_NETWORK_OK");
        }
    }
}

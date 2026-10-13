package org.eyepqc.mobile;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual OkHttp transport smoke adapter: compares a public fixture hash, never prints a frame. */
public final class NetworkCli {
    public static void main(String[] args)throws Exception {
        run(args,false);
    }
    static void run(String[] args,boolean account)throws Exception{
        final int required=account?6:5;
        if(args.length!=required&&args.length!=required+1)throw new IllegalArgumentException("NetworkCli key pin endpoint token/username [password] JPEGsha [rekey|stop]");
        final boolean timer=account&&args.length==required+1&&args[required].equals("timer");
        final boolean rekey=timer||args.length==required+1&&args[required].equals("rekey");
        final boolean stop=args.length==required+1&&args[required].equals("stop");
        if(args.length==required+1&&!rekey&&!stop)throw new IllegalArgumentException("unknown test mode");
        CountDownLatch done=new CountDownLatch(1);AtomicBoolean success=new AtomicBoolean();
        CountDownLatch resets=new CountDownLatch(rekey?2:1);AtomicInteger resetCount=new AtomicInteger();
        AtomicBoolean requested=new AtomicBoolean(),rotating=new AtomicBoolean();AtomicReference<StreamClient> owner=new AtomicReference<>();
        try(StreamClient client=new StreamClient(Files.readAllBytes(Paths.get(args[0])),Protocol.hex(args[1]),new StreamClient.Listener(){
            public void reset(){resetCount.incrementAndGet();resets.countDown();}
            public void status(String message){if(message.equals("重新协商密钥"))rotating.set(true);if(stop&&message.equals("已停止")){success.set(true);done.countDown();}}
            public void frame(byte[] jpeg){
                try{
                    if((stop||rekey&&!rotating.get())&&requested.get())return;
                    if(!Protocol.hex(Protocol.sha(jpeg)).equals(args[required-1])){done.countDown();return;}
                    if(stop){if(requested.compareAndSet(false,true)){if(account)owner.get().scheduleRotation(100);owner.get().stop();}}
                    else if(!rekey||rotating.get()){if(account&&!rekey)owner.get().scheduleRotation(100);success.set(!rekey||resetCount.get()==1);done.countDown();}
                    else if(requested.compareAndSet(false,true)){if(timer)owner.get().scheduleRotation(100);else owner.get().rekey();}
                }catch(Exception ignored){done.countDown();}
            }
        },account)){
            owner.set(client);
            if(account)client.connectAccount(args[2],args[3],args[4],false);else client.connect(args[2],args[3]);
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(20);boolean finished=false;
            while(System.nanoTime()<deadline){client.checkTimeout();if(done.await(100,TimeUnit.MILLISECONDS)){finished=true;break;}}
            if(!finished||!success.get())throw new AssertionError("authenticated fixture not received");
            System.out.println((account?"ACCOUNT_NETWORK":"ANDROID_NETWORK")+(stop?"_STOP_OK":rekey?"_REKEY_OK":"_OK"));
        }
        if(!resets.await(5,TimeUnit.SECONDS)||resetCount.get()!=(rekey?2:1))throw new AssertionError("session display reset missing or duplicated");
        if(account){Thread.sleep(250);if(resetCount.get()!=(rekey?2:1))throw new AssertionError("late rotation callback");for(Thread t:Thread.getAllStackTraces().keySet())if(t.isAlive()&&t.getName().equals("eyepqc-rotation"))throw new AssertionError("rotation timer survived close");}
    }
}

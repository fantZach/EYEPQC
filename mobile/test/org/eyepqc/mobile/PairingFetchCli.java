package org.eyepqc.mobile;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** JVM HTTPS integration probe; no Android UI, USB, or video session. */
public final class PairingFetchCli {
    public static void main(String[] args)throws Exception {
        if(args.length!=3&&args.length!=4)throw new IllegalArgumentException("endpoint success|failure previous-pin|- [credential-file]");
        String[] login=args.length==4?LiveProbe.accountCredentials(new String(Files.readAllBytes(Paths.get(args[3])),StandardCharsets.UTF_8)):
            new String[]{"public-fixture-user","public-fixture-password"};
        CountDownLatch done=new CountDownLatch(1);
        AtomicReference<PairingConfig> received=new AtomicReference<>();
        AtomicReference<String> failure=new AtomicReference<>();
        try(PairingClient client=new PairingClient()){
            client.fetch(args[0],login[0],login[1],args[2].equals("-")?null:Protocol.hex(args[2]),new PairingClient.Listener(){
                public void received(PairingConfig config,byte[] json){received.set(config);done.countDown();}
                public void failed(String message){failure.set(message);done.countDown();}
            });
            if(!done.await(20,TimeUnit.SECONDS))throw new AssertionError("pairing deadline");
            if(args[1].equals("success")){
                if(received.get()==null||failure.get()!=null||received.get().version!=2||!received.get().endpoint.equals(args[0]))throw new AssertionError("pairing fetch rejected");
            }else if(!args[1].equals("failure")||received.get()!=null||failure.get()==null)throw new AssertionError("pairing rejection missing");
        }
        java.util.Arrays.fill(login,null);
        System.out.println("PAIRING_FETCH_OK expected="+args[1]);
    }
}

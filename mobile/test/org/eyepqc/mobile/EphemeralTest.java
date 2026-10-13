package org.eyepqc.mobile;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** Public NIST keys only; deterministic bootstrap and independent temporary KEM KAT. */
public final class EphemeralTest {
    private static int checks;
    private static void check(boolean ok){checks++;if(!ok)throw new AssertionError("ephemeral check "+checks);}
    private interface Action{void run()throws Exception;}
    private static void reject(Action action)throws Exception{try{action.run();throw new AssertionError("accepted");}catch(IllegalArgumentException|IllegalStateException|javax.crypto.AEADBadTagException expected){checks++;}}
    private static byte[] value(JsonObject v,String name){return Protocol.hex(v.get(name).getAsString());}
    private static final class Fixture implements AutoCloseable{
        final Session client;final byte[] th,bootstrap,offer;final JsonObject temporary;
        Fixture(JsonObject identity,JsonObject temporary)throws Exception{
            this.temporary=temporary;byte[] key=value(identity,"ek");
            SecureRandom random=new SecureRandom(){int call;public void nextBytes(byte[] b){if(b.length!=32)throw new AssertionError("RNG size");if(call==0)Arrays.fill(b,(byte)1);else System.arraycopy(value(call==1?identity:temporary,"m"),0,b,0,32);call++;}};
            client=new Session(key,Protocol.sha(key),frame->{check(Arrays.equals(frame,new byte[]{-1,-40,-1,-39}));Session.wipe(frame);},random,2);
            byte[] hello=Protocol.unwrap(client.start()),ack=Protocol.control(2,Protocol.join(new byte[]{1,1,0,2},new byte[32]));
            byte[] kem=Protocol.unwrap(client.receive(Protocol.wrap(1,ack)).get(0));check(Arrays.equals(Arrays.copyOfRange(kem,12,780),value(identity,"c")));
            th=Protocol.sha(Protocol.join(Protocol.ascii("EYEPQC v1"),Protocol.sha(key),hello,ack,kem));bootstrap=Session.derive(value(identity,"k"),th);
            List<byte[]> finished=client.receive(Protocol.wrap(1,Protocol.control(4,Protocol.mac(Arrays.copyOfRange(bootstrap,16,48),Protocol.ascii("board finished"),th))));
            check(finished.size()==1&&Protocol.controlType(Protocol.unwrap(finished.get(0)))==5&&!client.streaming());
            offer=Protocol.control(10,Protocol.join(th,value(temporary,"ek"),new byte[32]));
            byte[] mac=Protocol.mac(Arrays.copyOfRange(bootstrap,16,48),Protocol.ascii("EYEPQC eph offer v1"),th,Arrays.copyOf(offer,844));System.arraycopy(mac,0,offer,844,32);
        }
        byte[] business()throws Exception{
            byte[] reply=Protocol.unwrap(client.receive(Protocol.wrap(1,offer)).get(0));check(Protocol.controlType(reply)==11&&reply.length==844);
            check(Arrays.equals(Arrays.copyOfRange(reply,44,812),value(temporary,"c")));
            check(Arrays.equals(Arrays.copyOfRange(reply,812,844),Protocol.mac(Arrays.copyOfRange(bootstrap,16,48),Protocol.ascii("EYEPQC eph reply v1"),th,offer,Arrays.copyOf(reply,812))));
            byte[] businessTH=Protocol.sha(Protocol.join(Protocol.ascii("EYEPQC eph business v1"),th,offer,reply)),material=Session.derive(value(temporary,"k"),businessTH);
            check(!Arrays.equals(bootstrap,material));
            List<byte[]> finalMessages=client.receive(Protocol.wrap(1,Protocol.control(4,Protocol.mac(Arrays.copyOfRange(material,16,48),Protocol.ascii("board finished"),businessTH))));
            check(finalMessages.size()==2&&client.streaming());check(Protocol.controlType(Protocol.unwrap(finalMessages.get(1)))==6);
            check(Arrays.equals(Protocol.unwrap(finalMessages.get(0)),Protocol.control(5,Protocol.mac(Arrays.copyOfRange(material,16,48),Protocol.ascii("host finished"),businessTH))));return material;
        }
        public void close(){client.close();Session.wipe(bootstrap);}
    }
    private static byte[] video(byte[] material)throws Exception{
        byte[] header=ByteBuffer.allocate(40).put(new byte[]{1,1,0,40}).put(material,52,4).putInt(0).putShort((short)0).putShort((short)1).putInt(4).putShort((short)4).putShort((short)0).putLong(0).putLong(0).array();
        byte[] nonce=ByteBuffer.allocate(12).put(material,48,4).putLong(0).array();Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(Arrays.copyOf(material,16),"AES"),new GCMParameterSpec(128,nonce));c.updateAAD(header);
        return Protocol.wrap(2,Protocol.join(header,c.doFinal(new byte[]{-1,-40,-1,-39})));
    }
    public static void main(String[] args)throws Exception{
        JsonArray vectors=JsonParser.parseString(new String(Files.readAllBytes(Paths.get(args[0],"data/kat/nist_mlkem512.json")),StandardCharsets.UTF_8)).getAsJsonObject().getAsJsonArray("encapsulation");
        JsonObject identity=vectors.get(0).getAsJsonObject(),temporary=vectors.get(1).getAsJsonObject();
        for(int run=0;run<6;run++)try(Fixture f=new Fixture(identity,temporary)){
            if(run==0){byte[] material=f.business();byte[] packet=video(material);f.client.receive(packet);check(f.client.completeFrames==1);reject(()->f.client.receive(packet));Session.wipe(material);}
            if(run==1){byte[] bad=f.offer.clone();bad[875]^=1;reject(()->f.client.receive(Protocol.wrap(1,bad)));check(!f.client.streaming());}
            if(run==2){byte[] bad=f.offer.clone();bad[12]^=1;reject(()->f.client.receive(Protocol.wrap(1,bad)));}
            if(run==3){f.client.receive(Protocol.wrap(1,f.offer));reject(()->f.client.receive(Protocol.wrap(1,f.offer)));}
            if(run==4)reject(()->f.client.receive(video(f.bootstrap)));
            if(run==5){f.client.receive(Protocol.wrap(1,f.offer));reject(()->f.client.receive(Protocol.wrap(1,Protocol.control(4,Protocol.mac(Arrays.copyOfRange(f.bootstrap,16,48),Protocol.ascii("board finished"),f.th)))));}
        }
        byte[] key=value(identity,"ek");try(Session s=new Session(key,Protocol.sha(key),frame->{},true)){s.start();reject(()->s.receive(Protocol.wrap(1,Protocol.control(2,Protocol.join(new byte[]{1,1,0,1},new byte[32])))));}
        reject(()->Protocol.controlType(Protocol.control(10,new byte[863])));reject(()->Protocol.controlType(Protocol.control(11,new byte[831])));
        check(StreamClient.accountAuthorization("wss://example.org/stream","viewer","password").equals("Basic dmlld2VyOnBhc3N3b3Jk"));
        reject(()->StreamClient.accountAuthorization("ws://127.0.0.1/stream","viewer","password"));reject(()->StreamClient.accountAuthorization("wss://example.org/stream","a:b","password"));reject(()->StreamClient.accountAuthorization("wss://example.org/stream","viewer","bad\npassword"));
        java.util.concurrent.CountDownLatch expired=new java.util.concurrent.CountDownLatch(1),cleaned=new java.util.concurrent.CountDownLatch(1);
        try(StreamClient client=new StreamClient(key,Protocol.sha(key),new StreamClient.Listener(){public void frame(byte[] frame){throw new AssertionError("expired frame");}public void status(String message){if(message.equals("业务密钥已到期，请重新连接"))expired.countDown();}public void reset(){cleaned.countDown();}},true)){
            java.lang.reflect.Field deadline=StreamClient.class.getDeclaredField("businessExpires");deadline.setAccessible(true);deadline.setLong(client,System.nanoTime()-1);client.checkTimeout();
            check(expired.await(5,java.util.concurrent.TimeUnit.SECONDS));check(cleaned.await(5,java.util.concurrent.TimeUnit.SECONDS));
        }
        if(args.length==2){
            JsonObject fixture=JsonParser.parseString(new String(Files.readAllBytes(Paths.get(args[1])),StandardCharsets.UTF_8)).getAsJsonObject();
            if(!fixture.get("test_only").getAsBoolean())throw new IllegalArgumentException("public test fixture required");
            byte[] fixtureKey=value(fixture,"identity_public_key");
            SecureRandom random=new SecureRandom(){int call;public void nextBytes(byte[] b){if(b.length!=32)throw new AssertionError("fixture RNG");byte[] source=call==0?Arrays.copyOfRange(value(fixture,"hello"),16,48):call==1?value(identity,"m"):value(fixture,"encaps_coins");System.arraycopy(source,0,b,0,32);call++;}};
            try(Session s=new Session(fixtureKey,Protocol.sha(fixtureKey),frame->{check(Arrays.equals(frame,new byte[]{-1,-40,-1,-39}));Session.wipe(frame);},random,2)){
                check(Arrays.equals(Protocol.unwrap(s.start()),value(fixture,"hello")));
                check(Arrays.equals(Protocol.unwrap(s.receive(Protocol.wrap(1,value(fixture,"ack"))).get(0)),value(fixture,"identity_kem")));
                List<byte[]> messages=s.receive(Protocol.wrap(1,value(fixture,"bootstrap_board_finished")));check(messages.size()==1&&!s.streaming());check(Arrays.equals(Protocol.unwrap(messages.get(0)),value(fixture,"bootstrap_host_finished")));
                check(Arrays.equals(Protocol.unwrap(s.receive(Protocol.wrap(1,value(fixture,"offer"))).get(0)),value(fixture,"reply")));
                messages=s.receive(Protocol.wrap(1,value(fixture,"business_board_finished")));check(messages.size()==2&&s.streaming());
                check(Arrays.equals(Protocol.unwrap(messages.get(0)),value(fixture,"business_host_finished")));check(Arrays.equals(Protocol.unwrap(messages.get(1)),value(fixture,"business_start")));
                s.receive(video(value(fixture,"business_material")));check(s.completeFrames==1);
            }
            System.out.println("EPHEMERAL_C_FIXTURE_OK");
        }
        System.out.println("EPHEMERAL_OK checks="+checks);
    }
}

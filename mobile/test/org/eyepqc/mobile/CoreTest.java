package org.eyepqc.mobile;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.bouncycastle.crypto.SecretWithEncapsulation;
import org.bouncycastle.pqc.crypto.mlkem.MLKEMGenerator;
import org.bouncycastle.pqc.crypto.mlkem.MLKEMParameters;
import org.bouncycastle.pqc.crypto.mlkem.MLKEMPublicKeyParameters;

/** Public KATs and adversarial wire tests; no board access or actual provisioning material. */
public final class CoreTest {
    private static int checks;
    private static void check(boolean ok){checks++;if(!ok)throw new AssertionError("check "+checks);}
    private interface Action {void run()throws Exception;}
    private static void rejects(Action a)throws Exception{try{a.run();throw new AssertionError("accepted invalid input");}catch(IllegalArgumentException|IllegalStateException|javax.crypto.AEADBadTagException expected){checks++;}}
    private static byte[] value(JsonObject o,String key){return Protocol.hex(o.get(key).getAsString());}
    private static JsonObject json(String path)throws Exception{return JsonParser.parseString(new String(Files.readAllBytes(Paths.get(path)),StandardCharsets.UTF_8)).getAsJsonObject();}
    private static byte[] encrypt(byte[] key,byte[] nonce,byte[] aad,byte[] text)throws Exception{Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(key,"AES"),new GCMParameterSpec(128,nonce));c.updateAAD(aad);return c.doFinal(text);}
    private static final class FixedRandom extends SecureRandom {
        private final byte[] coins;private int calls;
        FixedRandom(byte[] m){coins=m;}
        @Override public void nextBytes(byte[] bytes){if(bytes.length!=32)throw new AssertionError("unexpected RNG request");if(calls++==0)Arrays.fill(bytes,(byte)1);else System.arraycopy(coins,0,bytes,0,32);}
    }
    private static final class Fixture implements AutoCloseable {
        final Session client; final List<byte[]> frames=new ArrayList<>();final byte[] material;
        Fixture(JsonObject vector)throws Exception{
            byte[] pk=value(vector,"ek"),ack=Protocol.control(2,Protocol.join(new byte[]{1,1,0,1},repeat(2,32)));
            client=new Session(pk,Protocol.sha(pk),frames::add,new FixedRandom(value(vector,"m")));
            byte[] hello=Protocol.unwrap(client.start());List<byte[]> kem=client.receive(Protocol.wrap(1,ack));
            check(kem.size()==1);check(Arrays.equals(Arrays.copyOfRange(Protocol.unwrap(kem.get(0)),12,780),value(vector,"c")));
            byte[] transcript=Protocol.sha(Protocol.join(Protocol.ascii("EYEPQC v1"),Protocol.sha(pk),hello,ack,Protocol.unwrap(kem.get(0))));
            material=Session.derive(value(vector,"k"),transcript);
            check(Protocol.hex(transcript).equals("0555deee9cf871afdf53033dd557e7726fd16c001d03847cb7a872166179585e"));
            check(Protocol.hex(material).equals("dc958af9bb22925646ede9123f5189f354e5204533136122e82a25cf70fbe452dca3f83f5f553f5b9e9e562b808f5778159be0c4f09350f3"));
            byte[] ck=Arrays.copyOfRange(material,16,48);
            byte[] finished=Protocol.control(4,Protocol.mac(ck,Protocol.ascii("board finished"),transcript));
            List<byte[]> replies=client.receive(Protocol.wrap(1,finished));check(replies.size()==2&&client.streaming());
            check(Arrays.equals(Protocol.unwrap(replies.get(0)),Protocol.control(5,Protocol.mac(ck,Protocol.ascii("host finished"),transcript))));
            byte[] start=Protocol.unwrap(replies.get(1));check(Protocol.controlType(start)==6);
            check(Arrays.equals(Arrays.copyOfRange(start,20,52),Protocol.mac(ck,Protocol.ascii("host command"),transcript,Arrays.copyOf(start,12),new byte[8])));
        }
        byte[] video(byte[] jpeg,int pid,long seq,long frameId,long timestamp)throws Exception{
            return packet(material,jpeg,pid,seq,frameId,timestamp);
        }
        @Override public void close(){client.close();Session.wipe(material);}
    }
    private static byte[] packet(byte[] material,byte[] jpeg,int pid,long seq,long frameId,long timestamp)throws Exception{
            int payload=Math.min(1400,jpeg.length-pid*1400);
            ByteBuffer fields=ByteBuffer.allocate(40).put((byte)1).put((byte)1).putShort((short)40).put(Arrays.copyOfRange(material,52,56)).putInt((int)frameId).putShort((short)pid).putShort((short)((jpeg.length+1399)/1400)).putInt(jpeg.length).putShort((short)payload).putShort((short)0).putLong(timestamp).putLong(seq);
            byte[] nonce=ByteBuffer.allocate(12).put(Arrays.copyOfRange(material,48,52)).putLong(seq).array();
            return Protocol.wrap(2,Protocol.join(fields.array(),encrypt(Arrays.copyOf(material,16),nonce,fields.array(),Arrays.copyOfRange(jpeg,pid*1400,pid*1400+payload))));
    }
    private static byte[] repeat(int n,int count){byte[] b=new byte[count];Arrays.fill(b,(byte)n);return b;}
    public static void main(String[] args)throws Exception{
        String root=args.length==0?".":args[0];JsonArray kem=json(root+"/data/kat/nist_mlkem512.json").getAsJsonArray("encapsulation");
        int kemCount=0,gcmCount=0;
        for(com.google.gson.JsonElement entry:kem){JsonObject v=entry.getAsJsonObject();byte[] pk=value(v,"ek");SecretWithEncapsulation encaps=new MLKEMGenerator(new SecureRandom()).internalGenerateEncapsulated(new MLKEMPublicKeyParameters(MLKEMParameters.ml_kem_512,pk),value(v,"m"));try{check(Arrays.equals(encaps.getEncapsulation(),value(v,"c")));check(Arrays.equals(encaps.getSecret(),value(v,"k")));kemCount++;}finally{encaps.destroy();}}
        for(com.google.gson.JsonElement entry:json(root+"/data/kat/nist_gcm.json").getAsJsonArray("vectors")){JsonObject v=entry.getAsJsonObject();check(Arrays.equals(encrypt(value(v,"key"),value(v,"nonce"),value(v,"aad"),value(v,"plaintext")),Protocol.join(value(v,"ciphertext"),value(v,"tag"))));gcmCount++;}
        JsonObject vector=kem.get(0).getAsJsonObject();byte[] pk=value(vector,"ek");
        FixedRandom retryRandom=new FixedRandom(value(vector,"m"));Session retry=new Session(pk,Protocol.sha(pk),ignored->{},retryRandom);
        rejects(()->retry.retryHello());byte[] firstHello=retry.start();
        check(retry.waitingAck()&&Arrays.equals(firstHello,retry.retryHello())&&Arrays.equals(firstHello,retry.retryHello()));
        check(retryRandom.calls==1); // Retransmission must not consume randomness or change transcript.
        byte[] retryAck=Protocol.control(2,Protocol.join(new byte[]{1,1,0,1},repeat(2,32)));
        byte[] retryKem=Protocol.unwrap(retry.receive(Protocol.wrap(1,retryAck)).get(0));
        check(Arrays.equals(Arrays.copyOfRange(retryKem,12,780),value(vector,"c"))&&!retry.waitingAck());
        rejects(()->retry.retryHello());check(retry.receive(Protocol.wrap(1,retryAck)).isEmpty()&&retryRandom.calls==2);
        byte[] retryTranscript=Protocol.sha(Protocol.join(Protocol.ascii("EYEPQC v1"),Protocol.sha(pk),Protocol.unwrap(firstHello),retryAck,retryKem));
        byte[] retryMaterial=Session.derive(value(vector,"k"),retryTranscript);
        check(retry.receive(Protocol.wrap(1,Protocol.control(4,Protocol.mac(Arrays.copyOfRange(retryMaterial,16,48),Protocol.ascii("board finished"),retryTranscript)))).size()==2&&retry.streaming());
        rejects(()->retry.receive(Protocol.wrap(1,retryAck)));check(!retry.streaming());Session.wipe(retryMaterial);
        Session changedAck=new Session(pk,Protocol.sha(pk),ignored->{});changedAck.start();changedAck.receive(Protocol.wrap(1,retryAck));
        byte[] differentAck=retryAck.clone();differentAck[differentAck.length-1]^=1;
        rejects(()->changedAck.receive(Protocol.wrap(1,differentAck)));rejects(()->changedAck.retryHello());
        rejects(()->new Session(pk,new byte[32],jpeg->{}));
        rejects(()->Protocol.unwrap(new byte[]{1,0,4,1}));rejects(()->Protocol.unwrap(new byte[]{3,0,1,1}));
        rejects(()->Protocol.controlType(Protocol.control(3,new byte[767])));
        byte[] jpeg=repeat(7,1410);jpeg[0]=(byte)255;jpeg[1]=(byte)216;jpeg[1408]=(byte)255;jpeg[1409]=(byte)217;
        try(Fixture f=new Fixture(vector)){
            f.client.receive(f.video(jpeg,1,1,0,123));check(f.frames.isEmpty());
            f.client.receive(f.video(jpeg,0,0,0,123));check(f.frames.size()==1&&Arrays.equals(f.frames.get(0),jpeg));
            rejects(()->f.client.receive(f.video(jpeg,0,0,0,123)));check(!f.client.streaming());
        }
        try(Fixture f=new Fixture(vector)){byte[] packet=f.video(jpeg,0,0,0,123);packet[packet.length-1]^=1;rejects(()->f.client.receive(packet));check(f.frames.isEmpty()&&!f.client.streaming());}
        try(Fixture f=new Fixture(vector)){f.client.receive(f.video(jpeg,0,0,0,123));rejects(()->f.client.receive(f.video(jpeg,1,1,0,124)));check(f.frames.isEmpty());}
        try(Fixture f=new Fixture(vector)){f.client.receive(f.video(jpeg,0,0,0,123));f.client.receive(f.video(jpeg,0,1,1,124));check(f.client.droppedFrames==1);f.client.receive(f.video(jpeg,1,2,1,124));check(f.frames.size()==1);check(Protocol.controlType(Protocol.unwrap(f.client.stop()))==7&&!f.client.streaming());rejects(()->f.client.stop());}
        try(Fixture f=new Fixture(vector)){check(Protocol.controlType(Protocol.unwrap(f.client.rekey()))==8&&!f.client.streaming());check(Protocol.controlType(Protocol.unwrap(f.client.start()))==1);}
        try(Fixture f=new Fixture(vector)){
            byte[] old=f.video(jpeg,0,0,0,123);f.client.rekey();byte[] hello=Protocol.unwrap(f.client.start());
            check(f.client.receive(old).isEmpty()&&f.frames.isEmpty());
            byte[] ack=Protocol.control(2,Protocol.join(new byte[]{1,1,0,1},repeat(3,32)));
            byte[] kemRecord=Protocol.unwrap(f.client.receive(Protocol.wrap(1,ack)).get(0));
            byte[] transcript=Protocol.sha(Protocol.join(Protocol.ascii("EYEPQC v1"),Protocol.sha(pk),hello,ack,kemRecord));
            byte[] fresh=Session.derive(value(vector,"k"),transcript);
            check(!Arrays.equals(fresh,f.material));
            List<byte[]> replies=f.client.receive(Protocol.wrap(1,Protocol.control(4,Protocol.mac(Arrays.copyOfRange(fresh,16,48),Protocol.ascii("board finished"),transcript))));
            check(replies.size()==2&&f.client.streaming());
            f.client.receive(packet(fresh,jpeg,0,0,0,1));f.client.receive(packet(fresh,jpeg,1,1,0,1));
            check(f.frames.size()==1&&Arrays.equals(f.frames.get(0),jpeg));
            rejects(()->f.client.receive(old));Session.wipe(fresh);
        }
        Session idle=new Session(pk,Protocol.sha(pk),ignored->{});rejects(()->idle.receive(Protocol.wrap(2,new byte[57])));idle.start();rejects(()->idle.receive(Protocol.wrap(1,Protocol.control(4,new byte[32]))));
        Session badFinished=new Session(pk,Protocol.sha(pk),ignored->{});badFinished.start();badFinished.receive(Protocol.wrap(1,Protocol.control(2,Protocol.join(new byte[]{1,1,0,1},repeat(2,32)))));rejects(()->badFinished.receive(Protocol.wrap(1,Protocol.control(4,new byte[32]))));
        StreamClient.validateEndpoint("ws://192.168.1.2:8765/stream");StreamClient.validateEndpoint("ws://100.64.1.2:8765/stream");StreamClient.validateEndpoint("wss://example.org/stream");
        rejects(()->StreamClient.validateEndpoint("ws://8.8.8.8/stream"));rejects(()->StreamClient.validateEndpoint("ws://example.org/stream"));rejects(()->StreamClient.validateEndpoint("wss://example.org/wrong"));
        CountDownLatch reset=new CountDownLatch(1);AtomicInteger resets=new AtomicInteger();
        try(StreamClient failed=new StreamClient(pk,Protocol.sha(pk),new StreamClient.Listener(){
            public void frame(byte[] frame){throw new AssertionError("frame after failed connection");}
            public void status(String message){}
            public void reset(){resets.incrementAndGet();reset.countDown();}
        })){
            failed.connect("ws://8.8.8.8/stream","public-test-token");
            check(reset.await(5,TimeUnit.SECONDS));failed.close();failed.close();
            check(resets.get()==1);
        }
        System.out.println("ANDROID_CORE_OK checks="+checks+" MLKEM_KAT="+kemCount+" GCM_KAT="+gcmCount);
    }
}

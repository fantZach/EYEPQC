package org.eyepqc.mobile;

import java.nio.ByteBuffer;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.bouncycastle.crypto.SecretWithEncapsulation;
import org.bouncycastle.pqc.crypto.mlkem.MLKEMGenerator;
import org.bouncycastle.pqc.crypto.mlkem.MLKEMParameters;
import org.bouncycastle.pqc.crypto.mlkem.MLKEMPublicKeyParameters;

/** Single-worker session. Only authenticated, complete JPEG frames leave this class. */
public final class Session implements AutoCloseable {
    public interface Frames { void frame(byte[] jpeg); }
    private final byte[] pk;
    private final SecureRandom random;
    private final Frames frames;
    private int state; // 0 idle, 1 waiting ACK, 2 waiting board Finished, 3 streaming
    private byte[] hello, cachedAck, transcript, previousTranscript, videoKey, controlKey;
    private int epoch, sessionId;
    private long commandSequence, high;
    private long seen;
    private boolean received;
    private boolean rekeyDrain;
    private int drainingSessionId;
    private long frameId=-1, timestamp;
    private int frameLength, packetCount, got;
    private byte[] frame;
    private boolean[] packets;
    public long authenticatedPackets, completeFrames, droppedFrames;

    public Session(byte[] key, byte[] pin, Frames listener) throws Exception { this(key,pin,listener,new SecureRandom()); }
    Session(byte[] key, byte[] pin, Frames listener, SecureRandom rng) throws Exception {
        if (key.length!=800 || pin.length!=32 || !MessageDigest.isEqual(Protocol.sha(key),pin)) throw new IllegalArgumentException("board public-key pin mismatch");
        pk=key.clone(); frames=listener; random=rng;
    }
    public boolean streaming() { return state==3; }
    public boolean waitingAck() { return state==1; }
    public byte[] retryHello() {
        if(state!=1||hello==null)throw new IllegalStateException("not waiting for HELLO_ACK");
        return Protocol.wrap(1,hello);
    }
    public byte[] start() throws Exception {
        if(state!=0)throw new IllegalStateException("session already active");
        byte[] fresh=new byte[32]; random.nextBytes(fresh);
        hello=Protocol.control(1,Protocol.join(new byte[]{1,1,0,1},fresh)); wipe(fresh); state=1;
        return Protocol.wrap(1,hello);
    }
    public List<byte[]> receive(byte[] message) throws Exception {
        try {
            byte[] record=Protocol.unwrap(message); List<byte[]> replies=new ArrayList<>();
            if(message[0]==2) {
                // REKEY and HELLO share the ordered stream with already queued old video.
                if(rekeyDrain && state==1 && drainOldVideo(record))return replies;
                video(record); return replies;
            }
            int type=Protocol.controlType(record);
            if(type==9)throw new IllegalArgumentException("board reported error");
            if(state==2&&type==2&&cachedAck!=null&&Arrays.equals(record,cachedAck))return replies;
            if(state==1 && type==2) {
                if(!Arrays.equals(Arrays.copyOfRange(record,12,16),new byte[]{1,1,0,1}))throw new IllegalArgumentException("board suite mismatch");
                SecretWithEncapsulation result=null; byte[] shared=null, material=null;
                try {
                    result=new MLKEMGenerator(random).generateEncapsulated(new MLKEMPublicKeyParameters(MLKEMParameters.ml_kem_512,pk));
                    byte[] kem=Protocol.control(3,result.getEncapsulation()); shared=result.getSecret();
                    transcript=Protocol.sha(Protocol.join(Protocol.ascii("EYEPQC v1"),Protocol.sha(pk),hello,record,kem));
                    if(previousTranscript!=null && MessageDigest.isEqual(previousTranscript,transcript))throw new IllegalArgumentException("replayed handshake");
                    material=derive(shared,transcript); videoKey=Arrays.copyOfRange(material,0,16); controlKey=Arrays.copyOfRange(material,16,48);
                    ByteBuffer b=ByteBuffer.wrap(material,48,8);epoch=b.getInt();sessionId=b.getInt();cachedAck=record;state=2;rekeyDrain=false;
                    replies.add(Protocol.wrap(1,kem));
                } finally { wipe(shared);wipe(material);if(result!=null)result.destroy(); }
            } else if(state==2 && type==4) {
                byte[] expected=Protocol.mac(controlKey,Protocol.ascii("board finished"),transcript);
                boolean valid=MessageDigest.isEqual(expected,Arrays.copyOfRange(record,12,44));wipe(expected);
                if(!valid)throw new IllegalArgumentException("board Finished authentication failed");
                replies.add(Protocol.wrap(1,Protocol.control(5,Protocol.mac(controlKey,Protocol.ascii("host finished"),transcript))));
                replies.add(command(6));state=3;
            } else throw new IllegalArgumentException("unexpected control/state");
            return replies;
        } catch(Exception e) { close();throw e; }
    }
    static byte[] derive(byte[] shared,byte[] transcript) throws Exception {
        byte[] prk=Protocol.mac(transcript,shared),a=null,b=null;
        try { a=Protocol.mac(prk,Protocol.ascii("EYEPQC v1 keys"),new byte[]{1}); b=Protocol.mac(prk,a,Protocol.ascii("EYEPQC v1 keys"),new byte[]{2}); return Arrays.copyOf(Protocol.join(a,b),56); }
        finally {wipe(prk);wipe(a);wipe(b);}
    }
    private byte[] command(int type) throws Exception {
        if(commandSequence==-1L)throw new IllegalStateException("command counter exhausted");
        byte[] sequence=ByteBuffer.allocate(8).putLong(commandSequence++).array();
        byte[] prefix=Arrays.copyOf(Protocol.control(type,new byte[40]),12);
        return Protocol.wrap(1,Protocol.control(type,Protocol.join(sequence,Protocol.mac(controlKey,Protocol.ascii("host command"),transcript,prefix,sequence))));
    }
    public byte[] stop() throws Exception { if(state!=3)throw new IllegalStateException("not streaming");byte[] out=command(7);close();return out; }
    public byte[] rekey() throws Exception { if(state!=3)throw new IllegalStateException("not streaming");byte[] out=command(8);int oldSession=sessionId;close();drainingSessionId=oldSession;rekeyDrain=true;return out; }
    private boolean drainOldVideo(byte[] record) {
        if(record.length<57)return false;
        ByteBuffer b=ByteBuffer.wrap(record);
        if(b.get()!=1||b.get()!=1||b.getShort()!=40||b.getInt()!=drainingSessionId)return false;
        b.getInt();int pid=b.getShort()&65535,count=b.getShort()&65535,length=b.getInt(),payload=b.getShort()&65535;
        return length>=4&&length<=2097152&&count==(length+1399)/1400&&pid<count&&payload==Math.min(1400,length-pid*1400)&&b.getShort()==0&&record.length==40+payload+16;
    }
    private void video(byte[] record) throws Exception {
        if(state!=3 || record.length<57)throw new IllegalArgumentException("video before authentication/short video");
        ByteBuffer b=ByteBuffer.wrap(record);
        int version=b.get()&255,flags=b.get()&255,header=b.getShort()&65535,sid=b.getInt();
        long fid=Integer.toUnsignedLong(b.getInt());int pid=b.getShort()&65535,count=b.getShort()&65535,length=b.getInt(),payload=b.getShort()&65535,reserved=b.getShort()&65535;
        long ts=b.getLong(),sequence=b.getLong();
        if(version!=1||flags!=1||header!=40||sid!=sessionId||length<4||length>2097152||count!=(length+1399)/1400||pid>=count||reserved!=0||payload!=Math.min(1400,length-pid*1400)||record.length!=40+payload+16||Long.compareUnsigned(sequence,-65536L)>=0)throw new IllegalArgumentException("video header");
        byte[] nonce=ByteBuffer.allocate(12).putInt(epoch).putLong(sequence).array();
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,new SecretKeySpec(videoKey,"AES"),new GCMParameterSpec(128,nonce));c.updateAAD(record,0,40);
        byte[] plain=c.doFinal(record,40,record.length-40);
        try {
            if(!accept(sequence))throw new IllegalArgumentException("replayed video");
            authenticatedPackets++;
            if(frameId<0||fid>frameId) {
                if(frame!=null)droppedFrames++; clearFrame();frameId=fid;frameLength=length;packetCount=count;timestamp=ts;frame=new byte[length];packets=new boolean[count];
            }
            if(fid<frameId)return;
            if(frame==null)return; // Already delivered this frame.
            if(length!=frameLength||count!=packetCount||ts!=timestamp||packets[pid])throw new IllegalArgumentException("inconsistent frame");
            System.arraycopy(plain,0,frame,pid*1400,plain.length);packets[pid]=true;got++;
            if(got==count) {
                if(frame[0]!=(byte)255||frame[1]!=(byte)216||frame[length-2]!=(byte)255||frame[length-1]!=(byte)217)throw new IllegalArgumentException("JPEG markers");
                byte[] jpeg=frame;frame=null;packets=null;got=0;completeFrames++;frames.frame(jpeg);
            }
        } finally {wipe(plain);}
    }
    private boolean accept(long sequence) {
        if(!received){received=true;high=sequence;seen=1;return true;}
        if(Long.compareUnsigned(sequence,high)>0){long gap=sequence-high;seen=Long.compareUnsigned(gap,64)>=0?1:(seen<<(int)gap)|1;high=sequence;return true;}
        long gap=high-sequence;if(Long.compareUnsigned(gap,64)>=0||(seen&(1L<<(int)gap))!=0)return false;seen|=1L<<(int)gap;return true;
    }
    private void clearFrame(){wipe(frame);frame=null;packets=null;got=0;}
    static void wipe(byte[] b){if(b!=null)Arrays.fill(b,(byte)0);}
    @Override public void close(){if(transcript!=null)previousTranscript=transcript;wipe(videoKey);wipe(controlKey);videoKey=controlKey=null;transcript=hello=cachedAck=null;state=0;commandSequence=high=seen=0;received=rekeyDrain=false;drainingSessionId=0;frameId=-1;clearFrame();}
}

package org.eyepqc.mobile;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

public final class Protocol {
    private Protocol() {}
    public static byte[] ascii(String s) { return s.getBytes(StandardCharsets.US_ASCII); }
    public static byte[] join(byte[]... parts) {
        int n = 0; for (byte[] p : parts) n = Math.addExact(n, p.length);
        ByteBuffer out = ByteBuffer.allocate(n); for (byte[] p : parts) out.put(p); return out.array();
    }
    public static byte[] sha(byte[] b) throws Exception { return MessageDigest.getInstance("SHA-256").digest(b); }
    public static byte[] mac(byte[] key, byte[]... parts) throws Exception {
        Mac m = Mac.getInstance("HmacSHA256"); m.init(new SecretKeySpec(key, "HmacSHA256"));
        for (byte[] part : parts) m.update(part); return m.doFinal();
    }
    public static byte[] control(int type, byte[] body) {
        if (body.length > 1024) throw new IllegalArgumentException("control too long");
        return ByteBuffer.allocate(12 + body.length).put(ascii("EYPQ")).put((byte)1).put((byte)type).putShort((short)0).putInt(body.length).put(body).array();
    }
    public static int controlType(byte[] record) {
        if (record.length < 12 || record.length > 1036) throw new IllegalArgumentException("control length");
        ByteBuffer b = ByteBuffer.wrap(record);
        if (b.getInt() != 0x45595051 || b.get() != 1) throw new IllegalArgumentException("control version");
        int type = b.get() & 255;
        if (b.getShort() != 0 || b.getInt() != record.length - 12) throw new IllegalArgumentException("control header");
        int[] lengths = {0,36,36,768,32,32,40,40,40,0,864,832};
        if (type < 1 || type > 11 || (type != 9 && record.length != lengths[type]+12) || (type == 9 && record.length < 14)) throw new IllegalArgumentException("control type/body");
        return type;
    }
    public static byte[] wrap(int channel, byte[] record) {
        int limit = channel == 1 ? 1036 : channel == 2 ? 1456 : 0;
        if (record.length == 0 || record.length > limit) throw new IllegalArgumentException("USB record size");
        return ByteBuffer.allocate(3+record.length).put((byte)channel).putShort((short)record.length).put(record).array();
    }
    public static byte[] unwrap(byte[] message) {
        if (message.length < 4 || message.length > 1459) throw new IllegalArgumentException("network message size");
        int channel = message[0]&255, length = ((message[1]&255)<<8)|(message[2]&255);
        if (length != message.length-3 || (channel != 1 && channel != 2) || length > (channel == 1 ? 1036 : 1456)) throw new IllegalArgumentException("USB record header");
        return Arrays.copyOfRange(message,3,message.length);
    }
    public static byte[] hex(String text) {
        if ((text.length() & 1) != 0) throw new IllegalArgumentException("hex length");
        byte[] out = new byte[text.length()/2];
        for (int i=0;i<out.length;i++) { int a=Character.digit(text.charAt(i*2),16), b=Character.digit(text.charAt(i*2+1),16); if(a<0||b<0)throw new IllegalArgumentException("hex"); out[i]=(byte)((a<<4)|b); }
        return out;
    }
    public static String hex(byte[] bytes) {
        char[] out=new char[bytes.length*2], digits="0123456789abcdef".toCharArray();
        for(int i=0;i<bytes.length;i++){out[i*2]=digits[(bytes[i]&255)>>4];out[i*2+1]=digits[bytes[i]&15];}return new String(out);
    }
}

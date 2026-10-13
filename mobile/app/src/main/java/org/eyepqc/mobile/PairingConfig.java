package org.eyepqc.mobile;

import com.google.gson.Strictness;
import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonToken;
import java.io.StringReader;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;

/** A selected file is a trust decision; matching a bundled pin proves consistency only. */
public final class PairingConfig {
    public static final int MAX_BYTES=8192;
    public final String endpoint,token;
    public final byte[] publicKey,pin;
    private PairingConfig(String endpoint,String token,byte[] publicKey,byte[] pin){
        this.endpoint=endpoint;this.token=token;this.publicKey=publicKey;this.pin=pin;
    }
    public static PairingConfig parse(byte[] bytes)throws Exception {
        if(bytes.length==0||bytes.length>MAX_BYTES)throw new IllegalArgumentException("configuration size");
        String text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        Map<String,String> fields=new HashMap<>();
        try(JsonReader reader=new JsonReader(new StringReader(text))){
            reader.setStrictness(Strictness.STRICT);reader.beginObject();
            while(reader.hasNext()){
                String name=reader.nextName();
                if(fields.containsKey(name))throw new IllegalArgumentException("duplicate configuration field");
                if(name.equals("version")){
                    if(reader.peek()!=JsonToken.NUMBER||!reader.nextString().equals("1"))throw new IllegalArgumentException("configuration version");
                    fields.put(name,"1");
                }else{
                    if(!name.equals("endpoint")&&!name.equals("token")&&!name.equals("public_key_hex")&&!name.equals("public_key_sha256"))throw new IllegalArgumentException("unknown configuration field");
                    if(reader.peek()!=JsonToken.STRING)throw new IllegalArgumentException("configuration field type");
                    fields.put(name,reader.nextString());
                }
            }
            reader.endObject();
            if(reader.peek()!=JsonToken.END_DOCUMENT||fields.size()!=5)throw new IllegalArgumentException("incomplete or trailing configuration");
        }
        String endpoint=fields.get("endpoint"),token=fields.get("token"),keyHex=fields.get("public_key_hex"),pinHex=fields.get("public_key_sha256");
        StreamClient.validateEndpoint(endpoint);
        int port=new java.net.URI(endpoint).getPort();
        if(port==0||port>65535)throw new IllegalArgumentException("configuration port");
        if(token.length()<32||token.length()>256)throw new IllegalArgumentException("access token size");
        for(int i=0;i<token.length();i++)if(token.charAt(i)<33||token.charAt(i)>126)throw new IllegalArgumentException("access token format");
        if(!keyHex.matches("[0-9a-fA-F]{1600}")||!pinHex.matches("[0-9a-fA-F]{64}"))throw new IllegalArgumentException("public identity format");
        byte[] key=Protocol.hex(keyHex),pin=Protocol.hex(pinHex);
        if(!MessageDigest.isEqual(Protocol.sha(key),pin))throw new IllegalArgumentException("public-key pin mismatch");
        return new PairingConfig(endpoint,token,key,pin);
    }
}

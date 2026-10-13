package org.eyepqc.mobile;

import com.google.gson.JsonObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;

public final class PairingConfigTest {
    private static int checks;
    private static byte[] bytes(String json){return json.getBytes(StandardCharsets.UTF_8);}
    private static void reject(byte[] data)throws Exception {
        try{PairingConfig.parse(data);}catch(Exception expected){checks++;return;}
        throw new AssertionError("invalid configuration accepted");
    }
    public static void main(String[] args)throws Exception {
        byte[] key=new byte[800];Arrays.fill(key,(byte)3);
        JsonObject object=new JsonObject();object.addProperty("version",1);
        object.addProperty("endpoint","ws://10.179.236.247:8765/stream");
        object.addProperty("token","public-test-token-0123456789abcdef");
        object.addProperty("public_key_hex",Protocol.hex(key));object.addProperty("public_key_sha256",Protocol.hex(Protocol.sha(key)));
        String good=object.toString();PairingConfig config=PairingConfig.parse(bytes(good));
        if(!Arrays.equals(config.publicKey,key)||!config.token.equals(object.get("token").getAsString()))throw new AssertionError("configuration values");checks++;
        reject(bytes(good+"{}"));reject(bytes("//comment\n"+good));reject(bytes(good.replace("\"version\":1","\"version\":1,\"version\":1")));
        reject(bytes(good.replace("\"version\":1","\"version\":\"1\"")));reject(bytes(good.replace("\"version\":1","\"version\":2")));
        reject(bytes("[]"));reject(bytes("null"));reject(new byte[8193]);reject(new byte[]{(byte)0xff});
        for(String field:new String[]{"version","endpoint","token","public_key_hex","public_key_sha256"}){
            JsonObject missing=object.deepCopy();missing.remove(field);reject(bytes(missing.toString()));
            JsonObject wrong=object.deepCopy();wrong.add(field,com.google.gson.JsonNull.INSTANCE);reject(bytes(wrong.toString()));
        }
        for(String endpoint:new String[]{"ws://8.8.8.8/stream","ws://10.0.0.1:0/stream","wss://example.org:99999/stream","ws://10.0.0.1/stream?token=x"}){
            JsonObject wrong=object.deepCopy();wrong.addProperty("endpoint",endpoint);reject(bytes(wrong.toString()));
        }
        for(String token:new String[]{"short","a token contains spaces and is not acceptable!",new String(new char[257]).replace('\0','a')}){
            JsonObject wrong=object.deepCopy();wrong.addProperty("token",token);reject(bytes(wrong.toString()));
        }
        JsonObject wrong=object.deepCopy();wrong.addProperty("private_key_hex","do-not-import-secret-keys");reject(bytes(wrong.toString()));
        wrong=object.deepCopy();wrong.addProperty("public_key_hex","00");reject(bytes(wrong.toString()));
        wrong=object.deepCopy();wrong.addProperty("public_key_sha256",Protocol.hex(new byte[32]));reject(bytes(wrong.toString()));
        if(args.length==1){byte[] actual=Files.readAllBytes(Paths.get(args[0]));PairingConfig.parse(actual);checks++;}
        System.out.println("PAIRING_CONFIG_OK checks="+checks);
    }
}

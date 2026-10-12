package org.eyepqc.mobile;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Offline integration adapter only: FRAME contains public test fixture plaintext. */
public final class ClientCli {
    public static void main(String[] args) throws Exception {
        if(args.length!=2)throw new IllegalArgumentException("ClientCli <public-key path> <sha256 pin hex>");
        try(Session session=new Session(Files.readAllBytes(Paths.get(args[0])),Protocol.hex(args[1]),jpeg->System.out.println("FRAME "+Protocol.hex(jpeg)));
            BufferedReader in=new BufferedReader(new InputStreamReader(System.in))) {
            String line; while((line=in.readLine())!=null){
                if(line.equals("START"))send(session.start());
                else if(line.startsWith("RECEIVE "))for(byte[] reply:session.receive(Protocol.hex(line.substring(8))))send(reply);
                else if(line.equals("STOP"))send(session.stop());
                else if(line.equals("REKEY"))send(session.rekey());
                else if(line.equals("CLOSE"))break;
                else throw new IllegalArgumentException("unknown CLI command");
                System.out.println("READY");System.out.flush();
            }
        }
    }
    private static void send(byte[] record){System.out.println("SEND "+Protocol.hex(record));}
}

package org.eyepqc.mobile;

import com.google.gson.JsonObject;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Iterator;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import javax.imageio.stream.ImageInputStream;

/** JVM transport/decode probe only; never claims Android UI/device performance. */
public final class LiveProbe {
    static final class Measurement {
        final Path directory;
        long firstNano,lastNano,frames,maxGapNano;
        int width,height;
        String firstHash,lastHash;
        byte[] lastJpeg;
        boolean finishing;
        Measurement(Path directory){this.directory=directory;}
        synchronized void accept(byte[] jpeg,long arrival)throws Exception {
            if(finishing)return;
            if(jpeg.length<4||jpeg.length>2097152)throw new IllegalArgumentException("JPEG size");
            int decodedWidth,decodedHeight;
            try(ImageInputStream in=ImageIO.createImageInputStream(new ByteArrayInputStream(jpeg))){
                Iterator<ImageReader> readers=ImageIO.getImageReaders(in);
                if(!readers.hasNext())throw new IllegalArgumentException("JPEG reader");
                ImageReader reader=readers.next();
                try {
                    if(!reader.getFormatName().equalsIgnoreCase("JPEG"))throw new IllegalArgumentException("JPEG format");
                    reader.setInput(in,true,true);decodedWidth=reader.getWidth(0);decodedHeight=reader.getHeight(0);
                    if(decodedWidth<1||decodedHeight<1||decodedWidth>4096||decodedHeight>4096||(long)decodedWidth*decodedHeight>4194304)throw new IllegalArgumentException("JPEG dimensions");
                    BufferedImage decoded=reader.read(0);
                    if(decoded==null||decoded.getWidth()!=decodedWidth||decoded.getHeight()!=decodedHeight)throw new IllegalArgumentException("JPEG decode");
                    decoded.flush();
                } finally {reader.dispose();}
            }
            String hash=Protocol.hex(Protocol.sha(jpeg));
            if(frames==0){Files.write(directory.resolve("first.jpg"),jpeg);firstNano=arrival;firstHash=hash;}
            if(frames!=0)maxGapNano=Math.max(maxGapNano,arrival-lastNano);
            Session.wipe(lastJpeg);lastJpeg=jpeg.clone();lastHash=hash;lastNano=arrival;frames++;width=decodedWidth;height=decodedHeight;
        }
        synchronized long first(){return firstNano;}
        synchronized void finish(){finishing=true;}
        synchronized boolean passes(double seconds){return frames>=2&&(lastNano-firstNano)/1e9>=seconds*0.9&&maxGapNano<=TimeUnit.SECONDS.toNanos(5);}
        synchronized JsonObject result(double seconds,String failure)throws Exception {
            if(lastJpeg!=null)Files.write(directory.resolve("last.jpg"),lastJpeg);
            double span=frames<2?0:(lastNano-firstNano)/1e9;
            JsonObject out=new JsonObject();out.addProperty("outcome",failure==null&&passes(seconds)?"PASS":"FAIL");
            out.addProperty("client","JVM OkHttp + ImageIO (not Android device/UI)");out.addProperty("requested_seconds",seconds);
            out.addProperty("authenticated_decoded_frames",frames);out.addProperty("authenticated_decoded_span_seconds",span);
            out.addProperty("max_interframe_gap_seconds",maxGapNano/1e9);
            out.addProperty("authenticated_decoded_fps",span>0?(frames-1)/span:0);out.addProperty("width",width);out.addProperty("height",height);
            if(firstHash!=null)out.addProperty("first_jpeg_sha256",firstHash);if(lastHash!=null)out.addProperty("last_jpeg_sha256",lastHash);
            if(failure!=null)out.addProperty("failure",failure);else if(!passes(seconds))out.addProperty("failure","insufficient authenticated decoded duration or video gap over 5 seconds");
            Session.wipe(lastJpeg);lastJpeg=null;return out;
        }
    }
    private static byte[] publicJpeg(int width)throws Exception {
        BufferedImage image=new BufferedImage(width,8,BufferedImage.TYPE_INT_RGB);
        try(ByteArrayOutputStream out=new ByteArrayOutputStream()){if(!ImageIO.write(image,"JPEG",out))throw new AssertionError("no JPEG writer");return out.toByteArray();}
        finally{image.flush();}
    }
    private static void selfTest(Path base)throws Exception {
        String[] credentials=accountCredentials("username=fixture\npassword= keep spaces \n");
        if(!credentials[0].equals("fixture")||!credentials[1].equals(" keep spaces "))throw new AssertionError("credential parsing");
        for(String bad:new String[]{"username=fixture", "password=x\nusername=fixture", "username=\npassword=x", "username=fixture\npassword=x\nextra=value"}){
            try{accountCredentials(bad);throw new AssertionError("bad credential file accepted");}catch(IllegalArgumentException expected){}
        }
        Files.createDirectories(base);Path folder=Files.createTempDirectory(base,"live-probe-check-");byte[] jpeg=publicJpeg(8);
        Measurement good=new Measurement(folder);good.accept(jpeg,TimeUnit.SECONDS.toNanos(1));good.accept(jpeg,TimeUnit.SECONDS.toNanos(2));
        if(!good.passes(1)||good.passes(30))throw new AssertionError("duration threshold");
        good.finish();good.accept(jpeg,TimeUnit.SECONDS.toNanos(30));if(good.frames!=2)throw new AssertionError("late frame counted");
        JsonObject result=good.result(1,null);if(!result.get("outcome").getAsString().equals("PASS")||result.get("width").getAsInt()!=8||!Files.isRegularFile(folder.resolve("first.jpg"))||!Files.isRegularFile(folder.resolve("last.jpg")))throw new AssertionError("capture result");
        Measurement shortRun=new Measurement(folder);shortRun.accept(jpeg,TimeUnit.SECONDS.toNanos(1));shortRun.accept(jpeg,TimeUnit.SECONDS.toNanos(2));
        if(!shortRun.result(30,null).get("outcome").getAsString().equals("FAIL"))throw new AssertionError("short run passed");
        Measurement stalled=new Measurement(folder);stalled.accept(jpeg,TimeUnit.SECONDS.toNanos(1));stalled.accept(jpeg,TimeUnit.SECONDS.toNanos(31));
        if(stalled.passes(30))throw new AssertionError("stalled video passed");stalled.result(30,"public fixture stall");
        try{new Measurement(folder).accept(new byte[]{(byte)255,(byte)216,(byte)255,(byte)217},1);throw new AssertionError("malformed JPEG accepted");}catch(Exception expected){}
        try{new Measurement(folder).accept(publicJpeg(5000),1);throw new AssertionError("oversized JPEG accepted");}catch(IllegalArgumentException expected){}
        System.out.println("LIVE_PROBE_SELFTEST_OK");
    }
    public static void main(String[] args)throws Exception {
        boolean account=args.length==7&&args[0].equals("--account");
        if(account)args=java.util.Arrays.copyOfRange(args,1,args.length);
        if(args.length==2&&args[0].equals("--self-test")){selfTest(Paths.get(args[1]));return;}
        if(args.length!=6)throw new IllegalArgumentException("LiveProbe [--account] <public-key path> <pin> <endpoint> <credential-file> <capture-directory> <seconds>");
        double seconds=Double.parseDouble(args[5]);if(!Double.isFinite(seconds)||seconds<1||seconds>7200)throw new IllegalArgumentException("seconds must be 1..7200");
        Path keyFile=Paths.get(args[0]),tokenFile=Paths.get(args[3]),directory=Paths.get(args[4]);
        if(Files.size(keyFile)!=800||Files.size(tokenFile)>(account?2048:512))throw new IllegalArgumentException("public key/credential file size");
        Files.createDirectories(directory);
        for(String name:new String[]{"first.jpg","last.jpg","result.json"})if(Files.exists(directory.resolve(name)))throw new IllegalArgumentException("capture outputs already exist");
        byte[] tokenBytes=Files.readAllBytes(tokenFile);String token;
        try{token=new String(tokenBytes,StandardCharsets.UTF_8);if(!account)token=token.trim();}finally{Session.wipe(tokenBytes);}
        Measurement measurement=new Measurement(directory);AtomicBoolean failed=new AtomicBoolean(),stopping=new AtomicBoolean();
        CountDownLatch stopped=new CountDownLatch(1);
        String failure=null;
        try(StreamClient client=new StreamClient(Files.readAllBytes(keyFile),Protocol.hex(args[1]),new StreamClient.Listener(){
            public void frame(byte[] jpeg){try{measurement.accept(jpeg,System.nanoTime());}catch(Exception error){failed.set(true);throw new IllegalStateException("JPEG validation failed");}}
            public void status(String message){
                if(message.equals("已停止")){stopped.countDown();return;}
                if(!stopping.get()&&!message.equals("连接中")&&!message.equals("验证板卡中")&&!message.startsWith("已认证 /"))failed.set(true);
            }
        },account)){
            if(account){
                String[] fields=accountCredentials(token);
                client.connectAccount(args[2],fields[0],fields[1],false);
            }else client.connect(args[2],token);
            token=null;long connectionStart=System.nanoTime();
            while(!failed.get()){
                client.checkTimeout();long first=measurement.first(),now=System.nanoTime();
                if(first==0&&now-connectionStart>TimeUnit.SECONDS.toNanos(25)){failure="no authenticated decoded frame before deadline";break;}
                if(first!=0&&(now-first)/1e9>=seconds)break;
                Thread.sleep(50);
            }
            if(failed.get())failure="transport, authentication or JPEG decode failure";
            measurement.finish();
            if(failure==null){stopping.set(true);client.stop();if(!stopped.await(10,TimeUnit.SECONDS))failure="authenticated STOP was not queued before deadline";}
        } catch(Exception error){failure="probe setup/transport failure";measurement.finish();}
        JsonObject result=measurement.result(seconds,failure);
        Files.write(directory.resolve("result.json"),result.toString().getBytes(StandardCharsets.UTF_8));
        if(!result.get("outcome").getAsString().equals("PASS"))throw new AssertionError("LIVE_PROBE_FAIL: "+result.get("failure").getAsString());
        System.out.println("LIVE_PROBE_OK frames="+result.get("authenticated_decoded_frames")+" fps="+result.get("authenticated_decoded_fps")+" span="+result.get("authenticated_decoded_span_seconds")+" width="+result.get("width")+" height="+result.get("height"));
    }

    static String[] accountCredentials(String input){
        String[] fields=input.split("\\r?\\n");
        if(fields.length!=2||!fields[0].startsWith("username=")||!fields[1].startsWith("password=")||fields[0].length()<=9||fields[1].length()<=9)throw new IllegalArgumentException("credential file format");
        return new String[]{fields[0].substring(9),fields[1].substring(9)};
    }
}

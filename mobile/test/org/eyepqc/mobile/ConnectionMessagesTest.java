package org.eyepqc.mobile;

public final class ConnectionMessagesTest {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("connection diagnostics check "+checks);}
    public static void main(String[] args){
        check(ConnectionMessages.transport(new javax.net.ssl.SSLHandshakeException("private-password")).startsWith("TLS"));
        check(ConnectionMessages.transport(new java.io.IOException(new javax.net.ssl.SSLPeerUnverifiedException("secret"))).startsWith("TLS"));
        check(ConnectionMessages.transport(new java.net.SocketTimeoutException("secret")).contains("超时"));
        check(ConnectionMessages.transport(new java.net.UnknownHostException("secret")).contains("无法解析"));
        check(!ConnectionMessages.transport(new RuntimeException("private-password")).contains("private-password"));
        check(ConnectionMessages.transport(null).contains("网络连接失败"));
        RuntimeException cycle=new RuntimeException("secret");cycle.initCause(new RuntimeException(cycle));
        check(ConnectionMessages.transport(cycle).contains("网络连接失败"));
        System.out.println("CONNECTION_MESSAGES_OK checks="+checks);
    }
}

package org.eyepqc.mobile;

import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import javax.net.ssl.SSLException;

/** Static diagnostics only: never show throwable messages containing endpoints or credentials. */
final class ConnectionMessages {
    static String transport(Throwable error){
        for(int depth=0;error!=null&&depth<8;depth++,error=error.getCause()){
            if(error instanceof SSLException)return "TLS 证书校验失败：请检查证书期限、IP/域名和此版本信任的 CA；不要关闭校验";
            if(error instanceof SocketTimeoutException)return "网络连接超时：请检查 PC 服务、隧道和网络后手动重试";
            if(error instanceof UnknownHostException)return "服务器地址无法解析：请检查连接设置和网络";
        }
        return "网络连接失败：请检查 PC 服务、隧道和连接设置";
    }
}

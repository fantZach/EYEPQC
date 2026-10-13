package org.eyepqc.mobile;

/** Public-fixture WSS adapter; test CA uses the JVM trust store, never trust-all. */
public final class AccountNetworkCli {
    public static void main(String[] args)throws Exception{NetworkCli.run(args,true);}
}

package org.eyepqc.mobile;

/** UI-only action guards; the protocol client remains the security authority. */
final class ViewerState {
    enum Phase { IDLE, CONNECTING, LIVE, REKEYING, STOPPING, ERROR }
    private Phase phase=Phase.IDLE;
    Phase phase(){return phase;}
    boolean canConnect(){return phase==Phase.IDLE||phase==Phase.ERROR;}
    boolean canRekey(){return phase==Phase.LIVE;}
    boolean busy(){return phase==Phase.CONNECTING||phase==Phase.REKEYING;}
    boolean active(){return !canConnect();}
    boolean connect(){if(!canConnect())return false;phase=Phase.CONNECTING;return true;}
    boolean stop(){if(phase!=Phase.LIVE)return false;phase=Phase.STOPPING;return true;}
    boolean rekey(){if(!canRekey())return false;phase=Phase.REKEYING;return true;}
    void idle(){phase=Phase.IDLE;}
    void error(){phase=Phase.ERROR;}
    boolean client(StreamClient.State state){
        if(phase==Phase.IDLE||phase==Phase.ERROR)return false;
        if(phase==Phase.STOPPING&&state!=StreamClient.State.STOPPED&&state!=StreamClient.State.FAILED)return false;
        switch(state){
            case CONNECTING:case VERIFYING:if(phase!=Phase.REKEYING)phase=Phase.CONNECTING;break;
            case STREAMING:phase=Phase.LIVE;break;
            case REKEYING:phase=Phase.REKEYING;break;
            case STOPPED:phase=Phase.IDLE;break;
            case FAILED:phase=Phase.ERROR;break;
        }
        return true;
    }
}

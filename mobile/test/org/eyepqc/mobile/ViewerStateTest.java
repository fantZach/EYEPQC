package org.eyepqc.mobile;

public final class ViewerStateTest {
    private static int checks;
    private static void check(boolean value){checks++;if(!value)throw new AssertionError("viewer state check "+checks);}
    public static void main(String[] args){
        ViewerState state=new ViewerState();
        check(state.canConnect()&&!state.canRekey()&&!state.active());
        check(!state.stop()&&!state.rekey());
        check(state.connect()&&!state.connect()&&state.busy());
        state.client(StreamClient.State.CONNECTING);state.client(StreamClient.State.VERIFYING);
        check(!state.canConnect()&&!state.canRekey());
        state.client(StreamClient.State.STREAMING);
        check(state.canRekey()&&!state.canConnect()&&!state.busy());
        check(state.rekey()&&!state.rekey()&&state.busy());
        state.client(StreamClient.State.VERIFYING);
        check(state.phase()==ViewerState.Phase.REKEYING);
        state.client(StreamClient.State.REKEYING);state.client(StreamClient.State.STREAMING);
        check(state.canRekey());
        check(state.stop()&&!state.stop()&&!state.rekey());
        for(StreamClient.State late:new StreamClient.State[]{StreamClient.State.CONNECTING,StreamClient.State.VERIFYING,StreamClient.State.STREAMING,StreamClient.State.REKEYING}){
            check(!state.client(late));check(state.phase()==ViewerState.Phase.STOPPING&&!state.canConnect());
        }
        state.client(StreamClient.State.STOPPED);
        check(state.canConnect()&&!state.active());
        state.client(StreamClient.State.STREAMING);check(!state.canRekey());
        check(state.connect());state.client(StreamClient.State.FAILED);
        check(state.canConnect()&&state.phase()==ViewerState.Phase.ERROR);
        for(StreamClient.State late:StreamClient.State.values()){check(!state.client(late));check(state.phase()==ViewerState.Phase.ERROR);}
        check(state.connect());state.idle();
        for(StreamClient.State late:StreamClient.State.values()){check(!state.client(late));check(state.phase()==ViewerState.Phase.IDLE);}
        check(state.connect());state.client(StreamClient.State.STREAMING);check(state.stop());state.client(StreamClient.State.FAILED);
        check(state.phase()==ViewerState.Phase.ERROR&&state.canConnect());
        System.out.println("VIEWER_STATE_OK checks="+checks);
    }
}

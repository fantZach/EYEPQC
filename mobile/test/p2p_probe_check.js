// Parser/payload checks only; not a browser/Android WebRTC acceptance test.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('mobile/p2pprobe/src/main/assets/probe.html','utf8');
const elements={};
const context=vm.createContext({document:{getElementById:id=>elements[id]||(elements[id]={})},TextEncoder,ArrayBuffer,DataView,Uint8Array,clearInterval});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
const offer={type:'offer',sdp:'v=0\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n'};
context.parseOffer(JSON.stringify(offer));
for(const bad of ['{}','[]',JSON.stringify({...offer,type:'answer'}),JSON.stringify({...offer,sdp:offer.sdp+'m=audio 9 RTP/AVP 0\r\n'}),JSON.stringify({...offer,sdp:offer.sdp+'a=candidate:x typ relay\r\n'}),'x'.repeat(65537)])assert.throws(()=>context.parseOffer(bad));
const packet=new ArrayBuffer(1459);new DataView(packet).setUint32(0,3);new Uint8Array(packet).fill(3,4);
context.checkPacket(packet,3);
assert.throws(()=>context.checkPacket(packet,2));
new Uint8Array(packet)[50]=7;assert.throws(()=>context.checkPacket(packet,3));
assert.throws(()=>context.checkPacket(new ArrayBuffer(1458),3));
console.log('P2P_JS_CHECK_OK');

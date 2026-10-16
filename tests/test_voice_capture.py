"""Run the shipped capture processor and WAV encoder on synthetic PCM.

No microphone, model or browser permissions are needed. This covers the actual
worklet-to-server bytes, independently of controller tests that mock rendering.
"""
import base64
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import pytest

import navcom_voice as voice

ROOT = Path(__file__).resolve().parents[1]


def capture(script):
    if not shutil.which('node'):
        pytest.skip('Node required to exercise shipped AudioWorklet code')
    setup = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const posted=[];let Processor;
const context={Float32Array,sampleRate:16000,
 AudioWorkletProcessor:class{constructor(){this.port={postMessage:value=>posted.push(value==='done'?value:new Float32Array(value))}}},
 registerProcessor:(name,cls)=>{assert.equal(name,'navcom-capture');Processor=cls}};
vm.runInNewContext(fs.readFileSync('navcom_voice_worklet.js','utf8'),context);
const source=fs.readFileSync('navcom_voice.js','utf8');
const encoder=source.slice(source.indexOf('  function wav('),source.indexOf('  function attach('));
const wav=Function(encoder+';return wav')();
'''
    result = subprocess.run(['node', '-e', setup + script], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_real_worklet_stereo_mix_and_wav_bytes_are_accepted_by_server():
    result = capture(r'''
const processor=new Processor(),a=[1.5,-1.5,1,-1,.5,-.5],b=[1.5,-1.5,0,0,0,0];
assert.equal(processor.process([]),true);assert.equal(posted.length,0);
for(let start=0;start<1600;start+=128){
 const count=Math.min(128,1600-start),left=Float32Array.from({length:count},(_,i)=>a[(start+i)%a.length]),
       right=Float32Array.from({length:count},(_,i)=>b[(start+i)%b.length]),output=new Float32Array(count);
 assert.equal(processor.process([[left,right]],[[output]]),true);
 assert.ok(output.every(value=>value===0),'Capture must not monitor audio through the speaker');
}
const samples=new Float32Array(1600);let at=0;
for(const chunk of posted){samples.set(chunk,at);at+=chunk.length}
assert.equal(at,1600);assert.equal(posted.length,13);
console.log(JSON.stringify({audio:wav(samples),chunks:posted.length}));
''')
    audio = base64.b64decode(result['audio'])
    sanitized, duration = voice._audio(audio)
    assert duration == .1 and sanitized == audio
    with wave.open(io.BytesIO(audio), 'rb') as stream:
        assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (1, 2, 16000)
        pcm = struct.unpack('<1600h', stream.readframes(1600))
    expected = (32767, -32768, 16383, -16384, 8191, -8192)
    assert pcm == tuple(expected[i % len(expected)] for i in range(1600))


@pytest.mark.parametrize('rate', [16000, 44100, 48000])
def test_real_capture_stops_exactly_at_twenty_seconds_without_extra_audio(rate):
    result = capture('context.sampleRate=' + str(rate) + ';' + r'''
const processor=new Processor();let alive=true,frames=0;
while(alive){
 const input=new Float32Array(128).fill(.25);
 alive=processor.process([[input]]);
 if(posted.at(-1)==='done')break;
}
const chunks=posted.filter(value=>value!=='done');
frames=chunks.reduce((count,chunk)=>count+chunk.length,0);
assert.equal(frames,context.sampleRate*20);
assert.equal(posted.filter(value=>value==='done').length,1);
const messages=posted.length;
assert.equal(processor.process([[new Float32Array(128)]]),false);
assert.equal(posted.length,messages,'Finished worklet must not send extra PCM or done signals');
console.log(JSON.stringify({frames,done:posted.filter(value=>value==='done').length,last_chunk:chunks.at(-1).length}));
''')
    assert result['frames'] == rate * voice.MAX_SECONDS
    assert result['done'] == 1 and 0 < result['last_chunk'] <= 128


def test_cancel_during_discovery_permission_and_transcription_discards_late_results():
    if not shutil.which('node'):
        pytest.skip('Node required for voice controller proof')
    setup = r'''
const assert=require('node:assert/strict'),fs=require('node:fs');
class Element{
 constructor(){this.value='';this.children=[];this.listeners={};this.style={};this.classList={add(){},remove(){}}}
 append(...nodes){this.children.push(...nodes)}setAttribute(){}focus(){}
 addEventListener(name,fn){this.listeners[name]=fn}
}
const document={createElement:()=>new Element()},window={addEventListener(){}};
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve}};
let gate=deferred(),permission=deferred(),response=deferred(),micCalls=0,stopped=0,worklet,posts=0;
const navigator={mediaDevices:{getUserMedia:()=>{micCalls++;return permission.promise}}};
class AudioWorkletNode{constructor(){this.port={};worklet=this}connect(){}disconnect(){}}
class AudioContext{constructor(){this.sampleRate=16000;this.state='running';this.audioWorklet={addModule:async()=>{}};this.destination={}}
 createMediaStreamSource(){return {connect(){},disconnect(){}}}async resume(){}async close(){this.state='closed'}}
class OfflineAudioContext{createBuffer(){return {copyToChannel(){}}}createBufferSource(){return {connect(){},start(){}}}
 async startRendering(){return {getChannelData:()=>new Float32Array(1600).fill(.25)}}}
window.AudioWorkletNode=AudioWorkletNode;
eval(fs.readFileSync('navcom_voice.js','utf8'));
const button=new Element(),input=new Element(),status=new Element(),container=new Element();
input.value='Original query';input.maxLength=500;
const voice=window.NavcomVoice.attach({button,input,status,container,request:(_path,body)=>{
 if(body){posts++;return response.promise}return gate.promise}});
const tracks=[];
const stream=()=>{const track={readyState:'live',stop(){stopped++;this.readyState='ended'}};tracks.push(track);return {getTracks:()=>[track]}};
const settle=async predicate=>{for(let i=0;i<30&&!predicate();i++)await Promise.resolve();assert.ok(predicate())};
(async()=>{
 let pending=voice.start();assert.equal(voice.active(),true);voice.cancel();
 gate.resolve({available:true});await pending;
 assert.equal(micCalls,0);assert.equal(voice.active(),false);assert.equal(button.disabled,false);
 pending=voice.start();await settle(()=>micCalls===1);voice.cancel();
 permission.resolve(stream());await pending;
 assert.equal(stopped,1,'Permission granted after cancellation must immediately stop its tracks');
 assert.equal(posts,0);assert.equal(voice.active(),false);
 permission=deferred();permission.resolve(stream());
 await voice.start();worklet.port.onmessage({data:new Float32Array(1600).fill(.25)});
 pending=container.children[0].children[0].listeners.click();await settle(()=>posts===1);
 voice.cancel();input.value='New place and newer typing';response.resolve({text:'Late old transcript'});await pending;
 assert.equal(input.value,'New place and newer typing');assert.equal(voice.active(),false);
 assert.equal(button.disabled,false);assert.match(status.textContent,/cancelled/);
 assert.ok(stopped>=2);assert.ok(tracks.every(track=>track.readyState==='ended'));console.log('ok');
})().catch(error=>{voice.cancel();console.error(error);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', setup], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'ok'

"""Keyboard flight controls and editable voice review preserve the user's context."""
from pathlib import Path
from test_space_camera import run_js


ROOT=Path(__file__).resolve().parents[1]


def test_keyboard_select_reaches_fly_without_changing_desktop_pointer_selection():
    source=(ROOT/'navcom_space.js').read_text()
    select=source[source.index('function setSelection('):source.index('function shellQuote(')]
    run_js("const assert=require('node:assert/strict');\n"+select+"""
let route={place:'system:fixture',q:'matrix',zoom:2,pan:{x:12,y:9}},innerWidth=1440;
const reducedMotion={matches:false},scrolls=[],focus=[],places={querySelectorAll:()=>[]};
const fly={focus:options=>focus.push(options)},inspector={querySelector:()=>fly,scrollIntoView:options=>scrolls.push(options)};
const remember=()=>{},renderSelection=()=>{};
setSelection({id:'planet:one'},{detail:1});
assert.equal(focus.length,0);assert.equal(scrolls.length,0,'Mouse selection stays on the map');
setSelection({id:'planet:two'},{detail:0});
assert.equal(focus.length,1);assert.deepEqual(scrolls[0],{block:'nearest',behavior:'instant'});
assert.equal(route.selected,'planet:two');assert.equal(route.q,'matrix');assert.equal(route.zoom,2);
assert.deepEqual(route.pan,{x:12,y:9});
innerWidth=486;setSelection({id:'planet:three'},{detail:1});
assert.equal(focus.length,2);assert.deepEqual(scrolls[1],{block:'start',behavior:'smooth'});
reducedMotion.matches=true;setSelection({id:'planet:four'},{detail:1});
assert.equal(scrolls[2].behavior,'instant');
""")
    assert "event=>setSelection(n,event)" in source
    assert "event=>setSelection(node,event)" in source


def test_overlength_navigator_text_is_kept_without_any_request_or_route_change():
    source=(ROOT/'navcom_space.js').read_text()
    start=source.index('async function search(push=')
    search=source[start:source.index("form.addEventListener('submit'",start)]
    run_js("const assert=require('node:assert/strict');\n"+search+"""
const original='x'.repeat(650);let focused=false;
const input={value:original,maxLength:500,focus:()=>focused=true},navigatorStatus={};
const route={place:'system:fixture',q:'older query',local:false,offset:80,zoom:2,pan:{x:7,y:9}};
const before=JSON.stringify(route),api=()=>assert.fail('Overlength request reached the server');
(async()=>{await search();assert.equal(input.value,original);assert.equal(JSON.stringify(route),before);
assert.equal(focused,true);assert.match(navigatorStatus.textContent,/650.*500.*kept/);})().catch(e=>{console.error(e);process.exitCode=1});
""")


def test_voice_long_transcript_stays_editable_and_newer_typing_and_failure_survive():
    source=(ROOT/'navcom_voice.js').read_text()
    harness=r"""
const assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tagName=tag;this.value='';this.textContent='';this.className='';this.children=[];this.listeners={};this.style={};this.disabled=false;
  this.classList={add:v=>{this.className=[...new Set([...this.className.split(' '),v])].join(' ')},remove:v=>{this.className=this.className.split(' ').filter(x=>x!==v).join(' ')},contains:v=>this.className.split(' ').includes(v)};}
 append(...nodes){this.children.push(...nodes)}setAttribute(name,value){this[name]=value}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn)}
 async fire(name){await Promise.all((this.listeners[name]||[]).map(fn=>fn({target:this})))}
 focus(){document.activeElement=this}
}
const document={createElement:tag=>new Element(tag),activeElement:null};
let worklet,denied=false,stopped=0;
class AudioWorkletNode{constructor(){this.port={};worklet=this}connect(){}disconnect(){}}
class AudioContext{constructor(){this.sampleRate=16000;this.state='running';this.audioWorklet={addModule:async()=>{}};this.destination={}}
 createMediaStreamSource(){return {connect(){},disconnect(){}}}async resume(){}async close(){this.state='closed'}}
class OfflineAudioContext{createBuffer(){return {copyToChannel(){}}}createBufferSource(){return {connect(){},start(){}}}async startRendering(){return {getChannelData:()=>new Float32Array(1600)}}}
const navigator={mediaDevices:{getUserMedia:async()=>{if(denied)throw Error('Microphone denied');return {getTracks:()=>[{stop:()=>stopped++}]}}}};
const window={AudioWorkletNode,addEventListener(){}};
"""
    checks=r"""
const button=new Element('button'),input=new Element('input'),status=new Element('p'),container=new Element('section');
input.maxLength=500;input.value='Existing typed query';let reply='x'.repeat(650);const requests=[];
const voice=window.NavcomVoice.attach({button,input,status,container,request:async(path,body)=>{requests.push({path,body:!!body});return body?{text:reply}:{available:true}}});
const controls=container.children[0],draft=container.children[1];
const [transcript,note,use]=draft.children;
async function record(){await voice.start();worklet.port.onmessage({data:new Float32Array(1600)});await controls.children[0].fire('click')}
(async()=>{
 await record();assert.equal(input.value,'Existing typed query');assert.equal(transcript.tagName,'textarea');
 assert.equal(transcript.value.length,650);assert.equal(draft.classList.contains('hidden'),false);assert.equal(use.disabled,true);
 assert.match(note.textContent,/650\/500.*150/);assert.match(status.textContent,/500-character/);
 await use.fire('click');assert.equal(input.value,'Existing typed query','Oversize transcript cannot be applied even through the handler');
 transcript.value='How does login work?';await transcript.fire('input');assert.equal(use.disabled,false);
 await use.fire('click');assert.equal(input.value,'How does login work?');assert.equal(draft.classList.contains('hidden'),true);
 reply='A short transcript';await voice.start();input.value='Newer typing';await input.fire('input');
 worklet.port.onmessage({data:new Float32Array(1600)});await controls.children[0].fire('click');
 assert.equal(input.value,'Newer typing');assert.equal(transcript.value,'A short transcript');assert.equal(use.disabled,false);
 assert.match(status.textContent,/newer typing was kept/);
 denied=true;await voice.start();assert.equal(input.value,'Newer typing');assert.equal(button.disabled,false);assert.equal(voice.active(),false);
 assert.match(status.textContent,/Microphone denied.*keep typing/);assert.equal(document.activeElement,input);
 assert.ok(requests.every(r=>r.path==='/api/voice'),'Voice review never submits navigation');assert.ok(stopped>=2);
})().catch(e=>{voice.cancel();console.error(e);process.exitCode=1});
"""
    run_js(harness+source+checks)

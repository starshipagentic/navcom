"""Shared transcript rerenders must not strand the bridge reader on mobile."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_reader_close_survives_paging_failure_and_rerender_without_focus_churn():
    if not shutil.which('node'):
        pytest.skip('Node required for reader controller proof')
    source=(Path(__file__).resolve().parents[1]/'navcom_space.js').read_text()
    reader=source[source.index('let readerOrigin='):source.index('const voiceInput=',source.index('let readerOrigin='))]
    script=r"""
const assert=require('node:assert/strict');
let active=true,observerCallback,observing=false,disconnects=0,mutations=0,focuses=0;
const classes=()=>({values:new Set(),add(v){this.values.add(v)},remove(v){this.values.delete(v)},contains(v){return this.values.has(v)}});
const document={body:{classList:classes()},activeElement:null};document.activeElement=document.body;
const listeners={};const window={addEventListener:(name,fn)=>listeners[name]=fn};
let children=[],focusin=()=>{};
const box={
 querySelector:()=>children.find(n=>n.kind==='close')||null,
 querySelectorAll:()=>children.filter(n=>n.kind==='close'),
 prepend(n){children.unshift(n);n.isConnected=true;mutations++},
 addEventListener(name,fn){if(name==='focusin')focusin=fn}
};
const $=()=>box;
const makeNode=(kind)=>({kind,isConnected:true,focus(){focuses++;document.activeElement=this;focusin({target:this})},remove(){children=children.filter(n=>n!==this);this.isConnected=false;if(document.activeElement===this)document.activeElement=document.body;mutations++}});
const button=()=>makeNode('close'),input=makeNode('input'),origin=makeNode('origin');
class MutationObserver{constructor(fn){observerCallback=fn}observe(){observing=true}disconnect(){observing=false;disconnects++}}
function replaceContents(kind){for(const n of children){n.isConnected=false;if(document.activeElement===n)document.activeElement=document.body}children=[makeNode(kind)];mutations++}
let finish;const select=()=>{replaceContents('loading');return new Promise(resolve=>finish=()=>{replaceContents('transcript');resolve()})};
function tick(){if(observing)observerCallback()}
"""+reader+r"""
(async()=>{
 origin.focus();const opening=readConversation('session',1);
 assert.equal(children.filter(n=>n.kind==='close').length,1);assert.equal(document.activeElement.kind,'close');
 finish();await opening;tick();assert.equal(children.filter(n=>n.kind==='close').length,1);
 const afterRender=mutations,afterFocus=focuses;tick();tick();
 assert.equal(mutations,afterRender,'Observer must not mutate its own stable close control');
 assert.equal(focuses,afterFocus,'Observer must not repeatedly move focus');
 const next=makeNode('Next 80');children.push(next);next.focus();
 replaceContents('next transcript page');tick();
 assert.equal(children.filter(n=>n.kind==='close').length,1,'Next80 must retain mobile exit');
 assert.equal(document.activeElement.kind,'close','Removed pager focus recovers to visible close');
 replaceContents('request error and Retry');tick();assert.equal(children.filter(n=>n.kind==='close').length,1);
 const editor=makeNode('note editor');children.push(editor);editor.focus();children.push(makeNode('annotation status'));tick();
 assert.equal(document.activeElement,editor,'Appending content must not steal active typing');
 closeReader();assert.equal(observing,false);assert.equal(document.activeElement,origin);
 assert.equal(children.filter(n=>n.kind==='close').length,0);assert.equal(document.body.classList.contains('space-reading'),false);
 origin.focus();const pending=readConversation('other',81);closeReader();finish();await pending;tick();
 assert.equal(children.filter(n=>n.kind==='close').length,0,'Late response must not reopen closed reader');
 assert.equal(observing,false);assert.equal(document.activeElement,origin);
 const before=disconnects;listeners.pagehide();assert.equal(disconnects,before+1);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result=subprocess.run(['node','-e',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'closeReader(false);datedTicket++' in source, 'Leaving the bridge must disconnect its reader observer without stealing nav focus'

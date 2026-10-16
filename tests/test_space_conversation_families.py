"""The real card controller preserves parent identity and exact child passage targets."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_parent_child_actions_use_recorded_keys_and_matching_turns():
    if not shutil.which('node'):
        pytest.skip('Node is required for bridge controller proof')
    source=(ROOT/'navcom_space.js').read_text()
    controller=source[source.index('function conversationCard('):source.index('function renderSearch(')]
    script=r'''
const assert=require('node:assert/strict');
function el(tag,attrs={},...children){return {tag,attrs,children,append(...nodes){this.children.push(...nodes)}}}
const button=(text,click,attrs={})=>el('button',{...attrs,click},text),pathRow=path=>el('code',{},path);
const opened=[];const readConversation=(key,start)=>opened.push({key,start});
function walk(node){return typeof node==='object'?[node,...node.children.flatMap(walk)]:[]}
function text(node){return typeof node==='object'?node.children.map(text).join(' '):String(node)}
function click(card,label){const matches=walk(card).filter(n=>n.tag==='button'&&text(n)===label);assert.equal(matches.length,1);matches[0].attrs.click()}
''' + controller + r'''
const parent={key:'/parent',label:'Architecture discussion',provider:'codex',count:30,child:false,
 open_key:'/child',start:18,child_count:3,excerpt:'The child found the matching matrix',matching_children:[
 {key:'/child',ref:'child',label:'Matrix worker',start:18},{key:'/other-child',ref:'other',label:'Review worker',start:7}]};
const card=conversationCard(parent);
assert.match(text(card),/PARENT CONVERSATION/);assert.match(text(card),/3 child tasks/);
assert.match(text(card),/2 matching child tasks/);assert.match(text(card),/passage below is from a child task/);
click(card,'Read matching child →');assert.deepEqual(opened.pop(),{key:'/child',start:18});
click(card,'Read parent conversation →');assert.deepEqual(opened.pop(),{key:'/parent',start:1});
const tasks=walk(card).filter(n=>n.tag==='button'&&text(n)==='Read matching task →');
tasks[1].attrs.click();assert.deepEqual(opened.pop(),{key:'/other-child',start:7});
assert.equal(walk(card).filter(n=>n.tag==='details').length,1);
const orphan=conversationCard({key:'/orphan',label:'Detached task',child:true,start:9});
assert.match(text(orphan),/CHILD TASK · PARENT NOT INDEXED/);
assert.equal(walk(orphan).some(n=>n.tag==='button'&&text(n)==='Read parent conversation →'),false);
click(orphan,'Read child task →');assert.deepEqual(opened.pop(),{key:'/orphan',start:9});
const plain=conversationCard({key:'/ordinary',label:'Saved delegated-looking task',child:false});
assert.equal(text(plain).includes('CHILD TASK'),false,'Never infer ancestry from a task-looking title');
click(plain,'Read conversation →');assert.deepEqual(opened.pop(),{key:'/ordinary',start:1});
const expanded=conversationCard({key:'/child',label:'Expanded child',child:true,parent_key:'/parent',start:4});
click(expanded,'Read parent conversation →');assert.deepEqual(opened.pop(),{key:'/parent',start:1});
'''
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

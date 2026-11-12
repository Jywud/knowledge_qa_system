import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
function loadStore(stored) {
 const storage=new Map([["kqa_user",stored]]);
 const script=readFileSync(new URL("../src/store.js",import.meta.url),"utf8").replace(/^import .*;\s*/gm,"").replace(/export /g,"");
 const box={ref:value=>({value}),localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},axios:{create:()=>({get:async()=>({data:[]}),interceptors:{request:{use(){}},response:{use(){}}}})}};
 vm.createContext(box);vm.runInContext(script,box);
 return {...vm.runInContext("({user,setAuth,loadKnowledgeBases,selectedKb,knowledgeBases})",box),storage};
}
test("启动不信任缓存管理员权限并删除旧缓存",()=>{
 const s=loadStore(JSON.stringify({id:1,username:"admin",role:"admin",is_admin:true,password_hash:"old-secret"}));
 assert.equal(s.user.value,null); assert.equal(s.storage.has("kqa_user"),false);
});
test("登录只保存公开角色字段",()=>{
 const s=loadStore("null");
 s.setAuth("test",{id:2,username:"user",is_admin:false,role:"admin",password_hash:"secret",roles:[{id:3,name:"销售",system_key:null,secret:"hidden"}]});
 assert.deepEqual(JSON.parse(s.storage.get("kqa_user")),{id:2,username:"user",is_admin:false,roles:[{id:3,name:"销售",system_key:null}]});
});
test("损坏用户缓存不会阻断页面启动",()=>assert.equal(loadStore("broken json").user.value,null));
test("刷新可访问库会清除已撤权选择",async()=>{
 const s=loadStore("null"); s.setAuth("test",{id:2,username:"u",roles:[],is_admin:false});
 s.selectedKb.value=9;await s.loadKnowledgeBases();assert.equal(s.selectedKb.value,null);
});

import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";
function guard({current=null, fail=false}={}) {
 let handler;let cleared=false;
 const token={value:"token"};const user={value:current};
 const code=readFileSync(new URL("../src/router/index.js",import.meta.url),"utf8").replace(/^import .*;\s*/gm,"").replace('export default router;',"");
 const box={createRouter:()=>({beforeEach:fn=>{handler=fn;}}),createWebHistory(){},AppLayout:{},token,user,refreshUser:async()=>{if(fail)throw Error("network");user.value={is_admin:false};},clearAuth:()=>{token.value="";user.value=null;cleared=true;}};
 vm.createContext(box);vm.runInContext(code,box);
 return {handler,cleared:()=>cleared};
}
test("业务用户不能直接打开管理员页面",async()=>{
 const s=guard();assert.equal(await s.handler({path:"/roles",meta:{admin:true}}),"/chat");
});
test("身份刷新失败清除登录避免登录页循环跳转",async()=>{
 const s=guard({fail:true});assert.equal(await s.handler({path:"/roles",meta:{admin:true}}),"/login");assert.equal(s.cleared(),true);
 assert.equal(await s.handler({path:"/login",meta:{}}),true);
});

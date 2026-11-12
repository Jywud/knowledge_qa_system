import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";
function subject(file, extras = {}) {
 const script = readFileSync(new URL("../src/" + file, import.meta.url), "utf8").split("<script setup>")[1].split("</script>")[0].replace(/^import\s[\s\S]*?;\s*/gm, "");
 const calls = []; const notices = [];
 const box = {ref: value => ({value}),reactive: value => value,onMounted(){},useRouter:()=>({replace(){}}),refreshUser:async()=>{},loadKnowledgeBases:async()=>{},usernameRules:[],newPasswordRules:[],user:{value:{id:1}},api:{post:async (...args)=>calls.push(args),put:async (...args)=>calls.push(args),get:async()=>({data:[]})},ElMessage:{warning:m=>notices.push(m),error:m=>notices.push(m),success(){}},...extras};
 vm.createContext(box); vm.runInContext(script, box);
 return {run: code=>vm.runInContext(code,box), calls, notices};
}
test("新增用户必须明确选角色，提交多个角色ID且不带旧role", async()=>{
 const s=subject("views/UserManage.vue");
 s.run('formRef.value={validate:async()=>true}; form.username="employee"; form.password="123456"');
 await s.run('createUser()');
 assert.equal(s.calls.length,0);
 s.run('form.role_ids=[2,3]'); await s.run('createUser()');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0])),["/users",{username:"employee",password:"123456",role_ids:[2,3]}]);
});
test("分配角色以新接口发送且刷新自己的公开身份", async()=>{
 let refreshed=0;
 const s=subject("views/UserManage.vue", {refreshUser:async()=>{refreshed++;}});
 s.run('openRoles({id:1,username:"admin",roles:[{id:1}]}); roleIds.value=[1,2]');
 await s.run('saveRoles()');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0])),["/users/1/roles",{role_ids:[1,2]}]);
 assert.equal(refreshed,1);
});

test("角色保存发送明确知识库清单，允许空授权且系统角色不提交修改", async()=>{
 const s=subject("views/RoleManage.vue");
 s.run('openCreate(); form.name="销售"; form.kb_ids=[2,4]'); await s.run('saveRole()');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0])),["/roles",{name:"销售",description:"",kb_ids:[2,4]}]);
 s.run('openEdit({id:2,name:"销售",description:"",kb_ids:[2,4]}); form.kb_ids=[]'); await s.run('saveRole()');
 assert.deepEqual(JSON.parse(JSON.stringify(s.calls[1])),["/roles/2",{name:"销售",description:"",kb_ids:[]}]);
 s.run('openEdit({id:1,name:"系统管理员",system_key:"system_admin",kb_ids:[]})'); await s.run('saveRole()');
 assert.equal(s.calls.length,2);
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function loadStore(stored) {
  const storage = new Map([["kqa_user", stored]]);
  const script = readFileSync(new URL("../src/store.js", import.meta.url), "utf8")
    .replace(/^import .*;\s*/gm, "").replace(/export /g, "");
  const box = {ref: value => ({value}), localStorage: {getItem: k => storage.get(k) || null,
    setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)},
    axios: {create: () => ({interceptors: {request: {use() {}}, response: {use() {}}}})}};
  vm.createContext(box);
  vm.runInContext(script, box);
  return {...vm.runInContext("({user,setAuth})", box), storage};
}

test("加载旧用户缓存会移除密码哈希，登录只保存公开字段", () => {
  const subject = loadStore(JSON.stringify({id:1,username:"admin",role:"admin",password_hash:"old-secret"}));
  assert.equal(subject.user.value.password_hash, undefined);
  assert.doesNotMatch(subject.storage.get("kqa_user"), /password_hash|old-secret/);
  subject.setAuth("test", {id:2,username:"user",role:"user",password_hash:"new-secret"});
  assert.deepEqual(JSON.parse(subject.storage.get("kqa_user")), {id:2,username:"user",role:"user"});
});

test("损坏用户缓存不会阻断页面启动", () => {
  const subject = loadStore("broken json");
  assert.equal(subject.user.value, null);
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

for (const kbId of [null, 1]) {
  test("会话创建后固定全部或单库范围，kb=" + kbId, () => {
    const source = readFileSync(new URL("../src/views/ChatView.vue", import.meta.url), "utf8");
    const script = source.split("<script setup>")[1].split("</script>")[0]
      .replace(/^import\s[\s\S]*?;\s*/gm, "");
    const box = {
      ref: (value) => ({value}), reactive: (value) => value, watch() {},
      computed: (getter) => ({get value() {return getter();}}),
      useRouter: () => ({currentRoute: {value: {path: "/chat"}}}),
      currentConversationId: {value: 42}, conversations: {value: [{id: 42, kb_id: kbId}]},
      newPasswordRules: [],
    };
    vm.createContext(box);
    vm.runInContext(script, box);
    assert.equal(vm.runInContext("kbLocked.value", box), true);
  });
}

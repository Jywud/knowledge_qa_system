import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const reference = () => ({source: "guide.md", file_id: 1, file_version: 1, excerpts: [
  {index: 1, chunk_id: 10, file_id: 1, file_version: 1, chunk_index: 0, text: "当时保存的摘要"},
]});
const chunk = (content = "目标分块完整正文") => ({id: 10, file_id: 1, file_version: 1,
  chunk_index: 0, page_no: 0, filename: "guide.md", file_type: "md", content});

function createSubject(get) {
  const source = readFileSync(new URL("../src/views/ChatView.vue", import.meta.url), "utf8");
  const script = source.split("<script setup>")[1].split("</script>")[0]
    .replace(/^import\s[\s\S]*?;\s*/gm, "");
  const calls = [];
  const navigations = [];
  const token = {value: "test-token"};
  const currentConversationId = {value: 23};
  const box = {
    ref: (value) => ({value}), reactive: (value) => value,
    computed: (getter) => ({get value() {return getter();}}), nextTick: (fn) => fn?.(), watch() {},
    MarkdownIt: class {}, ElMessage: {error() {}, warning() {}},
    useRouter: () => ({replace: (path) => navigations.push(path)}),
    api: {get: async (url, options) => {calls.push([url, options]); return get(url, options);}},
    conversations: {value: []}, currentConversationId, token, selectedKb: {value: 1},
    knowledgeBases: {value: [{id: 1, chunk_count: 1}]},
    loadKnowledgeBases: async () => {}, refreshUser: async () => {},
    loadConversations: async () => {}, clearAuth: () => {token.value = ""; currentConversationId.value = null;},
  };
  vm.createContext(box);
  vm.runInContext(script, box);
  return { ...vm.runInContext("({openSourceDialog, sourceDialog, selectConversation, messages})", box),
    calls, token, navigations,
    retry: () => vm.runInContext("loadSourceItem(sourceDialog.items[0])", box) };
}

test("只查询对应分块且每次打开重新请求", async () => {
  const subject = createSubject(async (url) => {
    assert.equal(url, "/chunks/10");
    return {data: chunk()};
  });
  await subject.openSourceDialog(reference());
  assert.equal(subject.sourceDialog.items[0].content, "目标分块完整正文");
  const [, options] = subject.calls[0];
  assert.equal(options.params.file_id, 1);
  assert.equal(options.params.version, 1);
  await subject.openSourceDialog(reference());
  assert.equal(subject.calls.length, 2);
});

test("请求期间显示加载中，结束后取消 loading", async () => {
  let complete;
  const subject = createSubject(() => new Promise((resolve) => {complete = resolve;}));
  const pending = subject.openSourceDialog(reference());
  assert.equal(subject.sourceDialog.visible, true);
  assert.equal(subject.sourceDialog.items[0].loading, true);
  complete({data: chunk()});
  await pending;
  assert.equal(subject.sourceDialog.items[0].loading, false);
});

for (const status of [404, 410, 500]) {
  test("分块失败显示原因、保留摘要并可重试：" + status, async () => {
    let failed = true;
    const subject = createSubject(async () => {
      if (failed) throw {response: {status}};
      return {data: chunk()};
    });
    await subject.openSourceDialog(reference());
    const item = subject.sourceDialog.items[0];
    assert.ok(item.error);
    assert.equal(item.content, "");
    assert.equal(item.text, "当时保存的摘要");
    assert.equal(item.loading, false);
    failed = false;
    await subject.retry();
    assert.equal(item.error, "");
    assert.equal(item.content, "目标分块完整正文");
  });
}

test("已打开过的引用在文件更新后不得复用旧缓存", async () => {
  let updated = false;
  const subject = createSubject(async () => {
    if (updated) throw {response: {status: 410}};
    return {data: chunk()};
  });
  await subject.openSourceDialog(reference());
  updated = true;
  await subject.openSourceDialog(reference());
  assert.equal(subject.calls.length, 2);
  assert.equal(subject.sourceDialog.items[0].content, "");
  assert.match(subject.sourceDialog.items[0].error, /更新|失效/);
});

test("拒绝正文身份或版本与引用不符的响应", async () => {
  const subject = createSubject(async () => ({data: {...chunk("其他版本内容"), file_version: 2}}));
  await subject.openSourceDialog(reference());
  assert.equal(subject.sourceDialog.items[0].content, "");
  assert.ok(subject.sourceDialog.items[0].error);
});

for (const source of [
  {source: "old.md", excerpts: ["旧字符串摘要"]},
  {source: "old.md", excerpts: [{index: 1, file_id: 1, chunk_index: 0, text: "旧对象摘要"}]},
  {index: 1, source: "old.md", page: 2},
]) {
  test("旧引用兼容且不猜测当前分块：" + JSON.stringify(source), async () => {
    const subject = createSubject(async () => {throw new Error("旧引用不应读取当前文件");});
    await subject.openSourceDialog(source);
    assert.equal(subject.calls.length, 0);
    assert.equal(subject.sourceDialog.items.length, 1);
    assert.match(subject.sourceDialog.items[0].notice, /历史|精确|保存/);
  });
}

test("迟到响应不能覆盖后来打开的弹窗", async () => {
  let finishFirst;
  const subject = createSubject((url) => url === "/chunks/10"
    ? new Promise((resolve) => {finishFirst = resolve;})
    : Promise.resolve({data: {...chunk("第二个来源正文"), id: 20, file_id: 2}}));
  const first = subject.openSourceDialog(reference());
  const secondRef = {source: "other.md", file_id: 2, file_version: 1,
    excerpts: [{chunk_id: 20, file_id: 2, file_version: 1, text: "第二摘要"}]};
  await subject.openSourceDialog(secondRef);
  finishFirst({data: chunk()});
  await first;
  assert.equal(subject.sourceDialog.source, "other.md");
  assert.equal(subject.sourceDialog.items[0].content, "第二个来源正文");
});

test("关闭弹窗后响应不会重新打开弹窗", async () => {
  let complete;
  const subject = createSubject(() => new Promise((resolve) => {complete = resolve;}));
  const pending = subject.openSourceDialog(reference());
  subject.sourceDialog.visible = false;
  complete({data: chunk()});
  await pending;
  assert.equal(subject.sourceDialog.visible, false);
});

test("来源请求401清理凭证并跳登录", async () => {
  const subject = createSubject(async () => {throw {response: {status: 401}};});
  await subject.openSourceDialog(reference());
  assert.equal(subject.token.value, "");
  assert.ok(subject.navigations.includes("/login"));
});

test("坏来源JSON不会导致整条历史正文消失", async () => {
  const subject = createSubject(async () => ({data: [{role: "assistant", content: "正常历史正文", sources: "not valid json"}]}));
  await subject.selectConversation(23);
  assert.equal(subject.messages.value.length, 1);
  assert.equal(subject.messages.value[0].content, "正常历史正文");
  assert.equal(subject.messages.value[0].sources.length, 0);
});

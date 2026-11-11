import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function createSubject({ response, createError, fetchError, existing = true } = {}) {
  const source = readFileSync(new URL("../src/views/ChatView.vue", import.meta.url), "utf8");
  const script = source.split("<script setup>")[1].split("</script>")[0]
    .replace(/^import\s[\s\S]*?;\s*/gm, "");
  const ref = (value) => ({ value });
  const notices = [];
  const navigations = [];
  const token = ref("test-token");
  const currentConversationId = ref(existing ? 23 : null);
  const conversations = ref([]);
  let refreshes = 0;
  let requests = 0;
  let sentBody;
  const watchers = [];
  const box = {
    ref, reactive: (value) => value, computed: (getter) => ({ get value() { return getter(); } }),
    nextTick: (fn) => fn?.(), watch: (target, callback) => watchers.push([target, callback]),
    ElMessage: { error: (m) => notices.push(m), warning: (m) => notices.push(m) },
    MarkdownIt: class { render(value) { return value; } },
    api: { post: async () => {
      if (createError) throw createError;
      return { data: { id: 24, kb_id: 1, title: "" } };
    }, get: async () => ({ data: [] }) },
    conversations, currentConversationId, token, selectedKb: ref(1),
    loadConversations: async () => { refreshes++; },
    clearAuth: () => { token.value = ""; currentConversationId.value = null; conversations.value = []; },
    useRouter: () => ({ replace: async (path) => navigations.push(path) }),
    fetch: async (_url, options) => {
      requests++;
      sentBody = JSON.parse(options.body);
      if (fetchError) throw fetchError;
      return response || new Response('data: {"type":"token","content":"正常回答"}\n\ndata: {"type":"done"}\n\n');
    },
    TextDecoder, setInterval: () => 1, clearInterval() {},
  };
  vm.createContext(box);
  vm.runInContext(script, box);
  const state = vm.runInContext("({send, selectConversation, input, sending, messages})", box);
  state.input.value = "测试问题";
  return { ...state, token, currentConversationId, notices, navigations,
    refreshes: () => refreshes, requests: () => requests, sentBody: () => sentBody,
    flushWatchers: async () => {
      for (const [target, callback] of watchers) {
        if (target === currentConversationId) await callback(currentConversationId.value);
      }
    } };
}

for (const status of [400, 403, 404, 429, 500]) {
  test("HTTP " + status + " 显示后端错误且恢复发送", async () => {
    const subject = createSubject({ response: new Response(JSON.stringify({ detail: "后端错误原因" }), { status }) });
    await subject.send();
    assert.match(subject.messages.value[1].content, /后端错误原因/);
    assert.equal(subject.sending.value, false);
    assert.equal(subject.messages.value[1].done, true);
  });
}

test("非 JSON 服务错误仍有中文提示", async () => {
  const subject = createSubject({ response: new Response("<html>bad gateway</html>", { status: 502 }) });
  await subject.send();
  assert.match(subject.messages.value[1].content, /服务|稍后/);
  assert.doesNotMatch(subject.messages.value[1].content, /<html>/);
});

for (const existing of [true, false]) {
  test("401 清理会话并跳登录，existing=" + existing, async () => {
    const subject = createSubject({ existing, response: new Response('{"detail":"登录过期"}', { status: 401 }) });
    await subject.send();
    assert.equal(subject.token.value, "");
    assert.equal(subject.currentConversationId.value, null);
    assert.ok(subject.navigations.includes("/login"));
    assert.equal(subject.refreshes(), 0);
    assert.equal(subject.sending.value, false);
  });
}

test("会话创建失败保留输入、不留下空白回复", async () => {
  const error = Object.assign(new Error("bad request"), { response: { status: 400, data: { detail: "知识库不存在" } } });
  const subject = createSubject({ existing: false, createError: error });
  await subject.send();
  assert.equal(subject.input.value, "测试问题");
  assert.equal(subject.messages.value.length, 0);
  assert.equal(subject.sending.value, false);
  assert.ok(subject.notices.includes("知识库不存在"));
  assert.equal(subject.requests(), 0);
});

test("断网给出提示并结束 loading", async () => {
  const subject = createSubject({ fetchError: new TypeError("Failed to fetch") });
  await subject.send();
  assert.match(subject.messages.value[1].content, /网络|连接/);
  assert.equal(subject.sending.value, false);
});

test("正常 SSE 仍显示回答", async () => {
  const subject = createSubject();
  await subject.send();
  assert.equal(subject.messages.value[1].content, "正常回答");
  assert.equal(subject.messages.value[1].done, true);
  assert.equal(subject.sending.value, false);
});

test("部分回答后无 done 的 EOF 显示中断而不伪装完成", async () => {
  const subject = createSubject({ response: new Response('data: {"type":"token","content":"部分内容"}\n\n') });
  await subject.send();
  assert.match(subject.messages.value[1].content, /部分内容/);
  assert.match(subject.messages.value[1].content, /中断|重试/);
  assert.equal(subject.sending.value, false);
});

test("提问携带选定知识库，供旧会话首次绑定", async () => {
  const subject = createSubject();
  await subject.send();
  assert.equal(subject.sentBody().kb_id, 1);
});

test("新会话错误不会被切换会话时的空历史覆盖", async () => {
  const subject = createSubject({ existing: false, response: new Response('{"detail":"知识库暂无可用文档"}', {status: 400}) });
  await subject.send();
  await subject.flushWatchers();
  assert.equal(subject.messages.value.length, 2);
  assert.match(subject.messages.value[1].content, /知识库暂无可用文档/);
});

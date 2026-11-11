import assert from "node:assert/strict";
import test from "node:test";
import { renderMarkdown } from "../src/utils/markdown.js";

test("正文、列表和强调里的来源转换为独立数字角标", () => {
  const html = renderMarkdown("正文[来源3][来源12]\n\n- **重点[来源4]**");
  assert.equal((html.match(/class="citation-badge"/g) || []).length, 3);
  assert.match(html, /aria-label="来源3" title="来源3">3<\/span>/);
  assert.match(html, />12<\/span>/);
  assert.match(html, /<strong>重点<span/);
});

test("不改变代码、链接、图片说明及转义文本", () => {
  const html = renderMarkdown('`[来源3]`\n\n```text\n[来源4]\n```\n\n[来源5](https://example.com) ![图[来源6]](https://example.com/a.png) \\[来源7]');
  assert.doesNotMatch(html, /citation-badge/);
  assert.match(html, /<code>\[来源3\]<\/code>/);
  assert.match(html, /href="https:\/\/example.com">来源5<\/a>/);
  assert.match(html, /alt="图\[来源6\]"/);
});

test("流式未完成的标记及非引用方括号保留原文", () => {
  const html = renderMarkdown("[来源 [来源3 [来源0] [来源abc] [普通文本]");
  assert.doesNotMatch(html, /citation-badge/);
  assert.match(html, /\[来源3/);
});

test("原始 HTML 仍转义，不允许引用内容注入属性", () => {
  const html = renderMarkdown('<script>alert(1)</script> [来源3\" onclick=\"alert(1)] [来源2]');
  assert.doesNotMatch(html, /<script|<span[^>]+onclick/);
  assert.match(html, /&lt;script&gt;/);
  assert.equal((html.match(/class="citation-badge"/g) || []).length, 1);
});

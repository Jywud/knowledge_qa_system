import MarkdownIt from "markdown-it";

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true });

// 仅处理正文文本 token，避免改动代码、链接、图片说明和转义文本。
markdown.core.ruler.before("text_join", "source_citations", (state) => {
  for (const block of state.tokens) {
    if (block.type !== "inline" || !block.children) continue;
    let linkDepth = 0;
    block.children = block.children.flatMap((token) => {
      if (token.type === "link_open") linkDepth++;
      if (token.type === "link_close") linkDepth--;
      if (token.type !== "text" || linkDepth) return [token];

      const parts = [];
      let start = 0;
      for (const match of token.content.matchAll(/\[来源([1-9]\d*)\]/g)) {
        const text = new state.Token("text", "", 0);
        text.content = token.content.slice(start, match.index);
        parts.push(text);
        const citation = new state.Token("source_citation", "", 0);
        citation.content = match[1];
        parts.push(citation);
        start = match.index + match[0].length;
      }
      if (!parts.length) return [token];
      const tail = new state.Token("text", "", 0);
      tail.content = token.content.slice(start);
      return [...parts, tail];
    });
  }
});

markdown.renderer.rules.source_citation = (tokens, index) => {
  const number = tokens[index].content;
  return `<span class="citation-badge" aria-label="来源${number}" title="来源${number}">${number}</span>`;
};

export function renderMarkdown(content) {
  return markdown.render(content || "");
}

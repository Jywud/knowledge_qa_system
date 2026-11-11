import assert from "node:assert/strict";
import test from "node:test";
import config from "../vite.config.js";

test("开发代理覆盖客户端伪造的来源头", () => {
  let handler;
  config.server.proxy["/api"].configure({on: (event, callback) => {if (event === "proxyReq") handler = callback;}});
  const headers = {"X-Forwarded-For":"attacker", "X-Real-IP":"attacker"};
  handler({setHeader: (key,value) => {headers[key] = value;}}, {socket:{remoteAddress:"203.0.113.8"}});
  assert.equal(headers["X-Forwarded-For"], "203.0.113.8");
  assert.equal(headers["X-Real-IP"], "203.0.113.8");
});

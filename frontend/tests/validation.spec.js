import assert from "node:assert/strict";
import test from "node:test";

test("共用用户名和密码规则覆盖边界", async (t) => {
  const { usernameError, newPasswordError } = await import("../src/utils/validation.js");
  for (const value of ["", "   ", "x".repeat(65)]) {
    await t.test("拒绝用户名 " + JSON.stringify(value.slice(0, 10)), () => assert.ok(usernameError(value)));
  }
  for (const value of [" 大鱼 ", "x".repeat(64)]) {
    await t.test("接受用户名 " + value.slice(0, 10), () => assert.equal(usernameError(value), ""));
  }
  for (const value of ["", "12345", " ".repeat(6), "p".repeat(129)]) {
    await t.test("拒绝密码边界 " + value.length, () => assert.ok(newPasswordError(value)));
  }
  for (const value of ["123456", "p".repeat(128), " pass "]) {
    await t.test("接受密码边界 " + value.length, () => assert.equal(newPasswordError(value), ""));
  }
});

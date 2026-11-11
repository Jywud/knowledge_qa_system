export function usernameError(value) {
  if (typeof value !== "string" || !value.trim()) return "用户名不能为空";
  if (Array.from(value.trim()).length > 64) return "用户名不能超过 64 个字符";
  return "";
}

export function newPasswordError(value) {
  if (typeof value !== "string" || Array.from(value).length < 6) return "密码至少 6 位";
  if (Array.from(value).length > 128) return "密码不能超过 128 位";
  if (!value.trim()) return "密码不能全部为空白字符";
  return "";
}

function fieldRule(validate) {
  return {
    validator: (_rule, value, callback) => {
      const message = validate(value);
      callback(message ? new Error(message) : undefined);
    },
    trigger: "blur",
  };
}

export const usernameRules = [fieldRule(usernameError)];
export const newPasswordRules = [fieldRule(newPasswordError)];

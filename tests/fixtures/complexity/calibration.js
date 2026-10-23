export function straight(value) {
  return /[+-]?(?:a(?:b)?|c)(?:e[+-]?d+)?/.test(value);
}
export function choices(a, b, c) {
  if (a && b || c) return 1;
  return 0;
}
export function outer() {
  return function inner(value) { return value ? 1 : 2; };
}
export const arrow = value => value ? 1 : 2;
export const methods = { show() { return 1; }, restore() { return 2; } };
export function optional(value = 0) { return value?.entry?.(); }
export function boundary(value) {
  if (value) { value = 1; }
  if (value) { value = 2; }
  if (value) { value = 3; }
  if (value) { value = 4; }
  if (value) { value = 5; }
  if (value) { value = 6; }
  if (value) { value = 7; }
  if (value) { value = 8; }
  return value;
}
export class Initializers {
  value = true ? 1 : 2;
  factory = value => value ? 1 : 2;
  static { if (globalThis.flag) this.ready = true; }
}

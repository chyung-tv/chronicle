export const KIND: Record<string, string> = {
  wait: "等候",
  move: "前往",
  speak: "對白",
  take: "取物",
  drop: "放下",
  examine: "察看",
  attack: "襲擊",
  kill: "殺死",
  attempted_kill: "欲殺不成",
  world: "世變",
  world_kill: "世變致死",
  steer_motive: "導引·動機",
  steer_means: "導引·手段",
  steer_opportunity: "導引·時機",
  steer_escalation: "導引·加壓",
  failed_move: "未成行",
  failed_speak: "未成言",
  failed_attack: "未成擊",
  write_note: "寫紙",
};

export const STATUS: Record<string, string> = {
  brewing: "醞釀中",
  attempted: "已著手",
  succeeded: "已成",
  failed: "失敗",
  pending: "未發",
  injected: "已注入",
  done: "已畢",
};

export const RUNG: Record<string, string> = {
  motive: "動機",
  means: "手段",
  opportunity: "時機",
  escalation: "加壓",
};

export function kindLabel(kind: string) {
  return KIND[kind] || kind;
}

export function statusLabel(status: string) {
  return STATUS[status] || status;
}

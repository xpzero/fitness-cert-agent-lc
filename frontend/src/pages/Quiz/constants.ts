/** 刷题模式定义：value 对应后端 /quiz/start 的 mode 参数 */
export const MODES = [
  { label: "章节练习", value: "practice" },
  { label: "错题复习", value: "wrong_review" },
  { label: "收藏夹", value: "favorites" },
  { label: "全真模考", value: "mock" },
];

/** 题型中文名（后端 type 值：single/judge/multi） */
export const TYPE_LABEL: Record<string, string> = {
  single: "单选题",
  judge: "判断题",
  multi: "多选题",
};

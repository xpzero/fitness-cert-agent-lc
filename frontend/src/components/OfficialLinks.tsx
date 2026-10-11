/** 官方入口白名单：四大认证官方机构域名（防代考/免考包过类骗局），静态维护即可。 */
const OFFICIAL_ENTRIES: { kind: string; entries: Record<string, string> }[] = [
  {
    kind: "证书查询",
    entries: {
      "NSCA 认证中心": "https://www.nscacertification.org",
      "ACE 美国运动委员会": "https://www.acefitness.org",
      "ACSM 美国运动医学会": "https://www.acsm.org",
      "NASM 美国国家运动医学学会": "https://www.nasm.org",
    },
  },
  {
    kind: "报名入口",
    entries: {
      "NSCA 官网（含中国区直报）": "https://www.nsca.com",
      "ACE 官网": "https://www.acefitness.org",
      "ACSM 官网": "https://www.acsm.org",
      "NASM 官网": "https://www.nasm.org",
    },
  },
];

const UNOFFICIAL_WARNING =
  "注意：四大认证均无'免考/包过/内部渠道'，报名与证书验证只在上述官网进行；" +
  "中文代考、付费免考类宣传均为骗局，请勿轻信第三方机构。";

/** 页面底部常驻的官方入口区块 */
export default function OfficialLinks() {
  return (
    <div className="border-t border-border px-5 py-3.5 text-xs">
      <div className="mb-2 font-bold">
        🏛 官方入口{" "}
        <span className="font-normal text-muted-foreground">只认官网白名单，不走 AI 生成</span>
      </div>
      <div className="grid grid-cols-1 gap-x-10 gap-y-2 sm:grid-cols-2">
        {OFFICIAL_ENTRIES.map(({ kind, entries }) => (
          <div key={kind}>
            <div className="mb-1 font-semibold text-muted-foreground">{kind}</div>
            {Object.entries(entries).map(([n, u]) => (
              <div key={n} className="leading-5">
                <a className="text-sky-700 hover:underline" href={u} target="_blank" rel="noreferrer">
                  {n}
                </a>{" "}
                <span className="text-muted-foreground">{new URL(u).host}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="mt-2.5 text-[11.5px] text-red-600">⚠️ {UNOFFICIAL_WARNING}</div>
    </div>
  );
}

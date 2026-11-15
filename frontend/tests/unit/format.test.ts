import { fmtBps, fmtBytes, fmtPct, fmtUptime, parseList, relTime } from "@/lib/format";

describe("formatting", () => {
  it("formats bit rates with SI units", () => {
    expect(fmtBps(0)).toBe("0 bps");
    expect(fmtBps(1500)).toBe("1.5 Kbps");
    expect(fmtBps(1_200_000_000)).toBe("1.2 Gbps");
    expect(fmtBps(null)).toBe("–");
  });
  it("formats bytes, percentages and uptime", () => {
    expect(fmtBytes(2048)).toBe("2.0 KB");
    expect(fmtPct(12.345)).toBe("12.3%");
    expect(fmtPct(undefined)).toBe("–");
    expect(fmtUptime(90061)).toBe("1d 1h");
    expect(fmtUptime(3700)).toBe("1h 1m");
  });
  it("renders relative times", () => {
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(relTime("2026-01-01T11:59:30Z", now)).toBe("30s ago");
    expect(relTime("2026-01-01T10:00:00Z", now)).toBe("2h ago");
    expect(relTime(null, now)).toBe("never");
  });
  it("parses port lists and ranges", () => {
    expect(parseList("1-4, 7 25")).toEqual(["1", "2", "3", "4", "7", "25"]);
    expect(parseList("A1, 1/1, 3,3")).toEqual(["A1", "1/1", "3"]);
    expect(parseList("5-2")).toEqual(["5-2"]);
    expect(parseList("")).toEqual([]);
  });
});

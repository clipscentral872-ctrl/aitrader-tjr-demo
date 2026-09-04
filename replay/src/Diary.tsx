import React from "react";
import {AbsoluteFill, Sequence, interpolate, useCurrentFrame} from "remotion";
import type {Trade} from "./types";
import {TRADES} from "./trades";
import {TradeScene, sceneFrames} from "./TradeScene";
import {C, DISPLAY, MONO, SANS, money, rr} from "./theme";

export const OPEN = 90;
export const CLOSE = 200;

export type Props = {
  mode: "all" | "losers" | "winners";
  from?: string;    // inclusive date, YYYY-MM-DD
  to?: string;      // inclusive date
  weekday?: number; // 1 Monday through 5 Friday, for the by-weekday cuts
  title: string;
  subtitle: string;
};

// One composition, many cuts. The filter lives here rather than in the props so
// the trade data never has to travel through the command line.
export const selectTrades = (p: Props): Trade[] =>
  TRADES.filter((t) => {
    const d = t.open_t.slice(0, 10);
    if (p.from && d < p.from) return false;
    if (p.to && d > p.to) return false;
    if (p.weekday != null) {
      // parsed as UTC so the weekday cannot shift with the viewer's zone
      if (new Date(d + "T00:00:00Z").getUTCDay() !== p.weekday) return false;
    }
    if (p.mode === "losers") return t.pnl < 0;
    if (p.mode === "winners") return t.pnl > 0;
    return true;
  });

export const totalFrames = (p: Props) =>
  OPEN + selectTrades(p).reduce((a, t) => a + sceneFrames(t), 0) + CLOSE;

const stats = (ts: Trade[]) => {
  const pnl = ts.reduce((a, t) => a + t.pnl, 0);
  const wins = ts.filter((t) => t.pnl > 0).length;
  // trades taken without a stop have no R, so they are left out of the
  // expectancy rather than counted as zero
  const rs = ts.map((t) => t.got_r).filter((v): v is number => v != null);
  return {
    pnl, wins, losses: ts.length - wins,
    rate: ts.length ? (wins / ts.length) * 100 : 0,
    exp: rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : 0,
  };
};

const Card: React.FC<{children: React.ReactNode}> = ({children}) => {
  const frame = useCurrentFrame();
  const op = interpolate(frame, [0, 14], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{
      backgroundColor: C.ground, opacity: op, justifyContent: "center",
      alignItems: "center", flexDirection: "column",
    }}>
      {children}
    </AbsoluteFill>
  );
};

const Figure: React.FC<{label: string; value: string; color?: string}> = ({
  label, value, color,
}) => (
  <div style={{display: "flex", flexDirection: "column", gap: 6, alignItems: "center"}}>
    <span style={{font: `600 16px ${SANS}`, color: C.faint, letterSpacing: 3}}>
      {label.toUpperCase()}
    </span>
    <span style={{font: `700 46px ${MONO}`, color: color ?? C.text}}>{value}</span>
  </div>
);

export const Diary: React.FC<Props> = (props) => {
  const picked = selectTrades(props);
  const s = stats(picked);
  const days = Array.from(new Set(picked.map((t) => t.open_t.slice(0, 10)))).sort();

  // every flag that came up, most frequent first
  const counts = new Map<string, number>();
  picked.forEach((t) => t.flags.forEach((f) => counts.set(f, (counts.get(f) ?? 0) + 1)));
  const patterns = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);

  let at = OPEN;

  return (
    <AbsoluteFill style={{backgroundColor: C.ground}}>
      <Sequence durationInFrames={OPEN}>
        <Card>
          <div style={{
            font: `900 92px ${DISPLAY}`, color: C.text, marginBottom: 18,
            textTransform: "uppercase", letterSpacing: 1,
            filter: "drop-shadow(0 0 34px rgba(53,224,240,.42))",
          }}>
            {props.title}
          </div>
          <div style={{font: `400 26px ${MONO}`, color: C.muted, marginBottom: 54}}>
            {props.subtitle ? props.subtitle + " · " : ""}
            {picked.length} {picked.length === 1 ? "trade" : "trades"}
            {days.length ? " · " + (days.length > 1 ? days[0] + " to " + days[days.length - 1] : days[0]) : ""}
          </div>
          <div style={{display: "flex", gap: 84}}>
            <Figure label="net" value={money(s.pnl)} color={s.pnl >= 0 ? C.win : C.loss} />
            <Figure label="win rate" value={s.rate.toFixed(0) + "%"} />
            <Figure label="record" value={s.wins + "W " + s.losses + "L"} />
            <Figure label="expectancy" value={rr(s.exp)} color={s.exp >= 0 ? C.win : C.loss} />
          </div>
        </Card>
      </Sequence>

      {picked.map((t, i) => {
        const dur = sceneFrames(t);
        const from = at;
        at += dur;
        const before = picked.slice(0, i).reduce((a, x) => a + x.pnl, 0);
        return (
          <Sequence key={i} from={from} durationInFrames={dur}>
            <TradeScene trade={t} index={i} total={picked.length} runningBefore={before} />
          </Sequence>
        );
      })}

      <Sequence from={at} durationInFrames={CLOSE}>
        <Card>
          <div style={{
            font: `800 56px ${DISPLAY}`, color: C.text, marginBottom: 50,
            textTransform: "uppercase", letterSpacing: 2,
            filter: "drop-shadow(0 0 26px rgba(53,224,240,.32))",
          }}>
            What kept happening
          </div>
          <div style={{
            display: "flex", flexDirection: "column", gap: 15,
            width: 1180,
          }}>
            {patterns.map(([k, v]) => (
              <div key={k} style={{
                display: "flex", alignItems: "baseline", gap: 22,
                borderBottom: `1px solid ${C.lineSoft}`, paddingBottom: 13,
              }}>
                <span style={{font: `500 40px ${MONO}`, color: C.accent, width: 54}}>{v}</span>
                <span style={{font: `400 32px ${SANS}`, color: C.text}}>{k}</span>
              </div>
            ))}
          </div>
        </Card>
      </Sequence>
    </AbsoluteFill>
  );
};

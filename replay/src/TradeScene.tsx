import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame} from "remotion";
import type {Trade} from "./types";
import {C, DISPLAY, MONO, SANS, money, px, rr} from "./theme";

// One trade plays in three movements: a title card, the candles running in one
// minute at a time, then a hold on what it cost or earned and why.
export const INTRO = 45;
export const PER_BAR = 3;

export const holdFrames = (t: Trade) =>
  Math.min(340, Math.max(160, Math.round(t.note.length * 0.42) + 80));

export const sceneFrames = (t: Trade) =>
  INTRO + (t.bars?.length ?? 0) * PER_BAR + holdFrames(t);

// Chart box inside a 1920x1080 frame. Nothing is written over the candles: the
// values sit in a strip above, the levels get price tags on the right axis.
const CX0 = 92, CX1 = 1656, CY0 = 236, CY1 = 792;

type Ev = {i: number; head: string; body: string; tone: string};

const Val: React.FC<{label: string; value: string; sub?: string; color?: string}> = ({
  label, value, sub, color,
}) => (
  <div style={{
    flex: "1 1 auto", background: C.raised, padding: "12px 22px",
    display: "flex", flexDirection: "column", gap: 3,
  }}>
    <span style={{font: `600 14px ${SANS}`, color: C.faint, letterSpacing: 2.4}}>
      {label.toUpperCase()}
    </span>
    <span style={{font: `700 30px ${MONO}`, color: color ?? C.text}}>
      {value}
      {sub ? <span style={{font: `400 18px ${MONO}`, color: C.faint, marginLeft: 9}}>{sub}</span> : null}
    </span>
  </div>
);

export const TradeScene: React.FC<{
  trade: Trade; index: number; total: number; runningBefore: number;
}> = ({trade: t, index, total, runningBefore}) => {
  const frame = useCurrentFrame();
  const bars = t.bars ?? [];
  const n = bars.length;
  const ei = t.entry_i ?? 0;
  const xi = t.exit_i ?? Math.max(0, n - 1);
  const short = t.side === "Short";
  const risk = t.risk_pts ?? 0;

  const fade = (a: number, b: number, from: number, to: number) =>
    interpolate(frame, [a, b], [from, to], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp",
    });
  const titleOp = fade(INTRO - 14, INTRO, 1, 0);
  const chartOp = fade(INTRO - 14, INTRO, 0, 1);

  const playhead = Math.min(n - 1, Math.floor((frame - INTRO) / PER_BAR));
  const holding = frame >= INTRO + n * PER_BAR;

  // Fixed scale for the whole scene, worked out from every bar up front. If it
  // were derived from the bars revealed so far the chart would rescale on each
  // new candle and nothing would sit still long enough to read.
  let lo = Math.min(...bars.map((b) => b.l));
  let hi = Math.max(...bars.map((b) => b.h));
  const span0 = hi - lo;
  [t.entry, t.stop].forEach((v) => {
    if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  });
  let tgtOff = false;
  if (t.target != null) {
    if (t.target > lo - span0 * 0.5 && t.target < hi + span0 * 0.5) {
      lo = Math.min(lo, t.target); hi = Math.max(hi, t.target);
    } else tgtOff = true;
  }
  const pad = (hi - lo) * 0.09 || 1;
  lo -= pad; hi += pad;

  const W = CX1 - CX0, H = CY1 - CY0;
  const Y = (p: number) => CY0 + ((hi - p) / (hi - lo)) * H;
  const Yc = (p: number) => Math.max(CY0, Math.min(CY1, Y(p)));
  const X = (i: number) => CX0 + ((i + 0.5) / Math.max(1, n)) * W;
  const bw = Math.max(3, Math.min(26, (W / Math.max(1, n)) * 0.6));

  // What the trade is worth right now, in R and in money, so both numbers move
  // with the candles. The point value is recovered from the trade itself:
  // pnl = points * pointValue * qty, so it divides back out.
  const pointValue =
    t.got_pts && t.qty ? Math.abs(t.pnl / (t.got_pts * t.qty)) : 1;
  let liveR: number | null = 0, livePts = 0;
  if (playhead >= ei) {
    if (playhead >= xi) { liveR = t.got_r ?? null; livePts = t.got_pts; }
    else {
      const c = bars[playhead].c;
      livePts = short ? t.entry - c : c - t.entry;
      if (risk) liveR = livePts / risk;
    }
  }
  const liveMoney = livePts * pointValue * t.qty;

  const steps = (t.trail ?? [])
    .map((s) => ({...s, i: bars.findIndex((b) => b.t === s.t.slice(0, 5))}))
    .filter((s) => s.i >= 0);

  // The caption holds whatever happened most recently, so the strip always
  // explains the candle on screen rather than flashing and disappearing.
  const evs: Ev[] = [{
    i: ei, tone: C.text, head: "In at " + px(t.entry),
    body: risk
      ? "Risking " + risk + " points to the stop at " + px(t.stop ?? 0)
      : "No stop and no target were set on this one. Nothing was defining the "
        + "risk, so there is no R to score it by.",
  }];
  steps.forEach((s, k) => {
    if (k === 0) return;
    const early = s.fav_r != null && s.fav_r < 2 && s.kind !== "wrong side";
    evs.push({
      i: s.i,
      tone: s.kind === "wrong side" ? C.loss : early ? C.accent : C.muted,
      head: "Stop moved to " + px(s.sl),
      body: s.kind === "wrong side"
        ? "That is past the entry. On a short the stop is a buy order that must sit above the market, so it fired at once."
        : s.fav_r != null
          ? "Price had run " + s.fav_r.toFixed(2) + "R. Your rule holds the stop until 2R."
          : "",
    });
  });
  evs.push({
    i: xi, tone: t.pnl >= 0 ? C.win : C.loss,
    head: "Out at " + px(t.exit) + " by " + t.exit_type.toLowerCase(),
    body: rr(t.got_r) + "   " + money(t.pnl),
  });
  if (xi < n - 1) {
    evs.push({
      i: xi + 1, tone: C.muted, head: "What price did next",
      body: "Everything from here is after you were out.",
    });
  }
  const active = evs.filter((e) => e.i <= playhead).pop();
  const caption: Ev = active ?? {
    i: -1, tone: C.faint, head: "Waiting for the entry",
    body: t.symbol + " on the one minute",
  };

  const gridPrices = [0, 1, 2, 3, 4].map((k) => lo + ((hi - lo) * k) / 4);
  const tickEvery = Math.max(1, Math.ceil(n / 8));

  const AxisTag: React.FC<{p: number; bg: string}> = ({p, bg}) => {
    const y = Y(p);
    if (y < CY0 - 4 || y > CY1 + 4) return null;
    const txt = px(p);
    return (
      <g>
        <rect x={CX1 + 4} y={y - 16} width={txt.length * 13 + 22} height={32} fill={bg} />
        <text x={CX1 + 15} y={y + 8} fill={C.ground} style={{font: `500 22px ${MONO}`}}>{txt}</text>
      </g>
    );
  };

  return (
    <AbsoluteFill style={{backgroundColor: C.ground}}>
      {titleOp > 0.01 && (
        <AbsoluteFill style={{
          opacity: titleOp, justifyContent: "center", alignItems: "center",
          flexDirection: "column", gap: 18,
        }}>
          <div style={{font: `600 24px ${DISPLAY}`, color: C.accent, letterSpacing: 7}}>
            TRADE {index + 1} OF {total}
          </div>
          <div style={{
            font: `900 84px ${DISPLAY}`, color: C.text, textTransform: "uppercase",
            letterSpacing: 2, filter: "drop-shadow(0 0 30px rgba(53,224,240,.38))",
          }}>
            {t.symbol} {t.side}
          </div>
          <div style={{font: `400 30px ${MONO}`, color: C.muted}}>
            {t.open_t.slice(0, 10)} · {t.open_t.slice(11, 16)} to {t.close_t.slice(11, 16)}
          </div>
          {index > 0 && (
            <div style={{font: `400 26px ${MONO}`, color: C.faint, marginTop: 16}}>
              day so far{" "}
              <span style={{color: runningBefore >= 0 ? C.win : C.loss}}>
                {money(runningBefore)}
              </span>
            </div>
          )}
        </AbsoluteFill>
      )}

      <AbsoluteFill style={{opacity: chartOp}}>
        <div style={{
          position: "absolute", left: 92, top: 40, right: 92,
          display: "flex", alignItems: "baseline", gap: 26,
        }}>
          <span style={{font: `500 21px ${MONO}`, color: C.faint, letterSpacing: 2}}>
            {index + 1}/{total}
          </span>
          <span style={{
            font: `800 30px ${DISPLAY}`, color: C.text,
            textTransform: "uppercase", letterSpacing: 1.5,
          }}>
            {t.symbol} {t.side} ×{t.qty}
          </span>
          <span style={{font: `400 24px ${MONO}`, color: C.muted}}>
            {playhead >= 0 && playhead < n ? bars[playhead].t : ""}
          </span>
          <span style={{marginLeft: "auto", display: "flex", gap: 30, alignItems: "baseline"}}>
            <span style={{font: `600 40px ${MONO}`, color: t.pnl >= 0 ? C.win : C.loss}}>
              {playhead >= ei ? rr(liveR) : ""}
            </span>
            <span style={{font: `600 46px ${MONO}`, color: t.pnl >= 0 ? C.win : C.loss}}>
              {playhead >= ei ? money(liveMoney) : ""}
            </span>
          </span>
        </div>

        <div style={{
          position: "absolute", left: 92, right: 92, top: 106,
          display: "flex", gap: 1, background: C.lineSoft,
          border: `1px solid ${C.lineSoft}`,
        }}>
          <Val label="entry" value={px(t.entry)} />
          <Val label="stop" value={t.stop != null ? px(t.stop) : "—"}
            sub={risk ? risk + " pts" : undefined} color={C.loss} />
          <Val label="target" value={t.target != null ? px(t.target) : "—"}
            sub={t.planned_rr != null ? t.planned_rr.toFixed(2) + "R" : undefined} color={C.win} />
          <Val label="exit" value={px(t.exit)} sub={t.exit_type.toLowerCase()}
            color={t.pnl >= 0 ? C.win : C.loss} />
          <Val label="held" value={t.held_min + " min"} />
        </div>

        <svg width={1920} height={1080} style={{position: "absolute", inset: 0}}>
          {t.stop != null && (
            <rect x={CX0} y={Math.min(Yc(t.entry), Yc(t.stop))} width={W}
              height={Math.abs(Yc(t.stop) - Yc(t.entry))} fill={C.lossZone} />
          )}
          {t.target != null && (
            <rect x={CX0}
              y={Math.min(Yc(t.entry), Yc(tgtOff ? (short ? lo : hi) : t.target))}
              width={W}
              height={Math.abs(Yc(tgtOff ? (short ? lo : hi) : t.target) - Yc(t.entry))}
              fill={C.winZone} />
          )}

          {gridPrices.map((p, k) => (
            <g key={k}>
              <line x1={CX0} y1={Y(p)} x2={CX1} y2={Y(p)} stroke={C.lineSoft} strokeWidth={1} />
              <text x={CX1 + 15} y={Y(p) + 8} fill={C.faint} style={{font: `400 22px ${MONO}`}}>
                {px(p)}
              </text>
            </g>
          ))}
          {bars.map((b, i) =>
            i % tickEvery === 0 ? (
              <text key={"tk" + i} x={X(i)} y={CY1 + 36} fill={C.faint} textAnchor="middle"
                style={{font: `400 20px ${MONO}`}}>{b.t}</text>
            ) : null
          )}

          {bars.slice(0, playhead + 1).map((b, i) => {
            const up = b.c >= b.o;
            const col = up ? C.candleUp : C.candleDn;
            const y0 = Y(Math.max(b.o, b.c)), y1 = Y(Math.min(b.o, b.c));
            return (
              <g key={i} opacity={i > xi ? 0.34 : 1}>
                <line x1={X(i)} y1={Y(b.h)} x2={X(i)} y2={Y(b.l)} stroke={col} strokeWidth={2} />
                <rect x={X(i) - bw / 2} y={y0} width={bw} height={Math.max(2, y1 - y0)} fill={col} />
              </g>
            );
          })}

          {t.target != null && !tgtOff && (
            <line x1={CX0} y1={Y(t.target)} x2={CX1} y2={Y(t.target)}
              stroke={C.winFaded} strokeWidth={2} strokeDasharray="9 7" />
          )}
          {t.stop != null && (
            <line x1={CX0} y1={Y(t.stop)} x2={CX1} y2={Y(t.stop)}
              stroke={C.lossFaded} strokeWidth={2} strokeDasharray="9 7" />
          )}
          <line x1={CX0} y1={Y(t.entry)} x2={CX1} y2={Y(t.entry)} stroke={C.text} strokeWidth={2} />

          {/* the trail, stepping in as each move was actually made */}
          {steps.length > 1 && steps.map((s, k) => {
            if (s.i > playhead) return null;
            const next = steps[k + 1];
            const endI = next && next.i <= playhead ? next.i : Math.min(playhead, xi);
            const prev = steps[k - 1];
            return (
              <g key={"tr" + k}>
                <line x1={X(s.i)} y1={Y(s.sl)} x2={X(Math.max(endI, s.i))} y2={Y(s.sl)}
                  stroke={C.accent} strokeWidth={3} />
                {prev ? (
                  <line x1={X(s.i)} y1={Y(prev.sl)} x2={X(s.i)} y2={Y(s.sl)}
                    stroke={C.accent} strokeWidth={3} />
                ) : null}
              </g>
            );
          })}

          {playhead > xi && (
            <line x1={X(xi) + bw / 2 + 5} y1={CY0} x2={X(xi) + bw / 2 + 5} y2={CY1}
              stroke={C.faint} strokeWidth={2} strokeDasharray="5 7" />
          )}
          {playhead >= ei && (
            <circle cx={X(ei)} cy={Y(t.entry)} r={9} fill={C.text} stroke={C.ground} strokeWidth={3} />
          )}
          {playhead >= xi && (
            <circle cx={X(xi)} cy={Y(t.exit)} r={9} fill={t.pnl >= 0 ? C.win : C.loss}
              stroke={C.ground} strokeWidth={3} />
          )}

          {t.target != null && !tgtOff && <AxisTag p={t.target} bg={C.win} />}
          {t.stop != null && <AxisTag p={t.stop} bg={C.loss} />}
          <AxisTag p={t.entry} bg={C.text} />
        </svg>

        <div style={{
          position: "absolute", left: 92, right: 92, top: 866,
          borderTop: `1px solid ${C.line}`, paddingTop: 22,
        }}>
          {holding ? (
            <>
              <div style={{display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14}}>
                {t.flags.map((f) => (
                  <span key={f} style={{
                    font: `400 19px ${SANS}`, color: C.muted,
                    border: `1px solid ${C.line}`, padding: "3px 12px",
                  }}>{f}</span>
                ))}
              </div>
              <div style={{font: `400 26px ${SANS}`, color: "#D2D7E0", lineHeight: 1.5}}>
                {t.note}
              </div>
            </>
          ) : (
            <>
              <div style={{
                font: `800 32px ${DISPLAY}`, color: caption.tone, marginBottom: 12,
                textTransform: "uppercase", letterSpacing: 1.2,
              }}>
                {caption.head}
              </div>
              <div style={{font: `400 26px ${SANS}`, color: C.muted}}>{caption.body}</div>
            </>
          )}
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

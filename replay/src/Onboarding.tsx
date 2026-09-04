import React from "react";
import {AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame,
        useVideoConfig} from "remotion";
import {C, DISPLAY, MONO, SANS} from "./theme";

/**
 * A walkthrough for someone opening this cold.
 *
 * The honest status comes FIRST, before any of the features. A tool that looks
 * this finished invites the assumption that it works, and the most expensive
 * mistake a new trader can make with it is believing that before the evidence
 * exists. Everything else is the loop: read the higher timeframe, cut the
 * chart, take the trade blind, then let the diary tell you what you did.
 */

export const FPS = 30;
const S = (sec: number) => Math.round(sec * FPS);

export const CHAPTERS = [
  {id: "open", secs: 4},
  {id: "truth", secs: 13},
  {id: "tabs", secs: 12},
  {id: "loop", secs: 20},
  {id: "diary", secs: 12},
  {id: "close", secs: 7},
];
export const onboardingFrames = () =>
  CHAPTERS.reduce((a, c) => a + S(c.secs), 0);

const useFade = (hold: number) => {
  const f = useCurrentFrame();
  return interpolate(f, [0, 12, hold - 12, hold], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
};

const Rise: React.FC<{delay: number; children: React.ReactNode}> = ({delay, children}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: f - delay, fps, config: {damping: 200}});
  return (
    <div style={{opacity: s, transform: `translateY(${(1 - s) * 22}px)`}}>
      {children}
    </div>
  );
};

const Frame: React.FC<{hold: number; children: React.ReactNode}> = ({hold, children}) => (
  <AbsoluteFill style={{
    backgroundColor: C.ground, opacity: useFade(hold),
    padding: "90px 130px", justifyContent: "center",
  }}>
    {children}
  </AbsoluteFill>
);

const Head: React.FC<{children: React.ReactNode; tone?: string}> = ({children, tone}) => (
  <div style={{
    font: `800 46px ${DISPLAY}`, color: tone ?? C.text, textTransform: "uppercase",
    letterSpacing: 2, marginBottom: 40,
    filter: "drop-shadow(0 0 26px rgba(53,224,240,.28))",
  }}>{children}</div>
);

const Line: React.FC<{k: string; v: string; tone: string; delay: number}> = ({
  k, v, tone, delay,
}) => (
  <Rise delay={delay}>
    <div style={{
      display: "flex", gap: 28, alignItems: "baseline", padding: "16px 22px",
      background: C.raised, borderLeft: `3px solid ${tone}`, marginBottom: 10,
    }}>
      <span style={{
        font: `700 17px ${DISPLAY}`, color: tone, textTransform: "uppercase",
        letterSpacing: 1.6, flex: "0 0 330px",
      }}>{k}</span>
      <span style={{font: `400 25px ${SANS}`, color: C.muted, lineHeight: 1.45}}>{v}</span>
    </div>
  </Rise>
);

const Step: React.FC<{n: string; k: string; v: string; delay: number}> = ({
  n, k, v, delay,
}) => (
  <Rise delay={delay}>
    <div style={{display: "flex", gap: 26, alignItems: "flex-start", marginBottom: 26}}>
      <span style={{
        font: `900 40px ${MONO}`, color: C.accent, flex: "0 0 74px",
        filter: "drop-shadow(0 0 16px rgba(53,224,240,.5))",
      }}>{n}</span>
      <div>
        <div style={{font: `700 27px ${DISPLAY}`, color: C.text,
                     textTransform: "uppercase", letterSpacing: 1.4, marginBottom: 7}}>{k}</div>
        <div style={{font: `400 24px ${SANS}`, color: C.muted, lineHeight: 1.5,
                     maxWidth: 1180}}>{v}</div>
      </div>
    </div>
  </Rise>
);

export const Onboarding: React.FC = () => {
  let at = 0;
  const seq = (id: string, secs: number, node: React.ReactNode) => {
    const from = at;
    at += S(secs);
    return (
      <Sequence key={id} from={from} durationInFrames={S(secs)}>
        {node}
      </Sequence>
    );
  };

  return (
    <AbsoluteFill style={{backgroundColor: C.ground}}>
      {seq("open", 4,
        <Frame hold={S(4)}>
          <AbsoluteFill style={{justifyContent: "center", alignItems: "center"}}>
            <Rise delay={0}>
              <div style={{
                font: `900 96px ${DISPLAY}`, color: C.text, textTransform: "uppercase",
                letterSpacing: 2, filter: "drop-shadow(0 0 36px rgba(53,224,240,.42))",
              }}>Traders Diary</div>
            </Rise>
            <Rise delay={12}>
              <div style={{font: `400 28px ${MONO}`, color: C.muted, marginTop: 22}}>
                practise, record, and be told what you did
              </div>
            </Rise>
          </AbsoluteFill>
        </Frame>)}

      {seq("truth", 13,
        <Frame hold={S(13)}>
          <Head tone={C.loss}>Read this first</Head>
          <Line delay={6} tone={C.loss} k="Not validated"
            v="Nothing here has passed its own statistical gate. It fails walk-forward and it has no independent second data source." />
          <Line delay={20} tone={C.loss} k="One setting ever worked"
            v="EURUSD at a 0.5R target: about $500 a month on $50,000. Everything else measured negative or indistinguishable from zero." />
          <Line delay={34} tone={C.accent} k="A high win rate is a shape"
            v="Aim closer than your stop and you win most trades by design. It is not an edge, and costs eat the small wins." />
          <Line delay={48} tone={C.loss} k="Do not fund an account"
            v="Use it to practise and to keep an honest record. Nothing on the screen is evidence yet." />
        </Frame>)}

      {seq("tabs", 12,
        <Frame hold={S(12)}>
          <Head>Three tabs</Head>
          <Step n="1" delay={6} k="Demo"
            v="A live chart on NQ and ES with session highs and lows. Place a paper trade and watch what you risk against what you stand to make, before you commit." />
          <Step n="2" delay={22} k="Diary"
            v="Every trade you take, drawn on the minute bars it happened on, with a written read of what went right or wrong." />
          <Step n="3" delay={38} k="Replay"
            v="Step through history one bar at a time and trade it blind. This is where the practice happens." />
        </Frame>)}

      {seq("loop", 20,
        <Frame hold={S(20)}>
          <Head>The loop</Head>
          <Step n="1" delay={6} k="Read the higher timeframe"
            v="Open Replay on the 1H or 4H. The levels that matter were formed days or weeks before the day you are about to trade." />
          <Step n="2" delay={26} k="Cut the chart"
            v="Click a bar. Everything after it disappears and cannot come back. You cannot trade a day whose ending you can already see." />
          <Step n="3" delay={46} k="Take the trade blind"
            v="Drop to the 5m or 1m, set the stop and target, and step forward. Both levels touched inside one bar counts as the loss, because that is the honest assumption." />
          <Step n="4" delay={66} k="Save it to the diary"
            v="Practice is scored the same way real trades are, and kept apart from them so it can never flatter your record." />
        </Frame>)}

      {seq("diary", 12,
        <Frame hold={S(12)}>
          <Head>What the diary tells you</Head>
          <Line delay={6} tone={C.loss} k="Right, stop too tight"
            v="You read the direction correctly and were stopped anyway, then price ran your way. Both losses on the first real day were this." />
          <Line delay={20} tone={C.loss} k="Stop on the wrong side"
            v="Moved past the entry, where it is already triggered. Protecting the trade is what closed it." />
          <Line delay={34} tone={C.accent} k="Trailed early"
            v="Tightened before price had run the distance your own rule asks for." />
          <Line delay={48} tone={C.accent} k="Cut short"
            v="Closed by hand, and price reached your target shortly afterwards." />
        </Frame>)}

      {seq("close", 7,
        <Frame hold={S(7)}>
          <AbsoluteFill style={{justifyContent: "center", alignItems: "center"}}>
            <Rise delay={0}>
              <div style={{font: `800 54px ${DISPLAY}`, color: C.text,
                           textTransform: "uppercase", letterSpacing: 2,
                           textAlign: "center", lineHeight: 1.3}}>
                One hundred trades
              </div>
            </Rise>
            <Rise delay={14}>
              <div style={{font: `400 30px ${SANS}`, color: C.muted, marginTop: 26,
                           textAlign: "center", maxWidth: 1000, lineHeight: 1.5}}>
                That is roughly what it takes before a win rate means anything.
                Until then the numbers describe what happened, not what tends to.
              </div>
            </Rise>
          </AbsoluteFill>
        </Frame>)}
    </AbsoluteFill>
  );
};

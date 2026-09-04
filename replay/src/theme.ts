import {loadFont as loadOrbitron} from "@remotion/google-fonts/Orbitron";
import {loadFont as loadChakra} from "@remotion/google-fonts/ChakraPetch";
import {loadFont as loadJetBrains} from "@remotion/google-fonts/JetBrainsMono";

// Fonts must be loaded through Remotion rather than a stylesheet link, or the
// renderer screenshots frames before the faces arrive and everything falls back.
const {fontFamily: orbitron} = loadOrbitron("normal", {
  weights: ["600", "800", "900"], subsets: ["latin"],
});
const {fontFamily: chakra} = loadChakra("normal", {
  weights: ["400", "500", "600", "700"], subsets: ["latin"],
});
const {fontFamily: jetbrains} = loadJetBrains("normal", {
  weights: ["400", "500", "700"], subsets: ["latin"],
});

export const DISPLAY = `${orbitron}, sans-serif`;
export const SANS = `${chakra}, system-ui, sans-serif`;
export const MONO = `${jetbrains}, ui-monospace, monospace`;

// Same palette as the page, so the video and the diary read as one thing.
export const C = {
  ground: "#05070C",
  raised: "#0A0F17",
  lift: "#111A26",
  line: "#1B2838",
  lineSoft: "#121A26",
  text: "#E8F0F8",
  muted: "#7E90A8",
  faint: "#4A5A70",
  accent: "#35E0F0",
  win: "#2BE08A",
  loss: "#FF5C6E",
  winFaded: "#177A4C",
  lossFaded: "#8E2F3A",
  winZone: "rgba(43,224,138,0.085)",
  lossZone: "rgba(255,92,110,0.085)",
  candleUp: "#22B877",
  candleDn: "#C4485A",
};

export const px = (v: number) =>
  v.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});

// A trade taken with no stop has no R, because R is defined by the risk. That
// is not a missing number to paper over: it is the fact worth showing.
export const rr = (v: number | null | undefined) =>
  v == null ? "no R" : (v >= 0 ? "+" : "") + v.toFixed(2) + "R";

export const money = (v: number) =>
  (v < 0 ? "-" : "+") + "$" + Math.abs(v).toLocaleString("en-US", {maximumFractionDigits: 0});

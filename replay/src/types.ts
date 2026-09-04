export type Bar = {t: string; o: number; h: number; l: number; c: number};

export type TrailStep = {
  t: string;
  sl: number;
  kind?: string;
  fav_r?: number | null;
};

export type Trade = {
  symbol: string;
  side: string;
  qty: number;
  open_t: string;
  close_t: string;
  entry: number;
  exit: number;
  stop?: number | null;
  target?: number | null;
  risk_pts?: number | null;
  planned_rr?: number | null;
  // A trade taken with no stop has no R at all, because R is defined by the
  // risk. Null is the honest value, not zero.
  got_r: number | null;
  got_pts: number;
  pnl: number;
  mfe_r?: number | null;
  mae_r?: number | null;
  kept_pct?: number | null;
  held_min: number;
  exit_type: string;
  flags: string[];
  note: string;
  trail?: TrailStep[];
  bars?: Bar[];
  entry_i?: number;
  exit_i?: number;
};

// Real browser storage for saved lineups/rotations (localStorage), in the
// shape the save/load code below expects.
window.storage = {
  get: async (key) => {
    const value = localStorage.getItem(key);
    return value === null ? null : { value };
  },
  set: async (key, value) => { localStorage.setItem(key, value); },
};
const WATCHLIST_STORAGE_KEY = 'ucsd_watchlist_lineup_candidates_v1';
const OLD_WATCHLIST_STORAGE_KEY = 'ucsd_watchlist_lineup_candidates_v2';

// ─── PLAYER DATA ───────────────────────────────────────────────
// ─── TEAM CONTEXT (KenPom-style adj efficiency, 2025-26) ──────
const TEAM_DATA = {"UC San Diego": {"oe": 107.8,"de": 103.5,"em": 4.3,"rk": 121,"rkOE": 196,"rkDE": 69},"UC Irvine": {"oe": 104.6,"de": 98.9,"em": 5.71,"rk": 107,"rkOE": 264,"rkDE": 26},"UC Santa Barbara": {"oe": 113.7,"de": 110.8,"em": 2.95,"rk": 132,"rkOE": 98,"rkDE": 209},"UC Riverside": {"oe": 104.0,"de": 111.9,"em": -7.96,"rk": 261,"rkOE": 273,"rkDE": 232},"UC Davis": {"oe": 108.0,"de": 107.3,"em": 0.67,"rk": 162,"rkOE": 190,"rkDE": 135},"Cal Poly": {"oe": 109.4,"de": 113.3,"em": -3.89,"rk": 214,"rkOE": 165,"rkDE": 258},"Cal St. Fullerton": {"oe": 109.3,"de": 109.3,"em": 0.02,"rk": 170,"rkOE": 169,"rkDE": 176},"Cal St. Bakersfield": {"oe": 101.9,"de": 117.4,"em": -15.54,"rk": 327,"rkOE": 304,"rkDE": 323},"Long Beach St.": {"oe": 105.6,"de": 111.5,"em": -5.98,"rk": 233,"rkOE": 243,"rkDE": 224},"Hawaii": {"oe": 107.2,"de": 101.6,"em": 5.58,"rk": 108,"rkOE": 212,"rkDE": 47},"Loyola Chicago": {"oe": 103.6,"de": 113.5,"em": -9.87,"rk": 280,"rkOE": 280,"rkDE": 261},"Oregon St.": {"oe": 109.2,"de": 110.0,"em": -0.86,"rk": 179,"rkOE": 174,"rkDE": 191},"Florida Gulf Coast": {"oe": 105.7,"de": 112.3,"em": -6.57,"rk": 244,"rkOE": 240,"rkDE": 241},"Indiana St.": {"oe": 106.1,"de": 109.3,"em": -3.16,"rk": 207,"rkOE": 227,"rkDE": 175},"Northeastern": {"oe": 107.5,"de": 118.3,"em": -10.76,"rk": 287,"rkOE": 206,"rkDE": 333},"Pacific": {"oe": 110.7,"de": 105.4,"em": 5.26,"rk": 112,"rkOE": 144,"rkDE": 101},"West Virginia": {"oe": 111.9,"de": 97.2,"em": 14.67,"rk": 55,"rkOE": 123,"rkDE": 18},"North Dakota": {"oe": 106.8,"de": 116.6,"em": -9.84,"rk": 279,"rkOE": 216,"rkDE": 313},"Wake Forest": {"oe": 116.9,"de": 106.4,"em": 10.58,"rk": 80,"rkOE": 70,"rkDE": 113},"Columbia": {"oe": 108.6,"de": 110.7,"em": -2.09,"rk": 193,"rkOE": 182,"rkDE": 205},"Oakland": {"oe": 115.4,"de": 115.1,"em": 0.25,"rk": 168,"rkOE": 81,"rkDE": 293},"St. Thomas": {"oe": 112.9,"de": 108.0,"em": 4.92,"rk": 115,"rkOE": 108,"rkDE": 142},"Nebraska": {"oe": 119.5,"de": 93.0,"em": 26.58,"rk": 16,"rkOE": 47,"rkDE": 8},"Seton Hall": {"oe": 110.8,"de": 94.7,"em": 16.09,"rk": 51,"rkOE": 143,"rkDE": 15},"LSU": {"oe": 119.9,"de": 106.7,"em": 13.19,"rk": 61,"rkOE": 45,"rkDE": 124}};
let UCSD_ADJ_OE = 107.8, UCSD_ADJ_DE = 103.5, UCSD_ADJ_EM = 4.30;
const PRIOR_ADJ_OE = 107.8, PRIOR_ADJ_DE = 103.5;
// Conference translation used by the separate team efficiency projection.
const CONF_TRUE = {"BW": 0.0, "ACC": 3.28, "B12": 4.05, "BE": 2.99, "B10": 4.0, "SEC": 4.2, "WCC": 1.11, "MVC": 0.64, "CAA": -0.37, "Ivy": -0.15, "Horz": -0.49, "Sum": -1.23, "ASun": -1.31, "JUCO": -1.5, "D2": -3.0, "Pat": -0.6};
function teamCtx(t){ return TEAM_DATA[t] || null; }
function playerTeamOE(p){
  const t = teamCtx(p && p.team);
  return t ? t.oe : UCSD_ADJ_OE;
}
function adjTSof(p){
  return (p.ts||54) - (playerTeamOE(p) - UCSD_ADJ_OE) * 0.18;
}
function effOBPMof(p){
  const ca = (p.fromConf && CONF_TRUE[p.fromConf] !== undefined) ? CONF_TRUE[p.fromConf] : 0;
  return (p.obpr || 0) + ca;
}
// UCSD returner usage-weighted OBPM baseline (they produced the actual 107.8)
const OBPM_BASE = 0.421;
// ORtg anchored to UCSD's ACTUAL AdjOE with UCSD's actual four factors as deltas
const A_EFG = 52.6, A_TO = 17.0, A_OR = 25.6, A_FTR = 31.2;
function calcORtgV2(efg, to, rawOr, ftr, wOBPM, shooters){
  const orb = 27.0 + (rawOr - 27.0) * 0.55;                       // rebounding overlap
  const tal = Math.max(-6, Math.min(6, (wOBPM - OBPM_BASE) * 1.15));
  const spc = Math.max(-3, Math.min(3, (shooters - 2.5) * 1.40)); // spacing interaction
  return UCSD_ADJ_OE
    + (efg - A_EFG) * 1.75
    - (to  - A_TO)  * 0.85
    + (orb - A_OR)  * 0.30
    + (ftr - A_FTR) * 0.12
    + tal + spc;
}
function shooterCount(list, weights){
  let s = 0, tot = weights.reduce((a,b)=>a+b,0) || 1;
  list.forEach((p,i)=>{ if(p && (p.threePct||0) >= 33 && (p.threeRate||0) >= 0.25) s += (weights[i]/tot)*5; });
  return s;
}

function getEffectiveBpm(player) {
  return +lineupBpm(player).value.toFixed(1);
}

const PLAYERS = {
  beath: {
    team: 'UC San Diego',
    name: 'Leo Beath', num: 8, pos: 'PF/SF', yr: 'Sr', ht: '6-8',
    bpr: -0.1, obpr: 0.5, dbpr: -0.6, indDrtg: 100.8,
    ts: 55.0, usg: 20.5, threeRate: 0.43, threePct: 32.9,
    arate: 15.0, oreb: 8.0, torate: 14.8, ftr: 30.0, stl: 1.3, blk: 2.4, dreb: 18.8, htIn: 80,
    note: `Beath is UCSD's most complete two-way player. His steal rate and block production at 6-8 give the lineup elite wing defense. <strong>Key concern:</strong> TS% dipped in conference play and 3PT% at 32.9% limits his spacing value. With Suutela providing interior presence, Beath can shift to a more off-ball role next year, which should <strong>improve his efficiency</strong>. His combination of rebounding (5.1 RPG) and assist creation (15.0 ARate) makes him one of the more versatile forwards in the Big West.`
  },
  beattie: {
    team: 'UC San Diego',
    name: 'Tom Beattie', num: 9, pos: 'SG/PG/SF', yr: 'Sr', ht: '6-5',
    bpr: 2.6, obpr: 1.4, dbpr: 1.2, indDrtg: 100.4,
    ts: 54.3, usg: 18.6, threeRate: 0.46, threePct: 31.2,
    arate: 20.5, oreb: 4.8, torate: 15.2, ftr: 32.0, stl: 2.4, blk: 0.7, dreb: 17.2, htIn: 77,
    note: `The engine of this team. Beattie led the team in assists in conference play (3.4 APG) and logged the most minutes per game (31.4). His <strong>ARate of 20.5 is legitimately elite</strong> for a mid-major guard. The concern: his 3PT% dropped to 27.0% in conference play. Adding Dotson as a second playmaker takes pressure off Beattie and could unlock more off-ball movement for him. His <strong>steal rate (2.4) is exceptional</strong> and gives this team a pressure defense identity.`
  },
  chaikin: {
    team: 'UC San Diego',
    name: 'Alex Chaikin', num: 10, pos: 'SG', yr: 'Jr', ht: '6-5',
    bpr: -0.5, obpr: 0.4, dbpr: -0.9, indDrtg: 106.0,
    ts: 57.1, usg: 17.9, threeRate: 0.76, threePct: 38.2,
    arate: 8.0, oreb: 1.8, torate: 12.1, ftr: 18.0, stl: 1.1, blk: 1.3, dreb: 8.5, htIn: 77,
    note: `The most underrated player on this roster. Chaikin shot <strong>42.4% from 3 in conference play on real volume (50-118 attempts)</strong>. His 3PT attempt rate of 76% means he's almost purely a perimeter player, the ideal complement to interior finishers. <strong>Low DBPR (0.6)</strong> means he's a defensive liability — in a lineup with Beath and Beattie providing defensive presence, Chaikin's shooting value outweighs the risk.`
  },
  burke: {
    team: 'UC San Diego',
    name: 'Aidan Burke', num: 20, pos: 'SG/SF', yr: 'Sr', ht: '6-3',
    bpr: 0.0, obpr: 0.5, dbpr: -0.5, indDrtg: 103.3,
    ts: 57.0, usg: 14.0, threeRate: 0.69, threePct: 31.0,
    arate: 11.4, oreb: 3.0, torate: 16.4, ftr: 22.0, stl: 2.0, blk: 1.0, dreb: 11.0, htIn: 75,
    note: `Burke's overall TS% of 57.0 is solid, but his <strong>3PT% in conference play dropped to 23.5%</strong> (12-51). His FT rate shows he can create contact. His best role next season is as a <strong>defensive wing off the bench</strong> — especially with Chaikin and Dotson as more reliable perimeter threats. If his 3PT% regresses to the mean, he becomes a real asset.`
  },
  vance: {
    team: 'UC San Diego',
    name: 'Jaden Vance', num: 13, pos: 'SF', yr: 'So', ht: '6-6',
    bpr: 0.7, obpr: 0.5, dbpr: 0.2, indDrtg: 97.8,
    ts: 54.9, usg: 19.9, threeRate: 0.37, threePct: 33.0,
    arate: 9.1, oreb: 6.2, torate: 18.2, ftr: 28.0, stl: 3.2, blk: 3.3, dreb: 16.2, htIn: 78,
    note: `Vance has an intriguing physical profile — 6-6 with a <strong>block rate of 3.3% and steal rate of 3.2%</strong>. He only played 24 games but flashed real defensive upside. Strong candidate for a <strong>breakout sophomore season</strong>.`
  },
  vukicevic: {
    team: 'UC San Diego',
    name: 'Dimitrije Vukicevic', num: 33, pos: 'C', yr: 'So', ht: '7-0',
    bpr: -1.2, obpr: -0.6, dbpr: -0.6, indDrtg: 100.6,
    ts: 60.8, usg: 21.7, threeRate: 0.02, threePct: 0.0,
    arate: 14.0, oreb: 9.2, torate: 13.0, ftr: 38.0, stl: 1.7, blk: 2.8, dreb: 19.5, htIn: 84,
    note: `A 7-footer who shot <strong>60.0% from 2 on limited volume</strong>. His <strong>FT% of 50%</strong> is a late-game liability. At 7-0 with a 2.8 block rate, he changes the geometry of the defense. Best role: 12-18 minute interior specialist.`
  },
  pendleton: {
    team: 'UC San Diego',
    name: 'Cade Pendleton', num: 4, pos: 'C/PF', yr: 'Sr', ht: '6-10',
    bpr: -2.9, obpr: -1.8, dbpr: -1.1, indDrtg: 102.5,
    ts: 35.9, usg: 15.5, threeRate: 0.74, threePct: 22.0,
    arate: 11.6, oreb: 9.5, torate: 19.5, ftr: 15.0, stl: 0.9, blk: 3.6, dreb: 17.8, htIn: 82,
    note: `Pendleton's TS% of 35.9 is the most significant red flag on the roster. His block rate (3.6%) shows rim protection value. With Suutela and Vukicevic in the program, his path to meaningful minutes narrows — best as a <strong>defensive specialist in specific matchups</strong>.`
  },
  brooks: {
    team: 'UC San Diego',
    name: 'Jasen Brooks', num: 11, pos: 'PG/SG', yr: 'Jr', ht: '6-0',
    bpr: 0.2, obpr: -0.3, dbpr: 0.5, indDrtg: 102.3,
    fromConf: 'bigwest',
    ts: 50.0, usg: 19.1, threeRate: 0.60, threePct: 32.1,
    arate: 6.6, torate: 7.9, stl: 2.9, blk: 0.0, dreb: 8.5, oreb: 2.8,
    ftr: 5.3, htIn: 72,
    note: `<strong>Returning — UCSD (Big West), Fr → Jr · PG/SG · 6-0 · #11.</strong> Brooks appeared in 18 games in 2024-25 in a limited role (4.2 MPG, 0 starts). He posted a <strong>7.9% turnover rate</strong> in those minutes.<br><br>
    <strong>Shooting:</strong> 32.1% on 9-28 three-point attempts — adequate but limited volume. FT% of 100% (1-1) is too small to be meaningful. TS% of 50.0% reflects below-average efficiency overall.<br><br>
    <strong>Context:</strong> The sample is small (18 games, about 4 minutes per game). His 2.9% steal rate also stands out. <strong>Key upside:</strong> If he can earn rotation minutes, his ball security profile is exactly what a team with Barno's TORate of 16.6% needs as a backup PG.`
  },
  dotson: {
    team: 'Loyola Chicago',
    name: 'Kayde Dotson', num: 4, pos: 'PG/SG', yr: 'Jr', ht: '6-1',
    bpr: -1.2, obpr: -0.4, dbpr: -0.8, indDrtg: 108.3,
    fromConf: 'MVC',
    ts: 56.1, usg: 20.6, threeRate: 0.67, threePct: 38.0, ftr: 26.0,
    arate: 16.4, oreb: 3.2, torate: 17.4, stl: 1.2, blk: 0.2, dreb: 12.0, htIn: 73,
    note: `<strong>Excellent addition.</strong> Dotson's conference ARate of 18.9 ranked #21 nationally. He's a high-volume 3PT shooter (62-163, 38.0%) who can also create off the dribble. TORate of 17.4% is the main concern. Fits perfectly as a <strong>complementary playmaker next to Beattie</strong>.`
  },
  suutela: {
    team: 'Oregon St.',
    name: 'Olavi Suutela', num: 37, pos: 'C/PF', yr: 'So', ht: '6-10',
    bpr: -1.7, obpr: -1.2, dbpr: -0.4, indDrtg: 105.0,
    fromConf: 'WCC',
    ts: 63.7, usg: 16.4, threeRate: 0.26, threePct: 34.5, ftr: 47.4,
    arate: 10.9, oreb: 7.8, torate: 12.0, stl: 1.4, blk: 0.8, dreb: 16.4, htIn: 82,
    note: `<strong>The most impactful addition on the roster.</strong> Suutela's TS% of 63.7 is elite — driven by 65.1% 2PT shooting. His <strong>conference TS% of 62.1 (ranked #13 nationally)</strong> at Oregon State (WCC) proves this isn't a soft-competition number. <strong>In lineups with Chaikin and Dotson spacing the floor, Suutela at the 4/5 becomes one of the most efficient scoring options in the Big West.</strong>`
  },
  barno: {
    team: 'Florida Gulf Coast',
    name: 'Rahmir Barno', num: 1, pos: 'PG', yr: 'Jr', ht: '6-0',
    bpr: -1.2, obpr: 0.8, dbpr: -2.0, indDrtg: 103.5,
    fromConf: 'asun',
    ts: 50.5, usg: 22.1, threeRate: 0.31, threePct: 29.6,
    arate: 28.1, torate: 16.6, stl: 2.6, blk: 0.5, dreb: 10.5, oreb: 1.2,
    ftr: 38.7, htIn: 72,
    note: `<strong>Portal target — FGCU (ASUN), So → Jr.</strong> Barno was a full-time starter in 2025-26, averaging 11.7 PPG and 5.0 APG in 31.6 MIN/G across all 34 games. His <strong>ARate of 28.1 (conf rank #6)</strong> is elite. ORtg of 105.3 at 22.1% usage is solid for an ASUN guard.<br><br>
    <strong>Competition context:</strong> ASUN is comparable to the Big West — adjustment is minimal. His <strong>STL% of 2.6</strong> is a standout defensive metric. FTRate of 38.7 shows he attacks the rim.<br><br>
    <strong>Key concerns:</strong> TS% of 50.5 is below average — 3PT% of 29.6% is a spacing liability; TORate of 16.6 is elevated. <strong>Key upside:</strong> Elite playmaker at 6-0; passing vision and defensive activity address real roster needs.`
  },

  eaglestaff: {
    team: 'West Virginia',
    name: 'Treysen Eaglestaff', num: 5, pos: 'SG/SF', yr: 'Sr', ht: '6-6',
    bpr: 2.8, obpr: 0.1, dbpr: 1.4, fromConf: 'B12',
    ts: 52.7, usg: 23.5, threeRate: 0.57, threePct: 35.5,
    arate: 12.7, torate: 15.3, stl: 1.85, blk: 1.05, dreb: 12.25, oreb: 2.5,
    ftr: 24.1, htIn: 78, indDrtg: 101.8,
    note: `<strong>Committed — WVU (B12) 2025-26 + NoDak (Summit) 2024-25 · Sr · SG/SF · 6-6 · #5.</strong> Two-season blend: 60% B12 / 40% Summit by minutes. Raw BPM +2.8, adjBPM +9.56. High-volume 3PT shooter (57% of FGA from 3, 35.5% blended). DR% improved dramatically at WVU (8.6→15.9). Best fit: 3-and-D wing starter.`
  },
  holmes: {
    name: 'Jake Holmes', num: 15, pos: 'PF/SF', yr: 'Fr', ht: '6-8',
    team: 'Canterbury Rams',
    bpr: 1.5, obpr: 0.8, dbpr: 0.7,
    fromConf: 'nznbl',
    ts: 58.2, usg: 19.4, threeRate: 0.50, threePct: 34.4,
    arate: 9.4, torate: 11.3, stl: 2.0, blk: 1.8, dreb: 18.2, oreb: 5.3,
    ftr: 38.8, htIn: 80, indDrtg: 99.0,
    note: `<strong>Incoming Freshman — Canterbury Rams (NZ NBL) 2025-26 · Fr · PF/SF · 6-8 · #15.</strong> Played 20 games at 22.3 mpg as a teenager against grown professionals in New Zealand's top league, going 16-4. That context matters more than the raw line: holding a real rotation role in a pro league at his age is a genuine development signal.<br><br><strong>Directly computed from box score:</strong> TS% 58.2% · eFG% 55.0% · 3PT% 34.4% on 21-61 · 2P% 58.3% (35-60) · FT% 68.1% · FTRate 38.8 · 3P rate 0.50 — a 6-8 forward taking half his shots from three and finishing at 58% inside.<br><br><strong>Profile:</strong> Efficient, low-mistake stretch four. TORate of 11.3% is excellent, and the 58.2 TS% on a 19.4 usage says he picks his spots well rather than forcing. Fills the Beath/Suutela archetype with more perimeter range than either.<br><br><strong style="color:var(--red)">Estimation caveat — read these numbers differently than the rest of the roster.</strong> NZ NBL does not publish possession data, so every rate stat here (USG, TORate, ARate, STL%, BLK%, OReb%, DReb%, and therefore indDrtg 99.0) is derived from per-game box scores using an assumed 74 possessions per 40 minutes. Rebounding rates in particular swing several points on that assumption — DReb% lands anywhere from 18.2 to 23.9 depending on pace. Conservative ends of each range were used. There is also no Barttorvik BPM for this league; the +1.5 raw BPM is an estimate from the box score, not a measured value.<br><br><strong>League strength:</strong> NZ NBL is set at −1.00 vs Big West — near-neutral, and the single softest number in this profile. Unlike the D1 conference values, which are measured from 365 teams of AdjEM data, there is no shared opponent pool to calibrate a foreign pro league against. Treat his adj BPM of +0.5 as a placeholder that should be revised the moment there are D1 minutes to look at.`
  },
  johnson: {
    name: 'Jordan Johnson', num: 3, pos: 'PG/SG', yr: 'Jr', ht: '6-3',
    bpr: 0.5, obpr: 0.8, dbpr: 0.4, indDrtg: 100.8,
    fromConf: 'juco',
    ts: 55.0, usg: 20.0, threeRate: 0.38, threePct: 38.0,
    arate: 22.0, torate: 13.5, stl: 2.2, blk: 0.2, dreb: 14.0, oreb: 5.8,
    ftr: 32.0, htIn: 75,
    d2projection: true,
    projFloor:   { mpg: 18, ppg: 4.6, rpg: 1.9, apg: 1.8, threePct: 36.5, efg: 51.0, ft: 79.1 },
    projBase:    { mpg: 24, ppg: 6.8, rpg: 2.7, apg: 2.6, threePct: 38.0, efg: 53.5, ft: 79.1 },
    projCeiling: { mpg: 30, ppg: 9.3, rpg: 3.7, apg: 3.4, threePct: 40.0, efg: 56.0, ft: 79.1 },
    note: `<strong>Potential Addition — Calhoun Community College (NJCAA D1, Alabama), Jr · PG/SG · 6-3.</strong> Johnson is one of the more intriguing JUCO prospects on the board. His raw D2 numbers are exceptional across the board — the key question is how much translates to Big West competition.<br><br>

    <strong style="font-size:10px; letter-spacing:0.1em;">JUCO RAW STATS (2025-26) — 31 GP, 31 GS:</strong>
    <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:3px; margin:6px 0;">
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">3PT%</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px; color:var(--green);">43.5%</div><div style="font-size:7px; color:var(--muted);">40-92</div></div>
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">FT%</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px;">79.1%</div><div style="font-size:7px; color:var(--muted);">110-139</div></div>
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">TS%</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px;">58.0%</div></div>
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">AST/TO</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px;">142/64</div><div style="font-size:7px; color:var(--muted);">2.2:1</div></div>
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">PPG</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px;">17.0</div></div>
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">RPG</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px;">5.7</div></div>
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">APG</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px;">4.6</div></div>
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:4px 6px; text-align:center;"><div style="font-size:7px; color:var(--muted);">STL</div><div style="font-family:'Bebas Neue',sans-serif; font-size:14px;">2.2</div></div>
    </div>

    <strong style="font-size:10px; letter-spacing:0.1em;">D1/BIG WEST PROJECTION MODEL:</strong>
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:4px; margin:6px 0;">
      <div style="background:var(--card); border:1px solid var(--border); border-radius:2px; padding:6px 8px;">
        <div style="font-size:7px; color:var(--muted); letter-spacing:0.1em; margin-bottom:3px;">FLOOR · 18 MPG</div>
        <div style="font-family:'Bebas Neue',sans-serif; font-size:13px; color:var(--red);">4.6 PPG · 1.8 APG</div>
        <div style="font-size:8px; color:var(--muted);">3PT 36.5% · eFG 51.0%</div>
      </div>
      <div style="background:var(--gold-tint); border:1px solid var(--gold-dim); border-radius:2px; padding:6px 8px;">
        <div style="font-size:7px; color:var(--gold-dim); letter-spacing:0.1em; margin-bottom:3px;">BASE · 24 MPG</div>
        <div style="font-family:'Bebas Neue',sans-serif; font-size:13px; color:var(--gold);">6.8 PPG · 2.6 APG</div>
        <div style="font-size:8px; color:var(--muted);">3PT 38.0% · eFG 53.5%</div>
      </div>
      <div style="background:color-mix(in srgb, var(--green) 8%, transparent); border:1px solid var(--green); border-radius:2px; padding:6px 8px;">
        <div style="font-size:7px; color:var(--green); letter-spacing:0.1em; margin-bottom:3px;">CEILING · 30 MPG</div>
        <div style="font-family:'Bebas Neue',sans-serif; font-size:13px; color:var(--green);">9.3 PPG · 3.4 APG</div>
        <div style="font-size:8px; color:var(--muted);">3PT 40.0% · eFG 56.0%</div>
      </div>
    </div>

    <strong>Why the 3PT% translates:</strong> 43.5% on <strong>92 attempts</strong> across a full 31-game season is not a fluke sample — that's real volume. Conference-only 3PT% of 38.1% on 42 attempts holds up under scrutiny. The projection regresses to 36.5–40.0% at D1 which is still a legitimate floor-spacer range.<br><br>
    <strong>Passing:</strong> 142 AST vs 64 TO (2.2:1 ratio) is elite creation. ARate projects to ~22% at D1 — a genuine secondary playmaker alongside Barno.<br><br>
    <strong>Key concerns:</strong> NJCAA D1 competition gap is real — Calhoun CC is a strong JUCO program but Big West defenses are a significant step up. JUCO → D1 transitions have high variance. <strong>Key upside:</strong> A 6-3 guard who shoots 38%+ from 3 on volume, creates at a high rate, and plays elite defense (2.2 STL/g) is exactly the profile UCSD needs.`
  }
};


// Helper: display name (Last name, or First Initial. Last if ambiguous)
function shortName(player) {
  const parts = player.name.split(' ');
  return parts[parts.length - 1]; // last name
}
// ─── STATE ─────────────────────────────────────────────────────
// lineup is array of 5 slots: each is a player id or null
let lineup = [null, null, null, null, null];
let benchMinutes = {}; // id -> minutes

const ROTATION_BASE = {
  'barno': 25,
  'dotson': 25,
  'eaglestaff': 25,
  'beath': 25,
  'suutela': 25,
  'bench_0_0_id': 'johnson', 'bench_0_0_min': 10,
  'bench_0_1_id': 'beattie', 'bench_0_1_min': 5,
  'bench_0_2_id': '', 'bench_0_2_min': 0,
  'bench_1_0_id': 'chaikin', 'bench_1_0_min': 10,
  'bench_1_1_id': 'burke', 'bench_1_1_min': 5,
  'bench_1_2_id': '', 'bench_1_2_min': 0,
  'bench_2_0_id': 'chaikin', 'bench_2_0_min': 10,
  'bench_2_1_id': 'beattie', 'bench_2_1_min': 5,
  'bench_2_2_id': '', 'bench_2_2_min': 0,
  'bench_3_0_id': 'vance', 'bench_3_0_min': 20,
  'bench_3_1_id': '', 'bench_3_1_min': 0,
  'bench_3_2_id': '', 'bench_3_2_min': 0,
  'bench_4_0_id': 'vukicevic', 'bench_4_0_min': 10,
  'bench_4_1_id': '', 'bench_4_1_min': 0,
  'bench_4_2_id': '', 'bench_4_2_min': 0,
};
const ROTATION_SHOOTING = {
  'beattie': 25,
  'dotson': 25,
  'chaikin': 25,
  'vance': 25,
  'beath': 25,
  'bench_0_0_id': 'barno', 'bench_0_0_min': 10,
  'bench_0_1_id': 'johnson', 'bench_0_1_min': 5,
  'bench_0_2_id': '', 'bench_0_2_min': 0,
  'bench_1_0_id': 'burke', 'bench_1_0_min': 15,
  'bench_1_1_id': '', 'bench_1_1_min': 0,
  'bench_1_2_id': '', 'bench_1_2_min': 0,
  'bench_2_0_id': 'burke', 'bench_2_0_min': 5,
  'bench_2_1_id': 'johnson', 'bench_2_1_min': 10,
  'bench_2_2_id': '', 'bench_2_2_min': 0,
  'bench_3_0_id': 'beattie', 'bench_3_0_min': 10,
  'bench_3_1_id': 'beath', 'bench_3_1_min': 5,
  'bench_3_2_id': '', 'bench_3_2_min': 0,
  'bench_4_0_id': 'suutela', 'bench_4_0_min': 10,
  'bench_4_1_id': 'vukicevic', 'bench_4_1_min': 5,
  'bench_4_2_id': '', 'bench_4_2_min': 0,
};
const ROTATION_BIG = {
  'beattie': 25,
  'vance': 25,
  'beath': 25,
  'suutela': 25,
  'vukicevic': 25,
  'bench_0_0_id': 'barno', 'bench_0_0_min': 10,
  'bench_0_1_id': 'dotson', 'bench_0_1_min': 5,
  'bench_0_2_id': '', 'bench_0_2_min': 0,
  'bench_1_0_id': 'dotson', 'bench_1_0_min': 10,
  'bench_1_1_id': 'burke', 'bench_1_1_min': 5,
  'bench_1_2_id': '', 'bench_1_2_min': 0,
  'bench_2_0_id': 'burke', 'bench_2_0_min': 10,
  'bench_2_1_id': 'chaikin', 'bench_2_1_min': 5,
  'bench_2_2_id': '', 'bench_2_2_min': 0,
  'bench_3_0_id': 'beattie', 'bench_3_0_min': 10,
  'bench_3_1_id': 'beath', 'bench_3_1_min': 5,
  'bench_3_2_id': '', 'bench_3_2_min': 0,
  'bench_4_0_id': 'beath', 'bench_4_0_min': 5,
  'bench_4_1_id': 'pendleton', 'bench_4_1_min': 10,
  'bench_4_2_id': '', 'bench_4_2_min': 0,
};
const ROTATION_SMALL = {
  'beattie': 25,
  'dotson': 25,
  'chaikin': 25,
  'vance': 25,
  'beath': 25,
  'bench_0_0_id': 'barno', 'bench_0_0_min': 15,
  'bench_0_1_id': '', 'bench_0_1_min': 0,
  'bench_0_2_id': '', 'bench_0_2_min': 0,
  'bench_1_0_id': 'burke', 'bench_1_0_min': 15,
  'bench_1_1_id': '', 'bench_1_1_min': 0,
  'bench_1_2_id': '', 'bench_1_2_min': 0,
  'bench_2_0_id': 'burke', 'bench_2_0_min': 5,
  'bench_2_1_id': 'johnson', 'bench_2_1_min': 10,
  'bench_2_2_id': '', 'bench_2_2_min': 0,
  'bench_3_0_id': 'beattie', 'bench_3_0_min': 10,
  'bench_3_1_id': 'beath', 'bench_3_1_min': 5,
  'bench_3_2_id': '', 'bench_3_2_min': 0,
  'bench_4_0_id': 'suutela', 'bench_4_0_min': 15,
  'bench_4_1_id': '', 'bench_4_1_min': 0,
  'bench_4_2_id': '', 'bench_4_2_min': 0,
};
const ROTATION_DEFENSE = {
  'barno': 25,
  'beattie': 25,
  'beath': 25,
  'vance': 25,
  'suutela': 25,
  'bench_0_0_id': 'johnson', 'bench_0_0_min': 10,
  'bench_0_1_id': 'dotson', 'bench_0_1_min': 5,
  'bench_0_2_id': '', 'bench_0_2_min': 0,
  'bench_1_0_id': 'dotson', 'bench_1_0_min': 10,
  'bench_1_1_id': 'burke', 'bench_1_1_min': 5,
  'bench_1_2_id': '', 'bench_1_2_min': 0,
  'bench_2_0_id': 'burke', 'bench_2_0_min': 5,
  'bench_2_1_id': 'chaikin', 'bench_2_1_min': 10,
  'bench_2_2_id': '', 'bench_2_2_min': 0,
  'bench_3_0_id': 'beattie', 'bench_3_0_min': 10,
  'bench_3_1_id': 'beath', 'bench_3_1_min': 5,
  'bench_3_2_id': '', 'bench_3_2_min': 0,
  'bench_4_0_id': 'vukicevic', 'bench_4_0_min': 15,
  'bench_4_1_id': '', 'bench_4_1_min': 0,
  'bench_4_2_id': '', 'bench_4_2_min': 0,
};
const ROTATION_BEST = {
  'barno': 25,
  'dotson': 25,
  'eaglestaff': 25,
  'beattie': 25,
  'suutela': 25,
  'bench_0_0_id': 'beattie', 'bench_0_0_min': 10,
  'bench_0_1_id': 'dotson', 'bench_0_1_min': 5,
  'bench_0_2_id': '', 'bench_0_2_min': 0,
  'bench_1_0_id': 'chaikin', 'bench_1_0_min': 10,
  'bench_1_1_id': 'burke', 'bench_1_1_min': 5,
  'bench_1_2_id': '', 'bench_1_2_min': 0,
  'bench_2_0_id': 'vance', 'bench_2_0_min': 10,
  'bench_2_1_id': 'burke', 'bench_2_1_min': 5,
  'bench_2_2_id': '', 'bench_2_2_min': 0,
  'bench_3_0_id': 'beath', 'bench_3_0_min': 10,
  'bench_3_1_id': 'vance', 'bench_3_1_min': 5,
  'bench_3_2_id': '', 'bench_3_2_min': 0,
  'bench_4_0_id': 'beath', 'bench_4_0_min': 5,
  'bench_4_1_id': 'vukicevic', 'bench_4_1_min': 10,
  'bench_4_2_id': '', 'bench_4_2_min': 0,
};

const DEFAULT_ROTATION = ROTATION_BASE;
let dragId = null;

const SLOT_LABELS = ['PG', 'SG', 'SF', 'PF', 'C'];

// ─── DRAG AND DROP ─────────────────────────────────────────────
function dragStart(event, id) {
  dragId = id;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', id);
  setTimeout(() => {
    const el = document.querySelector(`[data-id="${id}"]`);
    if (el) el.classList.add('dragging');
  }, 0);
}

function dragEnd(event) {
  const el = document.querySelector(`[data-id="${dragId}"]`);
  if (el) el.classList.remove('dragging');
  document.querySelectorAll('.slot').forEach(s => s.classList.remove('drag-over'));
  dragId = null;
}

function dragOver(event) {
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  event.currentTarget.classList.add('drag-over');
}

function dragLeave(event) {
  event.currentTarget.classList.remove('drag-over');
}

function dropOnSlot(event, slotIndex) {
  event.preventDefault();
  event.currentTarget.classList.remove('drag-over');
  dragId = event.dataTransfer.getData('text/plain') || dragId;
  if (!dragId || !Object.hasOwn(PLAYERS, dragId)) return;

  // If player already in another slot, clear that slot
  const existingSlot = lineup.indexOf(dragId);
  if (existingSlot !== -1 && existingSlot !== slotIndex) {
    lineup[existingSlot] = null;
  }

  // If target slot has someone, swap or clear
  const displaced = lineup[slotIndex];
  if (displaced && displaced !== dragId) {
    // Put displaced player back in the slot the dragged player came from
    if (existingSlot !== -1) {
      lineup[existingSlot] = displaced;
    }
    // else just displace them (they go back to roster)
  }

  lineup[slotIndex] = dragId;
  dragId = null;
  renderLineup();
}

// ─── + BUTTON (adds to first empty slot) ──────────────────────
function addToNextSlot(id) {
  // If already in lineup, remove
  const idx = lineup.indexOf(id);
  if (idx !== -1) {
    lineup[idx] = null;
    renderLineup();
    return;
  }
  // Find first empty slot
  const empty = lineup.indexOf(null);
  if (empty === -1) return; // lineup full
  lineup[empty] = id;
  renderLineup();
}

function clearLineup() {
  lineup = [null, null, null, null, null];
  renderLineup();
}

function loadPreset(type) {
  const presets = {
    base:        ['barno', 'dotson', 'eaglestaff', 'beath', 'suutela'],
    shooting:    ['beattie', 'dotson', 'eaglestaff', 'chaikin', 'beath'],
    big:         ['beattie', 'beath', 'vance', 'suutela', 'vukicevic'],
    small:       ['beattie', 'dotson', 'chaikin', 'vance', 'beath'],
    defense:     ['barno', 'beattie', 'beath', 'vance', 'suutela'],
    best:        ['barno', 'dotson', 'eaglestaff', 'beattie', 'suutela']
  };
  const rotations = {
    base:        ROTATION_BASE,
    shooting:    ROTATION_SHOOTING,
    big:         ROTATION_BIG,
    small:       ROTATION_SMALL,
    defense:     ROTATION_DEFENSE,
    best:        ROTATION_BEST,
  };
  const p = presets[type];
  if (p) lineup = [...p];
  if (rotations[type]) {
    benchMinutes = {};
    Object.assign(benchMinutes, rotations[type]);
  }
  // Highlight active preset button
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.style.borderColor = '';
    btn.style.color = '';
    btn.style.fontWeight = '';
  });
  const activeBtn = document.querySelector(`.preset-btn[onclick*="'${type}'"]`);
  if (activeBtn) {
    activeBtn.style.borderColor = 'var(--gold)';
    activeBtn.style.color = 'var(--gold)';
    activeBtn.style.fontWeight = '600';
  }
  renderLineup();
  setTimeout(() => { renderBench(); updateRatings(); }, 50);
}

// ─── RENDER ────────────────────────────────────────────────────
function renderLineup() {
  // Update add buttons and row highlights
  Object.keys(PLAYERS).forEach(id => {
    const btn = document.getElementById('btn-' + id);
    const row = document.querySelector(`[data-id="${id}"]`);
    const inSlot = lineup.includes(id);
    if (btn) {
      btn.textContent = inSlot ? '−' : '+';
      btn.className = inSlot ? 'add-btn added' : 'add-btn';
    }
    if (row?.classList.contains('player-row')) {
      const p = PLAYERS[id];
      const rating = playerImpactScore(p);
      const badge = row.querySelector('.p-bpr');
      const hasRating = Number.isFinite(rating);
      badge.textContent = formatImpact(rating);
      badge.title = hasRating ? 'Score' : 'Score unavailable for this player';
      badge.className = 'p-bpr ' + (rating >= 3 ? 'c-gold' : !hasRating || rating >= 0 ? 'c-muted' : 'c-red');
      row.querySelector('.p-ts').textContent = `TS% ${p.ts.toFixed(1)}`;
      row.className = inSlot
        ? 'player-row in-lineup'
        : 'player-row';
      // Re-add draggable since className reset removes it
      row.setAttribute('draggable', 'true');
    }
  });

  // Render court slots
  for (let i = 0; i < 5; i++) {
    const slot = document.getElementById('slot-' + i);
    const id = lineup[i];
    if (id && PLAYERS[id]) {
      const p = PLAYERS[id];
      const rating = playerImpactScore(p);
      const ratingColor = rating >= 3 ? 'var(--green)' : rating >= 1 ? 'var(--gold)' :
        !Number.isFinite(rating) || rating >= 0 ? 'var(--muted)' : 'var(--red)';
      slot.className = 'slot filled';
      slot.innerHTML = `
        <div class="slot-pos">${SLOT_LABELS[i]}</div>
        <div class="slot-name">${htmlEscape(shortName(p))}</div>
        <div class="slot-bpr" style="color:${ratingColor}">Score ${formatImpact(rating)}</div>
        <button class="slot-remove" onclick="removeFromSlot(${i})">✕</button>
      `;
    } else {
      slot.className = 'slot';
      slot.innerHTML = `<span class="slot-empty-text">${SLOT_LABELS[i]}</span>`;
    }
    // Re-attach drag listeners (innerHTML wipes them on slot)
    slot.ondragover = (e) => dragOver(e);
    slot.ondragleave = (e) => dragLeave(e);
    slot.ondrop = (e) => dropOnSlot(e, i);
  }

  updateRatings();
  renderBench();
  renderConferenceContext();
}

function removeFromSlot(i) {
  lineup[i] = null;
  renderLineup();
}

// ─── RATINGS ───────────────────────────────────────────────────
function updateRatings() {
  const players = lineup.filter(Boolean).map(id => PLAYERS[id]).filter(Boolean);
  const playerMinMap = getAllPlayersWithMinutes();
  const forecast = rotationForecast(playerMinMap);
  renderProjectionSource('standard', forecast);
  if (players.length === 0) { resetRatings(); return; }

  const sumBPR = players.reduce((s, p) => s + getEffectiveBpm(p), 0);
  const avgTS  = players.reduce((s, p) => s + p.ts, 0) / players.length;
  const avgARate = players.reduce((s, p) => s + p.arate, 0) / players.length;
  const avgStl = players.reduce((s, p) => s + p.stl, 0) / players.length;
  const avgBlk = players.reduce((s, p) => s + p.blk, 0) / players.length;
  const avgDreb = players.reduce((s, p) => s + p.dreb, 0) / players.length;
  const avgHt  = players.reduce((s, p) => s + p.htIn, 0) / players.length;
  function spacingWeight(p) {
    const pct  = p.threePct  || 0;
    const rate = (p.threeRate || 0) * 100;
    if (pct >= 36 && rate >= 40) return 1.0;
    if (pct >= 33 || (pct >= 30 && rate >= 35)) return 0.5;
    return 0;
  }
  const spaceWeights = players.map(p => ({ name: p.name.split(' ').pop(), w: spacingWeight(p) }));
  const spacingScore = spaceWeights.reduce((s, x) => s + x.w, 0);
  const shooters = spacingScore;

  const usgVals = players.map(p => p.usg);
  const usgMean = usgVals.reduce((a,b)=>a+b,0)/usgVals.length;
  const usgStd  = Math.sqrt(usgVals.reduce((s,v)=>s+(v-usgMean)**2,0)/usgVals.length);
  const usgBalance = Math.max(0, 100 - usgStd * 8);

  const startingScore = renderLineupScore('rating-bpr', 'starting-rapm', sumBPR,
    players.map(player => [player, 1]), players.length, 'players');
  document.getElementById('rating-desc').textContent = players.length < 5 ? `${players.length}/5 players selected` : 'Sum of starting 5 scores';

  // ── ROTATION-WEIGHTED BPM ──────────────────────────────────────
  // Σ(player effective BPM × their total minutes) / 200
  const totalMinAssigned = Object.values(playerMinMap).reduce((a, b) => a + b, 0);
  // Ratings supplies the four factors. Aaron’s model turns them into team ORtg.
  const _activePl = totalMinAssigned > 0
    ? Object.entries(playerMinMap).filter(([, m]) => m > 0).map(([id]) => PLAYERS[id]).filter(Boolean)
    : players;
  const _projEFG = forecast.efg ?? A_EFG;
  const _projTO = forecast.turnover ?? A_TO;
  const _projOR = forecast.rebound ?? A_OR;
  const _projFTR = forecast.ftr ?? A_FTR;
  const _totUSG = _activePl.reduce((sum, player) => sum + (player.usg || 18), 0) || 1;

  // Base case
  const _wOBPM = _activePl.reduce((s,p)=>s+effOBPMof(p)*(p.usg||18),0) / (_totUSG||1);
  const _shoot = shooterCount(_activePl, _activePl.map(p=>(p.usg||18)));
  function _calcORtg(efg, to, orb, ftr) {
    return calcORtgV2(efg, to, orb, ftr, _wOBPM, _shoot);
  }

  const projOffRtg      = _calcORtg(_projEFG, _projTO, _projOR, _projFTR);
  const projOffRtgFloor = _calcORtg(_projEFG - 1.5, _projTO + 1.5, _projOR - 2.0, _projFTR - 3.0);
  const projOffRtgCeil  = _calcORtg(_projEFG + 1.5, _projTO - 1.5, _projOR + 2.0, _projFTR + 3.0);
  let rotationBPM = null;

  if (totalMinAssigned > 0) {
    let weightedSum = 0;
    Object.entries(playerMinMap).forEach(([pid, mins]) => {
      const p = PLAYERS[pid];
      if (p && mins > 0) weightedSum += getEffectiveBpm(p) * mins;
    });
    // Scale to per-5-player equivalent (multiply by 5, divide by total mins)
    rotationBPM = (weightedSum / totalMinAssigned) * 5;
  }

  const rotationScore = renderLineupScore('rating-rotation', 'rotation-rapm', rotationBPM,
    Object.entries(playerMinMap).map(([id, minutes]) => [PLAYERS[id], minutes]), 5, 'min');
  const rotDesc = document.getElementById('rating-rotation-desc');
  if (rotDesc) {
    rotDesc.textContent = totalMinAssigned ? `Minutes-weighted · ${totalMinAssigned} min assigned` : 'Set minutes in planner below';
  }

  renderHistoricalTier('rating-tier', totalMinAssigned > 0 ? rotationScore : startingScore,
    players.length, totalMinAssigned);

  // ── MINUTES-WEIGHTED PROJECTED STATS ─────────────────────────
  const { three: proj3Pct, threeRate: proj3PR, ftr: projFTR, turnover: projTORate,
    defensiveRebound: projDReb, rebound: projOReb, efg: projEFG } = forecast;
  const projARate = _activePl.reduce((sum, player) => sum + (player.arate || 0) * (player.usg || 0), 0)
    / (_activePl.reduce((sum, player) => sum + (player.usg || 0), 0) || 1);

  // ── DEFENSIVE RATING ─────────────────────────────────────────
  // Minutes-weighted average of individual player DRtg values
  // Each player's indDrtg comes from their actual 2025-26 UCSD DRtg
  // (or estimated for new additions based on defensive metrics)
  // Calibrated: base lineup projects ~104.0, defense lineup ~101.7
  // UCSD actual 2025-26: 103.5
  function calcDRtg(minMap, totalMin, fallbackPs) {
    // indDrtg values:
    // Returners: actual UCSD 2025-26 individual DRtg (from KenPom per-100)
    // New additions: 75% individual stat model (STL%×-2.39 + BLK%×-0.53 + DREB%×-0.34)
    //                + 25% conference-adjusted raw DRtg (individual skill weighted more)
    // Returners: 50% actual UCSD DRtg + 50% individual stat model
    const BW_AVG_DRTG = 102.5; // fallback: UCSD actual 103.5 - 1.0 scheme bonus
    if (totalMin > 0) {
      let weightedSum = 0;
      Object.entries(minMap).forEach(([pid, mins]) => {
        const p = PLAYERS[pid];
        if (p && mins > 0) {
          const drtg = p.indDrtg !== undefined ? p.indDrtg : BW_AVG_DRTG;
          weightedSum += drtg * mins;
        }
      });
      return weightedSum / totalMin;
    } else {
      // Fallback: simple average of starters
      const drtgs = fallbackPs.map(p => p.indDrtg !== undefined ? p.indDrtg : BW_AVG_DRTG);
      return drtgs.reduce((s,v)=>s+v,0) / (drtgs.length||1);
    }
  }
  const projDRtg = calcDRtg(playerMinMap, totalMinAssigned, players);

  function setRating(id, val, green, gold, muted, suffix='', invert=false) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!Number.isFinite(val)) {
      el.textContent = '—';
      el.className = 'rating-val c-muted';
      return;
    }
    el.textContent = val.toFixed(1) + suffix;
    const goodness = invert ? (val <= green ? 'c-green' : val <= gold ? 'c-gold' : val <= muted ? 'c-muted' : 'c-red')
                            : (val >= green ? 'c-green' : val >= gold ? 'c-gold' : val >= muted ? 'c-muted' : 'c-red');
    el.className = 'rating-val ' + goodness;
  }

  const offEl = document.getElementById('rating-off');
  offEl.textContent = projOffRtg.toFixed(1);
  offEl.className = 'rating-val ' + (projOffRtg >= 110 ? 'c-green' : projOffRtg >= 107.5 ? 'c-gold' : projOffRtg >= 105 ? 'c-muted' : 'c-red');
  const offDescEl = document.getElementById('rating-off-desc');
  if (offDescEl) offDescEl.textContent = players.length < 5
    ? 'Partial estimate'
    : projOffRtgFloor.toFixed(1) + ' – ' + projOffRtgCeil.toFixed(1) + ' range';

  const drtgEl = document.getElementById('rating-drtg');
  if (drtgEl) {
    drtgEl.textContent = projDRtg.toFixed(1);
    // Lower DRtg = better defense. UCSD actual 103.5, BW avg ~106
    drtgEl.className = 'rating-val ' + (projDRtg <= 102 ? 'c-green' : projDRtg <= 104.5 ? 'c-gold' : projDRtg <= 107 ? 'c-muted' : 'c-red');
  }

  const efgEl = document.getElementById('rating-efg');
  if (efgEl) {
    efgEl.textContent = projEFG === null ? '—' : projEFG.toFixed(1) + '%';
    // UCSD actual 52.6%, BW avg ~51.4%, elite ~55%+
    efgEl.className = 'rating-val ' + (projEFG === null ? 'c-muted' : projEFG >= 54 ? 'c-green' : projEFG >= 52 ? 'c-gold' : projEFG >= 50 ? 'c-muted' : 'c-red');
  }

  setRating('rating-3pct',  proj3Pct,  36,  33,  30, '%');
  setRating('rating-3pr',   proj3PR,   45,  35,  25, '%');
  setRating('rating-ftr',   projFTR,   45,  32,  22, '');
  setRating('rating-arate', projARate, 22,  18,  14, '%');   // individual ARate
  setRating('rating-torate',projTORate,15,  17,  19, '%', true); // lower=better, team TORate
  setRating('rating-dreb',  projDReb,  73,  68,  62, '%');   // team DREB%
  setRating('rating-oreb',  projOReb,  26,  22,  18, '%');   // team OREB%

  // Update live projection table in Big West landscape section
  window._offFloor = projOffRtgFloor;
  window._offCeil  = projOffRtgCeil;
  updateProjectionTable(projOffRtg, projDRtg, proj3Pct, proj3PR, projFTR, projOReb, projTORate, projDReb, projOffRtgFloor, projOffRtgCeil);
  renderStandingsTable();

  // Keep spacing score hidden but computed for generateFitAssessment
  const spaceEl = document.getElementById('rating-space');
  if (spaceEl) { spaceEl.textContent = spacingScore.toFixed(1); }

  setBar('ts', avgTS, 45, 65);
  setBar('3pt', spacingScore/5*100, 0, 100);
  setBar('usg', usgBalance, 0, 100);
  setBar('ast', avgARate, 5, 25);
  setBar('blk', avgBlk, 0, 4);
  setBar('stl', avgStl, 0, 4);
  setBar('reb', avgDreb, 5, 20);
  setBar('ht', (avgHt - 72) / 12 * 100, 0, 100);

  document.getElementById('val-ts').textContent = avgTS.toFixed(1) + '%';
  document.getElementById('val-3pt').textContent = spacingScore.toFixed(1) + '/5';
  document.getElementById('val-usg').textContent = usgBalance.toFixed(0) + '%';
  document.getElementById('val-ast').textContent = avgARate.toFixed(1) + '%';
  document.getElementById('val-blk').textContent = avgBlk.toFixed(1) + '%';
  document.getElementById('val-stl').textContent = avgStl.toFixed(1) + '%';
  document.getElementById('val-reb').textContent = avgDreb.toFixed(1) + '%';
  document.getElementById('val-ht').textContent = `${Math.floor(avgHt/12)}'${Math.round(avgHt%12)}"`;

  generateFitAssessment(players, shooters, avgTS);
}

function setBar(id, val, min, max) {
  const pct = Math.min(100, Math.max(0, (val - min) / (max - min) * 100));
  const el = document.getElementById('bar-' + id);
  if (el) el.style.width = pct + '%';
}

function resetRatings() {
  renderLineupScore('rating-bpr', 'starting-rapm');
  renderLineupScore('rating-rotation', 'rotation-rapm');
  renderHistoricalTier('rating-tier', null, 0, 0);
  ['rating-off','rating-space'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = '—'; el.className = 'rating-val c-muted'; }
  });
  document.getElementById('rating-desc').textContent = 'Add players to generate rating';
  ['rating-3pct','rating-3pr','rating-ftr','rating-drtg','rating-efg',
   'rating-arate','rating-torate','rating-dreb','rating-oreb'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = '—'; el.className = 'rating-val c-muted'; }
  });
  const rotDesc = document.getElementById('rating-rotation-desc');
  if (rotDesc) rotDesc.textContent = 'Minutes-weighted · full roster';
  document.getElementById('rating-off-desc').textContent = 'Proj. pts/100 poss';
  document.getElementById('fit-assessment').innerHTML = 'Select players from the roster or load a preset lineup to generate a fit assessment.';
  ['ts','3pt','usg','ast','blk','stl','reb','ht'].forEach(id => {
    const b = document.getElementById('bar-' + id);
    const v = document.getElementById('val-' + id);
    if (b) b.style.width = '0%';
    if (v) v.textContent = '—';
  });
}

function generateFitAssessment(players, shooters, avgTS) {
  const hasDoublePG = players.some(p=>p.name.includes('Dotson')) && players.some(p=>p.name.includes('Beattie'));
  const hasSuutela  = players.some(p=>p.name.includes('Suutela'));
  const hasChaikin  = players.some(p=>p.name.includes('Chaikin'));
  const hasBeath    = players.some(p=>p.name.includes('Beath'));
  const hasVukicevic = players.some(p=>p.name.includes('Vukicevic'));
  const hasDunn     = players.some(p=>p.name.includes('Dunn'));

  let notes = [];
  if (hasDoublePG) notes.push(`<strong>Beattie + Dotson backcourt</strong> gives you two playmakers who can switch on/off-ball. Combined ARate of ~37% projects to elite ball movement.`);
  if (hasDunn) notes.push(`<strong>Dunn's ARate (38.9)</strong> is the highest on the roster — but pair him carefully. His TS% (51.8) means you need shooters around him to offset offensive efficiency drag.`);
  if (hasSuutela && hasVukicevic) notes.push(`<strong>Suutela + Vukicevic frontcourt</strong> is physically dominant but creates spacing issues. Best in specific matchups vs. physical Big West opponents, not a default lineup.`);
  if (hasSuutela && !hasVukicevic) notes.push(`<strong>Suutela as primary big</strong> allows better floor spacing — his TS% of 63.7% is the best on the roster.`);
  if (hasChaikin) notes.push(`<strong>Chaikin's 42.4% conf 3PT%</strong> is the team's best spacing weapon — forces hard closeouts, opens driving lanes.`);
  if (hasBeath) notes.push(`<strong>Beath at PF/SF</strong> gives elite two-way versatility — his steal rate and rebounding anchor the defense without sacrificing too much spacing.`);
  if (shooters <= 2) notes.push(`<strong>Spacing concern:</strong> Only ${shooters} reliable 3PT shooters. Big West defenses will pack the paint — consider rotating in Chaikin or Dotson.`);
  if (shooters >= 4) notes.push(`<strong>Elite spacing lineup</strong> — 4+ perimeter threats force impossible defensive decisions.`);
  if (hasSuutela && hasChaikin) notes.push(`<strong>Suutela + Chaikin</strong> is a high-efficiency combo — interior finishing at 63.7% TS% paired with 42.4% 3PT shooting. Minimal offensive overlap.`);
  if (notes.length === 0) notes.push(`Standard lineup. TS% average of ${avgTS.toFixed(1)}% is ${avgTS >= 57 ? 'above' : 'below'} Big West average for starting units.`);

  const el = document.getElementById('fit-assessment');
  if (el) el.innerHTML = notes.map(n => `<p style="margin-bottom:8px">${n}</p>`).join('');
}

// ─── BENCH MINUTES ─────────────────────────────────────────────
const DEFAULT_STARTER_MIN = 28;
const MAX_BENCH_SPOTS = 3;

// benchMinutes structure:
// benchMinutes[starterId] = starter minutes (number)
// benchMinutes[`bench_${slotIdx}_${benchSpot}_id`] = player id string
// benchMinutes[`bench_${slotIdx}_${benchSpot}_min`] = minutes number

function getBenchSpots(slotIdx) {
  const spots = [];
  for (let b = 0; b < MAX_BENCH_SPOTS; b++) {
    const id  = benchMinutes[`bench_${slotIdx}_${b}_id`] || '';
    const min = benchMinutes[`bench_${slotIdx}_${b}_min`] !== undefined
      ? benchMinutes[`bench_${slotIdx}_${b}_min`] : 0;
    spots.push({ id, min });
  }
  return spots;
}

function getPositionTotal(slotIdx) {
  const starterId = lineup[slotIdx];
  const starterMin = starterId ? (benchMinutes[starterId] !== undefined ? benchMinutes[starterId] : DEFAULT_STARTER_MIN) : 0;
  const spots = getBenchSpots(slotIdx);
  const benchTotal = spots.reduce((s, sp) => s + (sp.id ? sp.min : 0), 0);
  return starterMin + benchTotal;
}

// Get total minutes for a specific player across ALL positions (starter + bench roles)
function getPlayerTotalMinutes(playerId) {
  let total = 0;
  // Starter minutes
  if (benchMinutes[playerId] !== undefined && lineup.includes(playerId)) {
    total += benchMinutes[playerId];
  }
  // Bench minutes across all slots
  for (let i = 0; i < 5; i++) {
    for (let b = 0; b < MAX_BENCH_SPOTS; b++) {
      if (benchMinutes[`bench_${i}_${b}_id`] === playerId) {
        total += benchMinutes[`bench_${i}_${b}_min`] || 0;
      }
    }
  }
  return total;
}

// Get all players who have any minutes assigned
function getAllPlayersWithMinutes() {
  const playerMap = {}; // id -> total minutes

  for (let i = 0; i < 5; i++) {
    const sid = lineup[i];
    if (!sid) continue;
    const starterMin = benchMinutes[sid] !== undefined ? benchMinutes[sid] : DEFAULT_STARTER_MIN;
    playerMap[sid] = (playerMap[sid] || 0) + starterMin;

    for (let b = 0; b < MAX_BENCH_SPOTS; b++) {
      const bid = benchMinutes[`bench_${i}_${b}_id`];
      const bmin = benchMinutes[`bench_${i}_${b}_min`] || 0;
      if (bid && bmin > 0) {
        playerMap[bid] = (playerMap[bid] || 0) + bmin;
      }
    }
  }
  return playerMap;
}

function totalColor(total) {
  return total > 40 ? 'var(--red)' : total === 40 ? 'var(--green)' : 'var(--gold)';
}

function bprColor(player) {
  const b = getEffectiveBpm(player);
  return b >= 3 ? 'var(--green)' : b >= 1 ? 'var(--gold)' : b >= 0 ? 'var(--muted)' : 'var(--red)';
}


function renderMinutesSummary() {
  const section = document.getElementById('bench-section');
  if (!section) return;
  const summaryEl = section.querySelector('#player-minutes-summary');
  if (!summaryEl) return;

  const playerMinMap = getAllPlayersWithMinutes();
  const sortedPlayers = Object.entries(playerMinMap)
    .filter(([, min]) => min > 0)
    .sort((a, b) => b[1] - a[1]);

  if (sortedPlayers.length === 0) { summaryEl.innerHTML = ''; return; }

  let html = '<div style="display:flex; flex-wrap:wrap; gap:6px; align-items:stretch;">';
  sortedPlayers.forEach(([pid, totalMin]) => {
    const p = PLAYERS[pid];
    if (!p) return;
    const isStarter = lineup.includes(pid);
    const pct = Math.round((totalMin / 40) * 100);
    const minColor = totalMin >= 30 ? 'var(--green)' : totalMin >= 18 ? 'var(--gold)' : 'var(--muted)';
    const barPct = Math.min(100, (totalMin / 40) * 100);
    const effBpr = getEffectiveBpm(p);
    const bprC = effBpr >= 2 ? 'var(--green)' : effBpr >= 0 ? 'var(--gold)' : 'var(--red)';
    html += '<div style="background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:10px 12px;">'
      + '<div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">'
      + '<div style="font-family:\'Bebas Neue\',sans-serif; font-size:14px; color:' + bprC + '; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">' + htmlEscape(shortName(p)) + '</div>'
      + (isStarter
          ? '<div style="font-size:7px; background:var(--blue-tint); color:var(--blue-light); border-radius:2px; padding:1px 4px; letter-spacing:0.1em;">START</div>'
          : '<div style="font-size:7px; background:var(--gold-tint); color:var(--gold-dim); border-radius:2px; padding:1px 4px; letter-spacing:0.1em;">BENCH</div>')
      + '</div>'
      + '<div style="display:flex; align-items:center; gap:8px;">'
      + '<div style="flex:1; height:4px; background:var(--border); border-radius:2px; overflow:hidden;"><div style="height:100%; width:' + barPct + '%; background:' + minColor + '; border-radius:2px;"></div></div>'
      + '<div style="font-family:\'Bebas Neue\',sans-serif; font-size:18px; color:' + minColor + '; width:24px; text-align:right;">' + totalMin + '</div>'
      + '<div style="font-size:8px; color:var(--muted);">min</div>'
      + '</div>'
      + '<div style="font-size:9px; color:var(--muted); margin-top:3px;">' + htmlEscape(p.pos) + ' · ' + htmlEscape(p.yr) + ' · ' + pct + '% of game</div>'
      + '</div>';
  });
  html += '</div>';
  summaryEl.innerHTML = html;
}

function renderBench() {
  const section = document.getElementById('bench-section');
  const startingIds = lineup.filter(Boolean);

  if (startingIds.length === 0) {
    section.innerHTML = `<div style="color:var(--muted); font-size:11px; font-family:'Crimson Pro',serif; font-style:italic;">Fill the starting lineup above to generate the minutes planner.</div>`;
    return;
  }

  // ALL players available for bench dropdowns — including starters
  const active = activeRotationPlayerIds();
  const currentWatchlistIds = new Set(WATCHLIST_POTENTIALS.map(player => player.id));
  const allPool = Object.keys(PLAYERS).filter(id => {
    const player = PLAYERS[id];
    return active.has(id) || (!player.savedOnly && (!player.isWatchlistPotential || currentWatchlistIds.has(id)));
  });

  // Init starter minutes
  for (let i = 0; i < 5; i++) {
    const sid = lineup[i];
    if (sid && benchMinutes[sid] === undefined) benchMinutes[sid] = DEFAULT_STARTER_MIN;
  }

  let html = `<div style="display:grid; grid-template-columns: repeat(5, 1fr); gap: 12px;">`;

  for (let i = 0; i < 5; i++) {
    const starterId = lineup[i];
    if (!starterId) {
      html += `<div style="border:1px dashed var(--border2); border-radius:4px; padding:12px; opacity:0.3;">
        <div class="pos-group-title" style="margin-bottom:8px;">${SLOT_LABELS[i]}</div>
        <div style="font-size:10px; color:var(--muted);">No starter</div>
      </div>`;
      continue;
    }

    const starter    = PLAYERS[starterId];
    const starterMin = benchMinutes[starterId] !== undefined ? benchMinutes[starterId] : DEFAULT_STARTER_MIN;
    const spots      = getBenchSpots(i);
    const total      = getPositionTotal(i);
    const tc         = totalColor(total);

    // Track which players are used in THIS slot's bench spots
    const usedInSlot = new Set(spots.map(s => s.id).filter(Boolean));

    html += `<div style="border:1px solid var(--border); border-radius:4px; padding:12px; background:var(--card);">`;

    // Position label + total
    html += `<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
      <div style="font-size:9px; letter-spacing:0.2em; text-transform:uppercase; color:var(--gold-dim);">${SLOT_LABELS[i]}</div>
      <div style="font-family:'Bebas Neue',sans-serif; font-size:14px; color:${tc};" id="total-${i}">${total}/40</div>
    </div>`;

    // STARTER ROW
    html += `<div style="margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid var(--border2);">
      <div style="display:flex; align-items:center; gap:6px; margin-bottom:5px;">
        <div style="font-size:8px; letter-spacing:0.15em; text-transform:uppercase; color:var(--muted); width:42px; flex-shrink:0;">START</div>
        <div style="font-family:'Bebas Neue',sans-serif; font-size:14px; color:${bprColor(starter)}; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${starter.name.split(' ').pop()}</div>
        <div style="font-size:9px; color:var(--muted);">${getEffectiveBpm(starter) > 0 ? '+' : ''}${getEffectiveBpm(starter)}</div>
      </div>
      <div style="display:flex; align-items:center; gap:6px;">
        <input type="range" class="minutes-slider" min="0" max="40" value="${starterMin}"
          oninput="updateStarterMin('${starterId}', this.value, ${i})"
          onchange="refreshPositionTotal(${i})"
          style="flex:1;">
        <div style="font-family:'Bebas Neue',sans-serif; font-size:16px; color:var(--text); width:20px; text-align:right;" id="sm-${starterId}">${starterMin}</div>
        <div style="font-size:8px; color:var(--muted);">min</div>
      </div>
    </div>`;

    // BENCH SPOT ROWS — now includes ALL players (starters can back up other positions)
    for (let b = 0; b < MAX_BENCH_SPOTS; b++) {
      const spot   = spots[b];
      const player = spot.id ? PLAYERS[spot.id] : null;
      const bprC   = player ? bprColor(player) : 'var(--muted)';
      const effBpr = player ? getEffectiveBpm(player) : 0;

      // Build options: all players, mark starters with ★
      const opts = `<option value="">— Bench ${b+1} —</option>` +
        allPool.map(bid => {
          // Exclude if already used in another bench spot in this same slot
          const isThisSpot    = bid === spot.id;
          const usedElsewhere = !isThisSpot && usedInSlot.has(bid);
          if (usedElsewhere) return '';
          const bp      = PLAYERS[bid];
          const isStart = lineup.includes(bid);
          const label   = (isStart ? '★ ' : '') + bp.name.split(' ').pop() + ` (${getEffectiveBpm(bp) > 0 ? '+' : ''}${getEffectiveBpm(bp)})`;
          return `<option value="${bid}" ${spot.id === bid ? 'selected' : ''}>${htmlEscape(label)}</option>`;
        }).join('');

      html += `<div style="margin-bottom:8px;">
        <select class="bench-slot-select" style="width:100%; margin-bottom:4px;"
          onchange="updateBenchPlayer(${i}, ${b}, this.value)">${opts}</select>`;

      if (spot.id) {
        html += `<div style="display:flex; align-items:center; gap:6px;">
          <input type="range" class="minutes-slider" min="0" max="40" value="${spot.min}"
            oninput="updateBenchMin(${i}, ${b}, this.value)"
            onchange="refreshPositionTotal(${i})"
            style="flex:1;">
          <div style="font-family:'Bebas Neue',sans-serif; font-size:16px; color:${bprC}; width:20px; text-align:right;" id="bm-${i}-${b}">${spot.min}</div>
          <div style="font-size:8px; color:var(--muted);">min</div>
        </div>`;
      }

      html += `</div>`;
    }

    html += `</div>`; // end column
  }

  html += `</div>`; // end grid

  // ── POSITION TOTALS ROW ──────────────────────────────────────
  const grandTotal = Array.from({length:5}, (_, i) => lineup[i] ? getPositionTotal(i) : 0).reduce((a,b)=>a+b,0);
  const gtColor = grandTotal === 200 ? 'var(--green)' : grandTotal > 200 ? 'var(--red)' : 'var(--gold)';
  html += `<div style="display:flex; align-items:center; gap:12px; margin-top:14px; padding-top:12px; border-top:1px solid var(--border);">
    <div style="font-size:9px; letter-spacing:0.2em; text-transform:uppercase; color:var(--muted); flex:1;">Position minutes total (target: 200)</div>
    <div style="font-family:'Bebas Neue',sans-serif; font-size:22px; color:${gtColor};" id="grand-total">${grandTotal}/200</div>
  </div>`;

  // ── PLAYER MINUTES SUMMARY TABLE ─────────────────────────────
  const playerMinMap = getAllPlayersWithMinutes();
  const sortedPlayers = Object.entries(playerMinMap)
    .filter(([, min]) => min > 0)
    .sort((a, b) => b[1] - a[1]);

  if (sortedPlayers.length > 0) {
    html += `
    <div id="player-minutes-summary-wrap" style="margin-top:20px; border-top:1px solid var(--border); padding-top:16px;">
      <div style="font-size:9px; letter-spacing:0.3em; text-transform:uppercase; color:var(--muted); margin-bottom:12px; display:flex; align-items:center; gap:10px;">
        Player Minutes Summary
        <div style="flex:1; height:1px; background:var(--border);"></div>
      </div>
      <div id="player-minutes-summary" style="display:flex; flex-wrap:wrap; gap:6px; align-items:stretch;">`;

    sortedPlayers.forEach(([pid, totalMin]) => {
      const p = PLAYERS[pid];
      if (!p) return;
      const isStarter = lineup.includes(pid);
      const pct = Math.round((totalMin / 40) * 100); // % of a full game
      const minColor = totalMin >= 30 ? 'var(--green)' : totalMin >= 18 ? 'var(--gold)' : 'var(--muted)';
      const barPct = Math.min(100, (totalMin / 40) * 100);
      const effBpr = getEffectiveBpm(p);
      const bprC = effBpr >= 2 ? 'var(--green)' : effBpr >= 0 ? 'var(--gold)' : 'var(--red)';

      html += `
        <div style="background:var(--surface); border:1px solid var(--border); border-radius:4px; padding:10px 12px;">
          <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
            <div style="font-family:'Bebas Neue',sans-serif; font-size:14px; color:${bprC}; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
              ${htmlEscape(shortName(p))}
            </div>
            ${isStarter ? `<div style="font-size:7px; background:var(--blue-tint); color:var(--blue-light); border-radius:2px; padding:1px 4px; letter-spacing:0.1em;">START</div>` : `<div style="font-size:7px; background:var(--gold-tint); color:var(--gold-dim); border-radius:2px; padding:1px 4px; letter-spacing:0.1em;">BENCH</div>`}
          </div>
          <div style="display:flex; align-items:center; gap:8px;">
            <div style="flex:1; height:4px; background:var(--border); border-radius:2px; overflow:hidden;">
              <div style="height:100%; width:${barPct}%; background:${minColor}; border-radius:2px;"></div>
            </div>
            <div style="font-family:'Bebas Neue',sans-serif; font-size:18px; color:${minColor}; width:24px; text-align:right;">${totalMin}</div>
            <div style="font-size:8px; color:var(--muted);">min</div>
          </div>
          <div style="font-size:9px; color:var(--muted); margin-top:3px;">${htmlEscape(p.pos)} · ${htmlEscape(p.yr)} · ${pct}% of game</div>
        </div>`;
    });

    html += `</div></div>`;
  }

  section.innerHTML = html;
  // Update all slider fills after DOM is set
  section.querySelectorAll('.minutes-slider').forEach(el => {
    updateSliderFill(el, parseInt(el.value), parseInt(el.max) || 40);
  });
}

function updateSliderFill(el, val, max) {
  const pct = (val / max) * 100;
  el.style.background = `linear-gradient(to right, var(--gold) 0%, var(--gold) ${pct}%, var(--border2) ${pct}%)`;
}

function updateStarterMin(id, val, slotIdx) {
  const proposed = parseInt(val);
  const slider   = event.target;

  // ── CAP 1: position slot must not exceed 40 ──────────────────
  const benchTotal = getBenchSpots(slotIdx).reduce((s, sp) => s + (sp.id ? sp.min : 0), 0);
  const slotCapped = Math.min(proposed, 40 - benchTotal);

  // ── CAP 2: team total must not exceed 200 ────────────────────
  const currentTeamTotal = Array.from({length:5}, (_, i) => lineup[i] ? getPositionTotal(i) : 0).reduce((a,b)=>a+b,0);
  const currentForSlot   = benchMinutes[id] !== undefined ? benchMinutes[id] : DEFAULT_STARTER_MIN;
  const teamHeadroom     = 200 - (currentTeamTotal - currentForSlot);
  const capped           = Math.min(slotCapped, teamHeadroom);

  if (capped !== proposed) {
    slider.value = capped;
    slider.style.outline = '2px solid var(--red)';
    setTimeout(() => { slider.style.outline = ''; }, 600);
  }

  benchMinutes[id] = capped;
  const el = document.getElementById('sm-' + id);
  if (el) el.textContent = capped;
  updateSliderFill(slider, capped, 40);
  refreshPositionTotalInline(slotIdx);
  renderMinutesSummary();
}

function updateBenchMin(slotIdx, benchSpot, val) {
  const proposed = parseInt(val);
  const slider   = event.target;
  const key      = `bench_${slotIdx}_${benchSpot}_min`;

  // ── CAP 1: position slot must not exceed 40 ──────────────────
  const starterId  = lineup[slotIdx];
  const starterMin = starterId ? (benchMinutes[starterId] !== undefined ? benchMinutes[starterId] : DEFAULT_STARTER_MIN) : 0;
  const otherBench = getBenchSpots(slotIdx).reduce((s, sp, idx) => {
    return idx === benchSpot ? s : s + (sp.id ? sp.min : 0);
  }, 0);
  const slotCapped = Math.min(proposed, 40 - starterMin - otherBench);

  // ── CAP 2: team total must not exceed 200 ────────────────────
  const currentTeamTotal = Array.from({length:5}, (_, i) => lineup[i] ? getPositionTotal(i) : 0).reduce((a,b)=>a+b,0);
  const currentForSpot   = benchMinutes[key] || 0;
  const teamHeadroom     = 200 - (currentTeamTotal - currentForSpot);
  const capped           = Math.min(Math.max(0, slotCapped), teamHeadroom);

  if (capped !== proposed) {
    slider.value = capped;
    slider.style.outline = '2px solid var(--red)';
    setTimeout(() => { slider.style.outline = ''; }, 600);
  }

  benchMinutes[key] = capped;
  const el = document.getElementById(`bm-${slotIdx}-${benchSpot}`);
  if (el) el.textContent = capped;
  updateSliderFill(slider, capped, 40);
  refreshPositionTotalInline(slotIdx);
  renderMinutesSummary();
}

function updateBenchPlayer(slotIdx, benchSpot, playerId) {
  benchMinutes[`bench_${slotIdx}_${benchSpot}_id`] = playerId;
  if (!playerId) benchMinutes[`bench_${slotIdx}_${benchSpot}_min`] = 0;
  updateRatings();
  renderBench();
}

function initSliderFills() {
  document.querySelectorAll('.minutes-slider').forEach(el => {
    updateSliderFill(el, parseInt(el.value), parseInt(el.max) || 40);
  });
}

// Lightweight inline update — only touches text nodes, never re-renders DOM
function refreshPositionTotalInline(slotIdx) {
  const total = getPositionTotal(slotIdx);
  const tc    = totalColor(total);
  const el    = document.getElementById('total-' + slotIdx);
  if (el) { el.textContent = `${total}/40`; el.style.color = tc; }

  const grand = Array.from({length:5}, (_, i) => lineup[i] ? getPositionTotal(i) : 0).reduce((a,b)=>a+b,0);
  const gtEl  = document.getElementById('grand-total');
  if (gtEl) {
    gtEl.textContent = `${grand}/200`;
    gtEl.style.color = grand === 200 ? 'var(--green)' : grand > 200 ? 'var(--red)' : 'var(--gold)';
  }

  // Update rotation BPM live as minutes change
  updateRatings();
}

// Full re-render — only called on mouseup/touchend, not during drag
function refreshPositionTotal(slotIdx) {
  refreshPositionTotalInline(slotIdx);
  renderBench();
  setTimeout(initSliderFills, 0);
}

// ─── DRAWER ────────────────────────────────────────────────────
function openDrawer(id) {
  const p = PLAYERS[id];
  if (!p) return;
  const drawer = document.getElementById('drawer');
  drawer.dataset.playerId = id;
  const bpm = lineupBpm(p);
  const currentRapm = currentImpact(p)?.rapm;
  const priorRapm = PRIOR_IMPACT[id]?.rapm;
  document.getElementById('drawer-tag').textContent = `#${p.num} · ${p.pos} · ${p.yr} · ${p.ht}`;
  document.getElementById('drawer-name').textContent = p.name;
  document.getElementById('drawer-sub').textContent =
    `Score ${formatImpact(playerImpactScore(p))} · TS% ${p.ts} · USG% ${p.usg}`;
  (function(){
    const el = document.getElementById('drawer-teamctx');
    if (!el) return;
    const t = teamCtx(p.team);
    if (!t) { el.innerHTML = ''; return; }
    const col = t.rk <= 100 ? 'var(--green)' : t.rk <= 200 ? 'var(--gold)' : 'var(--red)';
    const vsU = t.em - UCSD_ADJ_EM;
    el.innerHTML =
      '<div style="font-size:8px;letter-spacing:0.18em;text-transform:uppercase;color:var(--muted);margin-bottom:5px;">'
      + 'Team context — ' + htmlEscape(p.team) + ' 2025-26</div>'
      + '<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:10px;align-items:baseline;">'
      + '<span>AdjOE <strong>' + t.oe.toFixed(1) + '</strong> <span style="color:var(--muted);font-size:8px;">#' + t.rkOE + '</span></span>'
      + '<span>AdjDE <strong>' + t.de.toFixed(1) + '</strong> <span style="color:var(--muted);font-size:8px;">#' + t.rkDE + '</span></span>'
      + '<span>AdjEM <strong style="color:' + col + '">' + (t.em>=0?'+':'') + t.em.toFixed(2) + '</strong> '
      + '<span style="color:var(--muted);font-size:8px;">#' + t.rk + ' of 365</span></span>'
      + '<span style="color:var(--muted);">vs UCSD ' + (vsU>=0?'+':'') + vsU.toFixed(2) + '</span>'
      + '</div>';
  })();
  document.getElementById('drawer-stats').innerHTML = `
    <div class="ds-cell"><div class="ds-label">2025–26 BPM</div><div class="ds-val">${formatImpact(bpm.prior)}</div></div>
    <div class="ds-cell"><div class="ds-label">2026–27 BPM</div><div class="ds-val">${formatImpact(bpm.current)}</div></div>
    <div class="ds-cell"><div class="ds-label">Blended BPM</div><div class="ds-val">${formatImpact(bpm.value)}</div></div>
    <div class="ds-cell"><div class="ds-label">2025–26 RAPM</div><div class="ds-val">${formatImpact(priorRapm)}</div></div>
    <div class="ds-cell"><div class="ds-label">2026–27 RAPM</div><div class="ds-val">${formatImpact(currentRapm)}</div></div>
    <div class="ds-cell"><div class="ds-label">Blended RAPM</div><div class="ds-val">${formatImpact(lineupRapm(p))}</div></div>
    <div class="ds-cell"><div class="ds-label">TS%</div><div class="ds-val" style="color:${p.ts>=58?'var(--green)':p.ts>=54?'var(--gold)':'var(--muted)'}">${p.ts}</div></div>
    <div class="ds-cell"><div class="ds-label">USG%</div><div class="ds-val">${p.usg}</div></div>
    <div class="ds-cell"><div class="ds-label">A-Rate</div><div class="ds-val">${p.arate}%</div></div>
    <div class="ds-cell"><div class="ds-label">STL%</div><div class="ds-val">${p.stl}%</div></div>
    <div class="ds-cell"><div class="ds-label">BLK%</div><div class="ds-val">${p.blk}%</div></div>
    <div class="ds-cell"><div class="ds-label">3PT Rate</div><div class="ds-val">${(p.threeRate*100).toFixed(0)}%</div></div>
  `;
  renderPlayerForecast(id);
  document.getElementById('drawer-note').innerHTML = p.note;
  drawer.classList.add('open');
}

function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
}

// ─── PORTAL PLAYER ─────────────────────────────────────────────

function buildSkillTranslation(p) {
  const conf = p.fromConf || 'bigwest';
  const isBigWest = conf === 'bigwest';
  const arate = p.arate || 0;
  const passingScore = Math.min(100, (arate / 30) * 100) * 0.95;
  const threeP   = (p.threeRate || 0) * 100;
  const threePct = p.threePct != null ? p.threePct : Math.max(20, Math.min(45, (p.ts || 50) - 18));
  const rateScore = Math.min(100, (threeP / 40) * 100);
  const pctScore  = Math.min(100, Math.max(0, ((threePct - 26) / 16) * 100));
  const shootingScore = ((rateScore * 0.4) + (pctScore * 0.6)) * (isBigWest ? 1.0 : 0.88);
  const ftr = p.ftr || 20; const usg = p.usg || 18;
  const rimScore = Math.min(100, ((ftr/55)*60) + ((usg/28)*40)) * 0.80;
  const stl = p.stl || 0; const blk = p.blk || 0;
  const defScore = Math.min(100, (stl/3.5)*65 + (blk/3.0)*35) * 0.85;
  const ts = p.ts || 50; const bpr = p.bpr || 0;
  const effScore = Math.min(100, Math.max(0, ((ts-46)/22)*60 + ((bpr+5)/14)*40)) * (isBigWest ? 1.0 : 0.72);
  const composite = passingScore*0.30 + shootingScore*0.30 + rimScore*0.15 + defScore*0.15 + effScore*0.10;
  function scoreColor(s) { return s >= 65 ? 'var(--green)' : s >= 42 ? 'var(--yellow)' : 'var(--red)'; }
  function badge(port) {
    if (port >= 0.90) return '<span class="skill-badge badge-portable">Portable</span>';
    if (port >= 0.80) return '<span class="skill-badge badge-moderate">Moderate</span>';
    return '<span class="skill-badge badge-fragile">Fragile</span>';
  }
  function bar(score, color) {
    return '<div class="skill-bar-track"><div class="skill-bar-fill" style="width:' + score.toFixed(0) + '%;background:' + color + '"></div></div>';
  }
  const compColor = scoreColor(composite);
  const compGrade = composite >= 72 ? 'A' : composite >= 60 ? 'B' : composite >= 46 ? 'C' : composite >= 32 ? 'D' : 'F';
  const confLabel = isBigWest ? 'Big West' : ({ asun:'ASUN', cusa:'C-USA', mvc:'MVC', wcc:'WCC', mac:'MAC', mwc:'Mtn West', americaeast:'America East', bigsky:'Big Sky', sec:'SEC', big10:'Big Ten' }[conf] || conf.toUpperCase());
  const rows = [
    { label: 'Passing / ARate',   score: passingScore,  port: 0.95, raw: arate.toFixed(1) + '%' },
    { label: '3PT Shooting',      score: shootingScore,  port: 0.88, raw: threePct.toFixed(1) + '% / ' + threeP.toFixed(0) + '%r' },
    { label: 'Rim Attack / USG',  score: rimScore,       port: 0.80, raw: 'FTr ' + ftr.toFixed(0) },
    { label: 'Defense (STL+BLK)', score: defScore,       port: 0.85, raw: stl + '+' + blk + '%' },
    { label: 'Raw Efficiency',    score: effScore,       port: 0.72, raw: 'TS ' + ts + '%' },
  ];
  return '<div class="skill-translation">' +
    '<div class="skill-translation-header">' +
      '<span class="skill-translation-title">⬡ Skill Translation to Big West</span>' +
      '<span class="skill-translation-score" style="color:' + compColor + '">' + composite.toFixed(0) + '<span style="font-size:10px;color:var(--muted)"> / 100 · ' + compGrade + '</span></span>' +
    '</div>' +
    rows.map(r =>
      '<div class="skill-row">' +
        '<span class="skill-label">' + r.label + '</span>' +
        bar(r.score, scoreColor(r.score)) +
        '<span class="skill-val" style="color:' + scoreColor(r.score) + '">' + r.score.toFixed(0) + '</span>' +
        badge(r.port) +
        '<span style="font-size:8px;color:var(--muted);width:60px;text-align:right;flex-shrink:0">' + r.raw + '</span>' +
      '</div>'
    ).join('') +
    '<div class="skill-translation-footer">Portability = how reliably each skill transfers to Big West · from ' + confLabel + '</div>' +
  '</div>';
}

const BW_STANDINGS = [
  { team: 'UC Irvine', bpm: 12.6,       rec: '23-12', conf: '15-5',  netrtg: +5.71, ortg: 104.6, drtg: 98.9,  adjT: 68.4, oe: 106.7, de: 95.7,  efgO: 51.5, efgD: 44.5, toO: 17.9, orbO: 31.9, threeO: 36.1, threeD: 32.6, ftr: 35.9, threeRate: 28.0, color: 'var(--blue-light)' },
  { team: 'Hawaii', bpm: 11.1,          rec: '24-9',  conf: '14-6',  netrtg: +5.58, ortg: 107.2, drtg: 101.6, adjT: 69.8, oe: 107.9, de: 100.9, efgO: 52.8, efgD: 48.3, toO: 18.4, orbO: 29.2, threeO: 32.9, threeD: 30.7, ftr: 41.4, threeRate: 39.8, color: 'var(--green)' },
  { team: 'UC San Diego',    rec: '23-11', conf: '12-8',  netrtg: +4.30, ortg: 107.8, drtg: 103.5, adjT: 67.3, oe: 103.0, de: 100.4, efgO: 50.4, efgD: 48.3, toO: 17.0, orbO: 25.6, threeO: 30.9, threeD: 31.9, ftr: 31.2, threeRate: 42.3, color: '#c8a84b', highlight: true },
  { team: '↗ UCSD 2026-27', rec: 'PROJ',  conf: '—',    netrtg: +7.0,  ortg: 108.5, drtg: 101.5, adjT: 68.5, oe: 107.5, de: 100.8, efgO: 52.5, efgD: 48.0, toO: 16.8, orbO: 29.5, threeO: 35.0, threeD: 31.5, ftr: 36.5, threeRate: 45.0, color: '#c8a84b', projection: true },
  { team: 'Cal St. Fullerton', bpm: 4.9,rec:'18-16', conf: '12-8',  netrtg: +0.02, ortg: 109.3, drtg: 109.3, adjT: 72.9, oe: 108.0, de: 106.3, efgO: 52.6, efgD: 54.6, toO: 15.0, orbO: 23.5, threeO: 35.7, threeD: 33.9, ftr: 51.4, threeRate: 34.2, color: 'var(--muted)' },
  { team: 'CSUN', bpm: 4.9,            rec: '20-14', conf: '12-8',  netrtg: -0.68, ortg: 108.9, drtg: 109.6, adjT: 73.6, oe: 107.2, de: 104.9, efgO: 51.3, efgD: 50.7, toO: 17.1, orbO: 32.9, threeO: 32.0, threeD: 34.5, ftr: 34.2, threeRate: 32.0, color: 'var(--red)' },
  { team: 'UC Santa Barbara', bpm: 7.2, rec:'18-14', conf: '11-9',  netrtg: +2.95, ortg: 113.3, drtg: 110.8, adjT: 64.4, oe: 113.8, de: 107.3, efgO: 56.0, efgD: 51.5, toO: 19.0, orbO: 30.4, threeO: 38.3, threeD: 31.9, ftr: 53.6, threeRate: 44.1, color: 'var(--muted)' },
  { team: 'UC Davis', bpm: 5.8,        rec: '19-14', conf: '11-9',  netrtg: +0.67, ortg: 108.0, drtg: 107.3, adjT: 69.0, oe: 106.0, de: 104.7, efgO: 50.8, efgD: 52.8, toO: 17.4, orbO: 26.3, threeO: 36.0, threeD: 34.5, ftr: 51.9, threeRate: 43.5, color: 'var(--muted)' },
  { team: 'Cal Poly', bpm: 2.1,        rec: '14-19', conf: '10-10', netrtg: -3.89, ortg: 109.4, drtg: 113.3, adjT: 74.0, oe: 110.1, de: 111.9, efgO: 53.1, efgD: 53.6, toO: 18.8, orbO: 29.5, threeO: 33.5, threeD: 35.0, ftr: 53.7, threeRate: 52.6, color: 'var(--muted)' },
  { team: 'Long Beach St.', bpm: 1.4,  rec: '10-22', conf: '6-14',  netrtg: -5.98, ortg: 105.6, drtg: 111.5, adjT: 68.6, oe: 103.1, de: 107.2, efgO: 51.4, efgD: 51.1, toO: 18.0, orbO: 24.9, threeO: 34.2, threeD: 32.6, ftr: 30.7, threeRate: 34.8, color: 'var(--muted)' },
  { team: 'UC Riverside', bpm: -1.2,    rec: '10-22', conf: '5-15',  netrtg: -7.96, ortg: 104.0, drtg: 111.9, adjT: 68.5, oe: 101.6, de: 109.4, efgO: 47.2, efgD: 51.8, toO: 17.0, orbO: 28.9, threeO: 30.2, threeD: 33.5, ftr: 49.9, threeRate: 38.3, color: 'var(--muted)' },
  { team: 'Cal St. Bakers.', bpm: -8.3, rec: '8-24',  conf: '2-18',  netrtg:-15.54, ortg: 101.9, drtg: 117.4, adjT: 70.1, oe: 100.0, de: 118.4, efgO: 46.2, efgD: 56.2, toO: 17.6, orbO: 29.1, threeO: 30.6, threeD: 39.0, ftr: 46.6, threeRate: 28.9, color: 'var(--muted)' },
];

const BIG_WEST_TEAMS = {
  hawaii: {
    players: [
      { name: 'I. Johnson',   pos: 'C',  yr: 'Sr', bpm: 6.7 },
      { name: 'Bullock',      pos: 'SF', yr: 'Sr', bpm: 3.3 },
      { name: 'Rouhliadeff', pos: 'PF', yr: 'Sr', bpm: 2.6 },
      { name: 'Nemeiksa',    pos: 'SF', yr: 'Jr', bpm: 0.5 },
      { name: 'Finlinson',   pos: 'PF', yr: 'Jr', bpm: 1.0 },
      { name: 'Kerr',        pos: 'PG', yr: 'Jr', bpm: 0.6 },
      { name: 'Erickson',    pos: 'SG', yr: 'Sr', bpm: 0.0 },
    ]
  },
  uci: {
    players: [
      { name: 'Evans',        pos: 'C',  yr: 'Sr', bpm: 6.9 },
      { name: 'Dixon',        pos: 'SF', yr: 'So', bpm: 2.8 },
      { name: 'Carrington',  pos: 'SF', yr: 'Jr', bpm: 2.5 },
      { name: 'Henry',       pos: 'SG', yr: 'Sr', bpm: 1.4 },
      { name: 'Saran',       pos: 'PG', yr: 'So', bpm: 0.0 },
      { name: 'Jester Jr.',  pos: 'SG', yr: 'Fr', bpm: 0.2 },
      { name: 'Chol',        pos: 'C',  yr: 'Jr', bpm: -0.6 },
    ]
  },
  csun: {
    players: [
      { name: 'Fofana',      pos: 'SF', yr: 'Sr', bpm: 2.6 },
      { name: 'Hughes II',   pos: 'SG', yr: 'Sr', bpm: 2.1 },
      { name: "O'Garro",    pos: 'PF', yr: 'Sr', bpm: 1.5 },
      { name: 'Davis',       pos: 'PG', yr: 'Sr', bpm: -1.6 },
      { name: 'Lewis',       pos: 'C',  yr: 'Sr', bpm: -1.5 },
      { name: 'Brinson',     pos: 'SG', yr: 'Sr', bpm: 0.4 },
      { name: 'Szymczyk',   pos: 'C',  yr: 'Jr', bpm: 0.3 },
    ]
  }
};

function renderConferenceContext() {
  renderStandingsTable();

  const teamMap = { hawaii: 'hawaii-rows', uci: 'uci-rows', csun: 'csun-rows' };
  Object.entries(BIG_WEST_TEAMS).forEach(([key, team]) => {
    const el = document.getElementById(teamMap[key]);
    if (!el) return;
    el.innerHTML = team.players.map(p => {
      const c = p.bpm >= 4 ? 'var(--green)' : p.bpm >= 1.5 ? 'var(--gold)' : p.bpm >= 0 ? 'var(--muted)' : 'var(--red)';
      const sign = p.bpm > 0 ? '+' : '';
      return `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;border-bottom:1px solid var(--border);">
        <div style="font-size:9px;color:var(--muted);width:24px;flex-shrink:0;">${p.pos}</div>
        <div style="flex:1;font-size:11px;color:var(--text);">${p.name}</div>
        <div style="font-size:9px;color:var(--muted);width:18px;flex-shrink:0;">${p.yr}</div>
        <div style="font-family:'Bebas Neue',sans-serif;font-size:15px;color:${c};width:36px;text-align:right;">${sign}${p.bpm}</div>
      </div>`;
    }).join('');
  });

}

function renderStandingsTable() {
  const el = document.getElementById('standings-table');
  if (!el) return;

  const cols = [
    { label: 'Team',      key: 'team',      w: '120px' },
    { label: 'Conf',      key: 'conf',      w: '46px' },
    { label: 'NetRtg',   key: 'netrtg',    w: '56px' },
    { label: 'ORtg',     key: 'ortg',      w: '48px' },
    { label: 'DRtg',     key: 'drtg',      w: '48px' },
    { label: 'Tempo',    key: 'adjT',      w: '46px' },
    { label: 'eFG%',     key: 'efgO',      w: '44px' },
    { label: 'Def eFG%', key: 'efgD',      w: '56px' },
    { label: 'TO%',      key: 'toO',       w: '40px' },
    { label: 'OReb%',    key: 'orbO',      w: '46px' },
    { label: '3PT%',     key: 'threeO',    w: '44px' },
    { label: 'D3PT%',    key: 'threeD',    w: '44px' },
    { label: 'FTR',      key: 'ftr',       w: '40px' },
    { label: '3PR',      key: 'threeRate', w: '40px' },
  ];

  // Header
  let html = `<div style="display:flex;gap:0;margin-bottom:4px;padding-bottom:4px;border-bottom:1px solid var(--border2);">`;
  cols.forEach(c => {
    html += `<div style="width:${c.w};font-size:8px;letter-spacing:0.15em;text-transform:uppercase;color:var(--muted);flex-shrink:0;padding-right:6px;">${c.label}</div>`;
  });
  html += `</div>`;

  // Get min/max for each numeric col for coloring
  const numCols = cols.filter(c => c.key !== 'team' && c.key !== 'conf');
  const minMax = {};
  numCols.forEach(c => {
    const vals = BW_STANDINGS.map(t => t[c.key]);
    minMax[c.key] = { min: Math.min(...vals), max: Math.max(...vals) };
  });

  // Good direction per stat
  const higherBetter = { netrtg: true, ortg: true, oe: true, efgO: true, toO: false, orbO: true, threeO: true, threeD: false, adjT: null };
  const lowerBetter  = { drtg: true, de: true, efgD: true, threeD: true };

  BW_STANDINGS.forEach(t => {
    const isUCSD = t.highlight;
    const isProj = t.projection;
    const rowBg = isProj ? 'var(--gold-tint)' : isUCSD ? 'color-mix(in srgb, var(--gold) 5%, transparent)' : 'transparent';
    const borderTop = isProj ? 'border-top:1px dashed var(--gold-dim);' : '';
    html += `<div style="display:flex;gap:0;padding:4px 0;border-bottom:1px solid var(--border);background:${rowBg};${borderTop}">`;
    cols.forEach(c => {
      let val = t[c.key];
      if (val === undefined) {
        html += `<div style="width:${c.w};font-size:10px;color:var(--muted);flex-shrink:0;padding-right:6px;">—</div>`;
        return;
      }
      let dispVal = typeof val === 'number' ? (c.key === 'netrtg' ? (val > 0 ? '+' : '') + val.toFixed(2) : val.toFixed(1)) : val;
      let cellColor = (isUCSD || isProj) ? 'var(--gold)' : 'var(--text)';

      if (typeof val === 'number' && !['team','conf'].includes(c.key) && !isProj) {
        const mm = minMax[c.key];
        if (mm) {
          const { min, max } = mm;
          const pct = max === min ? 0.5 : (val - min) / (max - min);
          const isGoodHigh = ['netrtg','ortg','oe','efgO','orbO','threeO','ftr','threeRate'].includes(c.key);
          const isGoodLow  = ['drtg','de','efgD','threeD','toO'].includes(c.key);
          const goodness = isGoodHigh ? pct : isGoodLow ? (1 - pct) : 0.5;
          if (!isUCSD) cellColor = goodness > 0.7 ? 'var(--green)' : goodness < 0.3 ? 'var(--red)' : 'var(--muted)';
        }
      }

      const fw = ((isUCSD || isProj) && c.key === 'team') ? '500' : '400';
      const italic = isProj ? 'font-style:italic;' : '';
      let cellContent = dispVal;
      // Show BPM next to record column
      if (c.key === 'conf' && t.bpm !== undefined) {
        const bpmSign = t.bpm >= 0 ? '+' : '';
        const bpmCol  = t.bpm >= 5 ? 'var(--green)' : t.bpm >= 2 ? 'var(--gold)' : t.bpm >= 0 ? 'var(--muted)' : 'var(--red)';
        cellContent = dispVal + `<span style="font-size:9px;color:${bpmCol};margin-left:4px;">${bpmSign}${t.bpm.toFixed(1)}</span>`;
      }
      // For UCSD projected row — show live BPM
      if (c.key === 'conf' && t.projection) {
        const liveBPM = window._liveBPM !== undefined ? window._liveBPM : '—';
        const bpmSign = typeof liveBPM === 'number' && liveBPM >= 0 ? '+' : '';
        const bpmCol  = typeof liveBPM === 'number' ? (liveBPM >= 5 ? 'var(--green)' : liveBPM >= 2 ? 'var(--gold)' : liveBPM >= 0 ? 'var(--muted)' : 'var(--red)') : 'var(--muted)';
        const bpmStr  = typeof liveBPM === 'number' ? bpmSign + liveBPM.toFixed(1) : liveBPM;
        cellContent = dispVal + `<span style="font-size:9px;color:${bpmCol};margin-left:4px;">${bpmStr}</span>`;
      }
      // For UCSD actual row — show actual BPM
      if (c.key === 'conf' && t.highlight) {
        cellContent = dispVal + `<span style="font-size:9px;color:var(--gold);margin-left:4px;">+5.4</span>`;
      }
      html += `<div style="width:${c.w};font-size:10px;color:${cellColor};flex-shrink:0;padding-right:6px;font-weight:${fw};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;${italic}">${cellContent}</div>`;
    });
    html += `</div>`;
  });

  el.innerHTML = html;
}

// ─── SAVED LINEUPS ─────────────────────────────────────────────
const STORAGE_KEY = 'ucsd_saved_lineups_v1';

async function loadSavedLineups() {
  try {
    const result = await window.storage.get(STORAGE_KEY);
    return result ? JSON.parse(result.value) : [];
  } catch(e) { return []; }
}

async function persistSavedLineups(lineups) {
  try {
    await window.storage.set(STORAGE_KEY, JSON.stringify(lineups));
  } catch(e) { console.warn('Storage unavailable'); }
}

function showSaveInput() {
  const row = document.getElementById('save-input-row');
  row.style.display = 'flex';
  setTimeout(() => document.getElementById('save-lineup-name').focus(), 50);
}

function hideSaveInput() {
  document.getElementById('save-input-row').style.display = 'none';
  document.getElementById('save-lineup-name').value = '';
}

async function saveCurrentLineup() {
  const name = document.getElementById('save-lineup-name').value.trim();
  if (!name) return;
  const saved = await loadSavedLineups();
  const entry = {
    id: 'saved_' + Date.now(),
    name,
    lineup: [...lineup],
    benchMinutes: {...benchMinutes},
    recruits: recruitSnapshots(activeRotationPlayerIds()),
  };
  saved.push(entry);
  await persistSavedLineups(saved);
  hideSaveInput();
  renderSavedPresets(saved);
}

async function loadSavedLineup(id) {
  const saved = await loadSavedLineups();
  const entry = saved.find(e => e.id === id);
  if (!entry) return;
  restoreRecruitingPlayers(entry.recruits);
  lineup = entry.lineup.map(resolveSavedPlayerId);
  benchMinutes = {};
  for (const [key, value] of Object.entries(entry.benchMinutes)) {
    if (/^bench_\d+_\d+_id$/.test(key)) {
      benchMinutes[key] = resolveSavedPlayerId(value) || '';
    } else if (/^bench_\d+_\d+_min$/.test(key)) {
      benchMinutes[key] = value;
    } else {
      const playerId = resolveSavedPlayerId(key);
      if (playerId) benchMinutes[playerId] = value;
    }
  }
  showUnavailableSavedPlayers([...entry.lineup, ...Object.values(entry.benchMinutes)]);
  // Highlight active button
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.style.borderColor = ''; btn.style.color = ''; btn.style.fontWeight = '';
  });
  document.querySelectorAll('.saved-preset-btn').forEach(btn => {
    btn.style.borderColor = ''; btn.style.color = 'var(--gold)';
  });
  const activeBtn = document.querySelector(`.saved-preset-btn[data-id="${id}"]`);
  if (activeBtn) { activeBtn.style.borderColor = 'var(--gold)'; activeBtn.style.fontWeight = '600'; }
  renderLineup();
  setTimeout(() => { renderBench(); updateRatings(); }, 50);
}

async function deleteSavedLineup(id) {
  const saved = await loadSavedLineups();
  const updated = saved.filter(e => e.id !== id);
  await persistSavedLineups(updated);
  renderSavedPresets(updated);
}

function renderSavedPresets(saved) {
  const row = document.getElementById('saved-presets-row');
  if (!saved || saved.length === 0) { row.innerHTML = ''; return; }
  row.innerHTML = saved.map(e => `
    <button class="saved-preset-btn" data-id="${e.id}" onclick="loadSavedLineup('${e.id}')">
      ★ ${htmlEscape(e.name)}
      <span class="sp-delete" onclick="event.stopPropagation(); deleteSavedLineup('${e.id}')" title="Delete">✕</span>
    </button>`).join('');
}

async function initSavedLineups() {
  const saved = await loadSavedLineups();
  renderSavedPresets(saved);
  const nmSaved = await nmLoadSavedRotations();
  nmRenderSavedPresets(nmSaved);
}

// ─── 9-MAN SAVE/LOAD ───────────────────────────────────────────
const NM_STORAGE_KEY = 'ucsd_saved_9man_v1';

async function nmLoadSavedRotations() {
  try {
    const result = await window.storage.get(NM_STORAGE_KEY);
    return result ? JSON.parse(result.value) : [];
  } catch(e) { return []; }
}

async function nmPersistSaved(rotations) {
  try { await window.storage.set(NM_STORAGE_KEY, JSON.stringify(rotations)); }
  catch(e) { console.warn('Storage unavailable'); }
}

function nmShowSaveInput() {
  const row = document.getElementById('nm-save-input-row');
  row.style.display = 'flex';
  setTimeout(() => document.getElementById('nm-save-name').focus(), 50);
}

function nmHideSaveInput() {
  document.getElementById('nm-save-input-row').style.display = 'none';
  document.getElementById('nm-save-name').value = '';
}

async function nmSaveRotation() {
  const name = document.getElementById('nm-save-name').value.trim();
  if (!name) return;
  const saved = await nmLoadSavedRotations();
  const entry = {
    id: 'nm_' + Date.now(),
    name,
    players: nmPlayers.map(p => p ? p._pid || null : null),
    mins: [...nmMins],
    recruits: recruitSnapshots(nmPlayers.map(p => p?._pid)),
  };
  saved.push(entry);
  await nmPersistSaved(saved);
  nmHideSaveInput();
  nmRenderSavedPresets(saved);
}

async function nmRestoreRotation(id) {
  const saved = await nmLoadSavedRotations();
  const entry = saved.find(e => e.id === id);
  if (!entry) return;
  restoreRecruitingPlayers(entry.recruits);
  showUnavailableSavedPlayers(entry.players);
  nmClear();
  entry.players.forEach((savedId, i) => {
    const pid = resolveSavedPlayerId(savedId);
    if (pid) {
      nmPlayers[i] = PLAYERS[pid];
      nmPlayers[i]._pid = pid;
    }
  });
  nmMins = [...entry.mins];
  nmRender();
  nmUpdateStats();
  // Highlight
  document.querySelectorAll('#nm-saved-row .saved-preset-btn').forEach(b => {
    b.style.borderColor = ''; b.style.fontWeight = '';
  });
  const btn = document.querySelector('#nm-saved-row .saved-preset-btn[data-id="' + id + '"]');
  if (btn) { btn.style.borderColor = 'var(--gold)'; btn.style.fontWeight = '700'; }
}

async function nmDeleteRotation(id) {
  const saved = await nmLoadSavedRotations();
  await nmPersistSaved(saved.filter(e => e.id !== id));
  nmRenderSavedPresets(saved.filter(e => e.id !== id));
}

function nmRenderSavedPresets(saved) {
  const row = document.getElementById('nm-saved-row');
  if (!row || !saved || saved.length === 0) { if(row) row.innerHTML = ''; return; }
  row.innerHTML = saved.map(function(e) {
    return '<button class="saved-preset-btn" data-id="' + e.id + '" onclick="nmRestoreRotation(&quot;' + e.id + '&quot;)">'
      + '★ ' + htmlEscape(e.name)
      + '<span class="sp-delete" onclick="event.stopPropagation();nmDeleteRotation(&quot;' + e.id + '&quot;)" title="Delete">✕</span>'
      + '</button>';
  }).join('');
}


// ─── LIVE PROJECTION TABLE ─────────────────────────────────────
// Actuals from 2025-26 season (used for delta calculation)
const UCSD_ACTUAL_2526 = {
  netrtg: 4.30, ortg: 107.8, drtg: 103.5,
  threePct: 30.9, threeRate: 42.3, ftr: 31.2,
  oreb: 25.6, torate: 17.0, dreb: 73.0
};

function updateProjectionTable(projOrtg, projDrtg, proj3Pct, proj3PR, projFTR, projOReb, projTORate, projDReb, ortgFloor, ortgCeil) {
  const netrtg = projOrtg - projDrtg;
  const actual = UCSD_ACTUAL_2526;

  function colorDir(val, better='higher') {
    // For torate and drtg, lower is better
    return better === 'lower'
      ? (val < 0 ? 'var(--green)' : val > 0 ? 'var(--red)' : 'var(--muted)')
      : (val > 0 ? 'var(--green)' : val < 0 ? 'var(--red)' : 'var(--muted)');
  }

  function setCell(id, val, suffix, color) {
    const el = document.getElementById(id);
    if (el) { el.textContent = val === null ? '—' : val + suffix; el.style.color = color; }
  }

  function setDelta(id, delta, suffix, better='higher') {
    const el = document.getElementById(id);
    if (!el) return;
    if (!Number.isFinite(delta)) { el.textContent = '—'; el.style.color = 'var(--muted)'; return; }
    const sign = delta >= 0 ? '+' : '';
    el.textContent = sign + delta.toFixed(1) + suffix;
    el.style.color = colorDir(delta, better);
  }

  // Projected values
  setCell('proj-netrtg', (netrtg >= 0 ? '+' : '') + netrtg.toFixed(1), '', netrtg >= 4.3 ? 'var(--green)' : netrtg >= 2 ? 'var(--gold)' : 'var(--muted)');
  const ortgColor = projOrtg >= 108 ? 'var(--green)' : projOrtg >= 106 ? 'var(--gold)' : 'var(--muted)';
  const ortgText = ortgFloor ? projOrtg.toFixed(1) : projOrtg.toFixed(1);
  setCell('proj-ortg', ortgText, '', ortgColor);
  const ortgEl = document.getElementById('proj-ortg');
  if (ortgEl && ortgFloor) ortgEl.title = 'Range: ' + ortgFloor.toFixed(1) + ' – ' + ortgCeil.toFixed(1);
  setCell('proj-drtg',   projDrtg.toFixed(1),           '', projDrtg <= 103 ? 'var(--green)' : projDrtg <= 105 ? 'var(--gold)' : 'var(--muted)');
  setCell('proj-3pct',   proj3Pct?.toFixed(1) ?? null,    '%', proj3Pct >= 35 ? 'var(--green)' : proj3Pct >= 33 ? 'var(--gold)' : 'var(--red)');
  setCell('proj-3pr',    proj3PR?.toFixed(1) ?? null,            '', proj3PR >= 44 ? 'var(--green)' : proj3PR >= 40 ? 'var(--gold)' : 'var(--muted)');
  setCell('proj-ftr',    projFTR?.toFixed(1) ?? null,            '', projFTR >= 35 ? 'var(--green)' : projFTR >= 28 ? 'var(--gold)' : 'var(--muted)');
  setCell('proj-oreb',   projOReb?.toFixed(1) ?? null,    '%', projOReb >= 27 ? 'var(--green)' : projOReb >= 23 ? 'var(--gold)' : 'var(--red)');
  setCell('proj-torate', projTORate?.toFixed(1) ?? null,  '%', projTORate <= 16 ? 'var(--green)' : projTORate <= 17.5 ? 'var(--gold)' : 'var(--red)');
  setCell('proj-dreb',   projDReb?.toFixed(1) ?? null,   '%', projDReb >= 73 ? 'var(--green)' : projDReb >= 68 ? 'var(--gold)' : 'var(--muted)');

  // Deltas vs 2025-26 actual
  setDelta('delta-netrtg',  netrtg - actual.netrtg,        '', 'higher');
  setDelta('delta-ortg',    projOrtg - actual.ortg,        '', 'higher');
  setDelta('delta-drtg',    projDrtg - actual.drtg,        '', 'lower');
  setDelta('delta-3pct',    (proj3Pct ?? NaN) - actual.threePct,    '%', 'higher');
  setDelta('delta-3pr',     (proj3PR ?? NaN) - actual.threeRate,   '', 'higher');
  setDelta('delta-ftr',     (projFTR ?? NaN) - actual.ftr,         '', 'higher');
  setDelta('delta-oreb',    (projOReb ?? NaN) - actual.oreb,        '%', 'higher');
  setDelta('delta-torate',  (projTORate ?? NaN) - actual.torate,    '%', 'lower');
  setDelta('delta-dreb',    (projDReb ?? NaN) - actual.dreb,      '%', 'higher');

  // Also update BW standings projected row
  const projRow = BW_STANDINGS.find(t => t.projection);
  if (projRow) {
    projRow.netrtg = +netrtg.toFixed(1);
    projRow.ortg   = +projOrtg.toFixed(1);
    projRow.drtg   = +projDrtg.toFixed(1);
    projRow.threeO = proj3Pct === null ? null : +proj3Pct.toFixed(1);
    projRow.threeRate = proj3PR === null ? null : +proj3PR.toFixed(1);
    projRow.ftr    = projFTR === null ? null : +projFTR.toFixed(1);
    projRow.orbO   = projOReb === null ? null : +projOReb.toFixed(1);
    projRow.toO    = projTORate === null ? null : +projTORate.toFixed(1);
  }
}


function initProjectedStatsCard() {
  const el = document.getElementById('projected-stats-inline');
  if (!el) return;
  el.innerHTML = `
      <div class="analysis-card" style="margin-top:16px; border-top: 2px solid var(--gold);">
        <div class="ac-title" style="color: var(--gold);">UCSD 2026-27 Projected Stats vs. Last Season</div>
        <div style="overflow-x: auto;">
          <div style="display:flex; gap:0; margin-bottom:6px; padding-bottom:4px; border-bottom:1px solid var(--border2); min-width:600px;">
            <div style="width:120px; font-size:8px; letter-spacing:0.15em; text-transform:uppercase; color:var(--muted);">Season</div>
            <div style="width:64px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">NetRtg</div>
            <div style="width:56px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">ORtg</div>
            <div style="width:56px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">DRtg</div>
            <div style="width:48px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">3PT%</div>
            <div style="width:48px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">3P Rate</div>
            <div style="width:48px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">FTR</div>
            <div style="width:56px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">OReb%</div>
            <div style="width:48px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">TO%</div>
            <div style="width:56px; font-size:8px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted);">DReb%</div>
          </div>
          <div style="display:flex; gap:0; padding:5px 0; border-bottom:1px solid var(--border); min-width:600px;">
            <div style="width:120px; font-size:10px; color:var(--muted);">2025-26 Actual</div>
            <div style="width:64px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--gold);">+4.30</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--muted);">107.8</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--green);">103.5</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--red);">30.9%</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--muted);">42.3</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--muted);">31.2</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--red);">25.6%</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--green);">17.0%</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif; color:var(--green);">73.0%</div>
          </div>
          <div style="display:flex; gap:0; padding:5px 0; min-width:600px; background:var(--gold-tint);" id="proj-stats-row">
            <div style="width:120px; font-size:10px; color:var(--gold); font-style:italic;">2026-27 Projected ↗</div>
            <div style="width:64px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-netrtg">—</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-ortg">—</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-drtg">—</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-3pct">—</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-3pr">—</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-ftr">—</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-oreb">—</div>
            <div style="width:48px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-torate">—</div>
            <div style="width:56px; font-size:13px; font-family:'Bebas Neue',sans-serif;" id="proj-dreb">—</div>
          </div>
          <div style="display:flex; gap:0; padding:5px 0; border-top:1px dashed var(--border2); min-width:600px;" id="delta-stats-row">
            <div style="width:120px; font-size:9px; color:var(--muted); letter-spacing:0.1em;">CHANGE</div>
            <div style="width:64px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-netrtg">—</div>
            <div style="width:56px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-ortg">—</div>
            <div style="width:56px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-drtg">—</div>
            <div style="width:48px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-3pct">—</div>
            <div style="width:48px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-3pr">—</div>
            <div style="width:48px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-ftr">—</div>
            <div style="width:56px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-oreb">—</div>
            <div style="width:48px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-torate">—</div>
            <div style="width:56px; font-size:11px; font-family:'Bebas Neue',sans-serif;" id="delta-dreb">—</div>
          </div>
        </div>
        <div style="font-size:10px; color:var(--muted); margin-top:10px; font-family:'Crimson Pro',serif; font-style:italic; line-height:1.6;">
          <strong style="font-family:'DM Mono',monospace; font-size:9px; color:var(--text);">Key drivers:</strong>
          3PT% driven by Chaikin (42.4% conf) + Dotson (38.0%) replacing non-shooters ·
          FTR driven by Suutela (47.4 FTRate, top 100 nationally) replacing Dengdit ·
          OReb% driven by Suutela OR% 7.4 — directly addresses last season's 11th-place ranking ·
          DRtg held steady as Beath/Beattie/Vance defensive core returns intact
        </div>
      </div>`;
}


// ─── 9-MAN ROTATION ────────────────────────────────────────────
let nmPlayers = Array(9).fill(null); // {id, name, ...} or null
let nmMins    = Array(9).fill(20);   // minutes per player

function nmRender() {
  const grid = document.getElementById('nm-grid');
  if (!grid) return;
  let html = '';
  for (let i = 0; i < 9; i++) {
    const p = nmPlayers[i];
    const m = nmMins[i];
    if (p) {
      html += '<div class="nine-man-slot filled" id="nm-slot-' + i + '"'
        + ' ondragover="event.preventDefault();this.classList.add(&quot;drag-over&quot;)"'
        + ' ondragleave="this.classList.remove(&quot;drag-over&quot;)"'
        + ' ondrop="nmDrop(event,' + i + ')">'

        + '<div class="nine-man-slot-name">' + htmlEscape(shortName(p)) + '</div>'
        + '<div class="nine-man-slot-sub">' + htmlEscape(p.pos || '') + ' · ' + htmlEscape(p.ht || '') + '</div>'

        + '<div class="nine-man-mins-row">'
        + '<input type="range" class="minutes-slider" min="0" max="40" value="' + m + '"'
        + ' oninput="nmUpdateMins(' + i + ',this.value,this)" style="height:5px;">'
        + '<span class="nine-man-mins-val" id="nm-mins-' + i + '">' + m + '</span>'
        + '<span style="font-size:8px;color:var(--muted);margin-left:2px;">min</span>'
        + '</div>'
        + '<button class="nine-man-remove" onclick="nmRemove(' + i + ')">✕</button>'
        + '</div>';
    } else {
      html += '<div class="nine-man-slot" id="nm-slot-' + i + '"'
        + ' ondragover="event.preventDefault();this.classList.add(&quot;drag-over&quot;)"'
        + ' ondragleave="this.classList.remove(&quot;drag-over&quot;)"'
        + ' ondrop="nmDrop(event,' + i + ')">'

        + '<div class="nine-man-slot-empty" style="flex:1;">— Drop player here —</div>'
        + '</div>';
    }
  }
  grid.innerHTML = html;
  // Update slider fills
  grid.querySelectorAll('.minutes-slider').forEach(el => {
    updateSliderFill(el, parseInt(el.value), 40);
  });
  nmUpdateTotal();
}

function nmDrop(event, slotIdx) {
  event.preventDefault();
  const slot = document.getElementById('nm-slot-' + slotIdx);
  if (slot) slot.classList.remove('drag-over');
  const pid = event.dataTransfer.getData('text/plain');
  if (!pid || !Object.hasOwn(PLAYERS, pid)) return;
  nmPlayers[slotIdx] = PLAYERS[pid];
  nmPlayers[slotIdx]._pid = pid;
  nmMins[slotIdx] = 20;
  nmRender();
  nmUpdateStats();
}

function nmRemove(slotIdx) {
  nmPlayers[slotIdx] = null;
  nmMins[slotIdx] = 20;
  nmRender();
  nmUpdateStats();
}

function nmUpdateMins(slotIdx, val, slider) {
  const proposed = parseInt(val);
  const totalOther = nmMins.reduce((s, m, i) => i === slotIdx ? s : s + m, 0);
  const capped = Math.min(proposed, Math.min(40, 200 - totalOther));
  nmMins[slotIdx] = capped;
  if (capped !== proposed) {
    slider.value = capped;
    slider.style.outline = '2px solid var(--red)';
    setTimeout(() => slider.style.outline = '', 600);
  }
  updateSliderFill(slider, capped, 40);
  const el = document.getElementById('nm-mins-' + slotIdx);
  if (el) el.textContent = capped;
  nmUpdateTotal();
  nmUpdateStats();
}

function nmUpdateTotal() {
  const total = nmMins.reduce((s, m, i) => nmPlayers[i] ? s + m : s, 0);
  const el = document.getElementById('nm-total-val');
  if (el) {
    el.textContent = total;
    el.style.color = total > 200 ? 'var(--red)' : total >= 180 ? 'var(--green)' : 'var(--gold)';
  }
}

function nmClear() {
  nmPlayers = Array(9).fill(null);
  nmMins    = Array(9).fill(20);
  nmRender();
  nmUpdateStats();
}

function nmLoadPreset(type) {
  nmClear();

  if (type === 'base') {
    // Full base rotation: 5 starters + bench players, all with their preset minutes
    const rotMap = Object.assign({}, ROTATION_BASE);
    const order = ['barno','dotson','chaikin','beath','suutela',
                   'johnson','beattie','burke','vance','vukicevic'];
    let slot = 0;
    order.forEach(pid => {
      if (slot >= 9 || !PLAYERS[pid]) return;
      // Get minutes: starters use their key directly, bench use bench_X_Y_min
      let mins = 0;
      if (rotMap[pid] !== undefined) {
        mins = rotMap[pid];
      } else {
        // Find in bench slots
        for (let si = 0; si < 5; si++) {
          for (let b = 0; b < 3; b++) {
            if (rotMap['bench_' + si + '_' + b + '_id'] === pid) {
              mins = rotMap['bench_' + si + '_' + b + '_min'] || 0;
            }
          }
        }
      }
      if (mins > 0) {
        nmPlayers[slot] = PLAYERS[pid];
        nmPlayers[slot]._pid = pid;
        nmMins[slot] = mins;
        slot++;
      }
    });
  }

  if (type === 'adding') {
    // 8 players with defined minutes, 1 empty slot with 25 min remaining
    // Total = 175 min assigned, 25 left open for 9th player
    const players8 = [
      { pid: 'barno',   mins: 25 },
      { pid: 'dotson',  mins: 25 },
      { pid: 'chaikin', mins: 25 },
      { pid: 'beath',   mins: 25 },
      { pid: 'suutela', mins: 25 },
      { pid: 'beattie', mins: 20 },
      { pid: 'vance',   mins: 20 },
      { pid: 'johnson', mins: 10 },
    ];
    players8.forEach((entry, i) => {
      if (PLAYERS[entry.pid]) {
        nmPlayers[i] = PLAYERS[entry.pid];
        nmPlayers[i]._pid = entry.pid;
        nmMins[i] = entry.mins;
      }
    });
    // Slot 8 stays empty, mins = 25 (reserved)
    nmMins[8] = 25;
  }

  nmRender();
  nmUpdateStats();

  // Highlight active preset button
  document.querySelectorAll('.nine-man-total-bar .preset-btn').forEach(btn => {
    btn.style.fontWeight = '';
  });
  const activeBtn = document.querySelector('.nine-man-total-bar .preset-btn[onclick*="' + type + '"]');
  if (activeBtn) activeBtn.style.fontWeight = '700';
}

function nmLoadFromLineup() {
  // Import current 5-man lineup + bench rotation into 9-man
  nmClear();
  const active = lineup.filter(Boolean);
  active.forEach((pid, i) => {
    if (i < 9 && PLAYERS[pid]) {
      nmPlayers[i] = PLAYERS[pid];
      nmPlayers[i]._pid = pid;
      nmMins[i] = benchMinutes[pid] !== undefined ? benchMinutes[pid] : 25;
    }
  });
  // Pull bench players from benchMinutes
  let slot = active.length;
  for (let si = 0; si < 5 && slot < 9; si++) {
    for (let b = 0; b < 3 && slot < 9; b++) {
      const bid = benchMinutes['bench_' + si + '_' + b + '_id'];
      const bm  = benchMinutes['bench_' + si + '_' + b + '_min'];
      if (bid && bm > 0 && PLAYERS[bid]) {
        // Avoid duplicates
        if (!nmPlayers.slice(0, slot).some(p => p && p._pid === bid)) {
          nmPlayers[slot] = PLAYERS[bid];
          nmPlayers[slot]._pid = bid;
          nmMins[slot] = bm;
          slot++;
        }
      }
    }
  }
  nmRender();
  nmUpdateStats();
}

function nmUpdateStats() {
  const filled = nmPlayers.map((p, i) => p ? { p, m: nmMins[i] } : null).filter(Boolean);
  const minMap = nineManMinuteMap();
  const forecast = rotationForecast(minMap);
  renderProjectionSource('nineman', forecast);
  if (!forecast.minutes) {
    renderLineupScore('nm-bpm', 'nineman-rapm');
    document.getElementById('nm-bpm-desc').textContent = 'Add players to calculate';
    ['nm-ortg','nm-drtg','nm-efg','nm-3pct','nm-3pr','nm-ftr',
     'nm-arate','nm-torate','nm-dreb','nm-oreb','nm-net',
     'nm-ortg-top'].forEach(id => {
      const el = document.getElementById(id);
      if (el) { el.textContent = '—'; el.className = 'rating-val c-muted'; }
    });
    for (const id of ['nm-ortg-range', 'nm-ortg-top-range']) {
      const range = document.getElementById(id);
      if (range) range.textContent = '';
    }
    renderHistoricalTier('nm-tier', null, filled.length, 0);
    const nmSumEl = document.getElementById('nm-minutes-summary');
    if (nmSumEl) nmSumEl.innerHTML = '';
    return;
  }

  const totalMins = filled.reduce((s, x) => s + x.m, 0) || 1;

  const { efg: projEFG, turnover: projTO, rebound: projOR, ftr: projFTR,
    three: proj3Pct, threeRate: proj3PR, defensiveRebound: projDReb } = forecast;
  const efg = projEFG ?? A_EFG;
  const turnover = projTO ?? A_TO;
  const offensiveRebound = projOR ?? A_OR;
  const freeThrowRate = projFTR ?? A_FTR;
  const totUSG = filled.reduce((sum, { p }) => sum + (p.usg || 18), 0) || 1;
  const _nmWOBPM = filled.reduce((s,x)=>s+effOBPMof(x.p)*(x.p.usg||18),0)/(totUSG||1);
  const _nmShoot = shooterCount(filled.map(x=>x.p), filled.map(x=>x.m));
  const projORtg = calcORtgV2(efg, turnover, offensiveRebound, freeThrowRate, _nmWOBPM, _nmShoot);
  const projORtgFloor = calcORtgV2(efg-1.5, turnover+1.5, offensiveRebound-2, freeThrowRate-3, _nmWOBPM, _nmShoot);
  const projORtgCeil = calcORtgV2(efg+1.5, turnover-1.5, offensiveRebound+2, freeThrowRate+3, _nmWOBPM, _nmShoot);

  // DRtg: minutes-weighted individual DRtg
  const projDRtg = Object.entries(minMap).reduce((s,[pid,m])=>s+(PLAYERS[pid]?.indDrtg||102.5)*(m/totalMins),0);

  const projARate = filled.reduce((s,x)=>s+(x.p.arate||0)*(x.p.usg||18),0)/totUSG;
  const projNet   = projORtg - projDRtg;

  function nmSet(id, val, suffix, green, gold, muted, invert) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!Number.isFinite(val)) {
      el.textContent = '—';
      el.className = 'rating-val c-muted';
      return;
    }
    el.textContent = val.toFixed(1) + (suffix||'');
    const good = invert
      ? (val<=green?'c-green':val<=gold?'c-gold':val<=muted?'c-muted':'c-red')
      : (val>=green?'c-green':val>=gold?'c-gold':val>=muted?'c-muted':'c-red');
    el.className = 'rating-val ' + good;
  }

  nmSet('nm-ortg',   projORtg,   '',  110, 107.5, 105);
  const rangeEl = document.getElementById('nm-ortg-range');
  if (rangeEl) rangeEl.textContent = projORtgFloor.toFixed(1) + '–' + projORtgCeil.toFixed(1);
  nmSet('nm-drtg',   projDRtg,   '',  102, 104.5, 107, true);
  nmSet('nm-efg',    projEFG,    '%',  54,  52,  50);
  nmSet('nm-3pct',   proj3Pct,   '%',  36,  33,  30);
  nmSet('nm-3pr',    proj3PR,    '%',  45,  35,  25);
  nmSet('nm-ftr',    projFTR,    '',   45,  32,  22);
  nmSet('nm-arate',  projARate,  '%',  20,  15,  10);
  nmSet('nm-torate', projTO,     '%',  15,  17,  19, true);
  nmSet('nm-dreb',   projDReb,   '%',  73,  68,  62);
  nmSet('nm-oreb',   projOR,     '%',  26,  22,  18);
  const netEl = document.getElementById('nm-net');
  if (netEl) {
    netEl.textContent = (projNet>=0?'+':'') + projNet.toFixed(1);
    netEl.className = 'rating-val ' + (projNet>=4?'c-green':projNet>=2?'c-gold':projNet>=0?'c-muted':'c-red');
  }
  nmRenderMinutesSummary(filled, totalMins);

  // ── BPM + TIER ─────────────────────────────────────────────
  const rotationBPM = 5 * filled.reduce((sum, { p, m }) => sum + getEffectiveBpm(p) * m, 0) / totalMins;
  const rotationScore = renderLineupScore('nm-bpm', 'nineman-rapm', rotationBPM, filled.map(({ p, m }) => [p, m]), 5, 'min');
  renderHistoricalTier('nm-tier', rotationScore, filled.length, totalMins);
  const bpmDesc = document.getElementById('nm-bpm-desc');
  if (bpmDesc) bpmDesc.textContent = `Minutes-weighted · ${totalMins} min assigned`;

  // Net Rtg in top row
  const ortgTopEl    = document.getElementById('nm-ortg-top');
  const ortgTopRange = document.getElementById('nm-ortg-top-range');
  if (ortgTopEl) {
    ortgTopEl.textContent = (projNet >= 0 ? '+' : '') + projNet.toFixed(1);
    ortgTopEl.className = 'rating-val ' + (projNet >= 5 ? 'c-green' : projNet >= 2 ? 'c-gold' : projNet >= 0 ? 'c-muted' : 'c-red');
    if (ortgTopRange) ortgTopRange.textContent = 'Off ' + projORtg.toFixed(1) + ' · Def ' + projDRtg.toFixed(1);
  }


}

function nmRenderMinutesSummary(filled, totalMins) {
  const el = document.getElementById('nm-minutes-summary');
  if (!el) return;
  if (!filled || filled.length === 0) { el.innerHTML = ''; return; }
  const sorted = [...filled].sort((a, b) => b.m - a.m);
  const rows = sorted.map(x => {
    const p = x.p;
    const pct  = Math.round((x.m / 200) * 100);
    const barW = Math.round((x.m / 40) * 100);
    const eff = getEffectiveBpm(p);
    const bpmColor = eff >= 2 ? 'var(--green)' : eff >= 0 ? 'var(--gold)' : eff >= -1.5 ? 'var(--muted)' : 'var(--red)';
    const lastName = p.name.split(' ').pop();
    const sign = eff >= 0 ? '+' : '';
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:8px;width:100%;padding:3px 0;border-bottom:1px solid var(--border)';
    row.innerHTML = [
      '<span style="width:80px;font-size:10px;font-weight:500;color:var(--text);flex-shrink:0">' + htmlEscape(lastName) + '</span>',
      '<span style="width:28px;font-size:9px;color:var(--muted);flex-shrink:0">' + htmlEscape(p.pos || '') + '</span>',
      '<span style="flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden;display:block">'
        + '<span style="display:block;height:100%;width:' + barW + '%;background:var(--gold);border-radius:3px"></span></span>',
      '<span style="width:40px;font-size:14px;font-family:var(--font-heading,sans-serif);text-align:right;flex-shrink:0">'
        + x.m + '<span style="font-size:8px;color:var(--muted)"> min</span></span>',
      '<span style="width:28px;font-size:8px;color:var(--muted);text-align:right;flex-shrink:0">' + pct + '%</span>',
      '<span style="width:42px;font-size:10px;text-align:right;flex-shrink:0;color:' + bpmColor + '">' + sign + eff.toFixed(1) + '</span>'
    ].join('');
    return row.outerHTML;
  });
  el.innerHTML = rows.join('');
}

// Allow drops on nm-slots from roster panel
document.addEventListener('dragstart', e => {
  const row = e.target.closest('.player-row');
  if (row) e.dataTransfer.setData('text/plain', row.dataset.id);
});


function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.tab-btn[onclick*="'${tab}'"]`).classList.add('active');
  document.getElementById('tab-' + tab).classList.add('active');
  document.getElementById('lineup-score-controls').hidden = tab !== 'standard' && tab !== 'nineman';
  if (tab === 'nineman') { nmRender(); nmUpdateStats(); }
  if (tab === 'season') { renderSeason(); renderGames(); }
  if (tab === 'portal') renderPortal();
}

function toFiniteNumber(value, fallback = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function htmlEscape(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function activeRotationPlayerIds() {
  const active = new Set(lineup.filter(Boolean));
  Object.values(benchMinutes || {}).forEach((value) => {
    if (typeof value === 'string' && value) active.add(value);
  });
  if (Array.isArray(nmPlayers)) {
    nmPlayers.forEach((player) => {
      if (player && player._pid) active.add(player._pid);
    });
  }
  return active;
}

function normalizeWatchlistCandidate(candidate) {
  if (typeof candidate?.lineupId !== 'string' || !/^watchlist_[\w-]+$/.test(candidate.lineupId)) return null;
  return {
    id: String(candidate.lineupId),
    sourceId: String(candidate.sourceId || candidate.lineupId),
    name: String(candidate.name || 'Unknown Player'),
    team: String(candidate.team || ''),
    conf: String(candidate.conf || ''),
    division: String(candidate.division || ''),
    num: candidate.num ?? '–',
    pos: String(candidate.pos || 'G/F'),
    yr: String(candidate.yr || ''),
    ht: String(candidate.ht || '—'),
    htIn: toFiniteNumber(candidate.htIn, 0),
    bpr: toFiniteNumber(candidate.bpr, 0),
    obpr: toFiniteNumber(candidate.obpr, 0),
    dbpr: toFiniteNumber(candidate.dbpr, 0),
    ts: toFiniteNumber(candidate.ts, 0),
    usg: toFiniteNumber(candidate.usg, 0),
    threeRate: toFiniteNumber(candidate.threeRate, 0),
    threePct: toFiniteNumber(candidate.threePct, 0),
    arate: toFiniteNumber(candidate.arate, 0),
    torate: toFiniteNumber(candidate.torate, 0),
    stl: toFiniteNumber(candidate.stl, 0),
    blk: toFiniteNumber(candidate.blk, 0),
    dreb: toFiniteNumber(candidate.dreb, 0),
    oreb: toFiniteNumber(candidate.oreb, 0),
    ftr: toFiniteNumber(candidate.ftr, 0),
    indDrtg: toFiniteNumber(candidate.indDrtg, 102.5),
    note: candidateNote(candidate),
    isWatchlistPotential: true,
  };
}

function applyWatchlistPotentials(candidates) {
  const nextCandidates = Array.isArray(candidates)
    ? candidates.map(normalizeWatchlistCandidate).filter(Boolean)
    : [];
  const nextIds = new Set(nextCandidates.map((candidate) => candidate.id));
  const protectedIds = activeRotationPlayerIds();

  Object.entries(PLAYERS).forEach(([id, player]) => {
    if (!player || !player.isWatchlistPotential) return;
    if (nextIds.has(id)) return;
    if (protectedIds.has(id)) {
      return;
    }
    delete PLAYERS[id];
  });

  WATCHLIST_POTENTIALS = nextCandidates;
  nextCandidates.forEach((candidate) => {
    if (PLAYERS[candidate.id]) {
      Object.assign(PLAYERS[candidate.id], candidate, { savedOnly: false });
    } else {
      PLAYERS[candidate.id] = candidate;
    }
  });

  renderRecruitingRows();
  renderLineup();
  nmUpdateStats();
}

function readWatchlistPotentialsFromStorage() {
  try {
    const raw = localStorage.getItem(WATCHLIST_STORAGE_KEY)
      ?? localStorage.getItem(OLD_WATCHLIST_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.warn('Unable to read watchlist lineup candidates', err);
    return [];
  }
}

function readWatchlistPotentialsFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get('watchlist');
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    return [];
  }
}

function readWatchlistPotentialsFromParent() {
  try {
    if (!window.parent || window.parent === window) return null;
    const node = window.parent.document.getElementById('watchlist-lineup-data');
    if (!node) return null;
    const raw = (node.textContent || '').trim();
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch (err) {
    return null;
  }
}

let lastParentWatchlistPayload = '';
function syncWatchlistPotentialsFromParent() {
  const candidates = readWatchlistPotentialsFromParent();
  if (!Array.isArray(candidates)) return;
  const nextKey = JSON.stringify(candidates);
  if (nextKey === lastParentWatchlistPayload) return;
  lastParentWatchlistPayload = nextKey;
  applyWatchlistPotentials(candidates);
}


let WATCHLIST_POTENTIALS = [];
let PORTAL_PLAYERS = [];
let portalStatus = 'Loading transfer portal…';
let selectedPortalId = null;

function candidateNote(player) {
  const school = player.team || player.priorSchool;
  const affiliation = [school, player.conf || player.fromConf, player.division].filter(Boolean).join(' · ');
  return '<strong>' + htmlEscape([player.name, affiliation].filter(Boolean).join(' — ')) + '</strong>';
}

function recruitingRow(player, source) {
  const id = player.id;
  const description = [player.ht, player.yr, player.pos, player.team, player.conf, player.division]
    .filter(Boolean).join(' · ');
  return `
    <div class="player-row" data-id="${id}" draggable="true" ondragstart="dragStart(event, '${id}')" ondragend="dragEnd(event)" onclick="openDrawer('${id}')">
      <div class="p-num">${htmlEscape(player.num ?? '–')}</div>
      <div class="drag-handle">⠿</div>
      <div class="p-info">
        <div class="p-name">${htmlEscape(player.name)}</div>
        <div class="p-sub">${htmlEscape(description)}</div>
      </div>
      <div>
        <div class="p-bpr"></div>
        <div class="p-ts"></div>
      </div>
      <button class="add-btn" id="btn-${id}" aria-label="${source}: toggle ${htmlEscape(player.name)} in lineup"
        onclick="event.stopPropagation(); addToNextSlot('${id}')">+</button>
    </div>`;
}

function renderRecruitingRows() {
  document.getElementById('watchlist-roster').innerHTML = WATCHLIST_POTENTIALS
    .map(player => recruitingRow(player, 'Watchlist')).join('')
    || '<div class="p-sub" style="padding:6px 16px;">Add players from the dashboard watchlist.</div>';
  const active = activeRotationPlayerIds();
  const featured = PORTAL_PLAYERS.filter(
    (player, index) => index < 6 || active.has(player.id) || player.id === selectedPortalId
  );
  document.getElementById('portal-roster').innerHTML = featured
    .map(player => recruitingRow(player, 'Transfer Portal')).join('')
    || '<div class="p-sub" style="padding:6px 16px;">' + htmlEscape(portalStatus || 'No transfer candidates available.') + '</div>';
}

async function loadTransferPortal() {
  try {
    const response = await fetch('ucsd_model_data.json');
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    PORTAL_PLAYERS = data.portal.filter(player => /^[\w-]+$/.test(player.id)).map(player => {
      const conf = player.fromConf || '';
      const bpr = toFiniteNumber(player.bpr);
      return {
        ...player,
        id: 'portal_candidate_' + player.id,
        team: player.priorSchool || '',
        conf,
        bpr,
        _portalPlayer: true,
        note: candidateNote(player) + '<br>' + htmlEscape(player.note || ''),
      };
    });
    for (const player of PORTAL_PLAYERS) {
      if (PLAYERS[player.id]) Object.assign(PLAYERS[player.id], player, { savedOnly: false });
      else PLAYERS[player.id] = player;
    }
    const confFilter = document.getElementById('portal-conf');
    const conferences = [...new Set(PORTAL_PLAYERS.map(player => player.conf).filter(Boolean))].sort();
    conferences.forEach(conf => confFilter.add(new Option(conf, conf)));
    portalStatus = '';
  } catch (error) {
    portalStatus = 'Transfer portal data is unavailable.';
    console.warn('Could not load transfer portal data', error);
  }
  renderRecruitingRows();
  renderLineup();
  renderPortal();
}

function portalAddToLineup(id) {
  if (!PLAYERS[id]) return;
  selectedPortalId = id;
  if (!lineup.includes(id)) {
    const openSlot = lineup.indexOf(null);
    if (openSlot !== -1) lineup[openSlot] = id;
  }
  renderRecruitingRows();
  renderLineup();
  switchTab('standard');
  document.getElementById('btn-' + id)?.focus();
}

function recruitSnapshots(ids) {
  return Object.fromEntries(
    [...new Set(ids)].filter(id => {
      const player = PLAYERS[id];
      return player && (player.isWatchlistPotential || player._portalPlayer);
    }).map(id => [id, { ...PLAYERS[id] }])
  );
}

function restoreRecruitingPlayers(recruits) {
  for (const [id, player] of Object.entries(recruits || {})) {
    if (!/^(watchlist_|portal_candidate_)[\w-]+$/.test(id) || !player || Object.hasOwn(PLAYERS, id)) continue;
    PLAYERS[id] = { ...player, id, savedOnly: true, note: candidateNote(player) };
  }
}

function resolveSavedPlayerId(id) {
  if (typeof id !== 'string' || !id) return null;
  if (Object.hasOwn(PLAYERS, id)) return id;
  // The old sidebar saved the source ID directly for some portal players.
  const portalId = 'portal_candidate_' + id;
  return Object.hasOwn(PLAYERS, portalId) ? portalId : null;
}

function showUnavailableSavedPlayers(ids) {
  const missing = [...new Set(ids.filter(id => typeof id === 'string' && id && !resolveSavedPlayerId(id)))];
  if (missing.length) alert('This saved rotation contains unavailable players: ' + missing.join(', ') + '. Their slots will be empty.');
}

function initRecruiting() {
  const fromUrl = readWatchlistPotentialsFromUrl();
  applyWatchlistPotentials(fromUrl.length ? fromUrl : readWatchlistPotentialsFromStorage());
  syncWatchlistPotentialsFromParent();
  window.addEventListener('message', event => {
    if (event.origin !== window.location.origin || event.source !== window.parent) return;
    if (event.data?.type === 'ucsd-watchlist-lineup-sync') applyWatchlistPotentials(event.data.payload);
  });
  window.addEventListener('storage', event => {
    if (event.key === WATCHLIST_STORAGE_KEY) {
      applyWatchlistPotentials(readWatchlistPotentialsFromParent() ?? readWatchlistPotentialsFromStorage());
    }
  });
  setInterval(syncWatchlistPotentialsFromParent, 1000);
  loadTransferPortal();
}


function renderPortal() {
  const search  = (document.getElementById('portal-search')?.value || '').toLowerCase();
  const conf    = document.getElementById('portal-conf')?.value || '';
  const yr      = document.getElementById('portal-yr')?.value || '';
  const sortKey = document.getElementById('portal-sort')?.value || 'bpm';
  const minBpm  = parseFloat(document.getElementById('portal-min-bpm')?.value ?? -99);

  const filtered = PORTAL_PLAYERS.filter(p => {
    if (conf && p.conf !== conf) return false;
    if (yr   && p.yr   !== yr)   return false;
    if (getEffectiveBpm(p) < minBpm) return false;
    if (search && !p.name.toLowerCase().includes(search) && !p.team.toLowerCase().includes(search)) return false;
    return true;
  });

  const sortValue = player => {
    let value = player[sortKey];
    if (sortKey === 'bpm') value = getEffectiveBpm(player);
    if (sortKey === 'rapm') value = lineupRapm(player);
    if (!Number.isFinite(value)) return -Infinity;
    return sortKey === 'indDrtg' ? -value : value;
  };
  filtered.sort((a, b) => (sortValue(b) - sortValue(a)) || a.name.localeCompare(b.name));

  const countEl = document.getElementById('portal-count');
  if (countEl) countEl.textContent = portalStatus || filtered.length + ' players';

  const list = document.getElementById('portal-list');
  if (!list) return;

  list.innerHTML = filtered.map(p => {
    const bpm = getEffectiveBpm(p);
    const bpmColor = bpm >= 3 ? 'var(--green)' : bpm >= 0 ? 'var(--gold)' : 'var(--muted)';
    const drtgColor = p.indDrtg <= 101 ? 'var(--green)' : p.indDrtg <= 104 ? 'var(--gold)' : 'var(--muted)';
    return '<div class="portal-row" draggable="true"'
      + ` data-id="${p.id}" ondragstart="dragStart(event, '${p.id}')" ondragend="dragEnd(event)">`

      + '<div class="portal-name">' + htmlEscape(p.name) + '</div>'
      + '<div class="portal-team">' + htmlEscape(p.team) + '<br><span style="color:var(--muted);font-size:8px;">' + htmlEscape(p.conf) + ' · ' + htmlEscape(p.yr) + ' · ' + htmlEscape(p.ht) + '</span></div>'
      + '<div style="width:70px;font-size:18px;color:' + bpmColor + ';text-align:right;flex-shrink:0">' + formatImpact(bpm) + '<div style="font-size:7px;color:var(--muted)">BPM</div></div>'
      + '<div style="width:52px;font-size:10px;color:var(--gold);text-align:right;flex-shrink:0;">' + formatImpact(lineupRapm(p)) + '<div style="font-size:7px;color:var(--muted);">RAPM</div></div>'
      + '<div style="width:48px;font-size:10px;text-align:right;flex-shrink:0;">' + p.ts.toFixed(1) + '%<div style="font-size:7px;color:var(--muted);">TS%</div></div>'
      + '<div style="width:48px;font-size:10px;text-align:right;flex-shrink:0;">' + p.threePct.toFixed(1) + '%<div style="font-size:7px;color:var(--muted);">3PT%</div></div>'
      + '<div style="width:48px;font-size:10px;color:' + drtgColor + ';text-align:right;flex-shrink:0;">' + p.indDrtg.toFixed(1) + '<div style="font-size:7px;color:var(--muted);">DRtg</div></div>'
      + `<button class="portal-add-btn" aria-label="Add ${htmlEscape(p.name)} to lineup" onclick="portalAddToLineup('${p.id}')">+</button>`
      + '</div>';
  }).join('') || (portalStatus ? '' : '<div class="p-sub">No players match these filters.</div>');
}

// ═══ SEASON TRACKER — blends 2026-27 production into the projection ═══
// PRIOR is a frozen snapshot of pre-season values. Live PLAYERS fields are
// recomputed as  blended = w*current + (1-w)*prior,  w = GP/(GP+k).
// k is per-stat: it is roughly the number of games at which that stat
// carries as much signal as the prior. Shooting stabilizes slowly, usage fast.
const PRIOR = JSON.parse(JSON.stringify(PLAYERS));
const ROSTER_IDS = new Map(Object.entries(PLAYERS).map(([id, player]) => [player, id]));
// 2025–26 daily-model backfill through 2026-04-06, matched by name and prior school.
// See ratings/README.md. Players without a verified season row are omitted.
const PRIOR_IMPACT = {
  beath:       { bpm: -0.105, rapm:  1.702 },
  beattie:     { bpm:  1.963, rapm:  1.078 },
  chaikin:     { bpm: -0.632, rapm: -0.157 },
  burke:       { bpm: -0.443, rapm:  0.677 },
  vance:       { bpm:  0.040, rapm:  0.532 },
  vukicevic:   { bpm: -0.701, rapm: -0.922 },
  pendleton:   { bpm: -2.039, rapm: -0.470 },
  dotson:      { bpm: -1.085, rapm: -0.859 },
  suutela:     { bpm: -1.996, rapm: -0.087 },
  barno:       { bpm: -2.261, rapm: -0.354 },
  eaglestaff:  { bpm:  2.246, rapm:  3.671 },
};
// Final rotation ratings for 2021–22 through 2025–26, grouped by league and season.
// Rows are [conference finish, BPM, RAPM]. WCC finishes and league sizes
// exclude Gonzaga. Both league counts include teams below 90% RAPM coverage.
// See ratings-analysis/rotation-tier-backtest.json for the team-level audit.
const HISTORICAL_ROTATIONS = {
  'big-west': [
    { teamCount: 10, ratings: [[1,-0.081315,3.496749],[2,1.816702,3.195671],[3,0.528666,2.146688],[4,3.771964,2.601573],[5,3.878288,6.138754],[6,-0.696814,2.593789],[7,-3.313873,0.05054],[8,-15.142244,-9.769734],[9,-7.947109,-4.932672],[9,-11.835739,-6.682119]] }, // 2021–22
    { teamCount: 11, ratings: [[1,5.901154,2.174543],[1,5.096422,5.17739],[3,1.427708,3.00106],[4,3.222661,2.169518],[5,3.159861,4.432486],[6,0.584919,0.275584],[7,-0.805899,0.458075],[9,-8.192367,-5.212676],[10,-13.271085,-9.840946],[11,-10.446883,-7.79313]] }, // 2022–23
    { teamCount: 11, ratings: [[1,10.113674,8.761006],[2,4.299371,4.430916],[3,-0.319113,2.177821],[4,0.021422,1.750914],[5,-0.077597,2.419556],[5,-4.324756,-1.045427],[7,-2.559266,-1.372395],[7,-4.259146,-2.21616],[9,-5.529986,-1.932541],[11,-16.33702,-11.546549]] }, // 2023–24
    { teamCount: 11, ratings: [[1,18.213988,16.906288],[2,11.355542,9.665129],[3,-0.42644,-0.637341],[3,3.761302,3.283554],[5,1.65131,0.397243],[6,-5.250232,-2.587123],[7,-1.572971,-1.374343],[9,-5.087779,-3.885812],[10,-13.086784,-10.028036],[11,-19.852315,-17.816039]] }, // 2024–25
    { teamCount: 11, ratings: [[1,4.66228,7.052589],[2,5.480726,6.277906],[3,-1.957954,-0.465089],[3,-2.144095,0.230913],[3,3.133031,3.2484],[6,-1.261485,0.076333],[6,1.849833,2.064492],[8,-4.508021,-1.127444],[9,-7.103483,-3.26991],[10,-9.023953,-6.342287],[11,-15.725966,-11.044888]] }, // 2025–26
  ],
  'wcc': [
    { teamCount: 9, ratings: [[1,17.522343,15.092989],[2,9.552983,7.843966],[3,16.028364,13.150477],[4,10.068506,6.693785],[5,-1.042052,1.080203],[6,-4.852043,-4.724969],[7,-10.701191,-8.953432],[8,-4.107914,-4.314644],[9,-9.983825,-9.244769]] }, // 2021–22
    { teamCount: 9, ratings: [[1,19.623564,9.646135],[2,7.019439,5.809741],[3,3.26666,-0.155034],[4,4.788726,1.137664],[4,8.518718,6.065579]] }, // 2022–23
    { teamCount: 8, ratings: [[1,20.253359,13.212206],[2,11.799951,9.099144],[3,5.648218,3.393506],[4,-6.190306,-8.262104],[5,-2.3742,-1.800413]] }, // 2023–24
    { teamCount: 10, ratings: [[1,19.179566,16.08924],[2,10.381659,7.515571],[3,14.310899,12.927013],[4,8.749447,6.577667],[5,3.05456,0.559681],[5,-1.568886,-0.775456],[7,-12.269676,-8.054752],[8,-10.128721,-9.421543],[10,-12.433851,-8.692728]] }, // 2024–25
    { teamCount: 11, ratings: [[1,19.967021,17.647974],[2,17.333427,13.293041],[3,-2.13561,-0.684608],[4,2.831613,1.984466],[4,3.849911,3.441618],[4,3.944126,2.673576],[7,1.296657,-0.60736],[8,-5.630352,-4.176364],[8,-0.301991,0.099808],[10,-6.709205,-4.97456],[11,-9.750565,-7.776546]] }, // 2025–26
  ],
};
const RATING_WEIGHTS = {
  'metric-weight': { key: 'ucsd_rating_metric_weight_2627', from: 'BPM', to: 'RAPM' },
  'season-weight': { key: 'ucsd_rating_season_weight_2627', from: '2025–26', to: '2026–27' },
};
const RATINGS_CSV = 'https://raw.githubusercontent.com/Siddhu-S/ncaa-player-dashboard/ratings-data/player-ratings.csv';
let ratingMetricWeight = 0;
let ratingSeasonWeight = 0.25;
let liveRatings = new Map();

function ratingNameKey(name) {
  const parts = name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().match(/[a-z0-9]+/g) || [];
  if (/^(jr|sr|ii|iii|iv|v)$/.test(parts.at(-1))) parts.pop();
  return parts.join('');
}

function ratingKey(name, team) {
  const school = team.toLowerCase().replace(/\bst\.?($|\s)/g, 'state$1').replace(/[^a-z0-9]/g, '');
  return (school === 'ucsd' ? 'ucsandiego' : school) + ':' + ratingNameKey(name);
}

function readLiveRatings(csv) {
  // Split on commas outside quoted fields; the publisher's player and school
  // names are single-line fields and may contain commas or escaped quotes.
  const rows = csv.replace(/^\uFEFF/, '').trim().split(/\r?\n/).map(line =>
    line.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/).map(value => value.replace(/^"|"$/g, '').replaceAll('""', '"'))
  );
  const cols = Object.fromEntries(rows.shift().map((name, i) => [name, i]));
  if (!['season', 'player_name', 'team', 'bpm', 'rapm', 'bpm_through_date', 'rapm_through_date']
    .every(col => Object.hasOwn(cols, col))) throw new Error('Invalid daily ratings CSV');

  const ratings = new Map(), cutoffs = { bpm: '', rapm: '' };
  for (const row of rows) {
    if (row[cols.season] !== '2027' || !row[cols.player_name] || !row[cols.team]) continue;
    const record = {};
    for (const metric of ['bpm', 'rapm']) {
      const value = row[cols[metric]]?.trim();
      if (!value || !Number.isFinite(Number(value))) continue;
      record[metric] = Number(value);
      const cutoff = row[cols[metric + '_through_date']];
      if (/^\d{4}-\d{2}-\d{2}$/.test(cutoff) && cutoff > cutoffs[metric]) cutoffs[metric] = cutoff;
    }
    const key = ratingKey(row[cols.player_name], row[cols.team]);
    // A normalized name must identify a single player at this school.
    ratings.set(key, ratings.has(key) ? null : record);
  }
  if (!Array.from(ratings.values()).some(row => Number.isFinite(row?.bpm) || Number.isFinite(row?.rapm))) {
    throw new Error('No 2026–27 ratings');
  }
  return { ratings, cutoffs };
}

function currentImpact(player) {
  // The roster's team field can still be their previous school.
  const team = ROSTER_IDS.has(player) ? 'UC San Diego' : player.team;
  return team ? liveRatings.get(ratingKey(player.name, team)) : null;
}

function blendImpact(prior, current) {
  if (!Number.isFinite(prior)) return Number.isFinite(current) ? current : null;
  if (!Number.isFinite(current)) return prior;
  return prior + (current - prior) * ratingSeasonWeight;
}

function lineupBpm(player) {
  const id = ROSTER_IDS.get(player);
  const base = PRIOR[id] ?? player;
  const prior = id ? PRIOR_IMPACT[id]?.bpm : player.bpr;
  const manual = SEASON[id]?.bpr;
  const current = Number.isFinite(manual) ? manual : currentImpact(player)?.bpm;
  return { value: blendImpact(prior, current) ?? base.bpr, current, prior };
}

function lineupRapm(player) {
  return blendImpact(PRIOR_IMPACT[ROSTER_IDS.get(player)]?.rapm, currentImpact(player)?.rapm);
}

function formatImpact(value, digits = 1) {
  return Number.isFinite(value) ? (value >= 0 ? '+' : '') + value.toFixed(digits) : '—';
}

function mixImpact(bpm, rapm) {
  if (ratingMetricWeight === 0) return bpm;
  if (ratingMetricWeight === 1) return rapm;
  if (!Number.isFinite(bpm) || !Number.isFinite(rapm)) return null;
  return (1 - ratingMetricWeight) * bpm + ratingMetricWeight * rapm;
}

function playerImpactScore(player) {
  return mixImpact(getEffectiveBpm(player), lineupRapm(player));
}

const HISTORICAL_TIER_RANK = {
  champion: () => 1,
  topThree: () => 3,
  topFour: () => 4,
  topHalf: teamCount => Math.ceil(teamCount / 2),
  aboveBottomQuarter: teamCount => teamCount - Math.ceil(teamCount / 4),
};

function seasonalTierCutoffs({ teamCount, ratings }) {
  const scoresByRank = new Map();
  for (const [rank, bpm, rapm] of ratings) {
    const record = scoresByRank.get(rank) ?? { sum: 0, count: 0 };
    record.sum += mixImpact(bpm, rapm);
    record.count++;
    scoresByRank.set(rank, record);
  }
  const places = [...scoresByRank.keys()].sort((a, b) => a - b);
  const averageAt = rank => {
    const { sum, count } = scoresByRank.get(rank);
    return sum / count;
  };
  const cutoffs = Object.values(HISTORICAL_TIER_RANK).map(rankFor => {
    const firstOutside = places.findIndex(place => place > rankFor(teamCount));
    // Tied teams share a rank. Use the nearest rated finish on each side.
    // If no team outside the boundary has a rating, use the inside edge.
    if (firstOutside < 0) return averageAt(places.at(-1));
    return (averageAt(places[firstOutside - 1]) + averageAt(places[firstOutside])) / 2;
  });

  // Ratings don't always follow standings order. If neighboring benchmarks
  // cross, average them for that season so a higher tier can't be easier.
  const blocks = [];
  for (const cutoff of cutoffs) {
    blocks.push({ sum: cutoff, count: 1 });
    while (blocks.length > 1) {
      const higher = blocks.at(-2), lower = blocks.at(-1);
      if (higher.sum / higher.count >= lower.sum / lower.count) break;
      higher.sum += lower.sum;
      higher.count += lower.count;
      blocks.pop();
    }
  }
  return blocks.flatMap(({ sum, count }) => Array(count).fill(sum / count));
}

function historicalTierCutoffs(groups) {
  const seasonCutoffs = HISTORICAL_ROTATIONS[forecastConference].map(seasonalTierCutoffs);
  const order = Object.keys(HISTORICAL_TIER_RANK);
  return groups.map(group => {
    const index = order.indexOf(group);
    return seasonCutoffs.reduce((sum, cutoffs) => sum + cutoffs[index], 0) / seasonCutoffs.length;
  });
}

function renderHistoricalTier(id, score, playerCount, minutes) {
  const tier = document.getElementById(id);
  const detail = document.getElementById(id + '-desc');
  const conference = forecastConference === 'wcc' ? 'WCC' : 'BIG WEST';
  const fiveMan = id === 'rating-tier';
  const bands = fiveMan ? [
    { label: `${conference} TITLE`, group: 'champion', color: 'var(--gold)' },
    { label: `TOP 4 ${conference}`, group: 'topFour', color: 'var(--green)' },
    { label: 'MID-PACK', group: 'topHalf', color: 'var(--blue-light)' },
    { label: 'LOWER HALF', group: 'aboveBottomQuarter', color: 'var(--yellow)' },
    { label: 'REBUILD', color: 'var(--muted)' },
  ] : [
    { label: 'ELITE', group: 'champion', color: 'var(--green)' },
    { label: `TOP 3 ${conference}`, group: 'topThree', color: 'var(--green)' },
    { label: `TOP 4 ${conference}`, group: 'topFour', color: 'var(--green)' },
    { label: 'TOP HALF', group: 'topHalf', color: 'var(--gold)' },
    { label: 'MID-TIER', group: 'aboveBottomQuarter', color: 'var(--muted)' },
    { label: 'REBUILDING', color: 'var(--red)' },
  ];
  const cutoffs = historicalTierCutoffs(bands.slice(0, -1).map(band => band.group))
    .map(cutoff => Number(cutoff.toFixed(1)));
  document.getElementById(id + '-cutoffs').textContent = cutoffs
    .map((cutoff, i) => `${bands[i].label} ${formatImpact(cutoff)}`).join(' · ');
  tier.textContent = '—';
  tier.style.color = 'var(--muted)';
  if (fiveMan && playerCount < 5) {
    detail.textContent = 'Need 5 players';
    return;
  }
  if (!fiveMan && minutes <= 0) {
    detail.textContent = 'Add players and assign minutes';
    return;
  }
  if (!Number.isFinite(score)) {
    detail.textContent = 'RAPM needed for all players in the score';
    return;
  }

  // Classify using the same precision shown for scores and cutoffs.
  const displayedScore = Number(score.toFixed(1));
  const index = cutoffs.findIndex(minimum => displayedScore >= minimum);
  const band = index < 0 ? bands[bands.length - 1] : bands[index];
  tier.textContent = band.label;
  tier.style.color = band.color;
  const description = minutes === 0 ? 'Starting five' : `${minutes} rotation min`;
  detail.textContent = `${description} · 2021–22 to 2025–26 standings benchmark`;
}

function renderLineupScore(scoreId, breakdownId, bpm = null, entries = [], scale = 1, unit = 'players') {
  let total = 0, covered = 0, sum = 0;
  for (const [player, weight] of entries) {
    if (!player || weight <= 0) continue;
    total += weight;
    const rapm = lineupRapm(player);
    if (!Number.isFinite(rapm)) continue;
    covered += weight;
    sum += weight * rapm;
  }
  const rapm = total && covered === total ? scale * sum / total : null;
  const coverage = total && covered < total ? ` · ${covered}/${total} ${unit} rated` : '';
  const score = mixImpact(bpm, rapm);
  const scoreEl = document.getElementById(scoreId);
  scoreEl.textContent = formatImpact(score);
  scoreEl.className = 'rating-val ' + (score === null || ratingMetricWeight > 0 ? 'c-muted' :
    score >= 10 ? 'c-green' : score >= 3 ? 'c-gold' : score >= -2 ? 'c-muted' : 'c-red');
  document.getElementById(breakdownId).textContent =
    `BPM ${formatImpact(bpm)} · RAPM ${formatImpact(rapm)}${coverage}`;
  return score;
}

function refreshImpactViews() {
  renderLineup();
  nmUpdateStats();
  const drawer = document.getElementById('drawer');
  if (drawer.classList.contains('open')) openDrawer(drawer.dataset.playerId);
}

function updateRatingWeight(slider, refresh = true) {
  const { key, from, to } = RATING_WEIGHTS[slider.id];
  const percent = Number(slider.value);
  if (slider.id === 'metric-weight') ratingMetricWeight = percent / 100;
  else ratingSeasonWeight = percent / 100;
  const mix = `${100 - percent}% ${from} · ${percent}% ${to}`;
  document.getElementById(slider.id + '-blend').textContent = mix;
  slider.setAttribute('aria-valuetext', mix);
  updateSliderFill(slider, percent, 100);
  if (refresh) {
    try { localStorage.setItem(key, slider.value); } catch {}
    refreshImpactViews();
  }
}

async function loadLiveRatings() {
  const status = document.getElementById('ratings-feed-status');
  try {
    const response = await fetch(window.frameElement?.dataset.ratingsCsv || RATINGS_CSV, {
      cache: 'no-cache',
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const { ratings, cutoffs } = readLiveRatings(await response.text());
    liveRatings = ratings;
    status.textContent = Object.entries(cutoffs).map(([metric, date]) =>
      `${metric.toUpperCase()} ${date ? 'through ' + date : 'cutoff unavailable'}`).join(' · ');
  } catch (error) {
    console.warn('Could not load daily lineup ratings', error);
    status.textContent = 'Daily ratings unavailable. Showing prior-season and manually entered values.';
    return;
  }
  refreshImpactViews();
  renderSeason();
  renderPortal();
}

const SEASON_KEY = 'ucsd_season_2627_v1';
const KSTAB = { ts:22, threePct:30, threeRate:8, usg:5, torate:10, arate:10,
                oreb:10, dreb:10, stl:10, blk:12, ftr:12,
                obpr:15, dbpr:15, indDrtg:14 };
const SEASON_FIELDS = ['bpr','obpr','dbpr','ts','usg','efg','threePct','threeRate',
                       'arate','torate','oreb','dreb','stl','blk','ftr'];
let SEASON = {};                                   // pid -> {gp, <field>:value}
let TEAM_SEASON = { gp:0, adjOE:null, adjDE:null, manualOE:null, manualDE:null };


// ═══ GAME LOG — derives season rate stats from box scores ═══
// GAMES is the source of truth for anything a box score can produce.
// SEASON (manual entry / Barttorvik paste) can override the daily BPM feed.
let GAMES = [];
const BOXF = ['min','fgm','fga','tpm','tpa','ftm','fta','orb','drb','ast','tov','stl','blk'];
const D1_AVG_DE = 104.0;   // rough national average adj defensive efficiency

function possOf(fga, fta, tov, orb){ return fga - orb + tov + 0.44*fta; }

function gameTeam(g){
  const t = {}; BOXF.forEach(k=>t[k]=0);
  Object.values(g.rows||{}).forEach(r=>BOXF.forEach(k=>t[k]+=(+r[k]||0)));
  t.pts = 2*t.fgm + t.tpm + t.ftm;
  return t;
}

// Accumulate every game, then convert season totals into the rate stats the model uses.
function deriveFromGames(){
  const out = {};
  if(!GAMES.length) return out;
  const acc = {};
  const tm = {min:0,fgm:0,fga:0,fta:0,tov:0,orb:0,drb:0,pts:0};
  const op = {fga:0,tpa:0,fta:0,orb:0,drb:0,tov:0,pts:0};
  let oppDeSum = 0, oppDeN = 0;

  GAMES.forEach(g=>{
    const t = gameTeam(g), o = g.opp||{};
    ['min','fgm','fga','fta','tov','orb','drb'].forEach(k=>tm[k]+=t[k]);
    tm.pts += t.pts;
    ['fga','tpa','fta','orb','drb','tov','pts'].forEach(k=>op[k]+=(+o[k]||0));
    if(+g.oppAdjDE){ oppDeSum += +g.oppAdjDE; oppDeN++; }

    Object.entries(g.rows||{}).forEach(([pid,r])=>{
      if(!acc[pid]){ acc[pid]={gp:0};
        BOXF.forEach(k=>acc[pid][k]=0);
        ['tmMin','tmFga','tmFta','tmTov','tmFgm','tmOrb','tmDrb','opOrb','opDrb','opFga','opTpa','opPoss']
          .forEach(k=>acc[pid][k]=0); }
      const a = acc[pid];
      if (!(+r.min > 0)) return;
      a.gp++;
      BOXF.forEach(k=>a[k]+=(+r[k]||0));
      // team/opponent context is accumulated only for games this player appeared in
      a.tmMin+=t.min; a.tmFga+=t.fga; a.tmFta+=t.fta; a.tmTov+=t.tov;
      a.tmFgm+=t.fgm; a.tmOrb+=t.orb; a.tmDrb+=t.drb;
      a.opOrb+=(+o.orb||0); a.opDrb+=(+o.drb||0); a.opFga+=(+o.fga||0); a.opTpa+=(+o.tpa||0);
      a.opPoss += possOf(+o.fga||0, +o.fta||0, +o.tov||0, +o.orb||0);
    });
  });

  Object.entries(acc).forEach(([pid,a])=>{
    if(!a.min) return;
    const d = {gp:a.gp}, tmPoss5 = (a.tmMin/5)||1;
    const tsDen = 2*(a.fga + 0.44*a.fta);
    if(tsDen>0) d.ts = 100*(2*a.fgm + a.tpm + a.ftm)/tsDen;
    if(a.fga>0){ d.efg = 100*(a.fgm + 0.5*a.tpm)/a.fga;
                 d.threeRate = a.tpa/a.fga;
                 d.ftr = 100*a.fta/a.fga; }
    if(a.tpa>0) d.threePct = 100*a.tpm/a.tpa;
    const used = a.fga + 0.44*a.fta + a.tov;
    if(used>0) d.torate = 100*a.tov/used;
    const tmUsed = a.tmFga + 0.44*a.tmFta + a.tmTov;
    if(tmUsed>0) d.usg = 100*(used*tmPoss5)/(a.min*tmUsed);
    const astDen = (a.min/tmPoss5)*a.tmFgm - a.fgm;
    if(astDen>0) d.arate = 100*a.ast/astDen;
    if((a.tmOrb+a.opDrb)>0) d.oreb = 100*(a.orb*tmPoss5)/(a.min*(a.tmOrb+a.opDrb));
    if((a.tmDrb+a.opOrb)>0) d.dreb = 100*(a.drb*tmPoss5)/(a.min*(a.tmDrb+a.opOrb));
    if(a.opPoss>0)          d.stl  = 100*(a.stl*tmPoss5)/(a.min*a.opPoss);
    const opTwoA = a.opFga - a.opTpa;
    if(opTwoA>0)            d.blk  = 100*(a.blk*tmPoss5)/(a.min*opTwoA);
    Object.keys(d).forEach(k=>{ if(k!=='gp') d[k]=+(+d[k]).toFixed(2); });
    out[pid] = d;
  });

  const tmPoss = possOf(tm.fga, tm.fta, tm.tov, tm.orb);
  const opPoss = possOf(op.fga, op.fta, op.tov, op.orb);
  const rawOE = tmPoss>0 ? +(100*tm.pts/tmPoss).toFixed(2) : null;
  const rawDE = opPoss>0 ? +(100*op.pts/opPoss).toFixed(2) : null;
  // Crude schedule adjustment, only when opponent AdjDE was supplied. Damped 0.5
  // because a full additive correction overstates it. This is NOT KenPom's method.
  let sosOE = null, sosDE = null;
  if(oppDeN === GAMES.length && oppDeN > 0 && rawOE !== null){
    const gap = D1_AVG_DE - (oppDeSum/oppDeN);
    sosOE = +(rawOE + gap*0.5).toFixed(2);
    if(rawDE !== null) sosDE = +(rawDE - gap*0.5).toFixed(2);
  }
  out._team = { gp: GAMES.length, rawOE, rawDE, sosOE, sosDE,
                oppDeCoverage: oppDeN + '/' + GAMES.length };
  return out;
}

// Derived stats first, manual entry layered on top (manual always wins).
function effSeason(pid){
  const d = (DERIVED && DERIVED[pid]) ? DERIVED[pid] : null;
  const m = SEASON[pid] || null;
  if(!d && !m) return null;
  const o = Object.assign({}, d||{}, {});
  if(m) Object.keys(m).forEach(k=>{ if(m[k]!==null && m[k]!==undefined && m[k]!=='') o[k]=m[k]; });
  return o;
}
let DERIVED = {};

function wOf(gp, k){ return (gp > 0) ? gp/(gp+k) : 0; }
function seasonGP(pid){ const e = effSeason(pid); return (e && e.gp) ? +e.gp : 0; }

// Mean blend weight across the stat set — what the UI reports as "% current"
function blendPct(pid){
  const gp = seasonGP(pid); if (!gp) return 0;
  const ks = ['ts','usg','torate','oreb','dreb','stl','blk'];
  return Math.round(100 * ks.reduce((s,k)=>s+wOf(gp,KSTAB[k]),0)/ks.length);
}

function applySeasonBlend(){
  Object.keys(PRIOR).forEach(pid => {
    const prior = PRIOR[pid], live = PLAYERS[pid], cur = effSeason(pid);
    if (!prior || !live) return;
    const gp = seasonGP(pid);

    // reset to prior, then blend in whatever current-season data exists
    SEASON_FIELDS.forEach(f => { if (prior[f] !== undefined) live[f] = prior[f]; });

    if (gp > 0 && cur){
      SEASON_FIELDS.forEach(f => {
        if (f === 'bpr') return; // The season slider blends BPM separately.
        const v = cur[f];
        if (v === undefined || v === null || v === '') return;
        const w = wOf(gp, KSTAB[f] !== undefined ? KSTAB[f] : 12);
        live[f] = +(w*(+v) + (1-w)*(prior[f] !== undefined ? prior[f] : +v)).toFixed(3);
      });
    }

    // indDrtg: recompute from blended inputs, then fade from the stored prior
    const modeled = 102.5 + ((live.stl||1.5)-1.5)*-2.389
                          + ((live.blk||0.8)-0.8)*-0.530
                          + ((live.dreb||13)-13.0)*-0.344;
    const wD = wOf(gp, KSTAB.indDrtg);
    live.indDrtg = +(wD*modeled + (1-wD)*(prior.indDrtg !== undefined ? prior.indDrtg : modeled)).toFixed(1);
  });

  // Team anchor moves toward this season's actual efficiency
  const tg = +TEAM_SEASON.gp || 0, wT = wOf(tg, 12);
  UCSD_ADJ_OE = (tg>0 && TEAM_SEASON.adjOE) ? +(wT*(+TEAM_SEASON.adjOE) + (1-wT)*PRIOR_ADJ_OE).toFixed(2) : PRIOR_ADJ_OE;
  UCSD_ADJ_DE = (tg>0 && TEAM_SEASON.adjDE) ? +(wT*(+TEAM_SEASON.adjDE) + (1-wT)*PRIOR_ADJ_DE).toFixed(2) : PRIOR_ADJ_DE;
}

async function seasonLoad(){
  try {
    const r = await window.storage.get(SEASON_KEY);
    if (r){ const o = JSON.parse(r.value);
      SEASON = o.players||{}; TEAM_SEASON = o.team||TEAM_SEASON; GAMES = o.games||[]; }
  } catch(e){}
  DERIVED = deriveFromGames();
  const _t = DERIVED._team;
  if(_t && _t.gp){
    TEAM_SEASON.gp = _t.gp;
    if(!TEAM_SEASON.manualOE) TEAM_SEASON.adjOE = (_t.sosOE !== null ? _t.sosOE : _t.rawOE);
    if(!TEAM_SEASON.manualDE) TEAM_SEASON.adjDE = (_t.sosDE !== null ? _t.sosDE : _t.rawDE);
  }
  applySeasonBlend();
}
async function seasonSave(){
  try { await window.storage.set(SEASON_KEY, JSON.stringify({players:SEASON, team:TEAM_SEASON, games:GAMES})); }
  catch(e){ console.warn('season save failed'); }
}
function seasonRecalc(){
  applySeasonBlend();
  // each refresh is isolated: a failure in one view must not stop the others
  [['renderSeason',renderSeason],
   ['renderLineup',  typeof renderLineup==='function'?renderLineup:null],
   ['nmUpdateStats', typeof nmUpdateStats==='function'?nmUpdateStats:null]]
  .forEach(([n,fn])=>{ if(fn){ try{ fn(); }catch(e){ console.warn('season refresh:',n,e.message); } } });
  syncSeasonTeamFields();
  seasonSave();
}
function seasonSet(pid, field, val){
  if (!SEASON[pid]) SEASON[pid] = {};
  SEASON[pid][field] = (val === '' ? null : +val);
  seasonRecalc();
}
async function seasonClear(){
  SEASON = {}; GAMES = []; DERIVED = {};
  TEAM_SEASON = {gp:0, adjOE:null, adjDE:null, manualOE:null, manualDE:null};
  seasonRecalc(); renderGames();
}

// Bulk paste: header row naming columns, then one row per player.
// Accepts tab or comma separated. Player name must be the first column.
function seasonPaste(){
  const txt = (document.getElementById('season-paste')||{}).value || '';
  const lines = txt.trim().split('\n').filter(l=>l.trim());
  if (lines.length < 2){ alert('Paste a header row plus at least one player row.'); return; }
  const split = l => l.split(/\t|,/).map(s=>s.trim());
  const ALIAS = { 'gp':'gp','g':'gp','games':'gp','bpm':'bpr','obpm':'obpr','dbpm':'dbpr',
    'ts':'ts','ts%':'ts','usg':'usg','usg%':'usg',
    'efg':'efg','efg%':'efg','3p%':'threePct','3pct':'threePct','3prate':'threeRate',
    'ast':'arate','arate':'arate','to':'torate','torate':'torate','tov%':'torate',
    'or':'oreb','oreb':'oreb','or%':'oreb','dr':'dreb','dreb':'dreb','dr%':'dreb',
    'stl':'stl','stl%':'stl','blk':'blk','blk%':'blk','ftr':'ftr' };
  const hdr = split(lines[0]).map(h=>h.toLowerCase().replace(/\s+/g,''));
  const names = {}; Object.keys(PRIOR).forEach(pid=>{
    names[PLAYERS[pid].name.toLowerCase()] = pid;
    names[PLAYERS[pid].name.split(' ').pop().toLowerCase()] = pid;
  });
  let ok=0, miss=[];
  lines.slice(1).forEach(l=>{
    const cells = split(l); const key = (cells[0]||'').toLowerCase();
    const pid = names[key];
    if (!pid){ if(cells[0]) miss.push(cells[0]); return; }
    if (!SEASON[pid]) SEASON[pid] = {};
    hdr.forEach((h,i)=>{
      const f = ALIAS[h]; if (!f || i===0) return;
      const v = parseFloat(cells[i]); if (!isNaN(v)) SEASON[pid][f] = v;
    });
    ok++;
  });
  seasonRecalc();
  alert(`Imported ${ok} player${ok===1?'':'s'}.` + (miss.length?`\nUnmatched: ${miss.join(', ')}`:''));
}

function renderSeason(){
  const el = document.getElementById('season-table'); if (!el) return;
  const ids = Object.keys(PRIOR);
  const F = [['gp','GP'],['bpr','BPM'],['ts','TS%'],['usg','USG'],
             ['threePct','3P%'],['torate','TOv%'],['oreb','OR%'],['dreb','DR%'],
             ['stl','STL%'],['blk','BLK%'],['ftr','FTR']];
  let h = '<table style="width:100%;border-collapse:collapse;font-size:10px;">';
  h += '<tr style="background:var(--card);color:var(--text);">'
     + '<th style="text-align:left;padding:5px 6px;font-size:8px;letter-spacing:.1em;">PLAYER</th>'
     + F.map(f=>`<th style="padding:5px 3px;font-size:8px;">${f[1]}</th>`).join('')
     + '<th style="padding:5px 6px;font-size:8px;">% CUR</th>'
     + '<th style="padding:5px 6px;font-size:8px;">BLENDED BPM</th>'
     + '<th style="padding:5px 6px;font-size:8px;">BLENDED RAPM</th></tr>';
  ids.forEach((pid,i)=>{
    const p = PLAYERS[pid], pr = PRIOR[pid], cur = effSeason(pid)||{};
    const bpm = lineupBpm(p);
    const pct = blendPct(pid);
    const col = pct>=70?'var(--green)':pct>=35?'var(--gold)':'var(--muted)';
    h += `<tr style="background:${i%2?'var(--surface)':'transparent'};border-bottom:1px solid var(--border);">`
       + `<td style="padding:3px 6px;white-space:nowrap;">${p.name}`
       + `<span style="color:var(--muted);font-size:8px;"> ${p.pos||''}</span></td>`;
    F.forEach(f=>{
      const v = (f[0]==='gp') ? (cur.gp??'') : (cur[f[0]]??'');
      const placeholder = f[0] === 'bpr' ? (bpm.current?.toFixed(2) ?? '') :
        f[0] === 'gp' ? '0' : (pr[f[0]] ?? '');
      h += `<td style="padding:2px;"><input value="${v}" placeholder="${placeholder}"`
         + ` onchange="seasonSet('${pid}','${f[0]}',this.value)"`
         + ` style="width:100%;min-width:38px;font-family:'DM Mono',monospace;font-size:10px;padding:3px 2px;`
         + `text-align:center;border:1px solid var(--border);border-radius:2px;background:var(--bg);color:var(--text);"></td>`;
    });
    h += `<td style="padding:3px 6px;text-align:right;color:${col};font-weight:600;">${pct}%</td>`
       + `<td style="padding:3px 6px;text-align:right;">${formatImpact(bpm.value, 2)}`
       + `<span style="color:var(--muted);font-size:8px;"> · 2025–26 ${formatImpact(bpm.prior, 2)}</span></td>`
       + `<td style="padding:3px 6px;text-align:right;">${formatImpact(lineupRapm(p), 2)}</td></tr>`;
  });
  h += '</table>';
  el.innerHTML = h;
  const te = document.getElementById('season-anchor');
  if (te) te.innerHTML = `Model anchor now <strong>${(+UCSD_ADJ_OE).toFixed(1)} AdjOE</strong> / `
    + `<strong>${(+UCSD_ADJ_DE).toFixed(1)} AdjDE</strong> `
    + `<span style="color:var(--muted);">(pre-season ${PRIOR_ADJ_OE} / ${PRIOR_ADJ_DE})</span>`;
}

// ── game entry / parsing ──────────────────────────────────────
function gamesRecalc(){
  DERIVED = deriveFromGames();
  const t = DERIVED._team;
  if(t && t.gp){
    TEAM_SEASON.gp = t.gp;
    // Use schedule-adjusted when every game has an opponent AdjDE, else raw.
    if(TEAM_SEASON.manualOE === null || TEAM_SEASON.manualOE === undefined || TEAM_SEASON.manualOE === '')
      TEAM_SEASON.adjOE = (t.sosOE !== null ? t.sosOE : t.rawOE);
    if(TEAM_SEASON.manualDE === null || TEAM_SEASON.manualDE === undefined || TEAM_SEASON.manualDE === '')
      TEAM_SEASON.adjDE = (t.sosDE !== null ? t.sosDE : t.rawDE);
  } else if(!TEAM_SEASON.manualOE){
    TEAM_SEASON.gp = 0; TEAM_SEASON.adjOE = null; TEAM_SEASON.adjDE = null;
  }
  seasonRecalc();
  renderGames();
}

// Accepts a header row then one row per player. Tab or comma separated.
// Handles combined "5-9" cells for FG / 3P / FT.
function parseBox(txt){
  const lines = txt.trim().split('\n').filter(l=>l.trim());
  if(lines.length < 2) return {rows:{}, unmatched:[], err:'Need a header row plus at least one player row.'};
  const split = l => l.split(/\t|,/).map(s=>s.trim());
  const H = {min:'min',mp:'min',fgm:'fgm',fga:'fga','3pm':'tpm','3pa':'tpa','3fg':'tp','3p':'tp',
    ftm:'ftm',fta:'fta',fg:'fg',ft:'ft',or:'orb','or%':'orb',oreb:'orb',dr:'drb',dreb:'drb',
    ast:'ast',a:'ast',to:'tov',tov:'tov',stl:'stl',s:'stl',blk:'blk',b:'blk'};
  const hdr = split(lines[0]).map(h=>h.toLowerCase().replace(/[\s.%]/g,''));
  const names = {};
  Object.keys(PRIOR).forEach(pid=>{
    names[PLAYERS[pid].name.toLowerCase()] = pid;
    names[PLAYERS[pid].name.split(' ').pop().toLowerCase()] = pid;
  });
  const rows = {}, unmatched = [];
  lines.slice(1).forEach(l=>{
    const c = split(l), key = (c[0]||'').toLowerCase().replace(/[#0-9]/g,'').trim();
    const pid = names[key] || names[(c[0]||'').toLowerCase()];
    if(!pid){ if(c[0] && !/^(total|team)/i.test(c[0])) unmatched.push(c[0]); return; }
    const r = {};
    hdr.forEach((h,i)=>{
      if(i===0) return;
      const f = H[h]; if(!f) return;
      const cell = c[i]; if(cell===undefined || cell==='') return;
      if(f==='fg'||f==='tp'||f==='ft'){           // combined "5-9"
        const m = String(cell).match(/(-?[\d.]+)\s*[-/]\s*(-?[\d.]+)/);
        if(m){ const pfx = f==='fg'?'fg':f==='tp'?'tp':'ft';
               r[pfx+'m']=+m[1]; r[pfx+'a']=+m[2]; }
        return;
      }
      const v = parseFloat(cell); if(!isNaN(v)) r[f]=v;
    });
    if(Object.keys(r).length) rows[pid] = r;
  });
  return {rows, unmatched, err:null};
}

function addGame(){
  const g = {
    id: 'g'+Date.now(),
    date: (document.getElementById('gm-date')||{}).value || '',
    opp:  {},
    oppName: (document.getElementById('gm-opp')||{}).value || 'Opponent',
    oppAdjDE: parseFloat((document.getElementById('gm-oppde')||{}).value) || null,
    rows: {}
  };
  ['fga','tpa','fta','orb','drb','tov','pts'].forEach(k=>{
    const el = document.getElementById('gm-o-'+k);
    g.opp[k] = el ? (parseFloat(el.value)||0) : 0;
  });
  const parsed = parseBox((document.getElementById('gm-box')||{}).value || '');
  if(parsed.err){ alert(parsed.err); return; }
  if(!Object.keys(parsed.rows).length){ alert('No player rows matched the roster.'); return; }
  if(!g.opp.fga){ alert('Opponent FGA is required — the possession-based rates (USG%, OReb%, STL%) cannot be computed without it.'); return; }
  g.rows = parsed.rows;
  GAMES.push(g);
  gamesRecalc();
  ['gm-date','gm-opp','gm-oppde','gm-box'].forEach(id=>{ const e=document.getElementById(id); if(e) e.value=''; });
  ['fga','tpa','fta','orb','drb','tov','pts'].forEach(k=>{ const e=document.getElementById('gm-o-'+k); if(e) e.value=''; });
  alert('Game added: '+Object.keys(parsed.rows).length+' players.' +
        (parsed.unmatched.length ? '\nUnmatched: '+parsed.unmatched.join(', ') : ''));
}

function deleteGame(id){
  GAMES = GAMES.filter(g=>g.id!==id);
  gamesRecalc();
}

function renderGames(){
  const el = document.getElementById('games-list'); if(!el) return;
  if(!GAMES.length){ el.innerHTML = '<div style="font-size:10px;color:var(--muted);font-style:italic;padding:6px 0;">No box scores logged yet.</div>'; return; }
  const t = DERIVED._team || {};
  let h = '<div style="font-size:9px;color:var(--muted);margin-bottom:6px;">'
        + '<strong>'+GAMES.length+' game'+(GAMES.length===1?'':'s')+'</strong> · raw OE '
        + (t.rawOE!==null?t.rawOE:'—') + ' / raw DE ' + (t.rawDE!==null?t.rawDE:'—');
  if(t.sosOE!==null && t.sosOE!==undefined)
    h += ' · <span style="color:var(--gold-dim);">sched-adj ' + t.sosOE + ' / ' + t.sosDE + '</span>';
  else
    h += ' · <span style="color:var(--muted);">opp AdjDE ' + (t.oppDeCoverage||'0/0') + ' — raw only</span>';
  h += '</div>';
  GAMES.forEach(g=>{
    const tt = gameTeam(g), o = g.opp||{};
    const res = tt.pts > (+o.pts||0) ? 'W' : 'L';
    const col = res==='W' ? 'var(--green)' : 'var(--red)';
    h += '<div style="display:flex;align-items:center;gap:9px;padding:4px 7px;border:1px solid var(--border);'
       + 'border-radius:3px;margin-bottom:3px;background:var(--surface);font-size:10px;">'
       + '<span style="color:'+col+';font-weight:600;width:12px;">'+res+'</span>'
       + '<span style="width:74px;color:var(--muted);">'+htmlEscape(g.date || '—')+'</span>'
       + '<span style="flex:1;">'+htmlEscape(g.oppName || 'Opponent')+'</span>'
       + '<span style="color:var(--muted);">'+tt.pts+'–'+(+o.pts||0)+'</span>'
       + '<span style="color:var(--muted);font-size:8px;">'+Object.keys(g.rows||{}).length+' plyrs</span>'
       + '<button onclick="deleteGame(\''+g.id+'\')" style="background:none;border:none;color:var(--muted);'
       + 'cursor:pointer;font-size:10px;padding:0 3px;">✕</button></div>';
  });
  el.innerHTML = h;
}

function syncSeasonTeamFields() {
  for (const [id, value] of [
    ['ts-gp', TEAM_SEASON.gp || ''],
    ['ts-oe', TEAM_SEASON.adjOE ?? ''],
    ['ts-de', TEAM_SEASON.adjDE ?? ''],
  ]) {
    document.getElementById(id).value = value;
  }
}

function teamSet(field, val){
  const v = (val===''?null:+val), t = DERIVED._team;
  if(field==='adjOE'){ TEAM_SEASON.manualOE = v;
    TEAM_SEASON.adjOE = (v===null && t) ? (t.sosOE!==null?t.sosOE:t.rawOE) : v; }
  else if(field==='adjDE'){ TEAM_SEASON.manualDE = v;
    TEAM_SEASON.adjDE = (v===null && t) ? (t.sosDE!==null?t.sosDE:t.rawDE) : v; }
  else TEAM_SEASON[field] = v;
  seasonRecalc();
}

let ratingsForecast = null;
let forecastConference = 'big-west';

function nineManMinuteMap() {
  const map = {};
  nmPlayers.forEach((player, index) => {
    if (!player) return;
    const id = player._pid || Object.keys(PLAYERS).find(id => PLAYERS[id] === player);
    if (id) map[id] = (map[id] || 0) + nmMins[index];
  });
  return map;
}

function initRatingsForecast() {
  try {
    ratingsForecast = JSON.parse(window.frameElement?.dataset.lineupForecast || 'null');
  } catch {
    ratingsForecast = null;
  }
  const selector = document.getElementById('lineup-conference');
  selector.addEventListener('click', event => {
    const button = event.target.closest('[data-conference]');
    if (!button || button.dataset.conference === forecastConference) return;
    forecastConference = button.dataset.conference;
    for (const control of selector.querySelectorAll('[data-conference]')) {
      control.setAttribute('aria-pressed', String(control.dataset.conference === forecastConference));
    }
    refreshImpactViews();
  });
  renderProjectionSource('nineman', rotationForecast({}));
}

function playerForecast(id) {
  // Aaron's player records can list their previous school. Match roster players
  // against UCSD in the snapshot, never against the previous school or a recruit.
  if (!Object.hasOwn(PRIOR, id)) return null;
  const name = PRIOR[id].name.normalize('NFKD').replace(/[^\x00-\x7F]/g, '').toLowerCase();
  const parts = name.match(/[a-z0-9]+/g) || [];
  if (/^(jr|sr|ii|iii|iv|v)$/.test(parts.at(-1))) parts.pop();
  const players = forecastConference === 'wcc' ? ratingsForecast?.wcc : ratingsForecast?.players;
  return players?.[parts.join('')] ?? null;
}

function rotationForecast(minuteMap) {
  let minutes = 0;
  let forecastMinutes = 0;
  let threes = 0;
  let threeMakes = 0;
  let fieldGoals = 0;
  let effectiveMakes = 0;
  let freeThrows = 0;
  let possessionsUsed = 0;
  let turnovers = 0;
  let offensiveRebounds = 0;
  let defensiveRebounds = 0;

  for (const [id, playerMinutes] of Object.entries(minuteMap)) {
    const player = PLAYERS[id];
    if (!player || playerMinutes <= 0) continue;
    const forecast = playerForecast(id);
    const useForecast = ['three', 'two', 'three_freq', 'two_freq', 'fta', 'usage', 'personal_tov', 'orb', 'drb']
      .every(stat => Number.isFinite(forecast?.[stat]));
    const usage = useForecast ? forecast.usage : (player.usg ?? 18) / 100;
    const turnover = useForecast ? forecast.personal_tov : (player.torate ?? 17) / 100;
    const accuracy = useForecast ? forecast.three : (player.threePct ?? 0) / 100;
    const foulRate = (player.ftr ?? 28) / 100;
    // Estimate fallback shot volume from used possessions, turnovers and free throws.
    const fga = useForecast ? forecast.three_freq + forecast.two_freq :
      usage * (1 - turnover) / (1 + 0.44 * foulRate);
    const threeAttempts = useForecast ? forecast.three_freq : fga * (player.threeRate ?? 0);
    const madeThrees = threeAttempts * accuracy;
    const efgMakes = useForecast ? forecast.two_freq * forecast.two + 1.5 * madeThrees :
      fga * adjTSof(player) * 0.00935;

    minutes += playerMinutes;
    if (useForecast) forecastMinutes += playerMinutes;
    threes += threeAttempts * playerMinutes;
    threeMakes += madeThrees * playerMinutes;
    fieldGoals += fga * playerMinutes;
    effectiveMakes += efgMakes * playerMinutes;
    freeThrows += (useForecast ? forecast.fta : fga * foulRate) * playerMinutes;
    possessionsUsed += usage * playerMinutes;
    turnovers += usage * turnover * playerMinutes;
    offensiveRebounds += (useForecast ? forecast.orb : (player.oreb ?? 0) / 100) * playerMinutes;
    defensiveRebounds += (useForecast ? forecast.drb : (player.dreb ?? 0) / 100) * playerMinutes;
  }

  const percent = (numerator, denominator) => denominator > 0 ? 100 * numerator / denominator : null;
  return {
    minutes, forecastMinutes,
    three: percent(threeMakes, threes),
    threeRate: percent(threes, fieldGoals),
    efg: percent(effectiveMakes, fieldGoals),
    ftr: percent(freeThrows, fieldGoals),
    turnover: percent(turnovers, possessionsUsed),
    // Scale the minutes-weighted rebound shares to five players on court.
    rebound: percent(5 * offensiveRebounds, minutes),
    defensiveRebound: percent(5 * defensiveRebounds, minutes),
  };
}

function renderProjectionSource(view, { minutes, forecastMinutes }) {
  const status = document.getElementById(view + '-projection-source');
  if (!minutes) {
    status.textContent = 'Assign minutes to see projected stats.';
    return;
  }
  const context = forecastConference === 'wcc' ? 'WCC scenario' : 'Big West';
  const fallback = minutes - forecastMinutes;
  const parts = [context];
  if (forecastMinutes) parts.push(`Ratings for ${forecastMinutes} of ${minutes} min · Games through ${ratingsForecast.through}`);
  if (fallback) parts.push(`Aaron’s Big West inputs for ${fallback} min`);
  parts.push('Team efficiency uses Aaron’s model');
  status.textContent = parts.join(' · ');
}

function renderPlayerForecast(id) {
  const target = document.getElementById('drawer-ratings-forecast');
  target.replaceChildren();
  const forecast = playerForecast(id);
  if (!ratingsForecast) return;
  const details = document.createElement('details');
  details.className = 'ratings-forecast';
  const summary = document.createElement('summary');
  summary.textContent = forecastConference === 'wcc' ? 'Ratings forecast · WCC scenario' : 'Ratings forecast · 2026–27 Big West';
  details.append(summary);
  const note = document.createElement('p');
  note.className = 'ratings-forecast-meta';
  const fallbackSource = forecastConference === 'wcc' ? 'Aaron’s Big West inputs' : 'Aaron’s inputs';
  note.textContent = forecast ? 'Games through ' + ratingsForecast.through : `Rotation uses ${fallbackSource} for this player.`;
  details.append(note);
  if (forecast) {
    const grid = document.createElement('div');
    grid.className = 'drawer-stats';
    for (const {key, label, unit} of ratingsForecast.stats) {
      const value = forecast[key];
      if (!Number.isFinite(value)) continue;
      const cell = document.createElement('div');
      cell.className = 'ds-cell';
      const heading = document.createElement('div');
      heading.className = 'ds-label';
      heading.textContent = label;
      const stat = document.createElement('div');
      stat.className = 'ds-val';
      stat.textContent = unit === 'ratio' ? value.toFixed(3) :
        unit === 'percent' ? (100 * value).toFixed(1) + '%' : (100 * value).toFixed(2);
      cell.append(heading, stat);
      grid.append(cell);
    }
    details.append(grid);
  }
  target.append(details);
}

async function initApp() {
  initRatingsForecast();
  for (const [id, { key }] of Object.entries(RATING_WEIGHTS)) {
    const slider = document.getElementById(id);
    try {
      const saved = localStorage.getItem(key);
      if (saved !== null && /^\d{1,3}$/.test(saved) && Number(saved) <= 100) slider.value = saved;
    } catch {}
    updateRatingWeight(slider, false);
  }
  await seasonLoad();
  initProjectedStatsCard();
  loadPreset('base');
  renderSeason();
  renderGames();
  syncSeasonTeamFields();
  initSliderFills();
  loadLiveRatings();
  await initSavedLineups();
  initRecruiting();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp, { once: true });
} else {
  initApp();
}

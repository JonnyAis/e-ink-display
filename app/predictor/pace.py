# app/predictor/pace.py
import os, sqlite3, time, math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

CACHE_DIR = os.path.expanduser("~/.cache/transit-display")
DB_PATH   = os.path.join(CACHE_DIR, "predictor.db")

# Defaults if we have no data yet (tweak to taste)
SEC_PER_STOP_DEFAULT = 55.0     # median seconds to traverse one stop spacing
DWELL_DEFAULT_S      = 12.0     # dwell per stop, folded into short-stop cases
AVG_STOP_SPACING_M   = 300.0    # urban stop spacing (meters)
SPEED_DEFAULT_MPS    = 5.0      # ~11 mph
EMA_ALPHA            = 0.20     # smoothing factor
# Confidence blending
API_W_MIN, API_W_MAX = 0.25, 0.85  # floor/ceiling for API trust

def _ensure_db():
    os.makedirs(CACHE_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
    CREATE TABLE IF NOT EXISTS pace_stats (
      route_id TEXT,
      direction_id INTEGER,
      tod_bin INTEGER,
      dow INTEGER,
      ema_sec_per_stop REAL,
      ema_dwell_s REAL,
      ema_speed_mps REAL,
      avg_stop_spacing_m REAL,
      n INTEGER,
      PRIMARY KEY (route_id, direction_id, tod_bin, dow)
    )
    """)
    con.commit()
    return con

def _tod_bin(dt: datetime) -> int:
    # 5 bins that behave differently in most cities
    h = dt.hour
    if 6 <= h <= 9:   return 1   # AM peak
    if 10 <= h <= 15: return 2   # midday
    if 16 <= h <= 19: return 3   # PM peak
    if 20 <= h <= 23: return 4   # evening
    return 0                     # night/early

@dataclass(frozen=True)
class Key:
    route_id: str
    direction_id: int
    tod_bin: int
    dow: int  # Monday=0

class PaceDB:
    def __init__(self, path=DB_PATH):
        self.con = _ensure_db()

    def get(self, k: Key):
        cur = self.con.execute(
            "SELECT ema_sec_per_stop, ema_dwell_s, ema_speed_mps, avg_stop_spacing_m, n "
            "FROM pace_stats WHERE route_id=? AND direction_id=? AND tod_bin=? AND dow=?",
            (k.route_id, k.direction_id, k.tod_bin, k.dow),
        )
        row = cur.fetchone()
        if not row:
            return (SEC_PER_STOP_DEFAULT, DWELL_DEFAULT_S, SPEED_DEFAULT_MPS, AVG_STOP_SPACING_M, 0)
        return row

    def update(self, k: Key, obs_sec_per_stop: Optional[float]=None,
               obs_dwell_s: Optional[float]=None, obs_speed_mps: Optional[float]=None,
               obs_stop_spacing_m: Optional[float]=None):
        cur = self.con.execute(
            "SELECT ema_sec_per_stop, ema_dwell_s, ema_speed_mps, avg_stop_spacing_m, n "
            "FROM pace_stats WHERE route_id=? AND direction_id=? AND tod_bin=? AND dow=?",
            (k.route_id, k.direction_id, k.tod_bin, k.dow),
        )
        row = cur.fetchone()
        if not row:
            ema_sp, ema_dw, ema_v, ema_spacing, n = \
                SEC_PER_STOP_DEFAULT, DWELL_DEFAULT_S, SPEED_DEFAULT_MPS, AVG_STOP_SPACING_M, 0
        else:
            ema_sp, ema_dw, ema_v, ema_spacing, n = row

        a = EMA_ALPHA
        if obs_sec_per_stop and math.isfinite(obs_sec_per_stop):
            ema_sp = a*obs_sec_per_stop + (1-a)*ema_sp
        if obs_dwell_s and math.isfinite(obs_dwell_s):
            ema_dw = a*obs_dwell_s + (1-a)*ema_dw
        if obs_speed_mps and math.isfinite(obs_speed_mps):
            ema_v  = a*obs_speed_mps + (1-a)*ema_v
        if obs_stop_spacing_m and math.isfinite(obs_stop_spacing_m):
            ema_spacing = a*obs_stop_spacing_m + (1-a)*ema_spacing

        n = min(n + 1, 10_000_000)

        self.con.execute("""
            INSERT INTO pace_stats(route_id, direction_id, tod_bin, dow,
              ema_sec_per_stop, ema_dwell_s, ema_speed_mps, avg_stop_spacing_m, n)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(route_id, direction_id, tod_bin, dow)
            DO UPDATE SET
              ema_sec_per_stop=excluded.ema_sec_per_stop,
              ema_dwell_s=excluded.ema_dwell_s,
              ema_speed_mps=excluded.ema_speed_mps,
              avg_stop_spacing_m=excluded.avg_stop_spacing_m,
              n=excluded.n
        """, (k.route_id, k.direction_id, k.tod_bin, k.dow, ema_sp, ema_dw, ema_v, ema_spacing, n))
        self.con.commit()

class DeterministicPredictor:
    """
    Stateless per-call math + stateful learning (DB).
    You hold an instance at app start and reuse it.
    """
    def __init__(self):
        self.db = PaceDB()
        # Track last observation per vehicle (or trip) to learn from deltas.
        self._last_seen: Dict[str, Tuple[datetime,int]] = {}  # vehicle_key -> (t, stopsAway)
        # Safety: track last cleanup to prevent unbounded memory growth
        self._last_cleanup = datetime.now()

    @staticmethod
    def _vehicle_key(item: dict) -> str:
        # Prefer vehicleId; fallback to tripId; last resort: route+headsign
        return (
            item.get("vehicleId")
            or item.get("tripId")
            or f"{item.get('routeId','?')}|{item.get('directionId',-1)}|{item.get('headsign','')}"
        )

    @staticmethod
    def _key_for_item(item: dict, now: datetime) -> Key:
        rid = item.get("routeId") or item.get("route") or "?"
        did = int(item.get("directionId") or 0)
        return Key(rid, did, _tod_bin(now), now.weekday())

    def _api_eta_min(self, item: dict, now: datetime) -> Optional[float]:
        arr = item.get("arrive_dt")
        if not isinstance(arr, datetime): return None
        return max(0.0, (arr - now).total_seconds()/60.0)

    def _pace_eta_min(self, item: dict, now: datetime) -> float:
        k = self._key_for_item(item, now)
        ema_sp, ema_dw, ema_v, spacing_m, _ = self.db.get(k)
        S = item.get("stops", item.get("numberOfStopsAway"))
        try:
            S = int(S)
        except Exception:
            S = None
        if S is None:
            # fallback: single-stop traversal time
            return (ema_sp + ema_dw)/60.0
        # seconds = S * (sec/stop + dwell)
        return max(0.0, S * (ema_sp + ema_dw) / 60.0)

    def _kin_eta_min(self, item: dict, now: datetime) -> Optional[float]:
        k = self._key_for_item(item, now)
        ema_sp, ema_dw, ema_v, spacing_m, _ = self.db.get(k)

        # Prefer explicit distanceFromStop if available
        dist_m = item.get("distanceFromStop")
        S = item.get("stops", item.get("numberOfStopsAway"))
        try: S = int(S)
        except: S = None

        if dist_m is None and S is not None:
            dist_m = max(0.0, S * spacing_m)

        v = max(1.0, float(ema_v))  # m/s, floor to avoid div by zero

        if dist_m is None:
            return None

        travel = dist_m / v
        dwell  = (S or 0) * ema_dw
        return max(0.0, (travel + dwell) / 60.0)

    def fused_eta_minutes(self, item: dict, now: datetime) -> float:
        """Blend API eta with pace/kinematic depending on stops-away."""
        eta_api = self._api_eta_min(item, now)
        eta_pace = self._pace_eta_min(item, now)
        eta_kin  = self._kin_eta_min(item, now)

        # Choose alt source
        S = item.get("stops", item.get("numberOfStopsAway"))
        try: S = int(S)
        except: S = None

        if eta_kin is not None and S is not None and S <= 2:
            eta_alt = eta_kin  # close range: trust kinematics more
        else:
            eta_alt = eta_pace

        if eta_api is None:
            return eta_alt

        # Weight API by distance; farther = more API
        if S is None:
            w_api = 0.6
        else:
            w_api = min(API_W_MAX, max(API_W_MIN, S/6.0))

        eta = w_api * eta_api + (1.0 - w_api) * eta_alt
        return max(0.0, eta)

    def _cleanup_stale_vehicles(self, now: datetime, max_age_hours: float = 4.0):
        """Remove vehicles not seen for max_age_hours to prevent memory bloat."""
        cutoff = now - timedelta(hours=max_age_hours)
        stale_keys = [k for k, (last_t, _) in self._last_seen.items() if last_t < cutoff]
        for k in stale_keys:
            del self._last_seen[k]
        if stale_keys:
            print(f"Cleaned up {len(stale_keys)} stale vehicle entries")

    # ---- Learning from movement between polls ----
    def observe(self, prev_items: List[dict], curr_items: List[dict], now: datetime):
        """
        Called after each poll. Tracks buses by vehicle key; when S decreases,
        we update:
          - sec_per_stop from delta_t / delta_stops
          - speed from (delta_dist / delta_t) if we have distance
          - avg spacing from (delta_dist / delta_stops)
        When a bus disappears around S<=0, assume it just served this stop.
        """
        # Periodic cleanup to prevent memory bloat (every hour)
        if (now - self._last_cleanup).total_seconds() > 3600:
            self._cleanup_stale_vehicles(now)
            self._last_cleanup = now
            # Also cap the dict size as a safety net
            if len(self._last_seen) > 200:  # Way more than needed for 2 stops
                # Keep only the 100 most recent entries
                sorted_items = sorted(self._last_seen.items(), key=lambda x: x[1][0], reverse=True)
                self._last_seen = dict(sorted_items[:100])
                print(f"Capped vehicle tracking to 100 most recent entries")
        # Index current by vehicle key
        cur_by_key = {}
        for it in curr_items:
            key = self._vehicle_key(it)
            cur_by_key[key] = it

        # Walk last-seen dict and update stats
        for key, (t_prev, S_prev) in list(self._last_seen.items()):
            it = cur_by_key.get(key)
            if it is None:
                # Bus vanished. If it was at or near our stop, count as served; else drop.
                # (We don't need a DB update on vanish unless you want dwell-at-our-stop.)
                del self._last_seen[key]
                continue

            # We have a new observation => learn from delta
            try:
                S_curr = int(it.get("stops", it.get("numberOfStopsAway")))
            except:
                continue

            dt = (now - t_prev).total_seconds()
            if dt <= 0:  # clock skew / duplicate poll
                self._last_seen[key] = (now, S_curr)
                continue

            dS = (S_prev - S_curr)  # stops traversed towards us
            if dS > 0:
                k = self._key_for_item(it, now)
                # seconds per stop from this interval
                sec_per_stop = dt / dS

                # distance-based updates if present/estimable
                dist_prev = None
                dist_curr = it.get("distanceFromStop")
                # We don't store per-vehicle previous distance; approximate with spacing * dS
                # to update average spacing and speed.
                obs_spacing = None
                obs_speed   = None
                try:
                    # spacing: if we trust "distanceFromStop" deltas, compute. If not, approximate.
                    approx_dist = max(0.0, dS * AVG_STOP_SPACING_M)
                    obs_speed = approx_dist / dt
                    obs_spacing = approx_dist / dS
                except:
                    pass

                self.db.update(k,
                    obs_sec_per_stop=sec_per_stop,
                    obs_dwell_s=None,                # hard to isolate; leave to default EMA
                    obs_speed_mps=obs_speed,
                    obs_stop_spacing_m=obs_spacing
                )

            # Update last seen for this vehicle
            self._last_seen[key] = (now, S_curr)

        # Insert/update current vehicles that were not tracked yet
        for it in curr_items:
            key = self._vehicle_key(it)
            if key not in self._last_seen:
                try:
                    S0 = int(it.get("stops", it.get("numberOfStopsAway")))
                except:
                    S0 = 0
                self._last_seen[key] = (now, S0)

    # ---- Public surface -------------------------------------------------------
    def enhance(self, arrivals: List[dict], now: datetime) -> List[dict]:
        out = []
        for it in arrivals:
            eta_min = self.fused_eta_minutes(it, now)
            it2 = dict(it)
            it2["arrive_dt"] = now + timedelta(minutes=eta_min)
            it2["eta_fused_min"] = eta_min
            out.append(it2)
        return out

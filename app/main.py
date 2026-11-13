# ~/transit-display/app/main.py
import os, time, math, random, logging, requests, json
from datetime import datetime, timedelta
from requests import HTTPError
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops, ImageFilter
from IT8951.display import AutoEPDDisplay
from IT8951 import constants
from app.predictor.pace import DeterministicPredictor
from app import rotation as sports_rotation
from app import greetings as greeting_mod

# ========= ORIENTATION & SPEED =========
FLIP_X = False
FLIP_Y = False
SPI_HZ = 24_000_000

# ========= SAFE AREA / LAYOUT (unchanged) =========
SAFE_RIGHT = 24
NAV_H      = 200
PAD        = 28
COL_GAP    = 28
CLOCK_W    = 460
CLOCK_H    = 72

LOGO_VPAD     = 20
TIME_PAD_X    = 10
NAV_DATE_GAP  = 12
DATE_LINE_GAP = 4
DATE_RESERVE_W= 300
BADGE_W       = 220
BADGE_H       = 40

# Clean nav bar without separators

# Your stops and column titles come from config.toml ([bus] stops / titles), never from this file.
from app import config as _config
_STOPS  = list(_config.get("bus.stops", []) or [])
_TITLES = list(_config.get("bus.titles", []) or []) + ["Next Bus", "Next Bus"]
TITLE_LEFT, TITLE_RIGHT = _TITLES[0], _TITLES[1]

# ========= DATA CADENCE (unchanged intent) =========
if len(_STOPS) < 2:
    raise SystemExit("Set two OneBusAway stop IDs in config.toml: [bus] stops = [\"1_xxxxx\", \"1_yyyyy\"]")
LEFT_STOP, RIGHT_STOP = _STOPS[0], _STOPS[1]
POLL_BASE_SECS   = 30
POLL_MAX_SECS    = 600
CLOCK_TICK_SECS  = 1
GLOBAL_GC16_EVERY_SECS = 1800  # full scrub every 30 min

# --- Arrival/departure hysteresis (seconds) ---
ARRIVE_CONFIRM_POLLS   = 2     # need 2 consecutive polls before we claim "at_stop"
ARRIVE_ETA_SEC         = 15    # or show at_stop if ETA <= 15s
ARRIVE_DIST_M          = 35    # require <=35m if distanceFromStop available

DEPART_GRACE_SEC       = 20    # after ETA<0, wait this before "departed"
DEPART_VANISH_SEC      = 15    # if vehicle disappears after AT_STOP, mark departed after this
STALE_FORGET_SEC       = 180   # GC old vehicles from the FSM

# ========= PATHS =========
ROOT    = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ASSETS  = os.path.join(ROOT, "assets")
FONTS   = os.path.join(ASSETS, "fonts")
IMAGES  = os.path.join(ASSETS, "images")
PNG_LOGO= os.path.join(IMAGES, "king_county_metro.png")
SVG_LOGO= os.path.join(IMAGES, "king_county_metro2.svg")
ENV_PATH= os.path.join(ROOT, ".env")
LOG_DIR = os.path.expanduser("~/transit-display/logs")
CACHE_DIR = os.path.expanduser("~/.cache/transit-display")

# ========= LOGGING =========
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# Rotate log file if it gets too large (>10MB)
log_file = os.path.join(LOG_DIR, "run.log")
if os.path.exists(log_file) and os.path.getsize(log_file) > 10 * 1024 * 1024:
    backup_log = os.path.join(LOG_DIR, "run.log.old")
    if os.path.exists(backup_log):
        os.remove(backup_log)
    os.rename(log_file, backup_log)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
)

# ========= WARM START CACHE =========
def save_cache_data(left_data, right_data):
    """Save last good arrivals data to avoid blank screens on restart."""
    try:
        cache_data = {
            'timestamp': time.time(),
            'left': [{'route': it.get('route', ''), 
                     'headsign': it.get('headsign', ''),
                     'arrive_time': it['arrive_dt'].isoformat() if 'arrive_dt' in it else '',
                     'stops': it.get('stops'),
                     'pred': it.get('pred', False)} for it in left_data],
            'right': [{'route': it.get('route', ''), 
                      'headsign': it.get('headsign', ''),
                      'arrive_time': it['arrive_dt'].isoformat() if 'arrive_dt' in it else '',
                      'stops': it.get('stops'),
                      'pred': it.get('pred', False)} for it in right_data]
        }
        with open(os.path.join(CACHE_DIR, 'last_arrivals.json'), 'w') as f:
            json.dump(cache_data, f)
    except Exception as e:
        logging.warning("Failed to save cache data: %s", e)

def load_cache_data():
    """Load last good arrivals data for warm start."""
    try:
        cache_file = os.path.join(CACHE_DIR, 'last_arrivals.json')
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
            # Only use cache if it's less than 2 hours old
            if time.time() - cache_data['timestamp'] < 7200:
                logging.info("Loaded warm start cache from %s", 
                           datetime.fromtimestamp(cache_data['timestamp']).strftime('%H:%M'))
                return cache_data['left'], cache_data['right']
    except Exception as e:
        logging.warning("Failed to load cache data: %s", e)
    return [], []

# ========= ENV / API =========
load_dotenv(ENV_PATH)
OBA_KEY = os.getenv("OBA_KEY", "").strip()

def oba_arrivals(stop_id, max_items=5, timeout=6):
    if not OBA_KEY:
        raise RuntimeError("Missing OBA_KEY (.env)")
    url = f"https://api.pugetsound.onebusaway.org/api/where/arrivals-and-departures-for-stop/{stop_id}.json"
    r = requests.get(url, params={"key": OBA_KEY, "minutesBefore": 0, "minutesAfter": 90}, timeout=timeout)
    r.raise_for_status()
    arr = r.json()["data"]["entry"]["arrivalsAndDepartures"]
    out = []
    for a in arr[: max_items * 2]:  # overscan a little to skip empties
        when = (a.get("predictedArrivalTime") or a.get("predictedDepartureTime") or
                a.get("scheduledArrivalTime") or a.get("scheduledDepartureTime"))
        if when is None:
            continue
        out.append({
            "route": a.get("routeShortName") or "?",
            "routeId": a.get("routeId"),
            "directionId": a.get("directionId"),
            "tripId": a.get("tripId"),
            "vehicleId": a.get("vehicleId"),
            "stopSequence": a.get("stopSequence"),
            "headsign": (a.get("tripHeadsign") or "").strip(),
            "arrive_dt": datetime.fromtimestamp(when/1000),
            "stops": a.get("numberOfStopsAway"),
            "distanceFromStop": a.get("distanceFromStop"),  # some feeds expose this
            "pred": bool(a.get("predictedArrivalTime") or a.get("predictedDepartureTime")),
        })
        if len(out) >= max_items:
            break
    return out

# ========= IT8951 helpers (unchanged) =========
def mode_code(m):
    v = getattr(m, "value", m)
    if isinstance(v, (tuple, list)):
        for x in v:
            if isinstance(x, int): return x
        raise TypeError(f"Bad mode tuple: {v}")
    if isinstance(v, int): return v
    return int(v)

def mode_or(name, fallback):
    return mode_code(getattr(constants.DisplayModes, name, fallback))

MODE_A2   = mode_code(constants.DisplayModes.A2)
MODE_GC16 = mode_code(constants.DisplayModes.GC16)
MODE_GL16 = mode_or("GL16", constants.DisplayModes.A2)

def align4_bbox(b):
    x1,y1,x2,y2 = b
    ax1 = x1 - (x1 % 4)
    w   = x2 - x1
    aw  = math.ceil((w + (x1 - ax1)) / 4) * 4
    ax2 = ax1 + int(aw)
    return (ax1, y1, ax2, y2), (x1 - ax1)

def map_logical_to_physical_bbox(b, W, H):
    x1,y1,x2,y2 = b
    if FLIP_X: x1, x2 = W - x2, W - x1
    if FLIP_Y: y1, y2 = H - y2, H - y1
    return (x1, y1, x2, y2)

def transform_full(img):
    if FLIP_X: img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if FLIP_Y: img = img.transpose(Image.FLIP_TOP_BOTTOM)
    return img

def transform_partial(img):
    if FLIP_X: img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if FLIP_Y: img = img.transpose(Image.FLIP_TOP_BOTTOM)
    return img

def draw_full(display, img):
    img = transform_full(img)
    display.frame_buf.paste(img)
    display.draw_full(MODE_GC16)

def draw_full_a2(display, img):
    """Full-screen push in the fast black/white A2 mode (well under a second). Only for pure black/white frames."""
    img = transform_full(img)
    display.frame_buf.paste(img)
    display.draw_full(MODE_A2)

def draw_partial(display, logical_bbox, subimg, mode):
    W, H = display.epd.width, display.epd.height
    pb   = map_logical_to_physical_bbox(logical_bbox, W, H)
    ab, xoff = align4_bbox(pb)
    dims = (ab[2]-ab[0], ab[3]-ab[1])
    xy   = (ab[0], ab[1])
    subimg = transform_partial(subimg)
    part_aligned = Image.new('L', dims, 255)
    part_aligned.paste(subimg, (xoff, 0))
    display.frame_buf.paste(part_aligned, box=ab)
    display.update(part_aligned.tobytes(), xy, dims, mode)

# ========= Fonts (unchanged sizes you liked) =========
def load_font(size, *candidates):
    search = list(candidates) + [
        os.path.join(FONTS, "Marsden-Nr-SemiBold.ttf"),
        os.path.join(FONTS, "Marsden-Nr-Regular.ttf"),
        os.path.join("/usr/share/fonts/truetype/dejavu", "DejaVuSans.ttf"),
        os.path.join("/usr/share/fonts/truetype/dejavu", "DejaVuSansMono.ttf"),
    ]
    for p in search:
        if p and os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except Exception: pass
    return ImageFont.load_default()

FONT_TITLE = load_font(int(68 * 1.2 * 1.2 * 1.25), os.path.join(FONTS, "Marsden-Nr-SemiBold.ttf"))  # 123pt (80% larger total)
FONT_H2    = load_font(53, os.path.join(FONTS, "Marsden-Nr-SemiBold.ttf"))
FONT_BODY  = load_font(45, os.path.join(FONTS, "Marsden-Nr-Regular.ttf"))
FONT_SM    = load_font(35, os.path.join(FONTS, "Marsden-Nr-Light.ttf"))
FONT_NUM   = load_font(50, os.path.join(FONTS, "Marsden-Nr-Regular.ttf"))
FONT_TIME  = load_font(int(66 * 1.25), os.path.join(FONTS, "Marsden-Nr-SemiBold.ttf"))  # 83pt (25% larger)
FONT_MER   = load_font(int(36 * 1.25), os.path.join(FONTS, "Marsden-Nr-SemiBold.ttf"))  # 45pt (25% larger)
FONT_DATE  = load_font(int(30 * 1.25), os.path.join(FONTS, "Marsden-Nr-SemiBold.ttf"))  # 38pt (25% larger)

# ========= Logo mask (unchanged strict thresholding) =========
def load_logo_mask(target_h):
    if os.path.exists(PNG_LOGO):
        try:
            rgba = Image.open(PNG_LOGO).convert("RGBA")
            w0, h0 = rgba.size
            w_new  = int(round(w0 * (target_h / h0)))
            rgba   = rgba.resize((w_new, target_h), Image.LANCZOS)
            r,g,b,a = rgba.split()
            gray    = ImageOps.grayscale(Image.merge("RGB", (r,g,b)))
            a_mask  = a.point(  lambda v: 255 if v >= 220 else 0)
            l_mask  = gray.point(lambda v: 255 if v >= 220 else 0)
            mask    = ImageChops.multiply(a_mask, l_mask).filter(ImageFilter.SMOOTH)
            return mask, w_new
        except Exception as e:
            logging.warning("PNG logo load failed: %s", e)
    if os.path.exists(SVG_LOGO):
        try:
            import cairosvg, io
            png_bytes = cairosvg.svg2png(url=SVG_LOGO, output_width=600)
            g = Image.open(io.BytesIO(png_bytes)).convert("L")
            w0, h0 = g.size
            w_new  = int(round(w0 * (target_h / h0)))
            g      = g.resize((w_new, target_h), Image.LANCZOS)
            mask   = g.point(lambda p: 255 if p <= 35 else 0)
            return mask, w_new
        except Exception as e:
            logging.warning("SVG logo rasterize failed: %s", e)
    return None, 0

def paste_logo_white_on_black(dst, x, y, target_h, cache):
    if not cache or cache[0] is None or getattr(cache[0][0], "height", None) != target_h:
        cache[:] = [load_logo_mask(target_h)]
    mask, w = cache[0]
    if not mask: return 0
    dst.paste(Image.new('L', (w, target_h), 255), (x, y), mask)
    return w

# ========= Nav pieces: STATIC (logo + title + separators), DATE patch, CLOCK patch =========
# Cache for font measurements to reduce CPU usage
_FONT_MEASUREMENT_CACHE = {}

def get_text_size(text, font):
    """Get cached text measurements."""
    cache_key = (text, id(font))
    if cache_key not in _FONT_MEASUREMENT_CACHE:
        probe = Image.new('L', (10,10), 0)
        d = ImageDraw.Draw(probe)
        _FONT_MEASUREMENT_CACHE[cache_key] = d.textbbox((0,0), text, font=font)[2:]
    return _FONT_MEASUREMENT_CACHE[cache_key]

def calc_clock_metrics():
    ttw, tth = get_text_size("12:59", FONT_TIME)
    apw, aph = get_text_size("PM", FONT_MER)
    w = ttw + TIME_PAD_X + apw + 2*6
    h = max(tth, aph) + 2*8
    return w, h

def render_time_only(now_dt, size):
    w, h = size
    img = Image.new('L', (w, h), 0)
    d   = ImageDraw.Draw(img)
    t  = now_dt.strftime("%I:%M").lstrip("0") or "0"
    ap = now_dt.strftime("%p")
    ttw, tth = d.textbbox((0,0), t,  font=FONT_TIME)[2:]
    apw, aph = d.textbbox((0,0), ap, font=FONT_MER )[2:]
    x = w - 6 - (ttw + TIME_PAD_X + apw)
    y = (h - max(tth, aph)) // 2
    d.text((x, y), t,  font=FONT_TIME, fill=255)
    d.text((x + ttw + TIME_PAD_X, y + (tth - aph)//2), ap, font=FONT_MER, fill=255)
    return img

def render_date_block(now_dt, size):
    w, h = size
    img = Image.new('L', (w, h), 0)
    d   = ImageDraw.Draw(img)
    day  = now_dt.strftime("%A,")
    date = now_dt.strftime("%B %d").replace(" 0", " ")
    d1w, d1h = d.textbbox((0,0), day,  font=FONT_DATE)[2:]
    d2w, d2h = d.textbbox((0,0), date, font=FONT_DATE)[2:]
    block_w  = max(d1w, d2w)
    x = w - block_w
    block_h = d1h + DATE_LINE_GAP + d2h
    y = (h - block_h)//2
    d.text((x, y),               day,  font=FONT_DATE, fill=255)
    d.text((x, y + d1h + DATE_LINE_GAP), date, font=FONT_DATE, fill=255)
    return img

def render_nav_complete(W_safe, now_dt, logo_cache):
    """Complete unified nav bar with logo, title, date, and time - no gaps."""
    bar = Image.new('L', (W_safe, NAV_H), 0)
    d   = ImageDraw.Draw(bar)

    # Left: logo then "Departures" — keep the same sizing you settled on
    x = PAD
    logo_h = max(20, int(round((NAV_H - 2*LOGO_VPAD) * 0.72)))
    lw = paste_logo_white_on_black(bar, x, (NAV_H - logo_h)//2 + 10, logo_h,
                                   logo_cache if logo_cache else [None])
    if lw: x += lw + 20
    # Small extra padding like your last good build
    x += max(4, int(round(0.30 * logo_h)))

    title = "Departures"
    _,_,tw,th = d.textbbox((0,0), title, font=FONT_TITLE)
    d.text((x, (NAV_H - th)//2 + 20), title, font=FONT_TITLE, fill=255)

    # Right: time patch
    time_patch = render_time_only(now_dt, (CLOCK_W_MAX, CLOCK_H))
    clock_left = W_safe - PAD - CLOCK_W_MAX
    clock_top  = (NAV_H - CLOCK_H)//2 + 20
    bar.paste(time_patch, (clock_left, clock_top))

    # Date block to the left of time (right-aligned)
    day  = now_dt.strftime("%A,")
    date = now_dt.strftime("%B %d").replace(" 0", " ")
    d1w, d1h = d.textbbox((0,0), day,  font=FONT_DATE)[2:]
    d2w, d2h = d.textbbox((0,0), date, font=FONT_DATE)[2:]
    
    # Vertical separator line (centered between date and time)
    sep_x = clock_left - 4  # very close to time 
    sep_top = (NAV_H - CLOCK_H)//2 + 20 + 8  # align with time block
    sep_bottom = sep_top + CLOCK_H - 16
    d.line((sep_x, sep_top, sep_x, sep_bottom), fill=255, width=2)
    
    # Right-align each line of date text to the separator (with more left padding)
    date_right_edge = sep_x - 24  # more padding between date and separator
    block_h  = d1h + DATE_LINE_GAP + d2h
    dy_text  = (NAV_H - block_h)//2 + 20
    
    # Right-align day text
    d.text((date_right_edge - d1w, dy_text), day, font=FONT_DATE, fill=255)
    # Right-align date text 
    d.text((date_right_edge - d2w, dy_text + d1h + DATE_LINE_GAP), date, font=FONT_DATE, fill=255)

    return bar

# ========= Columns (unchanged layout you liked) =========
CARD_H   = int(128 * 1.25)  # 160
BADGE_SZ = int(92  * 1.25)  # 115
GAP_V    = 12
GAP_H    = int(18  * 1.25)  # 23
LEFT_TX  = BADGE_SZ + 2*GAP_H
TITLE_Y  = int(46  * 1.25)  # 58

def card_boxes_in_column(col_box, max_cards=5):
    x1,y1,x2,y2 = col_box
    boxes = []
    y = y1 + TITLE_Y
    for _ in range(max_cards):
        boxes.append((x1, y, x2, y + CARD_H))
        y += CARD_H + GAP_V
    return boxes

def draw_route_badge(draw, x, y, size, route):
    r = size // 4
    draw.rounded_rectangle((x, y, x+size, y+size), radius=r, fill=0)
    rt = route.strip()
    tw, th = draw.textbbox((0,0), rt, font=FONT_H2)[2:]
    draw.text((x + (size - tw)//2, y + (size - th)//2), rt, font=FONT_H2, fill=255)

def get_bus_state(item, index, now, is_downtown=False):
    """
    FSM first, then fall back to your original rules.
    Maps:
      at_stop    -> 'urgent'   (your "GO TO BUS STOP!")
      departed   -> 'departed'
    """
    k = _veh_key(item)
    node = PHASES.get(k)
    if node:
        if node["phase"] == "departed":
            return "departed"
        if node["phase"] == "at_stop":
            return "urgent"

    # Fallback to previous stateless logic
    arrive_time = item["arrive_dt"]
    time_diff = (arrive_time - now).total_seconds() / 60.0
    if time_diff < 0:
        if abs(time_diff) > 0.5:  # keep your 30s hide window
            return "hidden"
        return "departed"

    urgent_threshold = 3 if is_downtown else 5
    if index == 0 and item["pred"] and 0 < time_diff <= urgent_threshold:
        return "urgent"
    return "normal"

# ===== Per-vehicle arrival/departure FSM =====
from collections import defaultdict

def _veh_key(it):
    return it.get("vehicleId") or it.get("tripId") or f"{it.get('route','?')}|{it.get('headsign','')}"

# PHASES[vkey] = {"phase": "approach|at_stop|departed",
#                 "seen": monotonic, "entered": monotonic, "conf": int,
#                 "last_eta_s": float, "last_stops": int|None}
PHASES = {}

def _eta_seconds(it, now):
    try:
        return (it["arrive_dt"] - now).total_seconds()
    except Exception:
        return None

def _stops_int(it):
    try:
        return int(it.get("stops"))
    except Exception:
        return None

def update_fsm(current_items, now_mono, now_dt):
    """Update PHASES with this poll's vehicles."""
    seen_keys = set()
    for it in current_items:
        k = _veh_key(it); seen_keys.add(k)
        eta_s   = _eta_seconds(it, now_dt)
        stops   = _stops_int(it)
        dist_m  = it.get("distanceFromStop")
        node = PHASES.get(k, {"phase":"approach","seen":now_mono,"entered":now_mono,"conf":0,
                              "last_eta_s":eta_s, "last_stops":stops})

        # Confirmation for 'at_stop'
        at_stop_signal = False
        if stops is not None and stops <= 0:
            at_stop_signal = True
        if eta_s is not None and eta_s <= ARRIVE_ETA_SEC:
            at_stop_signal = True
        if dist_m is not None and isinstance(dist_m,(int,float)) and dist_m <= ARRIVE_DIST_M:
            at_stop_signal = True

        if node["phase"] == "approach":
            if at_stop_signal:
                node["conf"] += 1
                if node["conf"] >= ARRIVE_CONFIRM_POLLS:
                    node["phase"] = "at_stop"
                    node["entered"] = now_mono
            else:
                node["conf"] = 0

        elif node["phase"] == "at_stop":
            # Conditions to move to departed
            eta_neg = (eta_s is not None and eta_s < -DEPART_GRACE_SEC)
            passed  = (node.get("last_stops") in (0,1) and stops is not None and stops >= 1)
            # (optional) if distance grows quickly you can treat as passed too
            if eta_neg or passed:
                node["phase"] = "departed"
                node["entered"] = now_mono
            # else remain at_stop until disappearance handled below

        elif node["phase"] == "departed":
            # Keep for a short window, GC later
            pass

        node["seen"] = now_mono
        node["last_eta_s"] = eta_s
        node["last_stops"] = stops
        PHASES[k] = node

    # Handle disappearances and GC
    for k, node in list(PHASES.items()):
        if k not in seen_keys:
            # If we recently were at_stop, treat vanish as departed after grace
            if node["phase"] == "at_stop" and (now_mono - node["seen"] >= DEPART_VANISH_SEC):
                node["phase"] = "departed"
                node["entered"] = now_mono
                PHASES[k] = node
            # Forget very old entries
            if now_mono - node["seen"] > STALE_FORGET_SEC:
                del PHASES[k]

def filter_visible_buses(items, now, is_downtown=False):
    """Filter out hidden buses and return visible items with their display indices."""
    visible_items = []
    for idx, item in enumerate(items):
        state = get_bus_state(item, idx, now, is_downtown)
        if state != "hidden":
            visible_items.append(item)
            if len(visible_items) >= 5:  # Only show 5 items
                break
    return visible_items

def render_card_column(W, H, title, items, blink_state=False, is_downtown=False):
    """Render card column with optional blinking background for urgent entries.
    blink_state: True/False for grey background visibility on urgent entries
    is_downtown: True for downtown column (3min urgent), False for uptown (5min urgent)"""
    img = Image.new('L', (W, H), 255)
    d   = ImageDraw.Draw(img)
    d.text((4, 0), title, font=FONT_H2, fill=0)
    y = TITLE_Y
    now = datetime.now()
    
    # Filter out hidden buses (departed >30s ago)
    visible_items = filter_visible_buses(items, now, is_downtown)
    
    for display_idx, it in enumerate(visible_items):
        # Use display_idx for urgency check (first visible bus gets urgent status)
        state = get_bus_state(it, display_idx, now, is_downtown)
        
        # No background drawing - keep it clean white
        
        # Standard separator line below each card
        d.line((0, y + CARD_H + 2, W, y + CARD_H + 2), fill=200, width=2)

        # Route badge - enhanced styling for states
        if state == "urgent":
            # High contrast badge for urgency
            draw_route_badge(d, 4, y + (CARD_H - BADGE_SZ)//2, BADGE_SZ, it["route"])
        elif state == "departed":
            # Muted badge for departed
            r = BADGE_SZ // 4
            d.rounded_rectangle((4, y + (CARD_H - BADGE_SZ)//2, 4 + BADGE_SZ, y + (CARD_H - BADGE_SZ)//2 + BADGE_SZ), 
                               radius=r, fill=200, outline=160, width=1)
            rt = it["route"].strip()
            tw, th = d.textbbox((0,0), rt, font=FONT_H2)[2:]
            d.text((4 + (BADGE_SZ - tw)//2, y + (CARD_H - BADGE_SZ)//2 + (BADGE_SZ - th)//2), 
                   rt, font=FONT_H2, fill=100)
        else:
            # Normal badge
            draw_route_badge(d, 4, y + (CARD_H - BADGE_SZ)//2, BADGE_SZ, it["route"])
        
        # Labels
        label_left  = "Predicted Arrival" if it["pred"] else "Scheduled Arrival"
        label_right = "Number of Stops Away"
        label_color = 120 if state != "departed" else 160
        d.text((LEFT_TX, y + 8), label_left, font=FONT_SM, fill=label_color)
        ltw = d.textbbox((0,0), label_right, font=FONT_SM)[2]
        d.text((W - 8 - ltw, y + 8), label_right, font=FONT_SM, fill=label_color)

        # Time and stops (subtract 1 from stops to account for API delay)
        tm = it["arrive_dt"].strftime("%I:%M %p").lstrip("0")
        raw_stops = it.get("stops")
        if raw_stops is None:
            st = "N/A"
        elif state == "departed":
            st = "0"  # Show "0" instead of negative stops for departed buses
        else:
            adjusted_stops = max(0, raw_stops - 1)  # Subtract 1, minimum 0
            st = str(adjusted_stops)
        
        if state == "urgent":
            # Bold/larger time for urgency
            d.text((LEFT_TX, y + 50), tm, font=FONT_NUM, fill=0)
            stw = d.textbbox((0,0), st, font=FONT_NUM)[2]
            d.text((W - 8 - stw, y + 50), st, font=FONT_NUM, fill=0)
        elif state == "departed":
            # Muted text for departed
            d.text((LEFT_TX, y + 50), tm, font=FONT_BODY, fill=140)
            stw = d.textbbox((0,0), st, font=FONT_BODY)[2]
            d.text((W - 8 - stw, y + 50), st, font=FONT_BODY, fill=140)
        else:
            # Normal styling
            d.text((LEFT_TX, y + 50), tm, font=FONT_BODY, fill=0)
            stw = d.textbbox((0,0), st, font=FONT_BODY)[2]
            d.text((W - 8 - stw, y + 50), st, font=FONT_BODY, fill=0)

        # Headsign area - FIXED HEIGHT for all states
        head_y = y + 90

        # Show headsign (left side) - VERY aggressive truncation
        head = it.get("headsign") or ""
        if head:
            # Much more aggressive truncation to prevent overlap
            # Limit to about 18 characters max (shorter than "Mount Baker Transit")
            if len(head) > 18:
                head = head[:18].rstrip() + "…"
            
            # Reserve even more space for status message
            status_msg_reserve = 160  # Even more space for "GO TO BUS STOP!"
            avail_w = W - (LEFT_TX + 8) - status_msg_reserve
            tw = d.textbbox((0,0), head, font=FONT_SM)[2]
            if tw > avail_w:
                while head and d.textbbox((0,0), head + "…", font=FONT_SM)[2] > avail_w:
                    head = head[:-1]
                head += "…"
            head_color = 0 if state != "departed" else 140
            d.text((LEFT_TX, head_y), head, font=FONT_SM, fill=head_color)
        
        # Status messages on RIGHT side, below the stops number (better spacing)
        status_y = head_y + 5  # Just 5px below headsign for better alignment
        if state == "urgent":
            # Static "GO TO BUS STOP!" (blinking disabled due to refresh issues)
            msg = "GO TO BUS STOP!"
            msg_w = d.textbbox((0,0), msg, font=FONT_BODY)[2]  # Use FONT_BODY for bolder text
            # Right-align under the stops number
            d.text((W - 8 - msg_w, status_y), msg, font=FONT_BODY, fill=0)
        elif state == "departed":
            # Static "BUS DEPARTED" - no blinking
            msg = "BUS DEPARTED"
            msg_w = d.textbbox((0,0), msg, font=FONT_BODY)[2]  # Same font weight as urgent
            # Right-align under the stops number
            d.text((W - 8 - msg_w, status_y), msg, font=FONT_BODY, fill=120)
        
        # FIXED spacing - all entries same height
        y += CARD_H + 50  # Fixed increment

    return img

def nav_badge_box(W_safe, clock_w):
    x2 = W_safe - PAD - clock_w - NAV_DATE_GAP - DATE_RESERVE_W
    x1 = max(PAD, x2 - BADGE_W)
    y1 = (NAV_H - BADGE_H)//2
    y2 = y1 + BADGE_H
    return (x1, y1, x2, y2)

def render_nav_badge(text, size):
    w, h = size
    img = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(img)
    tw, th = d.textbbox((0,0), text, font=FONT_SM)[2:]
    d.text((w - 8 - tw, (h - th)//2), text, font=FONT_SM, fill=255)
    return img

# ========= Main (ONLY logic changes; visuals preserved) =========
def main():
    display = AutoEPDDisplay(vcom=-1.5, bus=0, device=0, spi_hz=SPI_HZ)
    W, H = display.epd.width, display.epd.height
    W_SAFE = W - SAFE_RIGHT
    # Sports pages (Celtics, scores) rotate in between stretches of the bus screen; see app/rotation.py
    rotation = sports_rotation.from_config()
    rotation.start_worker((W, H))
    # Greetings ("hello, <name>") are opt-in via config.toml [[greetings]]; see app/greetings/
    greetings = greeting_mod.from_config(size=(W, H))
    logging.info("greetings: %s", [(g.style, g.every_s, g.show_s) for g in greetings] or "none")
    logging.info("Panel %dx%d  SAFE_RIGHT=%d  SPI=%.0fMHz", W, H, SAFE_RIGHT, SPI_HZ/1e6)
    
    # Initialize predictor for enhanced ETAs
    predictor = DeterministicPredictor()

    # clock geometry
    global CLOCK_W_MAX, CLOCK_H
    CLOCK_W_MAX, CLOCK_H = calc_clock_metrics()

    # Traditional boxes (revert to original working approach)
    LEFT_BOX   = (PAD, NAV_H + PAD + 20, W_SAFE//2 - COL_GAP//2 - PAD, H - PAD)
    RIGHT_BOX  = (W_SAFE//2 + COL_GAP//2 + PAD, NAV_H + PAD + 20, W_SAFE - PAD, H - PAD)
    NAV_BOX    = (0, 0, W_SAFE, NAV_H)  # Unified nav box - this was working fine
    RIGHT_STRIP= (W_SAFE, 0, W, H)
    BADGE_BOX  = nav_badge_box(W_SAFE, CLOCK_W_MAX)

    # Double wipe to start totally clean
    white_full = Image.new('L', (W, H), 255)
    draw_full(display, white_full); time.sleep(0.2)
    draw_full(display, white_full)

    # Initial unified nav (no gaps, no white lines)
    logo_cache = [None]
    now = datetime.now()
    nav_complete = render_nav_complete(W_SAFE, now, logo_cache)
    full = Image.new('L', (W, H), 255)
    full.paste(nav_complete, (0,0))
    ImageDraw.Draw(full).rectangle(RIGHT_STRIP, fill=255)
    draw_full(display, full)

    # State
    poll_interval   = POLL_BASE_SECS
    last_fetch_t    = 0.0
    last_ok_time    = None
    last_minute     = now.minute
    last_left_img   = None
    last_right_img  = None
    left_updates    = 0
    right_updates   = 0
    badge_shown     = False
    
    # Cached data for blinking
    last_left_data  = []
    last_right_data = []
    has_urgent_left = False
    has_urgent_right = False

    # Precompute per-card bboxes for tiny diffs
    def card_boxes(col_box):
        x1,y1,x2,y2 = col_box
        boxes = []
        y = y1 + TITLE_Y
        for _ in range(5):
            boxes.append((x1, y, x2, y + CARD_H))
            y += CARD_H + GAP_V
        return boxes

    # Precompute status message areas for targeted blinking - measure actual text dimensions
    def status_msg_boxes(col_box):
        # Use cached measurements for performance
        urgent_msg = "GO TO BUS STOP!"
        departed_msg = "BUS DEPARTED"
        
        urgent_w, urgent_h = get_text_size(urgent_msg, FONT_BODY)
        departed_w, departed_h = get_text_size(departed_msg, FONT_BODY)
        
        # Use the larger dimensions to accommodate both messages
        max_text_w = max(urgent_w, departed_w)
        max_text_h = max(urgent_h, departed_h)
        
        # Add some padding
        padding_w = 8  # 4px on each side
        padding_h = 6  # 3px top and bottom
        
        box_w = max_text_w + padding_w
        box_h = max_text_h + padding_h
        
        x1,y1,x2,y2 = col_box
        boxes = []
        y = y1 + TITLE_Y
        for _ in range(5):  # Always create 5 boxes, even if fewer items visible
            # Status message area: EXACTLY sized for the measured text
            status_y = y + 90 + 5  # head_y + 5 
            # Position from right edge based on measured width
            status_x_start = x2 - 4 - box_w  # Right-align with padding
            status_box = (status_x_start, status_y, status_x_start + box_w, status_y + box_h)
            boxes.append(status_box)
            y += CARD_H + 50  # Match the card spacing
        return boxes

    left_card_boxes  = card_boxes(LEFT_BOX)
    right_card_boxes = card_boxes(RIGHT_BOX)
    left_status_boxes = status_msg_boxes(LEFT_BOX)
    right_status_boxes = status_msg_boxes(RIGHT_BOX)

    while True:
        t0 = time.monotonic()
        now = datetime.now()

        # ---- Nav refresh: unified patch prevents white line gaps ----
        if now.minute != last_minute:
            # Full nav redraw on minute change
            nav_complete = render_nav_complete(W_SAFE, now, logo_cache)
            draw_partial(display, NAV_BOX, nav_complete, MODE_GL16)
            last_minute = now.minute
        else:
            # Quick time-only update (still unified to avoid gaps)
            nav_complete = render_nav_complete(W_SAFE, now, logo_cache)
            draw_partial(display, NAV_BOX, nav_complete, MODE_A2)

        # ---- Targeted blinking for ONLY status message areas ----
        if has_urgent_left or has_urgent_right:
            # Blink every 1 second (on/off every second) 
            blink_state = int(time.monotonic()) % 2 == 0
            
            # Helper function to render just the status message area
            def render_status_msg_patch(width, height, state, blink_on):
                # Create patch - start with solid white
                patch = Image.new('L', (width, height), 255)
                d = ImageDraw.Draw(patch)
                
                # FORCE white fill - this should completely obliterate any previous content
                d.rectangle((0, 0, width-1, height-1), fill=255, outline=255)
                
                if state == "urgent" and blink_on:
                    # Show text when blinking ON
                    msg = "GO TO BUS STOP!"
                    msg_w, msg_h = d.textbbox((0,0), msg, font=FONT_BODY)[2:4]
                    # Center vertically in the patch
                    text_y = (height - msg_h) // 2
                    d.text((width - msg_w - 4, text_y), msg, font=FONT_BODY, fill=0)
                elif state == "departed":
                    # Always show departed message
                    msg = "BUS DEPARTED"
                    msg_w, msg_h = d.textbbox((0,0), msg, font=FONT_BODY)[2:4]
                    # Center vertically in the patch
                    text_y = (height - msg_h) // 2
                    d.text((width - msg_w - 4, text_y), msg, font=FONT_BODY, fill=120)
                # For urgent + blink_off or normal state: just solid white (no text)
                
                return patch
            
            # Check each status area and update only if urgent
            if has_urgent_left and last_left_data:
                for idx, item in enumerate(last_left_data):
                    if idx >= 5:  # Safety check
                        break
                    state = get_bus_state(item, idx, now, is_downtown=True)
                    if state == "urgent":  # Only update urgent entries
                        status_box = left_status_boxes[idx]
                        patch_w = status_box[2] - status_box[0]
                        patch_h = status_box[3] - status_box[1]
                        status_patch = render_status_msg_patch(patch_w, patch_h, state, blink_state)
                        draw_partial(display, status_box, status_patch, MODE_GL16)
                        
            if has_urgent_right and last_right_data:
                for idx, item in enumerate(last_right_data):
                    if idx >= 5:  # Safety check
                        break
                    state = get_bus_state(item, idx, now, is_downtown=False)
                    if state == "urgent":  # Only update urgent entries
                        status_box = right_status_boxes[idx]
                        patch_w = status_box[2] - status_box[0]
                        patch_h = status_box[3] - status_box[1]
                        status_patch = render_status_msg_patch(patch_w, patch_h, state, blink_state)
                        draw_partial(display, status_box, status_patch, MODE_GL16)

        # ---- Poll (with jitter/backoff); redraw ONLY changed cards ----
        if t0 - last_fetch_t >= poll_interval + random.uniform(-2, 2):
            try:
                left  = oba_arrivals(LEFT_STOP,  8)   # Request more to account for filtered departed buses
                right = oba_arrivals(RIGHT_STOP, 8)
                last_ok_time = time.monotonic()
                last_fetch_t = last_ok_time
                poll_interval = POLL_BASE_SECS

                # Keep copies for learning
                prev_left_raw  = last_left_data  if 'last_left_data'  in locals() else []
                prev_right_raw = last_right_data if 'last_right_data' in locals() else []

                # Enhance (replace arrive_dt based on fusion)
                now = datetime.now()
                left  = predictor.enhance(left,  now)
                right = predictor.enhance(right, now)

                # Learn from movement (use raw feeds pre-filtering)
                predictor.observe(prev_left_raw,  left,  now)
                predictor.observe(prev_right_raw, right, now)

                # Log prediction performance for monitoring
                for side, arr in (("L", left), ("R", right)):
                    if arr:
                        a0 = arr[0]
                        logging.info(
                            "[%s] route=%s S=%s fused_eta=%.1f",
                            side, a0.get("route"), a0.get("stops"),
                            a0.get("eta_fused_min", math.nan)
                        )

                # Filter out departed buses before processing
                visible_left = filter_visible_buses(left, now, is_downtown=True)
                visible_right = filter_visible_buses(right, now, is_downtown=False)
                
                # Update FSM with what's on screen this poll
                now_mono = time.monotonic()
                update_fsm(visible_left + visible_right, now_mono, now)
                
                # Cache filtered data for consistent rendering 
                last_left_data = visible_left
                last_right_data = visible_right
                
                # Save successful data to cache for warm start (save original data)
                save_cache_data(left, right)
                
                # Check for urgent buses and calculate soonest arrival (using filtered data)
                has_urgent_left = False
                has_urgent_right = False
                soonest_minutes = float('inf')
                
                for idx, it in enumerate(visible_left):
                    if get_bus_state(it, idx, now, is_downtown=True) == "urgent":
                        has_urgent_left = True
                    # Calculate minutes until arrival
                    time_diff = (it["arrive_dt"] - now).total_seconds() / 60.0
                    if time_diff > 0:
                        soonest_minutes = min(soonest_minutes, time_diff)
                        
                for idx, it in enumerate(visible_right):
                    if get_bus_state(it, idx, now, is_downtown=False) == "urgent":
                        has_urgent_right = True
                    # Calculate minutes until arrival  
                    time_diff = (it["arrive_dt"] - now).total_seconds() / 60.0
                    if time_diff > 0:
                        soonest_minutes = min(soonest_minutes, time_diff)
                
                # Dynamic poll interval based on soonest arrival
                if soonest_minutes <= 2:
                    poll_interval = 10  # Poll every 10s when bus is very close
                elif soonest_minutes <= 10:
                    poll_interval = POLL_BASE_SECS  # Normal 30s polling
                else:
                    poll_interval = 60  # Poll every 60s when all buses are far away
                    
                # Structured logging for monitoring
                urgent_count = int(has_urgent_left) + int(has_urgent_right)
                logging.info("poll_interval=%ds soonest_min=%.1f urgent_buses=%d left_items=%d right_items=%d", 
                           poll_interval, 
                           soonest_minutes if soonest_minutes != float('inf') else 0,
                           urgent_count, len(left), len(right))

                lw = LEFT_BOX[2]-LEFT_BOX[0];  lh = LEFT_BOX[3]-LEFT_BOX[1]
                rw = RIGHT_BOX[2]-RIGHT_BOX[0]; rh = RIGHT_BOX[3]-RIGHT_BOX[1]
                new_left  = render_card_column(lw, lh, TITLE_LEFT,  visible_left, False, is_downtown=True)   # Downtown = 3min urgent
                new_right = render_card_column(rw, rh, TITLE_RIGHT, visible_right, False, is_downtown=False) # Uptown = 5min urgent

                if last_left_img is None:
                    draw_partial(display, LEFT_BOX, new_left, MODE_GL16)
                if last_right_img is None:
                    draw_partial(display, RIGHT_BOX, new_right, MODE_GL16)

                # Per-card diffs (GL16 for readable text; change to A2 if you want even less blink)
                if last_left_img is not None:
                    for bbox in left_card_boxes:
                        rel = (bbox[0]-LEFT_BOX[0], bbox[1]-LEFT_BOX[1], bbox[2]-LEFT_BOX[0], bbox[3]-LEFT_BOX[1])
                        if ImageChops.difference(last_left_img.crop(rel), new_left.crop(rel)).getbbox():
                            draw_partial(display, bbox, new_left.crop(rel), MODE_GL16)
                            left_updates += 1
                if last_right_img is not None:
                    for bbox in right_card_boxes:
                        rel = (bbox[0]-RIGHT_BOX[0], bbox[1]-RIGHT_BOX[1], bbox[2]-RIGHT_BOX[0], bbox[3]-RIGHT_BOX[1])
                        if ImageChops.difference(last_right_img.crop(rel), new_right.crop(rel)).getbbox():
                            draw_partial(display, bbox, new_right.crop(rel), MODE_GL16)
                            right_updates += 1

                last_left_img  = new_left
                last_right_img = new_right

                if badge_shown:
                    clear = Image.new('L', (BADGE_BOX[2]-BADGE_BOX[0], BADGE_BOX[3]-BADGE_BOX[1]), 0)
                    draw_partial(display, BADGE_BOX, clear, MODE_A2)
                    badge_shown = False

            except HTTPError as e:
                last_fetch_t = time.monotonic()
                if e.response is not None and e.response.status_code == 429:
                    # Honor Retry-After header if provided
                    retry_after = e.response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            retry_seconds = int(retry_after)
                            poll_interval = min(retry_seconds + random.uniform(1, 5), POLL_MAX_SECS)
                            logging.warning("Rate limited, retry after %d seconds (using %d)", retry_seconds, int(poll_interval))
                        except (ValueError, TypeError):
                            poll_interval = min(max(poll_interval*2, POLL_BASE_SECS*2), POLL_MAX_SECS)
                            logging.warning("Rate limited, invalid Retry-After header: %s", retry_after)
                    else:
                        poll_interval = min(max(poll_interval*2, POLL_BASE_SECS*2), POLL_MAX_SECS)
                        logging.warning("Rate limited, backing off to %d seconds", int(poll_interval))
                    label = "RATE LIMIT"
                else:
                    poll_interval = min(max(int(poll_interval*1.5), POLL_BASE_SECS), POLL_MAX_SECS)
                    label = "STALE"
                mins_stale = int((time.monotonic() - (last_ok_time or last_fetch_t)) // 60)
                txt = f"{label} {mins_stale}m" if mins_stale > 0 else label
                badge = render_nav_badge(txt, (BADGE_BOX[2]-BADGE_BOX[0], BADGE_BOX[3]-BADGE_BOX[1]))
                draw_partial(display, BADGE_BOX, badge, MODE_A2)
                badge_shown = True
                logging.warning("Fetch error: %s ; next poll in ~%ss", e, poll_interval)
            except Exception as e:
                last_fetch_t = time.monotonic()
                poll_interval = min(max(int(poll_interval*1.5), POLL_BASE_SECS), POLL_MAX_SECS)
                mins_stale = int((time.monotonic() - (last_ok_time or last_fetch_t)) // 60)
                txt = f"STALE {mins_stale}m" if mins_stale > 0 else "STALE"
                badge = render_nav_badge(txt, (BADGE_BOX[2]-BADGE_BOX[0], BADGE_BOX[3]-BADGE_BOX[1]))
                draw_partial(display, BADGE_BOX, badge, MODE_A2)
                badge_shown = True
                logging.warning("Fetch exception: %s ; next poll in ~%ss", e, poll_interval)

        # Rare column scrubs to fight ghosting (not the whole column every time)
        if left_updates >= 10 and last_left_img is not None:
            draw_partial(display, LEFT_BOX, last_left_img, MODE_GL16)
            left_updates = 0
        if right_updates >= 10 and last_right_img is not None:
            draw_partial(display, RIGHT_BOX, last_right_img, MODE_GL16)
            right_updates = 0

        # Global scrub occasionally (keeps logo/title pristine)
        if time.monotonic() - getattr(main, "_last_full", 0.0) >= GLOBAL_GC16_EVERY_SECS:
            full = Image.new('L', (W, H), 255)
            full.paste(render_nav_complete(W_SAFE, now, logo_cache), (0,0))
            ImageDraw.Draw(full).rectangle(RIGHT_STRIP, fill=255)
            draw_full(display, full)
            if last_left_img:  draw_partial(display, LEFT_BOX,  last_left_img,  MODE_GL16)
            if last_right_img: draw_partial(display, RIGHT_BOX, last_right_img, MODE_GL16)
            main._last_full = time.monotonic()

        def restore_bus():
            full = Image.new('L', (W, H), 255)
            full.paste(render_nav_complete(W_SAFE, datetime.now(), logo_cache), (0,0))
            ImageDraw.Draw(full).rectangle(RIGHT_STRIP, fill=255)
            draw_full(display, full)
            if last_left_img:  draw_partial(display, LEFT_BOX,  last_left_img,  MODE_GL16)
            if last_right_img: draw_partial(display, RIGHT_BOX, last_right_img, MODE_GL16)
            main._last_full = time.monotonic()

        # Greeting: pure black/white frames pushed with A2 (fast, so a 2 s greeting is really on screen for ~2 s),
        # then a full GC16 restore of the bus screen to clear A2 ghosting. At most one per tick.
        greeting = greeting_mod.next_due(greetings)
        if greeting is not None:
            try:
                greeting.run(show=lambda img: draw_full_a2(display, img), restore=restore_bus)
                logging.info("greeting shown (%s)", greeting.style)
            except Exception as e:
                logging.error("greeting failed: %s", e)
            badge_shown = False   # overlays are gone after the full redraw

        # Sports rotation: a full-screen page for a few seconds, then the bus screen comes straight back
        elif rotation.due():
            try:
                shown = rotation.run(show=lambda img: draw_full(display, img), restore=restore_bus)
                logging.info("rotation showed %s", shown)
            except Exception as e:
                logging.error("sports rotation failed: %s", e)
            badge_shown = False   # overlays are gone after the full redraw

        # pace
        dt = CLOCK_TICK_SECS - (time.monotonic() - t0)
        if dt > 0: time.sleep(dt)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

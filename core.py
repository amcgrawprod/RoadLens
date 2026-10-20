
import json, math, re, time, datetime as dt, pathlib, html
import requests

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "data"; DATA.mkdir(exist_ok=True)
AREAS = DATA / "areas.json"; OVR = DATA / "overrides.json"
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
UA = {"User-Agent": "RoadLens-college-demo/0.2 (student project)"}
CHENNAI_BOX = (12.80, 79.95, 13.30, 80.35)
HALF_LAT, HALF_LON = 0.009, 0.010   # about 2 km x 2 km study box
HW = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service"

DEFAULTS = dict(
    parallel_w=2.0, angled_w=4.5, perp_w=5.0, width_includes_parking=True,
    min_moving_two_way=5.5, min_moving_one_way=3.0,
    bus_junction_m=40, attach_m=25, cluster_m=20, arms_min=5, signal_gap_m=150,
    school_m=100, hospital_m=100, shop_radius_m=40, shops_commercial=6, market_m=60,
    parking_near_m=100, anchor_road_m=40, include_service=False,
)

def slug(s): return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
def _load(p, d): return json.loads(p.read_text()) if p.exists() else d
PRESETS = {'t_nagar': {'name': 'T Nagar', 'bbox': [13.02883, 80.22184, 13.04683, 80.24184]}, 'anna_nagar': {'name': 'Anna Nagar', 'bbox': [13.07925, 80.19734, 13.09725, 80.21734]}, 'tambaram': {'name': 'Tambaram', 'bbox': [12.91679, 80.10792, 12.93479, 80.12792]}, 'velachery': {'name': 'Velachery', 'bbox': [12.97117, 80.21285, 12.98917, 80.23285]}, 'guindy': {'name': 'Guindy', 'bbox': [12.99967, 80.20261, 13.01767, 80.22261]}, 'mylapore': {'name': 'Mylapore', 'bbox': [13.02265, 80.26002, 13.04065, 80.28002]}}
def list_areas():
    a = dict(PRESETS); a.update(_load(AREAS, {})); return a
def save_area_meta(key, meta):
    a = list_areas(); a[key] = meta; AREAS.write_text(json.dumps(a, indent=1))
def load_overrides(): return _load(OVR, {})
def save_overrides(o): OVR.write_text(json.dumps(o, indent=1))
def load_snapshot(key): return json.loads((DATA / f"{key}.json").read_text())

def in_chennai(lat, lon):
    s, w, n, e = CHENNAI_BOX
    return s <= lat <= n and w <= lon <= e

def box_around(lat, lon):
    return (lat - HALF_LAT, lon - HALF_LON, lat + HALF_LAT, lon + HALF_LON)

def geocode(name):
    r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=20,
        params={"q": f"{name}, Chennai, Tamil Nadu, India", "format": "json", "limit": 1, "countrycodes": "in"}).json()
    if not r: raise ValueError("We could not find that place in Chennai. Try a nearby landmark or locality name.")
    lat, lon = float(r[0]["lat"]), float(r[0]["lon"])
    if not in_chennai(lat, lon): raise ValueError("That place is outside the Chennai area this prototype covers.")
    return box_around(lat, lon), r[0]["display_name"]

def _query(b):
    bb = f"{b[0]},{b[1]},{b[2]},{b[3]}"
    return (f'[out:json][timeout:120];(way["highway"~"^({HW})$"]({bb}););out body geom;'
            f'(node["highway"="bus_stop"]({bb});node["highway"="traffic_signals"]({bb});'
            f'nwr["amenity"~"^(school|kindergarten|college|hospital|marketplace|parking)$"]({bb});'
            f'nwr["healthcare"="hospital"]({bb});nwr["shop"]({bb}););out center tags;')

def fetch_snapshot(key, name, bbox, timeout=120):
    last = None
    for ep in ENDPOINTS:
        try:
            r = requests.post(ep, data={"data": _query(bbox)}, headers=UA, timeout=timeout)
            r.raise_for_status()
            els = r.json()["elements"]
            snap = {"name": name, "bbox": list(bbox), "retrieved": dt.date.today().isoformat(),
                    "source": "OpenStreetMap contributors via Overpass API", "elements": els, "format": 2}
            (DATA / f"{key}.json").write_text(json.dumps(snap))
            save_area_meta(key, {"name": name, "bbox": list(bbox), "retrieved": snap["retrieved"]})
            return snap
        except Exception as ex:
            last = ex
    raise RuntimeError(f"Could not download map data right now ({last}). Check your internet connection or try again.")

# ---------- geometry ----------
def _mk_proj(lat0, lon0):
    kx = 111320 * math.cos(math.radians(lat0)); ky = 110540
    return lambda lat, lon: ((lon - lon0) * kx, (lat - lat0) * ky)
def _d(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])
def _pt_poly(p, poly):
    best = (1e18, 0.0); cum = 0.0
    for a, b in zip(poly, poly[1:]):
        L = _d(a, b)
        if L == 0: continue
        t = max(0, min(1, ((p[0]-a[0])*(b[0]-a[0]) + (p[1]-a[1])*(b[1]-a[1])) / (L*L)))
        q = (a[0] + t*(b[0]-a[0]), a[1] + t*(b[1]-a[1]))
        d = _d(p, q)
        if d < best[0]: best = (d, cum + t*L)
        cum += L
    return best
def _near(p, s, r):
    x0, y0, x1, y1 = s["bbox"]
    if p[0] < x0 - r or p[0] > x1 + r or p[1] < y0 - r or p[1] > y1 + r: return None
    d, _ = _pt_poly(p, s["poly"])
    return d if d <= r else None

# ---------- tags ----------
def parse_width(v):
    if v is None: return None, "missing"
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m)?\s*", str(v))
    return (float(m.group(1)), "mapped") if m else (None, "ambiguous")
def parse_int(v):
    m = re.match(r"\s*(\d+)", str(v)) if v is not None else None
    return int(m.group(1)) if m else None
def _side_state(t, side):
    lane = t.get(f"parking:lane:{side}") or t.get("parking:lane:both")
    old = t.get(f"parking:{side}") or t.get("parking:both")
    if lane in ("parallel", "diagonal", "perpendicular"): return f"lane:{lane}"
    if lane in ("marked", "yes"): return "lane:parallel"
    if lane in ("no", "separate"): return "none"
    if lane in ("no_parking", "no_stopping"): return "restricted"
    if lane in ("street_side", "on_kerb", "half_on_kerb", "shoulder"): return "kerb"
    if old in ("lane", "yes"): return "lane:parallel"
    if old in ("no", "separate"): return "none"
    if old in ("street_side", "on_kerb", "half_on_kerb", "shoulder"): return "kerb"
    if old in ("no_parking", "no_stopping"): return "restricted"
    return "unknown"

BASE = {"motorway": "Highway", "trunk": "Highway", "primary": "Main road", "secondary": "Main road",
        "tertiary": "Connector road", "unclassified": "Connector road",
        "residential": "Residential street", "living_street": "Residential street", "service": "Service lane"}
MAJOR = {"trunk", "primary", "secondary", "tertiary"}
TYPE_ORDER = ["Highway", "Main road", "Commercial street", "School zone", "Hospital zone", "Connector road", "Residential street", "Service lane"]

# ---------- fixes: one proposal per bottleneck, chosen by road type ----------
def _f(title, text, scale, src=""): return dict(title=title, text=text, scale=scale, source=src)
IRC_BUS = "IRC far-side bus stop guidance (IRC:80-2022)"
SCHOOL_SRC = "School zone guidelines (IRC SP:32 based)"
FIX = {
 "bus_stop": {
  "Main road": _f("Move the stop just past the junction (far side) or add a bus bay", "Buses halting right at the junction hold up turning and through traffic. A stop just after the junction, or a bus bay cut into the kerb, lets buses clear the lane. Keep the stop area free of parked vehicles.", "Moderate", IRC_BUS),
  "Highway": _f("Provide a set-back bus bay with a slowing-down lane", "Fast traffic and stopping buses are a poor mix near a junction. A properly marked bay away from the junction keeps buses out of the through lanes.", "Needs design study", IRC_BUS),
  "Commercial street": _f("Shift the stop away from the corner and mark a no-parking length at the stop", "Shoppers, autos and parked vehicles crowd the corner. Moving the stop along the street and keeping the stop kerb clear reduces blocking.", "Quick fix", IRC_BUS),
  "School zone": _f("Separate the bus stop from the school drop-off kerb", "Children, parents' vehicles and buses compete for the same kerb. Put the stop on a different stretch with a protected waiting area.", "Quick fix", SCHOOL_SRC),
  "Hospital zone": _f("Keep the stop clear of the hospital entrance and ambulance route", "Move the stop or its queue away from the entrance so ambulances and patients can get in and out.", "Quick fix", "General practice (not from a Chennai-specific source)"),
  "default": _f("Move the stop a short distance from the corner and mark it clearly", "A marked stop slightly away from the junction reduces conflict with turning vehicles.", "Quick fix", IRC_BUS)},
 "junction": {
  "Main road": _f("Review turning movements and channelise the junction", "Many roads meet here. A turning-count review can show whether islands, marked lanes, banned turns or signal changes would help.", "Needs design study"),
  "Highway": _f("Study consolidating minor side accesses", "Many entry points onto a fast road create conflicts. Merging or closing minor accesses and using service roads reduces them.", "Needs design study"),
  "Commercial street": _f("Simplify the junction: close or make one arm one-way, add a crossing with a refuge", "Dense foot traffic and many arms make this junction slow. Reducing the number of conflicting movements helps both walkers and vehicles.", "Moderate"),
  "School zone": _f("Add a raised crossing and lower speed limit around the junction", "Slow, predictable traffic is the priority near schools.", "Moderate", SCHOOL_SRC),
  "Hospital zone": _f("Mark junction boxes and keep corners clear for emergency vehicles", "Keep the junction free of stopped vehicles so ambulances can pass.", "Quick fix", "General practice (not from a Chennai-specific source)"),
  "default": _f("Add priority markings and a raised table on the minor arms", "Clear priority and slower entry reduce conflicts at busy meeting points.", "Moderate")},
 "signals": {
  "Main road": _f("Coordinate the two signals so vehicles get a continuous green", "Signals this close together cause stop-and-go queues. Linked timing can let platoons pass both.", "Moderate"),
  "Highway": _f("Check whether both signals are needed", "Signals this close on a high-speed road are unusual. Consider removing one or replacing with a controlled crossing.", "Needs design study"),
  "Commercial street": _f("Coordinate timing and combine pedestrian crossing phases", "Walkers and vehicles both lose time. Aligned phases and fewer separate crossings can reduce waiting.", "Moderate"),
  "default": _f("Coordinate the signal timing between the two junctions", "Linked timing reduces repeated stopping.", "Moderate")},
 "lane_drop": {
  "Main road": _f("Extend the lane through the narrowing or add a long merge taper with signs", "Traffic must merge where lanes reduce. Keeping the lane going, or giving a gradual taper with markings, reduces queueing.", "Needs design study"),
  "Highway": _f("Add an advance merge taper with signs and markings", "Lane reductions on fast roads need early warning and a gradual taper.", "Needs design study"),
  "Commercial street": _f("Clear kerb parking at the narrowing so the lane can continue", "Parked vehicles often cause the narrowing. Removing them at that point restores the lane.", "Quick fix"),
  "default": _f("Check the narrowing on site and restore the lane if space allows", "Confirm the lane count on site and look for encroachment.", "Quick fix")},
 "narrow_parking": {
  "Main road": _f("Limit parking to one side or move it to managed bays", "Parking takes space from moving traffic. One-side or bay parking keeps the pinch point open.", "Moderate", "Chennai parking policy: area-level parking management"),
  "Commercial street": _f("Manage kerb parking: paid bays, loading windows, keep the pinch point clear", "Priced and time-limited parking raises turnover and keeps lanes open.", "Moderate", "Chennai parking policy: area-level parking management"),
  "Residential street": _f("Allow parking on one side only, with marked bays", "A single parking side leaves room for two-way movement.", "Quick fix"),
  "School zone": _f("No stopping during school hours and a marked drop-off bay", "Keep the road next to the school clear during drop-off and pick-up.", "Quick fix", SCHOOL_SRC),
  "Hospital zone": _f("Keep an emergency lane clear: no parking along the frontage", "A free lane protects ambulance access.", "Quick fix", "General practice (not from a Chennai-specific source)"),
  "default": _f("Limit parking to one side and mark bays", "Restoring width for moving traffic is the quickest gain.", "Quick fix")},
 "frontage_school": {"default": _f("Mark a pick-up/drop-off bay, keep on-street parking away from the gate, and calm traffic", "School guidelines advise designated drop-off areas, discouraging on-street parking near gates, and traffic calming around the entrance.", "Quick fix", SCHOOL_SRC)},
 "frontage_hospital": {"default": _f("Create a short-stay drop-off bay and a protected ambulance approach", "Patients, visitors and ambulances all need kerb access. Separate them and prevent long-term parking on the frontage.", "Moderate", "General practice (not from a Chennai-specific source)")},
 "frontage_commercial": {"default": _f("Set loading windows, paid parking, and point drivers to nearby off-street parking", "Dense shops attract parking, deliveries and pick-ups all at the same kerb. Timed rules and priced parking free the lane.", "Moderate", "Chennai parking policy: area-level parking management")},
}
KIND_TITLE = {"bus_stop": "Bus stop right at a junction", "junction": "Busy multi-road junction", "signals": "Two traffic signals very close together",
              "lane_drop": "Road narrows (fewer lanes)", "narrow_parking": "Parking squeezes the road", "frontage_school": "School frontage without nearby parking",
              "frontage_hospital": "Hospital frontage without nearby parking", "frontage_commercial": "Busy shopping frontage without nearby parking"}
KIND_W = {"lane_drop": 5, "junction": 4, "narrow_parking": 4, "signals": 3, "bus_stop": 3, "frontage_school": 2, "frontage_hospital": 2, "frontage_commercial": 2}
CLASS_W = {"Highway": 3, "Main road": 3, "Commercial street": 3, "School zone": 3, "Hospital zone": 3, "Connector road": 2, "Residential street": 1, "Service lane": 0}
TYPE_NOTES = {
 "Highway": ("Fast through traffic, few stops", "Protect speed and safety: set-back bus bays, fewer side accesses, merge tapers."),
 "Main road": ("Mixed traffic, buses, many junctions", "Keep traffic moving: bus bays or far-side stops, signal coordination, turn control."),
 "Commercial street": ("Shops, walkers, deliveries, parking", "Manage kerb space: loading windows, paid parking, crossings, simpler junctions."),
 "School zone": ("Children, drop-off peaks", "Slow and separate: drop-off bays, traffic calming, no on-street parking near gates."),
 "Hospital zone": ("Ambulances, patients, short stays", "Keep access clear: emergency lane, short-stay bay, no parking on the frontage."),
 "Connector road": ("Links between main roads and neighbourhoods", "Light-touch fixes: marking stops and junctions, one-side parking."),
 "Residential street": ("Local access, slow speeds", "Calm and prioritise: raised tables, one-side parking, clear priority."),
 "Service lane": ("Access to buildings, often excluded", "Usually left alone in this prototype."),
}

def fix_for(kind, rtype):
    tbl = FIX[kind]; return tbl.get(rtype) or tbl["default"]

# ---------- analysis ----------
def analyze(snap, P=None, ovr=None):
    P = {**DEFAULTS, **(P or {})}; ovr = ovr or {}
    els = snap["elements"]
    ways = [e for e in els if e["type"] == "way" and "geometry" in e and "highway" in e.get("tags", {})]
    if not P["include_service"]: ways = [w for w in ways if w["tags"]["highway"] != "service"]
    pts = [(g["lat"], g["lon"]) for w in ways for g in w["geometry"]]
    empty = dict(segments=[], bottlenecks=[], streets=[], summary={"n": 0}, params=P, bus=[], junction_clusters=[])
    if not pts: return empty
    lat0 = sum(p[0] for p in pts)/len(pts); lon0 = sum(p[1] for p in pts)/len(pts)
    proj = _mk_proj(lat0, lon0)

    def cen(e): return (e["lat"], e["lon"]) if e["type"] == "node" else (e["center"]["lat"], e["center"]["lon"])
    poi = {"school": [], "hospital": [], "market": [], "shop": [], "parking": []}
    bus, sigs = [], []
    for e in els:
        if e["type"] == "way" and "geometry" in e: continue
        t = e.get("tags", {})
        if e["type"] == "way" and "center" not in e: continue
        ll = cen(e); xy = proj(*ll)
        item = dict(id=e["id"], name=t.get("name"), ll=ll, xy=xy)
        if t.get("highway") == "bus_stop": bus.append(item)
        elif t.get("highway") == "traffic_signals": sigs.append(item)
        elif t.get("amenity") in ("school", "kindergarten", "college"): poi["school"].append(item)
        elif t.get("amenity") == "hospital" or t.get("healthcare") == "hospital": poi["hospital"].append(item)
        elif t.get("amenity") == "marketplace": poi["market"].append(item)
        elif t.get("amenity") == "parking": poi["parking"].append(item)
        elif "shop" in t: poi["shop"].append(item)

    deg, nxy, nll, node_ways = {}, {}, {}, {}
    for w in ways:
        ns = w["nodes"]
        for i, (n, g) in enumerate(zip(ns, w["geometry"])):
            deg[n] = deg.get(n, 0) + (1 if i in (0, len(ns)-1) else 2)
            nxy[n] = proj(g["lat"], g["lon"]); nll[n] = (g["lat"], g["lon"]); node_ways.setdefault(n, []).append(w["id"])
    jn = [n for n, d in deg.items() if d >= 3]

    segs = {}
    for w in ways:
        t = w["tags"]; poly = [proj(g["lat"], g["lon"]) for g in w["geometry"]]
        L = sum(_d(a, b) for a, b in zip(poly, poly[1:]))
        o = ovr.get(str(w["id"]), {})
        wv, wst = parse_width(t.get("width")); wsrc = "Map tag"
        if "width" in o: wv, wst, wsrc = float(o["width"]), "manual", f"Local entry: {o.get('source','')}"
        ps = {s: _side_state(t, s) for s in ("left", "right")}; psrc = "Map tags"
        if "parking_sides" in o:
            kind = o.get("parking_type", "parallel"); st_ = "none" if o["parking_sides"] == 0 else f"lane:{kind}"
            ps = {"left": st_, "right": st_ if o["parking_sides"] == 2 else "none"}; psrc = f"Local entry: {o.get('source','')}"
        known = any(v != "unknown" for v in ps.values())
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        segs[w["id"]] = dict(
            id=w["id"], name=t.get("name") or "", highway=t["highway"], base=BASE.get(t["highway"], "Connector road"),
            length=L, oneway=t.get("oneway") in ("yes", "1", "true", "-1"), coords=[(g["lat"], g["lon"]) for g in w["geometry"]],
            poly=poly, bbox=(min(xs), min(ys), max(xs), max(ys)), nodes=w["nodes"], lanes=parse_int(t.get("lanes")), width=wv,
            inputs={"width_m": dict(value=wv, status=wst, source=wsrc), "parking": dict(value=ps, status="manual" if psrc.startswith("Local") else ("mapped" if known else "missing"), source=psrc),
                    "lanes": dict(value=t.get("lanes"), status="mapped" if t.get("lanes") else "missing", source="Map tag"),
                    "oneway": dict(value=t.get("oneway"), status="mapped" if "oneway" in t else "missing", source="Map tag")},
            tags={k: t.get(k) for k in ("name", "width", "lanes", "oneway", "maxspeed", "surface", "sidewalk") if t.get(k)},
            parking_known=known, lane_sides=[v for v in ps.values() if v.startswith("lane:")], zones=[], reasons=[])
    S = list(segs.values())

    # road type: base class + surroundings
    for s in S:
        s["reasons"].append(f"Map classifies it as '{s['highway']}', so a {s['base'].lower()}.")
        if s["base"] == "Highway": s["type"] = "Highway"; continue
        near = lambda items, r: [(it, d) for it in items for d in [ _near(it["xy"], s, r)] if d is not None]
        sc = near(poi["school"], P["school_m"]); hs = near(poi["hospital"], P["hospital_m"])
        mk = near(poi["market"], P["market_m"]); shops = [1 for it in poi["shop"] if _near(it["xy"], s, P["shop_radius_m"]) is not None]
        s["shops"] = len(shops)
        if hs: s["zones"].append("Hospital zone"); s["reasons"].append(f"A hospital is mapped within {P['hospital_m']} m ({hs[0][0]['name'] or 'unnamed'}).")
        if sc: s["zones"].append("School zone"); s["reasons"].append(f"A school or college is mapped within {P['school_m']} m ({sc[0][0]['name'] or 'unnamed'}).")
        if mk or len(shops) >= P["shops_commercial"]:
            s["zones"].append("Commercial street"); s["reasons"].append(f"{len(shops)} shops mapped within {P['shop_radius_m']} m" + (" and a market nearby." if mk else "."))
        s["type"] = next((z for z in ("Hospital zone", "School zone", "Commercial street") if z in s["zones"]), s["base"])
    for s in S: s.setdefault("shops", 0)

    # bus stops -> segments
    for b in bus:
        best = None
        for s in S:
            d = _near(b["xy"], s, P["attach_m"])
            if d is not None and (best is None or d < best[0]): best = (d, s["id"])
        b["seg"] = best[1] if best else None

    B = []
    def add(kind, ll, seg, why, evidence, missing, conf, rtype=None, road=None):
        rt = rtype or (seg["type"] if seg else "Connector road")
        fk = kind
        fx = fix_for(fk, rt)
        B.append(dict(kind=kind, title=KIND_TITLE[kind], ll=ll, road=road or (seg["name"] if seg and seg["name"] else "Unnamed road"),
                      rtype=rt, conf=conf, why=why, fix=fx, evidence=evidence, missing=missing, seg=seg["id"] if seg else None,
                      score=KIND_W[kind] + CLASS_W.get(rt, 1) + (2 if conf == "map" else 1)))

    # junction clusters
    cell = {}
    for n in jn: cell.setdefault((int(nxy[n][0]//P["cluster_m"]), int(nxy[n][1]//P["cluster_m"])), []).append(n)
    par = {n: n for n in jn}
    def find(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    for n in jn:
        cx, cy = int(nxy[n][0]//P["cluster_m"]), int(nxy[n][1]//P["cluster_m"])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for m in cell.get((cx+dx, cy+dy), []):
                    if m != n and _d(nxy[n], nxy[m]) <= P["cluster_m"]: par[find(n)] = find(m)
    cl = {}
    for n in jn: cl.setdefault(find(n), []).append(n)
    cof = {n: r for r, ns in cl.items() for n in ns}
    arms = {r: [] for r in cl}
    for w in ways:
        ns = w["nodes"]
        for i, n in enumerate(ns):
            r = cof.get(n)
            if r is None: continue
            for j in (i-1, i+1):
                if 0 <= j < len(ns) and cof.get(ns[j]) != r: arms[r].append(w)
    jc = []
    for r, ns in cl.items():
        a = arms[r]
        ll = (sum(nll[n][0] for n in ns)/len(ns), sum(nll[n][1] for n in ns)/len(ns))
        jc.append(dict(ll=ll, arms=len(a)))
        if len(a) >= P["arms_min"] and any(w["tags"]["highway"] in MAJOR for w in a):
            top = max(a, key=lambda w: ["service", "living_street", "residential", "unclassified", "tertiary", "secondary", "primary", "trunk", "motorway"].index(w["tags"]["highway"]) if w["tags"]["highway"] in ["service", "living_street", "residential", "unclassified", "tertiary", "secondary", "primary", "trunk", "motorway"] else 0)
            sg = segs[top["id"]]
            sig = any(_d(nxy[ns[0]], q["xy"]) < 30 for q in sigs)
            add("junction", ll, sg, f"{len(a)} road arms meet within about {P['cluster_m']} m here{' (signalised)' if sig else ''}. Junctions with many arms are harder to move through and usually need turn control.",
                [f"Cluster of {len(ns)} junction node(s), {len(a)} arms.", f"Largest road: {sg['name'] or 'unnamed'} ({sg['highway']})."],
                ["Turning volumes", "Signal timings and markings", "Whether the map splits one real junction into several"], "map")

    # bus stop near junction
    for b in bus:
        if not b["seg"] or not jn: continue
        d, n = min((_d(b["xy"], nxy[n]), n) for n in jn)
        if d <= P["bus_junction_m"]:
            sg = segs[b["seg"]]
            add("bus_stop", b["ll"], sg, f"A bus stop is mapped only {d:.0f} m from a junction on {sg['name'] or 'this road'}. Buses stopping there can block turning and through traffic.",
                [f"Bus stop {b['name'] or '(unnamed)'} is {d:.0f} m from a junction node (limit used: {P['bus_junction_m']} m)."],
                ["Actual stopping position and dwell time", "Which direction the stop serves", "Passenger numbers"], "map")

    # close signals
    sc, scl = [], []
    for s_ in sigs:
        for c in sc:
            if _d(c["xy"], s_["xy"]) < 25: break
        else: sc.append(s_)
    def nearest_seg(xy, r=40):
        best = None
        for s in S:
            d = _near(xy, s, r)
            if d is not None and (best is None or d < best[0]): best = (d, s)
        return best[1] if best else None
    for i, a in enumerate(sc):
        for b in sc[i+1:]:
            d = _d(a["xy"], b["xy"])
            if 25 <= d <= P["signal_gap_m"]:
                sa, sb = nearest_seg(a["xy"]), nearest_seg(b["xy"])
                if sa and sb and sa["name"] and sa["name"] == sb["name"]:
                    add("signals", ((a["ll"][0]+b["ll"][0])/2, (a["ll"][1]+b["ll"][1])/2), sa,
                        f"Two traffic signals on {sa['name']} are only {d:.0f} m apart, so vehicles may have to stop at both.",
                        [f"Signal nodes {d:.0f} m apart (limit used: {P['signal_gap_m']} m)."], ["Signal timings and coordination", "Queue lengths"], "map")

    # lane drop
    for n, wl in node_ways.items():
        if len(wl) < 2: continue
        grp = [segs[i] for i in wl if i in segs and segs[i]["name"] and segs[i]["lanes"]]
        for i, a in enumerate(grp):
            for b in grp[i+1:]:
                if a["name"] == b["name"] and a["id"] != b["id"] and abs(a["lanes"] - b["lanes"]) >= 1:
                    hi, lo = (a, b) if a["lanes"] > b["lanes"] else (b, a)
                    add("lane_drop", nll[n], lo, f"On {a['name']} the map shows {hi['lanes']} lanes on one side of this point and {lo['lanes']} on the other, so traffic must merge.",
                        [f"lanes={hi['lanes']} (way {hi['id']}) vs lanes={lo['lanes']} (way {lo['id']})."], ["Whether the lane tags are accurate", "Direction of travel affected"], "map")

    # parking squeezing the road (needs width + parking)
    blocked_parking = 0
    for s in S:
        if not s["parking_known"]: blocked_parking += 1; continue
        if not s["lane_sides"]: continue
        ded = sum({"lane:parallel": P["parallel_w"], "lane:diagonal": P["angled_w"], "lane:perpendicular": P["perp_w"]}[v] for v in s["lane_sides"])
        if s["width"]:
            mv = s["width"] - ded if P["width_includes_parking"] else s["width"]
            thr = P["min_moving_one_way"] if s["oneway"] else P["min_moving_two_way"]
            s["moving_width"] = mv
            if mv < thr:
                mid = s["coords"][len(s["coords"])//2]
                add("narrow_parking", mid, s, f"Parking is mapped on the carriageway of {s['name'] or 'this road'}, leaving about {mv:.1f} m for moving traffic (the prototype flags anything under {thr:.1f} m).",
                    [f"Width {s['width']:.1f} m minus assumed parking {ded:.1f} m = {mv:.1f} m."], ["Whether vehicles are actually parked there", "Measured kerb-to-kerb width"], "map")

    # frontage pressure (inferred from surroundings)
    def parking_near(xy, r): return any(_d(xy, p["xy"]) <= r for p in poi["parking"])
    for kind, key, nm in (("frontage_school", "school", "school or college"), ("frontage_hospital", "hospital", "hospital")):
        for a in poi[key]:
            sg = None; bd = 1e9
            for s in S:
                d = _near(a["xy"], s, P["anchor_road_m"])
                if d is not None and d < bd and s["base"] not in ("Highway", "Service lane"): bd, sg = d, s
            if sg and not parking_near(a["xy"], P["parking_near_m"]):
                add(kind, a["ll"], sg, f"{a['name'] or 'A ' + nm} is on {sg['name'] or 'this road'} and no parking area is mapped within {P['parking_near_m']} m. Pick-ups, drop-offs and short stops may therefore happen at the kerb.",
                    [f"{nm.capitalize()} mapped {bd:.0f} m from the road.", "No mapped parking facility nearby (the map may be incomplete)."],
                    ["Actual drop-off behaviour and timing", "Unmapped parking or internal drop-off areas"], "inferred")
    cands = [s for s in S if s["type"] == "Commercial street" and s["shops"] >= P["shops_commercial"] and s["base"] != "Highway"]
    cands.sort(key=lambda s: -s["shops"]); kept = []
    for s in cands:
        mid = s["poly"][len(s["poly"])//2]
        if parking_near(mid, 120): continue
        if any(_d(mid, k[1]) < 120 for k in kept): continue
        kept.append((s, mid))
    for s, mid in kept:
        add("frontage_commercial", s["coords"][len(s["coords"])//2], s, f"About {s['shops']} shops are mapped along {s['name'] or 'this street'} and no parking area is mapped within 120 m, so parking, deliveries and pick-ups probably compete for the kerb.",
            [f"{s['shops']} shops within {P['shop_radius_m']} m of the segment.", "No mapped parking facility within 120 m."], ["Actual kerb use and loading activity", "Unmapped parking"], "inferred")

    B.sort(key=lambda b: -b["score"])
    for i, b in enumerate(B, 1): b["no"] = i

    # streets table
    st_ = {}
    for s in S:
        if not s["name"] or s["base"] == "Service lane": continue
        g = st_.setdefault(s["name"], dict(name=s["name"], length=0.0, types={}, n=0, w=0, l=0, p=0))
        g["length"] += s["length"]; g["types"][s["type"]] = g["types"].get(s["type"], 0) + s["length"]; g["n"] += 1
        g["w"] += bool(s["width"]); g["l"] += bool(s["lanes"]); g["p"] += s["parking_known"]
    streets = []
    for g in st_.values():
        nb = sum(1 for b in B if b["road"] == g["name"])
        streets.append(dict(name=g["name"], type=max(g["types"], key=g["types"].get), length=g["length"], bottlenecks=nb,
                            width_pct=100*g["w"]/g["n"], lanes_pct=100*g["l"]/g["n"], parking_pct=100*g["p"]/g["n"]))
    streets.sort(key=lambda g: -g["length"])

    km_by = {}
    for s in S: km_by[s["type"]] = km_by.get(s["type"], 0) + s["length"]/1000
    n = len(S)
    summary = dict(n=n, km=sum(s["length"] for s in S)/1000, km_by_type=km_by, n_bus=len(bus), n_signals=len(sc), n_junction_clusters=len(jc),
                   n_schools=len(poi["school"]), n_hospitals=len(poi["hospital"]), n_shops=len(poi["shop"]), n_parking=len(poi["parking"]),
                   cov={k: sum(1 for s in S if f(s)) for k, f in [("name", lambda s: s["name"]), ("width", lambda s: s["width"]), ("lanes", lambda s: s["lanes"]),
                        ("oneway", lambda s: s["inputs"]["oneway"]["status"] == "mapped"), ("parking tags", lambda s: s["parking_known"]),
                        ("surface", lambda s: s["tags"].get("surface")), ("sidewalk", lambda s: s["tags"].get("sidewalk"))]},
                   by_kind={k: sum(1 for b in B if b["kind"] == k) for k in KIND_TITLE},
                   narrow_checkable=sum(1 for s in S if s["parking_known"] and s["width"]),
                   lane_checkable=sum(1 for s in S if s["lanes"]))
    return dict(segments=S, bottlenecks=B, streets=streets, summary=summary, params=P, bus=bus, junction_clusters=jc)

def report_html(area, snap, B):
    e = html.escape; rows = ""
    for b in B:
        f = b["fix"]
        rows += (f"<div class='b'><h3>#{b['no']} {e(b['title'])}</h3><p><b>{e(b['road'])}</b> | {e(b['rtype'])} | "
                 f"{'Shown by map data' if b['conf']=='map' else 'Inferred from nearby places'}</p><p>{e(b['why'])}</p>"
                 f"<p><b>Suggested fix ({e(f['scale'])}):</b> {e(f['title'])}. {e(f['text'])}</p><p><small>Not checked: {e(', '.join(b['missing']))}</small></p></div>")
    return ("<html><head><meta charset='utf-8'><style>@page{size:A4;margin:15mm}body{font-family:Arial;font-size:10.5pt}.b{border-left:4px solid #c60;padding-left:8px;margin:12px 0;page-break-inside:avoid}"
            "small{color:#555}.n{background:#eee;padding:6px}</style></head><body>"
            f"<h1>RoadLens: bottlenecks and suggested fixes</h1><p>Area: {e(area)} | Map data retrieved: {e(snap['retrieved'])} | {len(B)} potential bottlenecks</p>{rows}"
            "<p class='n'>Screening prototype built from open map data (OpenStreetMap). Not field-validated. Fixes are suggestions for the road authority to assess, not engineering designs.</p></body></html>")

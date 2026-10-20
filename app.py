
import datetime as dt
import pandas as pd, streamlit as st, folium
from streamlit_folium import st_folium
import core

st.set_page_config(page_title="RoadLens Chennai", page_icon="🛣️", layout="wide")
ss = st.session_state
st.markdown("""<style>
.block-container{padding-top:1.4rem;max-width:1250px}
.tag{display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.8rem;margin-right:6px;color:white}
.t-map{background:#b23a2e}.t-inf{background:#c9801b}.t-q{background:#2e7d4f}.t-m{background:#a8741a}.t-s{background:#6b4aa8}
.small{color:#666;font-size:0.85rem}
</style>""", unsafe_allow_html=True)

TYPE_COL = {"Highway": "#8b1a1a", "Main road": "#d9531e", "Commercial street": "#8e44ad", "School zone": "#1f77b4", "Hospital zone": "#e91e63",
            "Connector road": "#e0a800", "Residential street": "#5aa469", "Service lane": "#999999"}
SCALE_CLS = {"Quick fix": "t-q", "Moderate": "t-m", "Needs design study": "t-s"}
P = {k: ss.get("p_" + k, v) for k, v in core.DEFAULTS.items()}

@st.cache_data(show_spinner="Analysing the area...")
def run(key, pj, oj, retrieved):
    return core.analyze(core.load_snapshot(key), __import__("json").loads(pj), __import__("json").loads(oj))

def start(name, bbox, key):
    try:
        if not (core.DATA / f"{key}.json").exists():
            with st.spinner("Downloading map data for this area (about 20 to 60 seconds)..."):
                core.fetch_snapshot(key, name, bbox)
        ss["area"] = key; ss.pop("bsel", None); st.rerun()
    except Exception as ex:
        st.error(str(ex))

# ------------------------------------------------ HOME
if not ss.get("area"):
    st.title("🛣️ RoadLens Chennai")
    st.markdown("**Pick an area of Chennai. RoadLens tells you what kind of roads it has, where traffic is likely to get stuck, and one suggested fix for each spot.**")
    c1, c2, c3 = st.columns(3)
    c1.info("**1. Pick an area**\n\nSearch, click the map, or choose a ready-made area.")
    c2.info("**2. See the road types**\n\nHighway, main road, shopping street, school or hospital zone.")
    c3.info("**3. Get bottlenecks and fixes**\n\nOne suggestion per spot, matched to the road type.")
    areas = core.list_areas()
    st.subheader("Popular areas")
    cols = st.columns(max(1, min(6, len(areas))))
    for i, (k, v) in enumerate(areas.items()):
        if cols[i % len(cols)].button(v["name"], key="q_" + k, use_container_width=True): start(v["name"], tuple(v["bbox"]), k)
    st.subheader("Or search any place in Chennai")
    q = st.text_input("Locality or landmark", placeholder="e.g. Besant Nagar, Perambur, Koyambedu bus stand")
    if st.button("Analyse this area", type="primary") and q.strip():
        try:
            bb, disp = core.geocode(q.strip()); start(q.strip().title(), bb, core.slug(q))
        except Exception as ex: st.error(str(ex))
    st.subheader("Or click on the map")
    m = folium.Map(location=[13.05, 80.24], zoom_start=11, tiles="OpenStreetMap")
    out = st_folium(m, height=380, use_container_width=True, returned_objects=["last_clicked"], key="homemap")
    lc = (out or {}).get("last_clicked")
    if lc:
        lat, lon = lc["lat"], lc["lng"]
        if core.in_chennai(lat, lon):
            st.write(f"Selected point: {lat:.4f}, {lon:.4f}. RoadLens will study a box of about 2 km by 2 km around it.")
            if st.button("Analyse around this point", type="primary"):
                start(f"Area near {lat:.3f}, {lon:.3f}", core.box_around(lat, lon), core.slug(f"near_{lat:.3f}_{lon:.3f}"))
        else: st.warning("That point is outside Chennai.")
    st.caption("The first visit to an area downloads its map data (internet needed). After that it is saved on your computer and works offline. Map data © OpenStreetMap contributors.")
    st.stop()

# ------------------------------------------------ ANALYSIS
import json
key = ss["area"]; snap = core.load_snapshot(key); ovr = core.load_overrides()
R = run(key, json.dumps(P, sort_keys=True), json.dumps(ovr, sort_keys=True), snap["retrieved"])
S, B, SM = R["segments"], R["bottlenecks"], R["summary"]
top = st.columns([6, 1])
top[0].title(f"🛣️ {snap['name']}")
if top[1].button("← Change area"): ss.pop("area"); st.rerun()
st.caption(f"Map data retrieved {snap['retrieved']} · screening result, not field-validated")
if SM["n"] == 0: st.error("No roads were found in this box. Try another area."); st.stop()

tabs = st.tabs(["Overview", "Bottlenecks & fixes", "Road types", "Technical details"])

# ---- Overview
with tabs[0]:
    wpct = 100 * SM["cov"]["width"] / SM["n"]; lpct = 100 * SM["cov"]["lanes"] / SM["n"]
    quality = "Good" if wpct >= 50 else ("Limited" if wpct >= 15 else "Poor")
    m = st.columns(4)
    m[0].metric("Possible bottlenecks", len(B)); m[1].metric("Road length studied", f"{SM['km']:.0f} km")
    m[2].metric("Map data quality", quality); m[3].metric("Schools / hospitals mapped", f"{SM['n_schools']} / {SM['n_hospitals']}")
    if quality != "Good":
        st.warning(f"**Not enough data for some checks.** Only {wpct:.0f}% of road segments have a recorded width and {lpct:.0f}% have a recorded lane count. Narrow-road and lane-drop checks could only be done where those details exist. See the 'Not enough data' list under Bottlenecks & fixes.")
    st.subheader("What kind of roads are here?")
    df = pd.DataFrame([{"Road type": t, "km": round(v, 1)} for t, v in sorted(SM["km_by_type"].items(), key=lambda x: core.TYPE_ORDER.index(x[0]))])
    c1, c2 = st.columns([3, 2]); c1.bar_chart(df.set_index("Road type")["km"]); c2.dataframe(df, hide_index=True, use_container_width=True)
    st.subheader("Bottlenecks found, by kind")
    kd = pd.DataFrame([{"Kind": core.KIND_TITLE[k], "Count": v} for k, v in SM["by_kind"].items() if v])
    st.dataframe(kd, hide_index=True, use_container_width=True) if len(kd) else st.info("No bottlenecks were detected from the available data.")
    st.markdown("**How to read this.** *Shown by map data* means the map itself contains the evidence (for example two signals 80 m apart). *Inferred from nearby places* means we are guessing from land use (for example many shops and no parking area). Both need a site visit before anyone acts.")

# ---- Bottlenecks
with tabs[1]:
    f1, f2 = st.columns(2)
    types = sorted({b["rtype"] for b in B}, key=core.TYPE_ORDER.index)
    pick_t = f1.multiselect("Road type", types, default=types)
    pick_c = f2.multiselect("Evidence", ["Shown by map data", "Inferred from nearby places"], default=["Shown by map data", "Inferred from nearby places"])
    show = [b for b in B if b["rtype"] in pick_t and (("Shown by map data" if b["conf"] == "map" else "Inferred from nearby places") in pick_c)]
    topn = st.slider("How many to show (highest priority first)", 5, max(6, len(show)), min(15, max(6, len(show)))) if len(show) > 5 else len(show)
    show = show[:topn]
    if not show: st.info("Nothing to show with these filters.")
    else:
        m = folium.Map(location=[sum(b["ll"][0] for b in show)/len(show), sum(b["ll"][1] for b in show)/len(show)], zoom_start=15, tiles="OpenStreetMap")
        for s in S: folium.PolyLine(s["coords"], color=TYPE_COL.get(s["type"], "#888"), weight=3, opacity=0.55).add_to(m)
        for b in show:
            col = "#b23a2e" if b["conf"] == "map" else "#c9801b"
            icon = folium.DivIcon(html=f'<div style="background:{col};color:#fff;border-radius:50%;width:26px;height:26px;line-height:26px;text-align:center;font-weight:bold;border:2px solid #fff">{b["no"]}</div>', icon_size=(26, 26), icon_anchor=(13, 13))
            folium.Marker(b["ll"], icon=icon, tooltip=f"#{b['no']} {b['title']}").add_to(m)
        out = st_folium(m, height=470, use_container_width=True, returned_objects=["last_object_clicked"], key="bmap")
        st.markdown('<span class="tag t-map">Shown by map data</span><span class="tag t-inf">Inferred from nearby places</span> <span class="small">Line colours show road type (see Road types tab).</span>', unsafe_allow_html=True)
        lo = (out or {}).get("last_object_clicked")
        if lo:
            nb = min(show, key=lambda b: (b["ll"][0]-lo["lat"])**2 + (b["ll"][1]-lo["lng"])**2)
            if (nb["ll"][0]-lo["lat"])**2 + (nb["ll"][1]-lo["lng"])**2 < 4e-7: ss["bsel"] = nb["no"]
        sel = ss.get("bsel")
        order = sorted(show, key=lambda b: (b["no"] != sel, b["no"]))
        for b in order:
            f = b["fix"]
            with st.container(border=True):
                st.markdown(f"### #{b['no']} {b['title']}" + ("  ← selected on map" if b["no"] == sel else ""))
                st.markdown(f"**{b['road']}** · {b['rtype']} " + f"<span class='tag {'t-map' if b['conf']=='map' else 't-inf'}'>{'Shown by map data' if b['conf']=='map' else 'Inferred from nearby places'}</span>", unsafe_allow_html=True)
                st.write(b["why"])
                st.markdown(f"**Suggested fix:** {f['title']} <span class='tag {SCALE_CLS[f['scale']]}'>{f['scale']}</span>", unsafe_allow_html=True)
                st.write(f["text"])
                if f["source"]: st.caption(f"Basis: {f['source']}")
                st.caption("Could not check: " + "; ".join(b["missing"]))
    st.divider()
    st.subheader("Not enough data to check")
    weak = [s for s in R["streets"] if s["width_pct"] == 0 and s["lanes_pct"] == 0 and s["length"] >= 200 and s["type"] != "Residential street"]
    st.write(f"Narrow-road checks need both width and parking tags: possible on only **{SM['narrow_checkable']}** of {SM['n']} segments. Lane-drop checks need lane counts: possible on **{SM['lane_checkable']}** segments.")
    if weak:
        wd = pd.DataFrame([{"Street": s["name"], "Road type": s["type"], "Length (m)": round(s["length"]), "Missing": "width, lanes" + ("" if s["parking_pct"] else ", parking")} for s in weak[:25]])
        st.dataframe(wd, hide_index=True, use_container_width=True)
        st.caption("These streets are flagged as 'insufficient data': we could not test them for narrowing. Add local data in Technical details or survey them.")
    st.download_button("Download all bottlenecks as an A4 note (HTML, print to PDF)", core.report_html(snap["name"], snap, B), file_name="roadlens_bottlenecks.html", mime="text/html")
    st.download_button("Download bottlenecks as CSV", pd.DataFrame([{"No": b["no"], "Problem": b["title"], "Road": b["road"], "Road type": b["rtype"], "Evidence": b["conf"], "Why": b["why"], "Fix": b["fix"]["title"], "Fix size": b["fix"]["scale"], "Lat": b["ll"][0], "Lon": b["ll"][1]} for b in B]).to_csv(index=False), file_name="roadlens_bottlenecks.csv")

# ---- Road types
with tabs[2]:
    st.write("Different road types need different solutions, so RoadLens first works out the type of each road, then picks the fix to match.")
    m = folium.Map(location=[sum(b[0] for s in S for b in [s["coords"][0]])/len(S), sum(b[1] for s in S for b in [s["coords"][0]])/len(S)], zoom_start=15, tiles="OpenStreetMap")
    for s in S:
        folium.PolyLine(s["coords"], color=TYPE_COL.get(s["type"], "#888"), weight=4, opacity=0.8, tooltip=f"{s['name'] or 'Unnamed'}: {s['type']}").add_to(m)
    st_folium(m, height=450, use_container_width=True, returned_objects=[], key="tmap")
    st.markdown(" ".join(f"<span class='tag' style='background:{TYPE_COL[t]}'>{t}</span>" for t in core.TYPE_ORDER if t in SM["km_by_type"]), unsafe_allow_html=True)
    st.subheader("Why fixes differ by road type")
    st.dataframe(pd.DataFrame([{"Road type": t, "What it is like": a, "Fix approach": b, "km here": round(SM["km_by_type"].get(t, 0), 1)} for t, (a, b) in core.TYPE_NOTES.items()]), hide_index=True, use_container_width=True)
    st.subheader("Streets in this area")
    sd = pd.DataFrame([{"Street": s["name"], "Road type": s["type"], "Length (m)": round(s["length"]), "Bottlenecks": s["bottlenecks"], "Data completeness": "Good" if s["width_pct"] >= 50 else ("Partial" if s["width_pct"] + s["lanes_pct"] > 0 else "Insufficient")} for s in R["streets"]])
    st.dataframe(sd, hide_index=True, use_container_width=True)
    st.subheader("Why is a road given this type?")
    ex = st.selectbox("Pick a street", [s["name"] for s in R["streets"]]) if R["streets"] else None
    if ex:
        seg = next(s for s in S if s["name"] == ex)
        for r in seg["reasons"]: st.write("- " + r)

# ---- Technical
with tabs[3]:
    t1, t2, t3, t4, t5 = st.tabs(["Data coverage", "Settings", "Add local data", "How it works", "Limits"])
    with t1:
        cov = pd.DataFrame([{"Input": k, "Segments with value": v, "Coverage %": round(100 * v / SM["n"], 1)} for k, v in SM["cov"].items()])
        st.dataframe(cov, hide_index=True, use_container_width=True); st.bar_chart(cov.set_index("Input")["Coverage %"])
        st.write(f"Counts: {SM['n']} segments, {SM['n_bus']} bus stops, {SM['n_signals']} signal sites, {SM['n_junction_clusters']} junction clusters, {SM['n_schools']} schools/colleges, {SM['n_hospitals']} hospitals, {SM['n_shops']} shops, {SM['n_parking']} parking areas.")
        st.dataframe(pd.DataFrame([{"Way ID": s["id"], "Name": s["name"], "Map class": s["highway"], "Road type": s["type"], "Length (m)": round(s["length"]), "Width": s["width"], "Lanes": s["lanes"], "Parking known": s["parking_known"], "Shops nearby": s["shops"]} for s in S]), hide_index=True, use_container_width=True)
    with t2:
        st.caption("All thresholds are assumptions for screening, not official standards. Changing one recalculates everything.")
        a, b_, c_ = st.columns(3)
        a.number_input("Parallel parking width (m)", 0.5, 4.0, core.DEFAULTS["parallel_w"], 0.1, key="p_parallel_w")
        a.number_input("Angled parking width (m)", 1.0, 6.0, core.DEFAULTS["angled_w"], 0.1, key="p_angled_w")
        a.number_input("Perpendicular parking width (m)", 1.0, 7.0, core.DEFAULTS["perp_w"], 0.1, key="p_perp_w")
        a.checkbox("Map width includes parking lanes", core.DEFAULTS["width_includes_parking"], key="p_width_includes_parking")
        b_.number_input("Min moving width, two-way (m)", 3.0, 9.0, core.DEFAULTS["min_moving_two_way"], 0.1, key="p_min_moving_two_way")
        b_.number_input("Min moving width, one-way (m)", 2.0, 6.0, core.DEFAULTS["min_moving_one_way"], 0.1, key="p_min_moving_one_way")
        b_.number_input("Bus stop to junction limit (m)", 10, 100, core.DEFAULTS["bus_junction_m"], 5, key="p_bus_junction_m")
        b_.number_input("Signals closer than (m)", 40, 400, core.DEFAULTS["signal_gap_m"], 10, key="p_signal_gap_m")
        c_.number_input("Junction merge distance (m)", 5, 50, core.DEFAULTS["cluster_m"], 5, key="p_cluster_m")
        c_.number_input("Min arms for a busy junction", 4, 8, core.DEFAULTS["arms_min"], 1, key="p_arms_min")
        c_.number_input("School zone radius (m)", 30, 300, core.DEFAULTS["school_m"], 10, key="p_school_m")
        c_.number_input("Hospital zone radius (m)", 30, 300, core.DEFAULTS["hospital_m"], 10, key="p_hospital_m")
        c_.number_input("Shops needed for a commercial street", 2, 30, core.DEFAULTS["shops_commercial"], 1, key="p_shops_commercial")
        c_.checkbox("Include service lanes", core.DEFAULTS["include_service"], key="p_include_service")
    with t3:
        st.write("Enter a width or parking arrangement you can source (survey, official drawing, news report). It is labelled 'Local entry' everywhere.")
        opts = {f"{s['name'] or 'Unnamed'} (way {s['id']}, {round(s['length'])} m)": s["id"] for s in S}
        ch = st.selectbox("Road segment", list(opts))
        w_ = st.number_input("Carriageway width (m), 0 = leave unknown", 0.0, 30.0, 0.0, 0.5)
        ps_ = st.selectbox("Parking on carriageway", ["Leave unknown", "None", "One side", "Both sides"])
        pt_ = st.selectbox("Parking type", ["parallel", "diagonal", "perpendicular"])
        src_ = st.text_input("Source (required)")
        if st.button("Save entry"):
            if not src_.strip(): st.error("A source is required.")
            else:
                o = core.load_overrides(); e = {"source": src_.strip()}
                if w_ > 0: e["width"] = w_
                if ps_ != "Leave unknown": e["parking_sides"] = {"None": 0, "One side": 1, "Both sides": 2}[ps_]; e["parking_type"] = pt_
                o[str(opts[ch])] = e; core.save_overrides(o); st.success("Saved. Results updated."); st.rerun()
        if ovr: st.json(ovr)
    with t4:
        st.markdown("""
**Pipeline.** Map data (OpenStreetMap) for a 2 km box is downloaded and saved. Each mapped road piece is a *segment*.

**Road type.** Start from the map's road class (highway, main road, connector, residential, service). Then add a *zone* if a hospital or school/college is mapped within the set radius, or if enough shops or a market are nearby. Zone beats class, in this order: hospital, school, commercial. Highways are never re-labelled.

**Bottleneck checks.**
- *Bus stop at junction:* a bus stop attached to a road and within the set distance of a junction.
- *Busy junction:* nodes within the merge distance form one junction; it counts if enough road arms leave it and at least one is a main or connector road.
- *Close signals:* two signal sites closer than the set distance on the same named road.
- *Lane drop:* the same named road has different lane counts on either side of a shared point.
- *Parking squeezes road:* needs width and parking tags; moving width = width minus assumed parking space.
- *Frontage pressure (inferred):* school, hospital or dense shops with no mapped parking area nearby.

**Fixes.** One suggestion per bottleneck, chosen from a table keyed on bottleneck kind and road type. Each carries a size: *Quick fix*, *Moderate*, or *Needs design study*. Sources noted where one exists (IRC bus-stop guidance, school-zone guidelines, Chennai parking policy); the rest is general practice.

**Priority.** A simple score: kind of bottleneck + importance of road type + evidence strength.
""")
    with t5:
        st.markdown("""
- Open map data is incomplete. A missing tag means *unknown*, never *absent*.
- Nothing here measures real traffic. A flag means 'worth checking', not 'confirmed cause'.
- Inferred items (frontage pressure) can be wrong if parking or entrances are unmapped.
- Thresholds are assumptions and editable under Settings.
- Fixes are suggestions for the road authority to assess, not engineering designs.
- Covers Chennai only, one area at a time. Not field-validated.
""")

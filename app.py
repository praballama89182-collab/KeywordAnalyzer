"""
Helium Audit — Helium 10 Cerebro + X-Ray analyzer.

Two uploads:
  • Cerebro CSV  -> keyword buckets (low competition, high volume, high sales,
    striking distance) with per-keyword and copy-all.
  • X-Ray CSV    -> competitor table filtered on price, sales, orders, BSR,
    ratings and reviews, ranges seeded from the file itself.
Each report renders in its own tab; either can be used on its own.
"""
import io
import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Helium Audit", page_icon="📊", layout="wide")

st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@600;700&display=swap');
.stApp{background:#fff}
html,body,[class*="css"]{font-family:'Inter',system-ui,sans-serif;color:#0f1419;font-size:15px}
h1,h2,h3,h4{font-family:'Archivo',sans-serif;color:#0b0f14;letter-spacing:-.015em}
.block-container{padding-top:1.1rem;max-width:1560px}
.hero{background:linear-gradient(115deg,#12203a,#243b63 52%,#3b5bdb);border-radius:16px;
 padding:18px 24px;margin-bottom:14px}
.hero h1{color:#fff;font-size:23px;font-weight:800;margin:0}
.hero p{color:#c6d0e4;font-size:13px;margin:5px 0 0}
.kpi{background:#fff;border:1px solid #e7eaf3;border-radius:13px;padding:13px 16px;
 box-shadow:0 3px 12px rgba(20,26,41,.05)}
.kpi .n{font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:700;color:#3b5bdb;line-height:1}
.kpi .l{font-size:12px;color:#6b7391;margin-top:3px}
.kpi.accent{background:linear-gradient(135deg,#3b5bdb,#5b7cfa);border:0}
.kpi.accent .n,.kpi.accent .l{color:#fff}
.kpi .d{font-size:11px;font-weight:600;margin-top:4px}
.up{color:#0b9d5b}.down{color:#e0245e}
.panel{background:#fff;border:1px solid #e7eaf3;border-radius:14px;padding:8px 10px 4px;
 box-shadow:0 3px 12px rgba(20,26,41,.05);margin-bottom:12px}
.panel h4{font-size:14px;margin:8px 6px 2px;color:#141a29}
.panel .sub{font-size:11.5px;color:#8a92a3;margin:0 6px 4px}
.leg{font-size:12px;color:#3a4256}
.note{background:#f4f7fe;border:1px solid #dbe4fb;border-left:5px solid #3b5bdb;border-radius:10px;
 padding:11px 15px;font-size:13.5px;color:#2a3549;margin:8px 0 14px}
div.stButton>button[kind="primary"]{background:#3b5bdb;border:0;font-weight:700;border-radius:8px}
.stDownloadButton>button{border-radius:8px;font-weight:600;width:100%}
[data-baseweb="tab"]{font-family:'Archivo',sans-serif;font-weight:700;font-size:15px}
.stDataFrame{border:1px solid #e7eaf3;border-radius:10px}
</style>""", unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>📊 Helium Audit</h1><p>Helium 10 Cerebro keyword '
            'analysis and X-Ray competitor analysis in one place. Upload either report, or both.</p>'
            '</div>', unsafe_allow_html=True)

UNRANKED = 99999


def to_num(series):
    s = (series.astype(str).str.replace(",", "", regex=False)
         .str.replace("$", "", regex=False).str.replace("%", "", regex=False).str.strip())
    return pd.to_numeric(s.replace({"-": None, "": None, "N/A": None, "n/a": None}), errors="coerce")


def copy_all(keywords, key, label="Copy all"):
    text = "\n".join(str(k) for k in keywords)
    payload = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    components.html(f"""
      <button id="c{key}" style="background:#3b5bdb;color:#fff;border:0;border-radius:8px;
        padding:9px 18px;font-size:14px;font-weight:700;cursor:pointer;font-family:Inter,sans-serif">
        {label} ({len(keywords)})</button>
      <script>
        const b=document.getElementById("c{key}");
        b.onclick=async()=>{{const t=`{payload}`;
          try{{await navigator.clipboard.writeText(t);}}
          catch(e){{const a=document.createElement('textarea');a.value=t;a.style.position='fixed';
            a.style.opacity='0';document.body.appendChild(a);a.select();
            document.execCommand('copy');document.body.removeChild(a);}}
          b.textContent='Copied {len(keywords)}';b.style.background='#22c55e';
          setTimeout(()=>{{b.textContent='{label} ({len(keywords)})';b.style.background='#3b5bdb';}},1500);}};
      </script>""", height=46)


def kpis(pairs):
    for c, (n, l) in zip(st.columns(len(pairs)), pairs):
        c.markdown(f'<div class="kpi"><div class="n">{n}</div><div class="l">{l}</div></div>',
                   unsafe_allow_html=True)


def rng(df, col, default_lo=None, default_hi=None):
    """A (min,max) slider seeded from the column's own range."""
    s = df[col].dropna()
    if s.empty:
        return None
    lo, hi = float(s.min()), float(s.max())
    if lo == hi:
        hi = lo + 1
    return lo, hi


# ----------------------------------------------------------------- keyword logic
COMPETITOR_BRAND_HINTS = [
    "nordic naturals", "grizzly", "zesty paws", "vital pet", "vital planet", "natural dog",
    "coco and luna", "hofseth", "pupper", "finn", "native pet", "petlab", "wild alaskan",
    "amazon brand", "wag", "furrific", "vetriscience", "nutramax", "life on the line",
    "heart eyes", "fur oil", "lifelines", "purina", "blue buffalo", "iams",
]

def brand_flag(series, extra=None):
    """Boolean mask: keyword contains a known competitor brand token."""
    hints = COMPETITOR_BRAND_HINTS + [b.strip().lower() for b in (extra or []) if b.strip()]
    pat = "|".join(re.escape(h) for h in hints)
    return series.str.lower().str.contains(pat, na=False)


def priority_score(d):
    """Volume per rank position: how much traffic a small rank gain unlocks.
    A keyword at rank 36 with 50k volume beats one at rank 40 with 8k."""
    return (d["volume"].fillna(0) / d["organic"].clip(lower=1)).round(0)


# ----------------------------------------------------------------- charts
PALETTE = ["#3b5bdb", "#5b7cfa", "#22b8cf", "#0b9d5b", "#f59f00", "#e8590c", "#e0245e", "#adb5bd"]
GREEN_RED = {"Page 1 top (1-15)": "#0b9d5b", "Page 1 (16-30)": "#37b24d",
             "Striking (31-100)": "#f59f00", "Deep (100+)": "#e8590c", "Not ranking": "#adb5bd"}

def _layout(fig, h=270, legend=True):
    fig.update_layout(
        height=h, margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=13, color="#26303c"),
        showlegend=legend,
        legend=dict(orientation="v", x=1.02, y=0.5, font=dict(size=11.5)),
    )
    return fig

def donut(counts, colors=None, order=None):
    if order:
        counts = counts.reindex([o for o in order if o in counts.index])
    colors = [colors.get(k, "#adb5bd") for k in counts.index] if isinstance(colors, dict) \
        else (colors or PALETTE)
    fig = go.Figure(go.Pie(
        labels=list(counts.index), values=list(counts.values), hole=.62, sort=False,
        marker=dict(colors=colors, line=dict(color="#fff", width=2)),
        textinfo="percent", textfont=dict(size=12, color="#fff"),
        hovertemplate="%{label}<br>%{value} keywords (%{percent})<extra></extra>"))
    total = int(counts.sum())
    fig.add_annotation(text=f"<b>{total:,}</b><br>keywords", showarrow=False,
                       font=dict(size=15, color="#141a29"))
    return _layout(fig)

def hbar(labels, values, color="#3b5bdb", fmt="{:,}"):
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=color), text=[fmt.format(v) for v in values],
        textposition="outside", textfont=dict(size=11.5),
        hovertemplate="%{y}<br>%{x:,}<extra></extra>"))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=12))
    return _layout(fig, h=max(150, 30 * len(labels) + 40), legend=False)

def scatter_opportunity(d):
    """Volume vs organic rank; colour = title density, so the sweet spot is
    high volume, high rank number (poor rank) and low density — top-left, cool."""
    dd = d[d["ranks"] & d["volume"].notna()].copy()
    if dd.empty:
        return None
    fig = go.Figure(go.Scatter(
        x=dd["organic"], y=dd["volume"], mode="markers",
        marker=dict(size=9, color=dd["title_density"].fillna(0), colorscale="RdYlGn_r",
                    showscale=True, colorbar=dict(title="Title<br>density", thickness=12,
                    len=.7, x=1.02), line=dict(width=.5, color="#fff"), opacity=.75),
        text=dd["keyword"],
        hovertemplate="%{text}<br>rank %{x}, vol %{y:,}<extra></extra>"))
    fig.add_vrect(x0=0, x1=30, fillcolor="#0b9d5b", opacity=.06, line_width=0)
    fig.add_vrect(x0=31, x1=100, fillcolor="#f59f00", opacity=.06, line_width=0)
    fig.update_xaxes(title="Organic rank (lower is better)", gridcolor="#eef1f6", range=[0, 160])
    fig.update_yaxes(title="Search volume", gridcolor="#eef1f6", type="log")
    return _layout(fig, h=340, legend=False)

def panel(title, sub=""):
    st.markdown(f'<div class="panel"><h4>{title}</h4>'
                + (f'<div class="sub">{sub}</div>' if sub else ""), unsafe_allow_html=True)

def panel_end():
    st.markdown("</div>", unsafe_allow_html=True)


# ================================================================= loaders
def _read_csv_any(b):
    """Read bytes to a DataFrame across the encodings and delimiters Helium 10
    exports use, without raising."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        for sep in (",", ";", "\t"):
            try:
                df = pd.read_csv(io.BytesIO(b), encoding=enc, sep=sep, dtype=str,
                                 engine="python", on_bad_lines="skip")
                if df.shape[1] >= 2:
                    return df
            except Exception:
                continue
    return None


def _clean_headers(df):
    """Strip BOM, stray quotes and whitespace from column names, so a file saved
    with a byte-order mark still matches the expected column labels."""
    df.columns = [str(c).replace("\ufeff", "").strip().strip('"').strip() for c in df.columns]
    return df


CEREBRO_MAP = {
    "Keyword Phrase": "keyword", "Search Volume": "volume", "Search Volume Trend": "trend",
    "Keyword Sales": "sales", "Organic Rank": "organic", "Sponsored Rank": "sponsored",
    "Title Density": "title_density", "Competing Products": "competing", "CPR": "cpr",
    "Cerebro IQ Score": "iq", "H10 PPC Sugg. Bid": "bid",
}
CEREBRO_NUM = ["volume", "trend", "sales", "organic", "sponsored", "title_density",
               "competing", "cpr", "iq", "bid"]

XRAY_MAP = {
    "Product Details": "title", "ASIN": "asin", "Brand": "brand", "Price  $": "price",
    "ASIN Sales": "sales", "Parent Level Sales": "parent_sales", "Recent Purchases": "orders",
    "ASIN Revenue": "revenue", "BSR": "bsr", "Ratings": "rating", "Review Count": "reviews",
    "Category": "category", "Active Sellers": "sellers", "URL": "url",
}
XRAY_NUM = ["price", "sales", "parent_sales", "orders", "revenue", "bsr", "rating",
            "reviews", "sellers"]


@st.cache_data(show_spinner=False)
def load_cerebro(b):
    df = pd.read_csv(io.BytesIO(b), encoding="utf-8-sig", dtype=str)
    df = df.rename(columns={k: v for k, v in CEREBRO_MAP.items() if k in df.columns})
    if "keyword" not in df.columns:
        return None, "No 'Keyword Phrase' column — is this a Cerebro export?"
    for c in CEREBRO_NUM:
        df[c] = to_num(df[c]) if c in df.columns else pd.NA
    df = df[~df["keyword"].fillna("").str.match(r"(?i)^b0[a-z0-9]{8}$")]
    df["keyword"] = df["keyword"].fillna("").str.strip()
    df = df[df["keyword"] != ""].reset_index(drop=True)
    df["ranks"] = df["organic"].notna()
    return df, ""


@st.cache_data(show_spinner=False)
def load_xray(b):
    df = pd.read_csv(io.BytesIO(b), encoding="utf-8-sig", dtype=str)
    df = df.rename(columns={k: v for k, v in XRAY_MAP.items() if k in df.columns})
    if "asin" not in df.columns:
        return None, "No 'ASIN' column — is this an X-Ray export?"
    for c in XRAY_NUM:
        df[c] = to_num(df[c]) if c in df.columns else pd.NA
    for c in ["title", "brand", "asin", "category"]:
        if c in df.columns:
            df[c] = df[c].fillna("").str.strip()
    df = df[df["asin"] != ""].reset_index(drop=True)
    return df, ""


# ================================================================= uploads
c1, c2 = st.columns(2)
with c1:
    st.markdown("##### 1 · Cerebro keyword export")
    cere_file = st.file_uploader("Cerebro CSV", type=["csv"], key="cere",
                                 label_visibility="collapsed")
with c2:
    st.markdown("##### 2 · X-Ray competitor export")
    xray_file = st.file_uploader("X-Ray CSV", type=["csv"], key="xray",
                                 label_visibility="collapsed")

if cere_file is None and xray_file is None:
    st.info("Upload a Cerebro export, an X-Ray export, or both. Each opens in its own tab below.")
    st.stop()

cere_df = xray_df = None
if cere_file is not None:
    cere_df, e = load_cerebro(cere_file.getvalue())
    if e:
        st.error(f"Cerebro: {e}")
if xray_file is not None:
    xray_df, e = load_xray(xray_file.getvalue())
    if e:
        st.error(f"X-Ray: {e}")

CERE_COLS = {"keyword": "Keyword", "volume": "Volume", "organic": "Organic Rank",
             "sponsored": "Sponsored Rank", "priority": "Priority", "sales": "Kw Sales",
             "title_density": "Title Density", "competing": "Competing", "trend": "Trend %",
             "bid": "Sugg. Bid $"}


def cere_view(d, key, note):
    st.markdown(f'<div class="note">{note}</div>', unsafe_allow_html=True)
    if d.empty:
        st.warning("No keywords match. Loosen the filters.")
        return
    kpis([(f"{len(d):,}", "keywords"),
          (f"{int(d['volume'].fillna(0).sum()):,}", "total volume"),
          (f"{int(d['ranks'].sum()):,}", "you rank for"),
          (f"{int((d['organic'] <= 30).sum()):,}", "on page 1")])
    a, b = st.columns(2)
    with a:
        copy_all(d["keyword"].tolist(), key, "Copy all keywords")
    with b:
        st.download_button("Download (.csv)", d.to_csv(index=False).encode("utf-8"),
                           f"keywords_{key}.csv", "text/csv", key=f"dl{key}")
    cols = [c for c in CERE_COLS if c in d.columns]
    st.dataframe(d[cols].rename(columns=CERE_COLS), use_container_width=True, height=440,
                 hide_index=True,
                 column_config={"Keyword": st.column_config.TextColumn(width="large")})
    st.caption("Click any cell and press ⌘/Ctrl-C to copy a single keyword.")


# ================================================================= layout
sections = []
if cere_df is not None:
    sections.append("🔑 Keywords (Cerebro)")
if xray_df is not None:
    sections.append("🏷️ Competitors (X-Ray)")
top = st.tabs(sections)
idx = 0

# ----------------------------------------------------------------- CEREBRO
if cere_df is not None:
    with top[idx]:
        idx += 1
        df = cere_df
        vmax = int(df["volume"].fillna(0).max() or 1000)
        cmax = int(df["competing"].fillna(0).max() or 1000)
        tdmax = int(df["title_density"].fillna(0).max() or 10)

        sb = st.sidebar
        sb.header("Keyword filters")
        sb.caption("Apply to the **All keywords** tab. Each preset below has its own on top.")
        f_vol = sb.slider("Search volume", 0, vmax, (100, vmax), step=50, key="kf_vol")
        f_rank = sb.selectbox("Organic rank", ["Any", "Ranked only", "Not ranking",
                              "Page 1 (1–30)", "Striking (31–100)", "Deep/unranked (100+)"],
                              key="kf_rank")
        f_td = sb.slider("Max title density", 0, tdmax, tdmax, key="kf_td")
        f_comp = sb.slider("Max competing products", 0, cmax, cmax, step=50, key="kf_comp")
        f_has = sb.checkbox("Only with tracked sales", key="kf_has")
        f_has_kw = sb.text_input("Contains", placeholder="salmon, dogs", key="kf_c")
        f_excl = sb.text_area("Exclude (one per line)", height=70, key="kf_x",
                              placeholder="extra competitor brands")
        f_nobrand = sb.checkbox("Hide competitor-brand keywords", value=False, key="kf_nb",
                                help="Terms containing a rival brand — you can't rank these "
                                     "organically, only bid on them. On by default in the "
                                     "ranking tabs.")

        def base(d):
            d = d[d["volume"].fillna(0).between(*f_vol)]
            if f_rank == "Ranked only": d = d[d["ranks"]]
            elif f_rank == "Not ranking": d = d[~d["ranks"]]
            elif f_rank == "Page 1 (1–30)": d = d[d["organic"] <= 30]
            elif f_rank == "Striking (31–100)": d = d[d["organic"].between(31, 100)]
            elif f_rank == "Deep/unranked (100+)": d = d[(d["organic"] > 100) | (~d["ranks"])]
            d = d[d["title_density"].fillna(0) <= f_td]
            d = d[d["competing"].fillna(0) <= f_comp]
            if f_has: d = d[d["sales"].fillna(0) > 0]
            if f_has_kw.strip():
                ts = [t.strip().lower() for t in f_has_kw.split(",") if t.strip()]
                d = d[d["keyword"].str.lower().apply(lambda k: any(t in k for t in ts))]
            xs = [t.strip().lower() for t in (f_excl or "").splitlines() if t.strip()]
            if xs:
                d = d[~d["keyword"].str.lower().apply(lambda k: any(t in k for t in xs))]
            if f_nobrand:
                d = d[~brand_flag(d["keyword"], xs)]
            return d

        t = st.tabs(["📊 Dashboard", "All keywords", "Low competition", "High volume",
                     "High sales", "Striking distance", "PPC opportunities"])

        with t[0]:
            dd = base(df)
            def _bucket(o, r):
                if not r: return "Not ranking"
                if o <= 15: return "Page 1 top (1-15)"
                if o <= 30: return "Page 1 (16-30)"
                if o <= 100: return "Striking (31-100)"
                return "Deep (100+)"
            dd = dd.assign(bucket=[_bucket(o, r) for o, r in zip(dd["organic"], dd["ranks"])])

            page1 = int((dd["organic"] <= 30).sum())
            strike = int(dd["organic"].between(31, 100).sum())
            ranked = int(dd["ranks"].sum())
            avgbid = dd["bid"].mean()
            cards = [
                (f"{len(dd):,}", "keywords in view", "", ""),
                (f"{int(dd['volume'].fillna(0).sum()):,}", "total search volume", "", "accent"),
                (f"{ranked:,}", "you rank for", f"{ranked/max(len(dd),1)*100:.0f}% of view", ""),
                (f"{page1:,}", "on page 1 (≤30)", "defend these", ""),
                (f"{strike:,}", "striking distance", "push to page 1", ""),
                (f"${avgbid:.2f}" if avgbid == avgbid else "—", "avg suggested bid", "", ""),
            ]
            cols = st.columns(6)
            for c, (n, l, d_, cls) in zip(cols, cards):
                c.markdown(f'<div class="kpi {cls}"><div class="n">{n}</div>'
                           f'<div class="l">{l}</div>'
                           + (f'<div class="d">{d_}</div>' if d_ else "")
                           + '</div>', unsafe_allow_html=True)

            st.markdown("")
            g1, g2, g3 = st.columns(3)
            with g1:
                panel("Where you rank", "share of keywords by organic-rank band")
                order = ["Page 1 top (1-15)", "Page 1 (16-30)", "Striking (31-100)",
                         "Deep (100+)", "Not ranking"]
                st.plotly_chart(donut(dd["bucket"].value_counts(), GREEN_RED, order),
                                use_container_width=True, key="d_rank")
                panel_end()
            with g2:
                panel("Search-volume tiers", "how the demand is spread")
                def _vt(v):
                    v = v or 0
                    return ("5000+" if v >= 5000 else "1000-4999" if v >= 1000
                            else "500-999" if v >= 500 else "100-499" if v >= 100 else "under 100")
                vt = dd["volume"].apply(_vt).value_counts().reindex(
                    ["5000+", "1000-4999", "500-999", "100-499", "under 100"]).dropna()
                st.plotly_chart(donut(vt, PALETTE), use_container_width=True, key="d_vol")
                panel_end()
            with g3:
                panel("Title density", "how hard keywords are to rank")
                def _td(x):
                    x = x if x == x else 0
                    return ("0 (open)" if x == 0 else "1-2 (easy)" if x <= 2
                            else "3-5 (moderate)" if x <= 5 else "6+ (crowded)")
                td = dd["title_density"].apply(_td).value_counts().reindex(
                    ["0 (open)", "1-2 (easy)", "3-5 (moderate)", "6+ (crowded)"]).dropna()
                st.plotly_chart(donut(td, ["#0b9d5b", "#37b24d", "#f59f00", "#e8590c"]),
                                use_container_width=True, key="d_td")
                panel_end()

            b1, b2 = st.columns([3, 2])
            with b1:
                panel("Opportunity map",
                      "each dot a keyword you rank for · left = better rank · higher = more volume "
                      "· green = low title density · the green band is page 1")
                fig = scatter_opportunity(dd)
                if fig: st.plotly_chart(fig, use_container_width=True, key="d_sc")
                else: st.caption("No ranked keywords in view to plot.")
                panel_end()
            with b2:
                panel("Top volume you don't rank for", "the biggest gaps to close")
                gap = dd[~dd["ranks"]].nlargest(8, "volume")
                if not gap.empty:
                    st.plotly_chart(
                        hbar(gap["keyword"].str.slice(0, 30).tolist(),
                             gap["volume"].fillna(0).astype(int).tolist(), "#e8590c"),
                        use_container_width=True, key="d_gap")
                else:
                    st.caption("You rank for everything in view.")
                panel_end()

        with t[1]:
            cere_view(base(df).sort_values("volume", ascending=False), "all",
                      "Everything passing the sidebar filters, by volume. Your working set.")
        with t[2]:
            st.markdown("#### Low-competition keywords")
            a, b, c = st.columns(3)
            td = a.slider("Max title density", 0, tdmax, min(1, tdmax), key="lc_td")
            cp = b.slider("Max competing", 0, cmax, min(500, cmax), step=50, key="lc_cp")
            vl = c.number_input("Min volume", 0, vmax, min(300, vmax), step=50, key="lc_vl")
            d = df[(df["title_density"].fillna(0) <= td) & (df["competing"].fillna(0) <= cp)
                   & (df["volume"].fillna(0) >= vl)].sort_values(
                   ["title_density", "volume"], ascending=[True, False])
            cere_view(d, "low", "Low title density plus few competitors means few sellers own the "
                      "keyword in their title — the easiest to rank cold. Send to backend terms and "
                      "new PPC.")
        with t[3]:
            st.markdown("#### High-volume keywords")
            a, b = st.columns(2)
            vl = a.number_input("Min volume", 0, vmax, min(1000, vmax), step=100, key="hv_vl")
            rk = b.selectbox("Rank", ["Any", "Only where you rank", "Only where you don't"], key="hv_rk")
            d = df[df["volume"].fillna(0) >= vl]
            if rk == "Only where you rank": d = d[d["ranks"]]
            elif rk == "Only where you don't": d = d[~d["ranks"]]
            cere_view(d.sort_values("volume", ascending=False), "vol",
                      "Biggest traffic terms. Defend where you rank; decide winnable-vs-brand where "
                      "you don't.")
        with t[4]:
            st.markdown("#### High-sales keywords")
            if df["sales"].notna().sum() == 0:
                st.warning("This export has no Keyword Sales column. Re-run Cerebro with it enabled.")
            else:
                smax = int(df["sales"].fillna(0).max())
                a, b = st.columns(2)
                sl = a.number_input("Min keyword sales", 0, max(smax, 1), min(50, smax),
                                    step=10, key="hs_sl")
                vl = b.number_input("Min volume", 0, vmax, 0, step=50, key="hs_vl")
                d = df[(df["sales"].fillna(0) >= sl) & (df["volume"].fillna(0) >= vl)]
                cere_view(d.sort_values("sales", ascending=False), "sales",
                          "Keywords driving the most units market-wide. These convert — put them in "
                          "the title, top bullets and core PPC.")
        with t[5]:
            st.markdown("#### Striking distance")
            a, b, c, e = st.columns(4)
            lo = a.number_input("Rank from", 1, 300, 11, key="sd_lo")
            hi = b.number_input("Rank to", 1, 306, 100, key="sd_hi")
            vl = c.number_input("Min volume", 0, vmax, min(300, vmax), step=50, key="sd_vl")
            sort_by = e.selectbox("Sort by", ["Priority (volume ÷ rank)", "Volume", "Rank"],
                                  key="sd_sort")
            d = df[df["organic"].between(lo, hi) & (df["volume"].fillna(0) >= vl)].copy()
            if f_nobrand:
                d = d[~brand_flag(d["keyword"])]
            d["priority"] = priority_score(d)
            if sort_by.startswith("Priority"):
                d = d.sort_values("priority", ascending=False)
            elif sort_by == "Volume":
                d = d.sort_values("volume", ascending=False)
            else:
                d = d.sort_values("organic")
            cere_view(d, "strike", "Already ranking, just off page 1. Sorted by <b>priority</b> — "
                      "volume divided by rank position — so the keyword where a small rank gain "
                      "unlocks the most traffic sits first. Usually the highest-ROI work in the export.")

        with t[6]:
            st.markdown("#### PPC opportunities")
            st.markdown('<div class="note">Two paid-search plays the ranking tabs miss: keywords '
                        'you <b>advertise but do not rank</b> for (earn what you rent) and '
                        '<b>competitor-brand</b> terms (conquest bidding). Both read from the same '
                        'export.</div>', unsafe_allow_html=True)

            st.markdown("##### 1 · Rank gap — paid but not organic")
            st.caption("You hold a Sponsored position but no organic rank. PPC is carrying traffic "
                       "your listing could earn. Feed these into the title and backend terms, then "
                       "push to convert the paid rank into an organic one.")
            gap = df[(df["sponsored"].notna()) & (df["organic"].isna())].copy()
            gap = gap[gap["volume"].fillna(0) >= 100]
            gap = gap[~brand_flag(gap["keyword"])]
            gap = gap.sort_values("volume", ascending=False)
            if gap.empty:
                st.info("No paid-only keywords above 100 volume — your organic coverage is strong.")
            else:
                cere_view(gap, "gap", "")

            st.markdown("---")
            st.markdown("##### 2 · Competitor-brand terms — conquest bidding")
            st.caption("Terms containing a rival brand. You cannot rank these organically, but "
                       "bidding on them puts you in front of shoppers already looking at a "
                       "competitor. Add your own brands to the exclude box if any are yours.")
            extra = [t_.strip().lower() for t_ in (f_excl or "").splitlines() if t_.strip()]
            conquest = df[brand_flag(df["keyword"], extra)].copy()
            conquest = conquest[conquest["volume"].fillna(0) >= 100].sort_values("volume", ascending=False)
            if conquest.empty:
                st.info("No competitor-brand terms found in this export.")
            else:
                cere_view(conquest, "conq", "")

            st.markdown("---")
            st.markdown("##### 3 · Undefended winners — organic top-30, no ad")
            st.caption("You rank on page 1 organically but run no Sponsored ad, so a competitor can "
                       "bid above your listing and take the click. Cheap to defend.")
            undef = df[(df["organic"] <= 30) & (df["sponsored"].isna())].copy()
            undef = undef.sort_values("volume", ascending=False)
            if undef.empty:
                st.info("Every page-1 keyword already has a Sponsored position.")
            else:
                cere_view(undef, "undef", "")


# ----------------------------------------------------------------- X-RAY
if xray_df is not None:
    with top[idx]:
        df = xray_df
        st.markdown("### Competitor analysis")
        st.markdown('<div class="note">Every filter range is seeded from this file. Narrow the '
                    'market, then read off brand, ASIN, item, price, sales, orders, BSR, rating and '
                    'reviews.</div>', unsafe_allow_html=True)

        def slider_for(col, label, step=None, as_int=True):
            r = rng(df, col)
            if r is None:
                return None
            lo, hi = r
            if as_int:
                lo, hi = int(lo), int(hi) + (1 if int(lo) == int(hi) else 0)
                return st.slider(label, lo, hi, (lo, hi), step=step or 1, key=f"xr_{col}")
            return st.slider(label, float(lo), float(hi), (float(lo), float(hi)),
                             step=step or 0.01, key=f"xr_{col}")

        colA, colB, colC = st.columns(3)
        with colA:
            f_price = slider_for("price", "Price $", as_int=False)
            f_bsr = slider_for("bsr", "BSR (lower is better)")
        with colB:
            sales_col = "sales" if df["sales"].notna().any() else "parent_sales"
            f_sales = slider_for(sales_col, "Monthly sales")
            f_orders = slider_for("orders", "Recent orders") if df["orders"].notna().any() else None
        with colC:
            f_rating = slider_for("rating", "Rating", step=0.1, as_int=False)
            f_reviews = slider_for("reviews", "Review count")

        f_brand = st.text_input("Brand contains", placeholder="filter to one brand, optional",
                                key="xr_brand")

        d = df.copy()
        if f_price: d = d[d["price"].fillna(-1).between(*f_price) | df["price"].isna()]
        if f_bsr: d = d[d["bsr"].fillna(10**9).between(*f_bsr) | df["bsr"].isna()]
        if f_sales: d = d[d[sales_col].fillna(-1).between(*f_sales)]
        if f_orders: d = d[d["orders"].fillna(-1).between(*f_orders) | df["orders"].isna()]
        if f_rating: d = d[d["rating"].fillna(-1).between(*f_rating) | df["rating"].isna()]
        if f_reviews: d = d[d["reviews"].fillna(-1).between(*f_reviews) | df["reviews"].isna()]
        if f_brand.strip():
            d = d[d["brand"].str.lower().str.contains(f_brand.strip().lower(), na=False)]

        d = d.sort_values(sales_col, ascending=False, na_position="last")

        st.markdown("---")
        if d.empty:
            st.warning("No competitors match. Widen the ranges.")
        else:
            kpis([(f"{len(d)}", "competitors"),
                  (f"${d['price'].mean():.2f}" if d['price'].notna().any() else "—", "avg price"),
                  (f"{int(d[sales_col].fillna(0).sum()):,}", "combined monthly sales"),
                  (f"{d['rating'].mean():.1f}" if d['rating'].notna().any() else "—", "avg rating")])

            cc1, cc2 = st.columns(2)
            with cc1:
                panel("Sales share by brand", "who owns the demand in this set")
                bs = d.groupby("brand")[sales_col].sum().sort_values(ascending=False)
                st.plotly_chart(donut(bs.head(8), PALETTE),
                                use_container_width=True, key="x_share")
                panel_end()
            with cc2:
                panel("Price vs sales", "bubble size = review count · find the price band that sells")
                dd = d[d["price"].notna() & d[sales_col].notna()]
                if not dd.empty:
                    rev = dd["reviews"].fillna(dd["reviews"].median() if dd["reviews"].notna().any() else 100)
                    fig = go.Figure(go.Scatter(
                        x=dd["price"], y=dd[sales_col], mode="markers+text",
                        marker=dict(size=(rev / rev.max() * 46 + 10),
                                    color=dd["rating"].fillna(0), colorscale="RdYlGn",
                                    cmin=3.5, cmax=5, showscale=True,
                                    colorbar=dict(title="Rating", thickness=12, len=.7),
                                    line=dict(width=1, color="#fff"), opacity=.8),
                        text=dd["brand"].str.slice(0, 14), textposition="top center",
                        textfont=dict(size=9, color="#5b6472"),
                        hovertemplate="%{text}<br>$%{x:.2f} · %{y:,} sales<extra></extra>"))
                    fig.update_xaxes(title="Price $", gridcolor="#eef1f6")
                    fig.update_yaxes(title="Sales", gridcolor="#eef1f6")
                    st.plotly_chart(_layout(fig, h=300, legend=False),
                                    use_container_width=True, key="x_ps")
                panel_end()

            out_cols = [("brand", "Brand"), ("asin", "ASIN"), ("title", "Item name"),
                        ("price", "Price $"), (sales_col, "Sales"), ("orders", "Orders"),
                        ("revenue", "Revenue $"), ("bsr", "BSR"), ("rating", "Rating"),
                        ("reviews", "Reviews")]
            out_cols = [(c, n) for c, n in out_cols if c in d.columns]
            table = d[[c for c, _ in out_cols]].rename(columns=dict(out_cols))

            a, b = st.columns(2)
            with a:
                copy_all(d["asin"].tolist(), "xr_asin", "Copy all ASINs")
            with b:
                st.download_button("Download competitors (.csv)",
                                   table.to_csv(index=False).encode("utf-8"),
                                   "competitors.csv", "text/csv", key="dlxray")
            st.dataframe(table, use_container_width=True, height=440, hide_index=True,
                         column_config={
                             "Item name": st.column_config.TextColumn(width="large"),
                             "ASIN": st.column_config.TextColumn(width="small"),
                             "Price $": st.column_config.NumberColumn(format="$%.2f"),
                             "Revenue $": st.column_config.NumberColumn(format="$%.0f"),
                             "Rating": st.column_config.NumberColumn(format="%.1f ⭐"),
                         })
            st.caption("Sorted by sales. Click any cell and press ⌘/Ctrl-C to copy it; use "
                       "Copy all ASINs for the set.")

            with st.expander("Market summary"):
                brands = d.groupby("brand").agg(
                    listings=("asin", "count"),
                    total_sales=(sales_col, "sum"),
                    avg_price=("price", "mean")).sort_values("total_sales", ascending=False)
                brands["avg_price"] = brands["avg_price"].round(2)
                st.markdown("**Sales share by brand**")
                st.dataframe(brands, use_container_width=True)

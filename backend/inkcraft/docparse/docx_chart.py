"""Hardened DrawingML chart XML parser (`word/charts/chart*.xml`)."""

from __future__ import annotations

from lxml import etree

from inkcraft.docparse.docir import ChartData, ChartSeries
from inkcraft.docparse.docx_omml import NS

_SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=False,
)


def _extract_chart_title(root: etree._Element) -> str:
    title_el = root.find(".//c:title", NS)
    if title_el is None:
        return ""
    texts = [t.text for t in title_el.findall(".//a:t", NS) if t.text]
    if texts:
        return "".join(texts).strip()
    vals = [v.text for v in title_el.findall(".//c:v", NS) if v.text]
    return "".join(vals).strip()


def _extract_str_cache(parent: etree._Element | None) -> list[str]:
    if parent is None:
        return []
    pts = parent.findall(".//c:strCache/c:pt", NS)
    if not pts:
        pts = parent.findall(".//c:numCache/c:pt", NS)
    if not pts:
        pts = parent.findall(".//c:strLit/c:pt", NS)
    if not pts:
        pts = parent.findall(".//c:numLit/c:pt", NS)
    indexed: list[tuple[int, str]] = []
    for i, pt in enumerate(pts):
        idx = int(pt.get("idx", str(i)))
        v = pt.find("c:v", NS)
        indexed.append((idx, (v.text or "").strip() if v is not None else ""))
    indexed.sort(key=lambda t: t[0])
    return [val for _, val in indexed]


def _extract_num_cache(parent: etree._Element | None) -> list[float]:
    if parent is None:
        return []
    pts = parent.findall(".//c:numCache/c:pt", NS)
    if not pts:
        pts = parent.findall(".//c:numLit/c:pt", NS)
    indexed: list[tuple[int, float]] = []
    for i, pt in enumerate(pts):
        idx = int(pt.get("idx", str(i)))
        v = pt.find("c:v", NS)
        if v is not None and v.text is not None:
            try:
                indexed.append((idx, float(v.text.strip())))
            except ValueError:
                indexed.append((idx, 0.0))
    indexed.sort(key=lambda t: t[0])
    return [val for _, val in indexed]


def parse_drawingml_chart_xml(xml_bytes: bytes) -> ChartData | None:
    """Parse an OOXML `word/charts/chartN.xml` payload into `ChartData`."""
    try:
        root = etree.fromstring(xml_bytes, parser=_SAFE_XML_PARSER)
    except etree.XMLSyntaxError:
        return None

    plot_area = root.find(".//c:plotArea", NS)
    if plot_area is None:
        return None

    chart_elem = None
    chart_type = "bar"
    for xml_name, ctype in (
        ("barChart", "bar"),
        ("bar3DChart", "bar"),
        ("lineChart", "line"),
        ("line3DChart", "line"),
        ("pieChart", "pie"),
        ("pie3DChart", "pie"),
        ("doughnutChart", "pie"),
        ("scatterChart", "scatter"),
        ("areaChart", "line"),
    ):
        found = plot_area.find(f"c:{xml_name}", NS)
        if found is not None:
            chart_elem = found
            chart_type = ctype
            break

    if chart_elem is None:
        return None

    title = _extract_chart_title(root)
    categories: list[str] = []
    series_list: list[ChartSeries] = []

    for idx, ser in enumerate(chart_elem.findall("c:ser", NS)):
        tx = ser.find("c:tx", NS)
        ser_name = ""
        if tx is not None:
            v_el = tx.find(".//c:v", NS)
            if v_el is not None and v_el.text:
                ser_name = v_el.text.strip()
        if not ser_name:
            ser_name = f"S{idx + 1}"

        if chart_type == "scatter":
            x_vals = _extract_num_cache(ser.find("c:xVal", NS))
            y_vals = _extract_num_cache(ser.find("c:yVal", NS))
            if y_vals:
                series_list.append(
                    ChartSeries(name=ser_name, values=y_vals, x_values=x_vals or None)
                )
        else:
            if not categories:
                categories = _extract_str_cache(ser.find("c:cat", NS))
            vals = _extract_num_cache(ser.find("c:val", NS))
            if vals:
                series_list.append(ChartSeries(name=ser_name, values=vals))

    x_label = ""
    y_label = ""
    cat_ax = plot_area.find("c:catAx", NS)
    if cat_ax is not None:
        t_el = cat_ax.find("c:title", NS)
        if t_el is not None:
            x_label = "".join(t.text for t in t_el.findall(".//a:t", NS) if t.text).strip()
    val_ax = plot_area.find("c:valAx", NS)
    if val_ax is not None:
        t_el = val_ax.find("c:title", NS)
        if t_el is not None:
            y_label = "".join(t.text for t in t_el.findall(".//a:t", NS) if t.text).strip()

    if not series_list:
        return None

    if not categories and chart_type != "scatter":
        max_len = max(len(s.values) for s in series_list)
        categories = [str(i + 1) for i in range(max_len)]

    return ChartData(
        chart_type=chart_type,  # type: ignore[arg-type]
        title=title,
        x_label=x_label,
        y_label=y_label,
        categories=categories,
        series=series_list,
        extra={"origin": "docx_xml"},
    )

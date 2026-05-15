"""Visualizer module — generates an interactive HTML visualization of VPC subnets."""

from __future__ import annotations

import ipaddress
import json
import webbrowser
from pathlib import Path
from typing import Any

_AZ_COLORS = ["az-amber", "az-cyan", "az-emerald", "az-rose"]


def _subnet_to_dict(subnet: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw AWS subnet dict for the visualizer."""
    name = next(
        (tag["Value"] for tag in subnet.get("Tags", []) if tag["Key"] == "Name"),
        "N/A",
    )
    return {
        "id": subnet["SubnetId"],
        "name": name,
        "cidr": subnet["CidrBlock"],
        "az": subnet["AvailabilityZone"],
        "type": subnet.get("_type", "Private"),
        "tags": [{"key": t["Key"], "value": t["Value"]} for t in subnet.get("Tags", [])],
    }


def _vpc_cidr_range(cidrs: list[str]) -> tuple[float, float]:
    nets = [ipaddress.ip_network(c) for c in cidrs]
    start = int(min(n.network_address for n in nets))
    end = int(max(n.broadcast_address for n in nets))
    return float(start), float(end)


def _subnet_position(cidr: str, vpc_start: float, vpc_end: float) -> dict[str, float]:
    net = ipaddress.ip_network(cidr)
    subnet_start = int(net.network_address)
    subnet_end = int(net.broadcast_address)
    vpc_size = vpc_end - vpc_start
    subnet_size = subnet_end - subnet_start
    x = ((subnet_start - vpc_start) / vpc_size) * 100
    width = (subnet_size / vpc_size) * 100
    return {"x": round(x, 2), "width": round(width, 2)}


def _build_vpc_data(
    vpc_id: str,
    subnets: list[dict[str, Any]],
    vpc_cidrs: list[str] | None = None,
) -> dict[str, Any]:
    """Build a single VPC's visualization data, grouped by AZ."""
    if vpc_cidrs is None:
        cidrs = [s["CidrBlock"] for s in subnets]
        vpc_cidrs = cidrs if cidrs else ["10.0.0.0/16"]
    vpc_start, vpc_end = _vpc_cidr_range(vpc_cidrs)

    bars: list[dict[str, Any]] = []
    by_az: dict[str, list] = {}

    for s in subnets:
        pos = _subnet_position(s["CidrBlock"], vpc_start, vpc_end)
        name = next(
            (tag["Value"] for tag in s.get("Tags", []) if tag["Key"] == "Name"),
            "N/A",
        )
        net = ipaddress.ip_network(s["CidrBlock"])
        total_usable = max(1, net.num_addresses - 5)
        available = s.get("AvailableIpAddressCount", 0)
        used = total_usable - available
        util_pct = round((used / total_usable) * 100, 1)
        eks_tags = [
            t["Key"]
            for t in s.get("Tags", [])
            if t["Key"] in ("kubernetes.io/role/internal-elb", "kubernetes.io/role/elb")
        ]
        bar: dict[str, Any] = {
            "id": s["SubnetId"],
            "name": name,
            "cidr": s["CidrBlock"],
            "az": s["AvailabilityZone"],
            "type": s.get("_type", "Private"),
            "x": pos["x"],
            "width": pos["width"],
            "total_ips": total_usable,
            "available": available,
            "used": used,
            "util_pct": util_pct,
            "eks_tags": eks_tags,
            "tags": [{"key": t["Key"], "value": t["Value"]} for t in s.get("Tags", [])],
        }
        bars.append(bar)
        by_az.setdefault(s["AvailabilityZone"], []).append(bar)

    return {
        "id": vpc_id,
        "cidrs": vpc_cidrs,
        "vpc_start": vpc_start,
        "vpc_end": vpc_end,
        "subnets": bars,
        "by_az": by_az,
    }


def _ip(n: float) -> str:
    i = int(n)
    return f"{i >> 24 & 255}.{i >> 16 & 255}.{i >> 8 & 255}.{i & 255}"


def _bar_html(s: dict[str, Any]) -> str:
    eks_str = ",".join(s.get("eks_tags", []))
    util_pct = s.get("util_pct", 0)
    used = s.get("used", 0)
    return (
        f'<div class="subnet-bar {s["type"].lower()}"'
        f' data-id="{s["id"]}" data-name="{s["name"]}" data-cidr="{s["cidr"]}"'
        f' data-type="{s["type"]}" data-az="{s["az"]}" data-total="{s["total_ips"]}"'
        f' data-available="{s["available"]}" data-used="{used}" data-util="{util_pct}"'
        f' data-eks="{eks_str}"'
        f' style="left:{s["x"]}%;width:{s["width"]}%"'
        f' onmouseenter="showTip(event,this)" onmouseleave="hideTip()" onclick="selectBar(this)">'
        f'<div class="ip-fill" style="width:{util_pct}%"></div>'
        f'<span class="bar-label">{s["name"]}</span>'
        f'</div>'
    )


def _tree_subnet_item(s: dict[str, Any]) -> str:
    eks_badges = "".join(
        f'<span class="eks-badge">{t.split("/")[-1]}</span>'
        for t in s.get("eks_tags", [])
    )
    return (
        f'<li><div class="tree-leaf" onclick="scrollToRow(\'{s["id"]}\')">'
        f'<span class="dot {s["type"].lower()}"></span>'
        f'<span class="leaf-name">{s["name"]}</span>'
        f'<span class="leaf-cidr">{s["cidr"]}</span>'
        f'<span class="badge {s["type"].lower()}">{s["type"]}</span>'
        f'<span class="leaf-ips">{s["total_ips"]:,} IPs</span>'
        f'{eks_badges}'
        f'</div></li>'
    )


def _table_row(s: dict[str, Any]) -> str:
    eks = "".join(
        f'<span class="eks-badge">{t.split("/")[-1]}</span>'
        for t in s.get("eks_tags", [])
    ) or '<span class="dim">&#8212;</span>'
    util_pct = s.get("util_pct", 0)
    used = s.get("used", 0)
    util_bar = (
        f'<div class="util-wrap">'
        f'<div class="util-fill" style="width:{util_pct}%"></div>'
        f'<span class="util-pct">{util_pct}%</span>'
        f'</div>'
    )
    return (
        f'<tr id="row-{s["id"]}">'
        f'<td>{s["name"]}</td>'
        f'<td class="mono dim">{s["id"]}</td>'
        f'<td>{s["az"]}</td>'
        f'<td><span class="badge {s["type"].lower()}">{s["type"]}</span></td>'
        f'<td class="mono">{s["cidr"]}</td>'
        f'<td class="num">{s["total_ips"]:,}</td>'
        f'<td class="num">{used:,}</td>'
        f'<td class="num">{s["available"]:,}</td>'
        f'<td>{util_bar}</td>'
        f'<td>{eks}</td>'
        f'</tr>'
    )


def _render_vpc_section(
    vpc: dict[str, Any],
    is_active: bool,
    eks_data: dict[str, Any] | None = None,
    unallocated: list[str] | None = None,
) -> str:
    """Render a self-contained section for one VPC (shown or hidden)."""
    vid = vpc["id"]
    hidden_attr = "" if is_active else ' hidden'

    # Stats
    total_subnets = len(vpc["subnets"])
    public_count = sum(1 for s in vpc["subnets"] if s["type"] == "Public")
    private_count = total_subnets - public_count
    total_ips = sum(s["total_ips"] for s in vpc["subnets"])
    az_count = len(vpc["by_az"])
    vpc_cidr_str = ", ".join(vpc["cidrs"])
    cidr_start = _ip(vpc["vpc_start"])
    cidr_end = _ip(vpc["vpc_end"])

    # AZ swim lanes
    az_lanes_html = ""
    for i, (az, az_subnets) in enumerate(vpc["by_az"].items()):
        az_cls = _AZ_COLORS[i % len(_AZ_COLORS)]
        bars_html = "".join(_bar_html(s) for s in az_subnets)
        az_lanes_html += (
            f'<div class="az-row">'
            f'<div class="az-label {az_cls}">{az}</div>'
            f'<div class="vpc-bar">{bars_html}</div>'
            f'</div>'
        )
    if unallocated:
        unalloc_bars = "".join(
            f'<div class="subnet-bar unallocated"'
            f' style="left:{pos["x"]}%;width:{pos["width"]}%" title="{cidr}">'
            f'<span class="bar-label">{cidr}</span>'
            f'</div>'
            for cidr in unallocated
            for pos in [_subnet_position(cidr, vpc["vpc_start"], vpc["vpc_end"])]
        )
        az_lanes_html += (
            f'<div class="az-row">'
            f'<div class="az-label az-free">Free</div>'
            f'<div class="vpc-bar">{unalloc_bars}</div>'
            f'</div>'
        )
    az_lanes_html = az_lanes_html or (
        '<p style="color:var(--dim);padding:1rem 0">No subnets found</p>'
    )

    # Dependency tree
    tree_inner = ""
    for i, (az, az_subnets) in enumerate(vpc["by_az"].items()):
        az_cls = _AZ_COLORS[i % len(_AZ_COLORS)]
        items_html = "".join(_tree_subnet_item(s) for s in az_subnets)
        tree_inner += (
            f'<li>'
            f'<div class="tree-az"><span class="az-dot {az_cls}"></span>{az}</div>'
            f'<ul>{items_html}</ul>'
            f'</li>'
        )
    tree_html = (
        f'<ul class="tree">'
        f'<li>'
        f'<div class="tree-vpc">'
        f'<span class="vpc-icon">&#11042;</span>'
        f'&nbsp;VPC&nbsp;&nbsp;<code>{vid}</code>'
        f'&nbsp;&nbsp;<span class="dim">({vpc_cidr_str})</span>'
        f'</div>'
        f'<ul>{tree_inner}</ul>'
        f'</li>'
        f'</ul>'
    )

    # Details table
    table_rows_html = "".join(_table_row(s) for s in vpc["subnets"])
    table_rows_html = table_rows_html or (
        '<tr><td colspan="10" style="text-align:center;color:var(--dim);padding:2rem">No subnets</td></tr>'
    )

    # EKS section
    if eks_data:
        status = eks_data.get("status", "OK")
        st_cls = "ok" if status == "OK" else "warning"
        issues_html = ""
        proposals_html = ""
        if eks_data.get("issues"):
            items = "".join(f'<li>{iss}</li>' for iss in eks_data["issues"])
            issues_html = f'<div class="eks-group"><h4>Issues</h4><ul class="eks-list">{items}</ul></div>'
        if eks_data.get("proposals"):
            items = "".join(f'<li>{prop}</li>' for prop in eks_data["proposals"])
            proposals_html = f'<div class="eks-group"><h4>Proposals</h4><ul class="eks-list">{items}</ul></div>'
        eks_body = (
            issues_html + proposals_html
            if (issues_html or proposals_html)
            else '<p class="ok-msg">&#10003; All EKS networking best practices are met.</p>'
        )
        eks_section = (
            f'<div class="section eks-section {st_cls}">'
            f'<div class="section-header">'
            f'<h2>EKS Readiness</h2>'
            f'<span class="eks-status {st_cls}">{status}</span>'
            f'</div>'
            f'{eks_body}'
            f'</div>'
        )
    else:
        eks_section = ""

    return f"""<div class="vpc-section" id="section-{vid}"{hidden_attr}>
  <div class="stats-row">
    <div class="stat-card">
      <div class="stat-label">Subnets</div>
      <div class="stat-value">{total_subnets}</div>
      <div class="stat-sub">
        <span class="stat-pub">{public_count} public</span> &middot;
        <span class="stat-priv">{private_count} private</span>
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Availability Zones</div>
      <div class="stat-value">{az_count}</div>
      <div class="stat-sub">across all subnets</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Usable IPs</div>
      <div class="stat-value">{total_ips:,}</div>
      <div class="stat-sub">total across subnets</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">VPC CIDR</div>
      <div class="stat-value" style="font-size:1rem;font-family:monospace;letter-spacing:0">{vpc_cidr_str}</div>
      <div class="stat-sub">address space</div>
    </div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>CIDR Map</h2>
      <div class="zoom-controls">
        <button class="zoom-btn" onclick="zoomOut('{vid}')" title="Zoom out">&#8722;</button>
        <span class="zoom-level" id="zoom-level-{vid}">100%</span>
        <button class="zoom-btn" onclick="zoomIn('{vid}')" title="Zoom in">&#43;</button>
        <button class="zoom-btn" onclick="zoomReset('{vid}')" title="Reset zoom">&#8634;</button>
      </div>
    </div>
    <div id="az-lanes-{vid}">{az_lanes_html}</div>
    <div class="cidr-range-row">
      <span>{cidr_start}</span>
      <span>{cidr_end}</span>
    </div>
    <div class="legend">
      <div class="legend-item"><div class="legend-dot" style="background:var(--public)"></div>Public subnet</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--private)"></div>Private subnet</div>
      <div class="legend-item"><div class="legend-dot" style="background:var(--unalloc);border:1px dashed var(--border2)"></div>Unallocated</div>
      <div class="legend-item"><div class="legend-dot" style="background:rgba(0,0,0,.3)"></div>Used IPs overlay</div>
    </div>
  </div>

  <div class="section">
    <div class="section-header"><h2>Dependency Map</h2></div>
    {tree_html}
  </div>

  <div class="section">
    <div class="section-header"><h2>Subnet Details</h2></div>
    <div class="table-wrap">
      <table class="details-table" data-vpc="{vid}">
        <thead>
          <tr>
            <th onclick="sortTable(this,0)">Name</th>
            <th onclick="sortTable(this,1)">Subnet ID</th>
            <th onclick="sortTable(this,2)">AZ</th>
            <th onclick="sortTable(this,3)">Type</th>
            <th onclick="sortTable(this,4)">CIDR</th>
            <th onclick="sortTable(this,5)" style="text-align:right">Total IPs</th>
            <th onclick="sortTable(this,6)" style="text-align:right">Used</th>
            <th onclick="sortTable(this,7)" style="text-align:right">Available</th>
            <th onclick="sortTable(this,8)">Utilization</th>
            <th>EKS Tags</th>
          </tr>
        </thead>
        <tbody class="details-body">{table_rows_html}</tbody>
      </table>
    </div>
  </div>

  {eks_section}
</div>"""


def _render_html(
    vpcs: list[dict[str, Any]],
    vpc_id: str | None = None,
    eks_data: dict[str, Any] | None = None,
    unallocated: list[str] | None = None,
    vpc_extras: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Render the full HTML page."""
    active_id = vpc_id or (vpcs[0]["id"] if vpcs else "")

    vpc_selector_display = "none" if len(vpcs) <= 1 else "flex"
    vpc_buttons = "".join(
        f'<button class="vpc-btn{" active" if v["id"] == active_id else ""}"'
        f' onclick="selectVpc(this,\'{v["id"]}\')">{v["id"]}</button>'
        for v in vpcs
    )

    # Ensure every VPC dict has by_az (tests may pass pre-built dicts without it)
    for v in vpcs:
        if "by_az" not in v:
            by_az: dict[str, list] = {}
            for s in v.get("subnets", []):
                by_az.setdefault(s.get("az", "unknown"), []).append(s)
            v["by_az"] = by_az

    # Each VPC rendered as its own section div (show/hide on switch — no JS re-render)
    vpc_sections_html = "".join(
        _render_vpc_section(
            v,
            is_active=(v["id"] == active_id),
            eks_data=(
                vpc_extras.get(v["id"], {}).get("eks_data")
                if vpc_extras else
                (eks_data if v["id"] == active_id else None)
            ),
            unallocated=(
                vpc_extras.get(v["id"], {}).get("unallocated")
                if vpc_extras else
                (unallocated if v["id"] == active_id else None)
            ),
        )
        for v in vpcs
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>VPC Visualizer &#8212; {active_id}</title>
<style>
:root {{
  --bg: #0b1120;
  --surface: #131c2e;
  --surface2: #1a2540;
  --border: #1e3050;
  --border2: #2a3f65;
  --text: #e2e8f0;
  --dim: #64748b;
  --dim2: #94a3b8;
  --public: #22c55e;
  --public-bg: rgba(34,197,94,.14);
  --private: #3b82f6;
  --private-bg: rgba(59,130,246,.14);
  --accent: #7c3aed;
  --accent2: #8b5cf6;
  --highlight: #f59e0b;
  --unalloc: #1e293b;
  --az-amber: #f59e0b;
  --az-cyan: #06b6d4;
  --az-emerald: #10b981;
  --az-rose: #f43f5e;
  --ok: #22c55e;
  --warning: #f59e0b;
  --card-radius: 1rem;
}}
*,*::before,*::after {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  padding: 1.5rem 2rem 3rem;
  background-image:
    radial-gradient(ellipse at 15% 0%, rgba(124,58,237,.09) 0%, transparent 55%),
    radial-gradient(ellipse at 85% 0%, rgba(6,182,212,.06) 0%, transparent 55%);
}}
code {{
  font-family: 'SF Mono',Menlo,Monaco,'Cascadia Code',monospace;
  font-size: 0.875em;
}}

/* ── Page header ─────────────────────────────────── */
.page-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 0.75rem;
}}
.page-title {{
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}}
.page-title code {{
  color: var(--accent2);
  background: rgba(139,92,246,.12);
  padding: 0.15em 0.45em;
  border-radius: 0.375rem;
}}
.vpc-selector {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
.vpc-btn {{
  padding: 0.35rem 0.8rem;
  border: 1px solid var(--border2);
  background: var(--surface);
  color: var(--dim2);
  border-radius: 0.5rem;
  cursor: pointer;
  font-size: 0.75rem;
  font-family: 'SF Mono',monospace;
  transition: all 0.2s;
}}
.vpc-btn:hover {{ border-color: var(--accent2); color: var(--text); }}
.vpc-btn.active {{ background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }}

/* ── Stats cards ─────────────────────────────────── */
.stats-row {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 1rem;
  margin-bottom: 1.25rem;
}}
.stat-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--card-radius);
  padding: 1.1rem 1.25rem;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s, transform 0.2s;
}}
.stat-card::after {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  opacity: 0.7;
}}
.stat-card:hover {{ border-color: var(--border2); transform: translateY(-1px); }}
.stat-label {{
  font-size: 0.63rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--dim);
  margin-bottom: 0.4rem;
}}
.stat-value {{
  font-size: 1.65rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1;
}}
.stat-sub {{ font-size: 0.7rem; color: var(--dim2); margin-top: 0.3rem; }}
.stat-pub  {{ color: var(--public);  font-weight: 600; }}
.stat-priv {{ color: var(--private); font-weight: 600; }}

/* ── Section card ────────────────────────────────── */
.section {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--card-radius);
  padding: 1.5rem;
  margin-bottom: 1.25rem;
}}
.section-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}}
.section-header h2 {{
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim2);
}}

/* ── Zoom controls ───────────────────────────────── */
.zoom-controls {{ display: flex; gap: 0.25rem; align-items: center; }}
.zoom-btn {{
  width: 1.75rem; height: 1.75rem;
  border: 1px solid var(--border2);
  background: var(--surface2);
  color: var(--text);
  border-radius: 0.375rem;
  cursor: pointer;
  font-size: 1rem;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
  line-height: 1;
}}
.zoom-btn:hover {{ border-color: var(--accent2); color: var(--accent2); }}
.zoom-level {{ font-size: 0.68rem; color: var(--dim2); min-width: 2.5rem; text-align: center; }}

/* ── AZ swim lanes ───────────────────────────────── */
.az-row {{
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 0.625rem;
}}
.az-label {{
  font-size: 0.63rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  min-width: 8rem;
  text-align: right;
  white-space: nowrap;
  flex-shrink: 0;
}}
.az-amber   {{ color: var(--az-amber); }}
.az-cyan    {{ color: var(--az-cyan); }}
.az-emerald {{ color: var(--az-emerald); }}
.az-rose    {{ color: var(--az-rose); }}
.az-free    {{ color: var(--dim); }}
.vpc-bar {{
  flex: 1;
  height: 2.75rem;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  position: relative;
  transform-origin: left center;
  transition: transform 0.2s;
}}
.cidr-range-row {{
  display: flex;
  padding-left: calc(8rem + 1rem);
  font-size: 0.6rem;
  color: var(--dim);
  margin-top: 0.2rem;
  margin-bottom: 0.75rem;
  justify-content: space-between;
}}

/* ── Subnet bars ─────────────────────────────────── */
.subnet-bar {{
  position: absolute;
  top: 1px; bottom: 1px;
  min-width: 18px;
  border-radius: 0.375rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.6rem;
  font-weight: 700;
  overflow: hidden;
  white-space: nowrap;
  transition: filter 0.15s, outline 0.15s;
  outline: 2px solid transparent;
  outline-offset: 1px;
}}
.subnet-bar:hover  {{ filter: brightness(1.2); outline-color: var(--highlight); z-index: 10; }}
.subnet-bar.selected {{ outline-color: var(--highlight); z-index: 20; filter: brightness(1.15); }}
.subnet-bar.public  {{
  background: linear-gradient(135deg, #15803d 0%, #22c55e 100%);
  color: #052e16;
}}
.subnet-bar.private {{
  background: linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%);
  color: #fff;
}}
.subnet-bar.unallocated {{
  background: var(--unalloc);
  color: var(--dim);
  border: 1px dashed var(--border2);
}}
.ip-fill {{
  position: absolute;
  left: 0; top: 0; bottom: 0;
  background: rgba(0,0,0,.3);
  pointer-events: none;
  border-radius: 0.375rem 0 0 0.375rem;
}}
.bar-label {{
  position: relative;
  z-index: 1;
  padding: 0 0.35rem;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
  pointer-events: none;
}}

/* ── Legend ──────────────────────────────────────── */
.legend {{
  display: flex;
  gap: 1.25rem;
  flex-wrap: wrap;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
  font-size: 0.73rem;
  color: var(--dim2);
}}
.legend-item {{ display: flex; align-items: center; gap: 0.375rem; }}
.legend-dot {{
  width: 0.7rem; height: 0.7rem;
  border-radius: 0.2rem;
  flex-shrink: 0;
}}

/* ── Tooltip ─────────────────────────────────────── */
.tooltip {{
  position: fixed;
  background: var(--surface2);
  border: 1px solid var(--border2);
  border-radius: 0.875rem;
  padding: 0.875rem 1rem;
  font-size: 0.78rem;
  box-shadow: 0 24px 48px rgba(0,0,0,.6), 0 0 0 1px rgba(255,255,255,.04);
  z-index: 200;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.1s;
  min-width: 220px;
  max-width: 320px;
}}
.tooltip.visible {{ opacity: 1; }}
.tip-name {{ font-weight: 700; font-size: 0.875rem; margin-bottom: 0.5rem; color: var(--text); }}
.tip-row {{ display: flex; justify-content: space-between; color: var(--dim2); margin: 0.15rem 0; gap: 1rem; }}
.tip-row .tip-val {{ color: var(--text); text-align: right; }}
.tip-util {{
  margin-top: 0.5rem;
  background: rgba(255,255,255,.07);
  border-radius: 99px;
  height: 4px;
  overflow: hidden;
}}
.tip-util-fill {{ height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); border-radius: inherit; }}
.tip-eks-row {{ display: flex; align-items: center; gap: 0.375rem; flex-wrap: wrap; margin-top: 0.4rem; }}
.tip-eks-label {{ font-size: 0.72rem; color: var(--dim2); }}

/* ── Dependency tree ─────────────────────────────── */
.tree, .tree ul {{ list-style: none; }}
.tree {{ padding: 0.25rem 0; }}
.tree ul {{
  margin-left: 1.25rem;
  padding-left: 0;
  border-left: 1px solid var(--border2);
  margin-top: 0.25rem;
  padding-bottom: 0.25rem;
}}
.tree ul li {{
  position: relative;
  padding: 0.15rem 0 0.15rem 1.25rem;
}}
.tree ul li::before {{
  content: '';
  position: absolute;
  left: 0; top: 0.7rem;
  width: 1.25rem;
  border-top: 1px solid var(--border2);
}}
.tree-vpc {{
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  font-weight: 600;
  padding: 0.5rem 0.875rem;
  background: var(--surface2);
  border-radius: 0.5rem;
  border: 1px solid var(--border2);
  margin-bottom: 0.25rem;
}}
.vpc-icon {{ color: var(--accent2); }}
.tree-az {{
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.73rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 0.25rem 0.5rem;
  color: var(--dim2);
}}
.az-dot {{
  width: 0.45rem; height: 0.45rem;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}}
.az-dot.az-amber   {{ background: var(--az-amber); }}
.az-dot.az-cyan    {{ background: var(--az-cyan); }}
.az-dot.az-emerald {{ background: var(--az-emerald); }}
.az-dot.az-rose    {{ background: var(--az-rose); }}
.tree-leaf {{
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.775rem;
  padding: 0.3rem 0.5rem;
  border-radius: 0.375rem;
  cursor: pointer;
  transition: background 0.15s;
  flex-wrap: wrap;
}}
.tree-leaf:hover {{ background: var(--surface2); }}
.dot {{ width: 0.45rem; height: 0.45rem; border-radius: 50%; flex-shrink: 0; }}
.dot.public  {{ background: var(--public); }}
.dot.private {{ background: var(--private); }}
.leaf-name {{ font-weight: 600; color: var(--text); }}
.leaf-cidr {{ color: var(--dim); font-family: 'SF Mono',monospace; font-size: 0.72rem; }}
.leaf-ips  {{ color: var(--dim2); font-size: 0.7rem; }}

/* ── Badges ──────────────────────────────────────── */
.badge {{
  display: inline-flex; align-items: center;
  padding: 0.1rem 0.45rem;
  border-radius: 9999px;
  font-size: 0.62rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}}
.badge.public  {{ background: var(--public-bg);  color: var(--public); }}
.badge.private {{ background: var(--private-bg); color: var(--private); }}
.eks-badge {{
  display: inline-flex; align-items: center;
  padding: 0.1rem 0.4rem;
  border-radius: 0.25rem;
  font-size: 0.62rem;
  font-weight: 600;
  background: rgba(124,58,237,.14);
  color: var(--accent2);
  border: 1px solid rgba(124,58,237,.22);
  white-space: nowrap;
}}

/* ── Details table ───────────────────────────────── */
.table-wrap {{ overflow-x: auto; border-radius: 0.5rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; }}
thead th {{
  padding: 0.55rem 0.75rem;
  text-align: left;
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition: color 0.15s;
}}
thead th:hover {{ color: var(--text); }}
thead th.sorted-asc::after  {{ content: ' \2191'; color: var(--accent2); }}
thead th.sorted-desc::after {{ content: ' \2193'; color: var(--accent2); }}
tbody tr {{ transition: background 0.1s; }}
tbody tr:hover {{ background: rgba(255,255,255,.03); }}
tbody tr.highlighted {{
  background: rgba(124,58,237,.08);
  outline: 1px solid rgba(124,58,237,.2);
  outline-offset: -1px;
}}
tbody td {{
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}}
.mono {{ font-family: 'SF Mono',Menlo,monospace; font-size: 0.73em; }}
.num  {{ text-align: right; font-variant-numeric: tabular-nums; }}
.dim  {{ color: var(--dim2); }}
.util-wrap {{
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 80px;
}}
.util-fill {{
  height: 3px;
  min-width: 2px;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  border-radius: 99px;
  flex-shrink: 0;
}}
.util-pct {{ font-size: 0.7rem; color: var(--dim2); white-space: nowrap; min-width: 2.5rem; }}

/* ── EKS section ─────────────────────────────────── */
.eks-section {{ border-left: 3px solid transparent; }}
.eks-section.ok      {{ border-left-color: var(--ok); }}
.eks-section.warning {{ border-left-color: var(--warning); }}
.eks-status {{
  padding: 0.2rem 0.7rem;
  border-radius: 9999px;
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}}
.eks-status.ok      {{ background: rgba(34,197,94,.12);  color: var(--ok); }}
.eks-status.warning {{ background: rgba(245,158,11,.12); color: var(--warning); }}
.eks-group {{ margin-bottom: 1rem; }}
.eks-group h4 {{
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--dim);
  margin-bottom: 0.5rem;
}}
.eks-list {{ padding-left: 1.125rem; }}
.eks-list li {{ font-size: 0.8rem; color: var(--dim2); padding: 0.2rem 0; line-height: 1.55; }}
.ok-msg {{ color: var(--ok); font-size: 0.85rem; }}
</style>
</head>
<body>

<div class="page-header">
  <div class="page-title">
    VPC Visualizer &nbsp;&#8212;&nbsp; <code id="active-vpc-id">{active_id}</code>
  </div>
  <div class="vpc-selector" id="vpc-selector" style="display:{vpc_selector_display}">{vpc_buttons}</div>
</div>

{vpc_sections_html}

<!-- Tooltip: pre-built template updated via textContent (no innerHTML) -->
<div class="tooltip" id="tooltip">
  <div class="tip-name" id="tip-name"></div>
  <div class="tip-row"><span>CIDR</span><span class="tip-val mono" id="tip-cidr"></span></div>
  <div class="tip-row"><span>ID</span><span class="tip-val mono" id="tip-id"></span></div>
  <div class="tip-row"><span>AZ</span><span class="tip-val" id="tip-az"></span></div>
  <div class="tip-row"><span>Type</span><span class="tip-val"><span class="badge" id="tip-type"></span></span></div>
  <div class="tip-row"><span>IPs</span><span class="tip-val" id="tip-ips"></span></div>
  <div class="tip-util"><div class="tip-util-fill" id="tip-util-fill"></div></div>
  <div class="tip-row"><span>Utilization</span><span class="tip-val" id="tip-util-pct"></span></div>
  <div class="tip-eks-row" id="tip-eks-row" style="display:none">
    <span class="tip-eks-label">EKS</span>
    <span class="mono" id="tip-eks-text"></span>
  </div>
</div>

<script>
var currentVpcId = "{active_id}";
var zoomMap = {{}};
var selectedBar = null;

// ── Tooltip (textContent only — no innerHTML) ─────────────────
var tip = document.getElementById('tooltip');

function showTip(evt, el) {{
  var d = el.dataset;
  var util = parseFloat(d.util);

  document.getElementById('tip-name').textContent = d.name;
  document.getElementById('tip-cidr').textContent = d.cidr;
  document.getElementById('tip-id').textContent   = d.id;
  document.getElementById('tip-az').textContent   = d.az;

  var typeEl = document.getElementById('tip-type');
  typeEl.textContent = d.type;
  typeEl.className   = 'badge ' + d.type.toLowerCase();

  document.getElementById('tip-ips').textContent =
    Number(d.used).toLocaleString() + ' used / ' + Number(d.total).toLocaleString() + ' total';
  document.getElementById('tip-util-fill').style.width = util + '%';
  document.getElementById('tip-util-pct').textContent  = util + '%';

  var eksRow  = document.getElementById('tip-eks-row');
  var eksArr  = d.eks ? d.eks.split(',').filter(Boolean) : [];
  if (eksArr.length) {{
    document.getElementById('tip-eks-text').textContent =
      eksArr.map(function(t) {{ return t.split('/').pop(); }}).join(' · ');
    eksRow.style.display = '';
  }} else {{
    eksRow.style.display = 'none';
  }}

  tip.classList.add('visible');
  placeTip(evt);
}}

function placeTip(evt) {{
  var x = evt.clientX + 16;
  var y = evt.clientY + 16;
  if (x + 330 > window.innerWidth)  {{ x = evt.clientX - 334; }}
  if (y + 260 > window.innerHeight) {{ y = evt.clientY - 264; }}
  tip.style.left = x + 'px';
  tip.style.top  = y + 'px';
}}

function hideTip() {{ tip.classList.remove('visible'); }}

document.addEventListener('mousemove', function(e) {{
  if (tip.classList.contains('visible')) {{ placeTip(e); }}
}});

// ── Bar + row selection ───────────────────────────────────────
function selectBar(el) {{
  if (selectedBar) {{ selectedBar.classList.remove('selected'); }}
  selectedBar = el;
  el.classList.add('selected');
  scrollToRow(el.dataset.id);
}}

function scrollToRow(id) {{
  var row = document.getElementById('row-' + id);
  if (!row) {{ return; }}
  var section = document.getElementById('section-' + currentVpcId);
  if (section) {{
    section.querySelectorAll('tbody tr').forEach(function(r) {{
      r.classList.remove('highlighted');
    }});
  }}
  row.classList.add('highlighted');
  row.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
}}

// ── VPC Switcher (show/hide pre-rendered sections) ────────────
function selectVpc(btn, id) {{
  document.querySelectorAll('.vpc-section').forEach(function(s) {{ s.hidden = true; }});
  var target = document.getElementById('section-' + id);
  if (target) {{ target.hidden = false; }}
  document.querySelectorAll('.vpc-btn').forEach(function(b) {{ b.classList.remove('active'); }});
  btn.classList.add('active');
  currentVpcId = id;
  document.getElementById('active-vpc-id').textContent = id;
  if (selectedBar) {{ selectedBar.classList.remove('selected'); selectedBar = null; }}
}}

// ── Table sorting ─────────────────────────────────────────────
var sortState = {{}};

function sortTable(th, col) {{
  var table = th.closest('table');
  var vid   = table.dataset.vpc;
  var key   = vid + ':' + col;
  sortState[key] = sortState[key] === 1 ? -1 : 1;
  var dir = sortState[key];

  table.querySelectorAll('thead th').forEach(function(h, i) {{
    h.classList.remove('sorted-asc','sorted-desc');
    if (i === col) {{ h.classList.add(dir === 1 ? 'sorted-asc' : 'sorted-desc'); }}
  }});

  var tbody = table.querySelector('tbody');
  var rows  = Array.from(tbody.querySelectorAll('tr'));
  rows.sort(function(a, b) {{
    var ac = a.cells[col] ? a.cells[col].textContent.trim() : '';
    var bc = b.cells[col] ? b.cells[col].textContent.trim() : '';
    var an = parseFloat(ac.replace(/,/g,''));
    var bn = parseFloat(bc.replace(/,/g,''));
    if (!isNaN(an) && !isNaN(bn)) {{ return (an - bn) * dir; }}
    return ac.localeCompare(bc) * dir;
  }});
  rows.forEach(function(r) {{ tbody.appendChild(r); }});
}}

// ── Zoom (per-VPC) ────────────────────────────────────────────
function getZoom(vid) {{ return zoomMap[vid] || 1; }}

function applyZoom(vid) {{
  var z = getZoom(vid);
  var section = document.getElementById('section-' + vid);
  if (!section) {{ return; }}
  section.querySelectorAll('.vpc-bar').forEach(function(bar) {{
    bar.style.transform = 'scaleX(' + z + ')';
    bar.style.transformOrigin = 'left center';
  }});
  var lbl = document.getElementById('zoom-level-' + vid);
  if (lbl) {{ lbl.textContent = Math.round(z * 100) + '%'; }}
}}

function zoomIn(vid)    {{ zoomMap[vid] = Math.min(getZoom(vid) + 0.25, 5);    applyZoom(vid); }}
function zoomOut(vid)   {{ zoomMap[vid] = Math.max(getZoom(vid) - 0.25, 0.25); applyZoom(vid); }}
function zoomReset(vid) {{ zoomMap[vid] = 1;                                    applyZoom(vid); }}
</script>
</body>
</html>"""


def generate_visualization(
    vpc_data: dict[str, Any],
    subnets: list[dict[str, Any]],
    vpc_id: str | None = None,
    output_dir: str | None = None,
    eks_data: dict[str, Any] | None = None,
    unallocated: list[str] | None = None,
) -> Path:
    """Generate an HTML visualization file and return its path."""
    vpc_cidrs = [a["CidrBlock"] for a in vpc_data.get("CidrBlockAssociationSet", [])]
    if not vpc_cidrs:
        vpc_cidrs = [vpc_data.get("CidrBlock", "10.0.0.0/16")]
    vid = vpc_id or vpc_data.get("VpcId", "")
    vpcs = [_build_vpc_data(vid, subnets, vpc_cidrs)]
    html = _render_html(vpcs, vpc_id=vid, eks_data=eks_data, unallocated=unallocated)

    out = Path(output_dir) if output_dir else Path.cwd()
    filepath = out / f"vpc-visualizer-{vid}.html"
    filepath.write_text(html, encoding="utf-8")
    return filepath


def generate_multi_vpc_visualization(
    vpcs_data: list[dict[str, Any]],
    output_dir: str | None = None,
    vpc_extras: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Generate an HTML visualization for multiple VPCs."""
    vpcs = []
    for v in vpcs_data:
        vid = v.get("VpcId", "unknown")
        vpc_cidrs = [a["CidrBlock"] for a in v.get("CidrBlockAssociationSet", [])]
        subnets = v.get("Subnets", [])
        vpcs.append(_build_vpc_data(vid, subnets, vpc_cidrs if vpc_cidrs else None))

    html = _render_html(vpcs, vpc_extras=vpc_extras)

    out = Path(output_dir) if output_dir else Path.cwd()
    filepath = out / "vpc-visualizer-multi.html"
    filepath.write_text(html, encoding="utf-8")
    return filepath


def open_visualization(filepath: Path) -> None:
    """Open the visualization file in the default browser."""
    webbrowser.open(filepath.as_uri())

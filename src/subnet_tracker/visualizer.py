"""Visualizer module — generates an interactive HTML visualization of VPC subnets."""

from __future__ import annotations

import ipaddress
import json
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any


def _subnet_to_dict(subnet: dict[str, Any]) -> dict[str, Any]:
    """Normalize a subnet dict into a flat dict the visualizer understands."""
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
        "tags": [
            {"key": t["Key"], "value": t["Value"]}
            for t in subnet.get("Tags", [])
        ],
    }


def _vpc_cidr_range(cidrs: list[str]) -> tuple[float, float]:
    """Return (start, end) for a list of CIDR blocks within a VPC."""
    nets = [ipaddress.ip_network(c) for c in cidrs]
    start = int(min(n.network_address for n in nets))
    end = int(max(n.broadcast_address for n in nets))
    return float(start), float(end)


def _subnet_position(cidr: str, vpc_start: float, vpc_end: float) -> dict[str, float]:
    """Compute x, width (in px) for a subnet bar within the VPC range."""
    net = ipaddress.ip_network(cidr)
    subnet_start = int(net.network_address)
    subnet_end = int(net.broadcast_address)
    vpc_size = vpc_end - vpc_start
    subnet_size = subnet_end - subnet_start

    x = ((subnet_start - vpc_start) / vpc_size) * 100
    width = (subnet_size / vpc_size) * 100

    return {"x": round(x, 2), "width": round(width, 2)}


def _build_vpc_data(vpc_id: str, subnets: list[dict[str, Any]], vpc_cidrs: list[str] | None = None) -> dict[str, Any]:
    """Build a single VPC's visualization data."""
    if vpc_cidrs is None:
        cidrs = [s["CidrBlock"] for s in subnets]
        vpc_cidrs = cidrs if cidrs else ["10.0.0.0/16"]
    vpc_start, vpc_end = _vpc_cidr_range(vpc_cidrs)

    bars = []
    for s in subnets:
        pos = _subnet_position(s["CidrBlock"], vpc_start, vpc_end)
        name = next(
            (tag["Value"] for tag in s.get("Tags", []) if tag["Key"] == "Name"),
            "N/A",
        )
        bars.append({
            "id": s["SubnetId"],
            "name": name,
            "cidr": s["CidrBlock"],
            "az": s["AvailabilityZone"],
            "type": s.get("_type", "Private"),
            "x": pos["x"],
            "width": pos["width"],
            "total_ips": ipaddress.ip_network(s["CidrBlock"]).num_addresses,
            "available": s.get("AvailableIpAddressCount", 0),
            "tags": [
                {"key": t["Key"], "value": t["Value"]}
                for t in s.get("Tags", [])
            ],
        })

    return {
        "id": vpc_id,
        "cidrs": vpc_cidrs,
        "vpc_start": vpc_start,
        "vpc_end": vpc_end,
        "subnets": bars,
    }


def _render_html(vpcs: list[dict[str, Any]], vpc_id: str | None = None) -> str:
    """Render the full HTML page."""
    vpc_id = vpc_id or (vpcs[0]["id"] if vpcs else "")
    vpcs_json = json.dumps(vpcs)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VPC Visualizer</title>
<style>
  :root {{
    --bg: #0f172a;
    --surface: #1e293b;
    --border: #334155;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --public: #22c55e;
    --public-dim: #16a34a;
    --private: #3b82f6;
    --private-dim: #2563eb;
    --accent: #8b5cf6;
    --highlight: #f59e0b;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 2rem;
  }}
  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 2rem;
  }}
  .header h1 {{
    font-size: 1.5rem;
    font-weight: 600;
  }}
  .header h1 span {{ color: var(--accent); }}
  .vpc-selector {{
    display: flex;
    gap: 0.5rem;
  }}
  .vpc-btn {{
    padding: 0.5rem 1rem;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    border-radius: 0.5rem;
    cursor: pointer;
    font-size: 0.875rem;
    transition: all 0.2s;
  }}
  .vpc-btn:hover {{ border-color: var(--accent); }}
  .vpc-btn.active {{
    background: var(--accent);
    border-color: var(--accent);
    color: white;
  }}
  .zoom-controls {{
    display: flex;
    gap: 0.25rem;
    align-items: center;
  }}
  .zoom-btn {{
    width: 2rem;
    height: 2rem;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    border-radius: 0.5rem;
    cursor: pointer;
    font-size: 1rem;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s;
  }}
  .zoom-btn:hover {{ border-color: var(--accent); }}
  .zoom-level {{
    font-size: 0.75rem;
    color: var(--text-dim);
    min-width: 3rem;
    text-align: center;
  }}
  .map {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 1rem;
    padding: 2rem;
    overflow-x: auto;
    position: relative;
  }}
  .vpc-bar {{
    height: 3rem;
    background: var(--bg);
    border-radius: 0.5rem;
    position: relative;
    margin-bottom: 1rem;
  }}
  .subnet-bar {{
    position: absolute;
    top: 0;
    height: 100%;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 500;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    padding: 0 0.5rem;
    border: 2px solid transparent;
  }}
  .subnet-bar.public {{ background: var(--public); color: #064e3b; }}
  .subnet-bar.private {{ background: var(--private); color: white; }}
  .subnet-bar:hover {{
    transform: scaleY(1.1);
    border-color: var(--highlight);
    z-index: 10;
  }}
  .subnet-bar.expanded {{
    transform: scaleY(1.3);
    border-color: var(--highlight);
    z-index: 20;
  }}
  .tooltip {{
    position: fixed;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1rem;
    font-size: 0.875rem;
    box-shadow: 0 20px 25px -5px rgba(0,0,0,0.3);
    z-index: 100;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s;
    min-width: 200px;
  }}
  .tooltip.visible {{ opacity: 1; }}
  .tooltip h3 {{ margin-bottom: 0.5rem; font-size: 1rem; }}
  .tooltip p {{ color: var(--text-dim); margin: 0.25rem 0; }}
  .tooltip .tag {{
    display: inline-block;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 0.25rem;
    padding: 0.125rem 0.5rem;
    font-size: 0.75rem;
    margin: 0.125rem;
  }}
  .legend {{
    display: flex;
    gap: 1.5rem;
    margin-top: 1rem;
    padding: 1rem;
    background: var(--surface);
    border-radius: 0.5rem;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
  }}
  .legend-color {{
    width: 1rem;
    height: 1rem;
    border-radius: 0.25rem;
  }}
  .cidr-labels {{
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-top: 0.25rem;
  }}
  .details-panel {{
    margin-top: 2rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 1rem;
    padding: 1.5rem;
  }}
  .details-panel h2 {{
    font-size: 1.125rem;
    margin-bottom: 1rem;
  }}
  .subnet-detail {{
    background: var(--bg);
    border-radius: 0.5rem;
    padding: 1rem;
    margin-bottom: 0.5rem;
  }}
  .subnet-detail h4 {{
    font-size: 0.875rem;
    margin-bottom: 0.25rem;
  }}
  .subnet-detail p {{
    font-size: 0.875rem;
    color: var(--text-dim);
  }}
</style>
</head>
<body>
<div class="header">
  <h1>VPC <span id="vpc-name">Visualizer</span></h1>
  <div class="vpc-selector" id="vpc-selector"></div>
  <div class="zoom-controls">
    <button class="zoom-btn" onclick="zoomOut()">-</button>
    <span class="zoom-level" id="zoom-level">100%</span>
    <button class="zoom-btn" onclick="zoomIn()">+</button>
    <button class="zoom-btn" onclick="zoomReset()" title="Reset">&#8634;</button>
  </div>
</div>
<div class="map" id="map">
  <div class="vpc-bar" id="vpc-bar"></div>
  <div class="cidr-labels" id="cidr-labels"></div>
</div>
<div class="legend">
  <div class="legend-item">
    <div class="legend-color" style="background: var(--public)"></div>
    Public
  </div>
  <div class="legend-item">
    <div class="legend-color" style="background: var(--private)"></div>
    Private
  </div>
</div>
<div class="details-panel">
  <h2>Subnet Details</h2>
  <div id="subnet-details"></div>
</div>
<div class="tooltip" id="tooltip"></div>

<script>
const data = {vpcs_json};
const vpcId = "{vpc_id}";
let currentVpc = null;
let zoom = 1;
let expandedSubnet = null;

function findVpc(id) {{
  return data.find(v => v.id === id) || data[0];
}}

function renderVpcSelector() {{
  const el = document.getElementById('vpc-selector');
  el.innerHTML = data.map(v =>
    `<button class="vpc-btn ${{v.id === vpcId ? 'active' : ''}}" onclick="selectVpc('${{v.id}}')">$${{v.id}}</button>`
  ).join('');
}}

function selectVpc(id) {{
  document.querySelectorAll('.vpc-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  const vpc = findVpc(id);
  document.getElementById('vpc-name').textContent = vpc.id;
  renderMap(vpc);
  renderDetails(vpc);
}}

function renderMap(vpc) {{
  currentVpc = vpc;
  const bar = document.getElementById('vpc-bar');
  bar.innerHTML = '';
  bar.style.transform = `scaleX(${{zoom}})`;
  bar.style.transformOrigin = 'left center';

  vpc.subnets.forEach(s => {{
    const el = document.createElement('div');
    el.className = `subnet-bar ${{s.type === 'Public' ? 'public' : 'private'}}`;
    if (expandedSubnet === s.id) el.classList.add('expanded');
    el.style.left = `${{s.x}}%`;
    el.style.width = `${{s.width}}%`;
    el.textContent = s.name;
    el.dataset.id = s.id;
    el.addEventListener('click', () => toggleExpand(s.id));
    el.addEventListener('mouseenter', (e) => showTooltip(e, s));
    el.addEventListener('mouseleave', hideTooltip);
    bar.appendChild(el);
  }});

  const labels = document.getElementById('cidr-labels');
  labels.innerHTML = `<span>$${{ip(vpc.vpc_start)}} - $${{ip(vpc.vpc_end)}}</span>`;
}}

function renderDetails(vpc) {{
  const el = document.getElementById('subnet-details');
  el.innerHTML = vpc.subnets.map(s => `
    <div class="subnet-detail">
      <h4>$${{s.name}} ($${{s.cidr}})</h4>
      <p>AZ: $${{s.az}} | Type: $${{s.type}} | IPs: $${{s.total_ips}} total / $${{s.available}} available</p>
      $${{s.tags.length > 0 ? '<p>$${{s.tags.map(t => '<span class="tag">' + t.key + ': ' + t.value + '</span>').join(' ')}}</p>' : ''}}
    </div>
  `).join('');
}}

function toggleExpand(id) {{
  expandedSubnet = expandedSubnet === id ? null : id;
  const vpc = findVpc(vpcId);
  renderMap(vpc);
}}

function showTooltip(e, s) {{
  const tip = document.getElementById('tooltip');
  tip.innerHTML = `
    <h3>$${{s.name}}</h3>
    <p><strong>CIDR:</strong> $${{s.cidr}}</p>
    <p><strong>Type:</strong> $${{s.type}}</p>
    <p><strong>AZ:</strong> $${{s.az}}</p>
    <p><strong>IPs:</strong> $${{s.total_ips}} total / $${{s.available}} available</p>
    $${{s.tags.length > 0 ? '<p>$${{s.tags.map(t => '<span class="tag">' + t.key + ': ' + t.value + '</span>').join(' ')}}</p>' : ''}}
  `;
  tip.style.left = `${{e.clientX + 10}}px`;
  tip.style.top = `${{e.clientY + 10}}px`;
  tip.classList.add('visible');
}}

function hideTooltip() {{
  document.getElementById('tooltip').classList.remove('visible');
}}

function zoomIn() {{
  zoom = Math.min(zoom + 0.25, 3);
  document.getElementById('zoom-level').textContent = `${{Math.round(zoom * 100)}}%`;
  const vpc = findVpc(vpcId);
  renderMap(vpc);
}}

function zoomOut() {{
  zoom = Math.max(zoom - 0.25, 0.25);
  document.getElementById('zoom-level').textContent = `${{Math.round(zoom * 100)}}%`;
  const vpc = findVpc(vpcId);
  renderMap(vpc);
}}

function zoomReset() {{
  zoom = 1;
  document.getElementById('zoom-level').textContent = '100%';
  const vpc = findVpc(vpcId);
  renderMap(vpc);
}}

function ip(n) {{
  return (n >>> 24 & 255) + '.' + (n >>> 16 & 255) + '.' + (n >>> 8 & 255) + '.' + (n & 255);
}}

// Init
renderVpcSelector();
const vpc = findVpc(vpcId);
renderMap(vpc);
renderDetails(vpc);
</script>
</body>
</html>"""


def generate_visualization(
    vpc_data: dict[str, Any],
    subnets: list[dict[str, Any]],
    vpc_id: str | None = None,
    output_dir: str | None = None,
) -> Path:
    """Generate an HTML visualization file and return its path."""
    vpc_cidrs = [
        a["CidrBlock"]
        for a in vpc_data.get("CidrBlockAssociationSet", [])
    ]
    if not vpc_cidrs:
        vpc_cidrs = [vpc_data.get("CidrBlock", "10.0.0.0/16")]
    vpcs = [_build_vpc_data(vpc_id or vpc_data.get("VpcId", ""), subnets, vpc_cidrs)]
    html = _render_html(vpcs, vpc_id)

    output_dir = Path(output_dir) if output_dir else Path.cwd()
    filename = f"vpc-visualizer-{vpc_id}.html"
    filepath = output_dir / filename

    filepath.write_text(html, encoding="utf-8")
    return filepath


def generate_multi_vpc_visualization(
    vpcs_data: list[dict[str, Any]],
    output_dir: str | None = None,
) -> Path:
    """Generate an HTML visualization for multiple VPCs."""
    vpcs = [
        {
            "id": v.get("VpcId", "unknown"),
            "cidrs": [
                a["CidrBlock"]
                for a in v.get("CidrBlockAssociationSet", [])
            ],
            "vpc_start": 0,
            "vpc_end": 0,
            "subnets": [_subnet_to_dict(s) for s in v.get("Subnets", [])],
        }
        for v in vpcs_data
    ]

    # Compute CIDR ranges for each VPC
    for vpc in vpcs:
        vpc["vpc_start"], vpc["vpc_end"] = _vpc_cidr_range(vpc["cidrs"])

    html = _render_html(vpcs)

    output_dir = Path(output_dir) if output_dir else Path.cwd()
    filepath = output_dir / "vpc-visualizer-multi.html"

    filepath.write_text(html, encoding="utf-8")
    return filepath


def open_visualization(filepath: Path) -> None:
    """Open the visualization file in the default browser."""
    webbrowser.open(filepath.as_uri())

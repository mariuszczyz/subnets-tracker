# AWS Subnet Tracker

A read-only command-line tool to discover and analyze AWS VPC subnets. It calculates IP usage, identifies unallocated VPC space, and provides EKS networking best practice recommendations — with an optional interactive HTML visualization.

## Features

- **Subnet Inventory**: Shows ID, Name, AZ, Type (Public/Private), CIDR, Total/Used/Available IPs, and EKS tags.
- **Unallocated Space**: Lists free CIDR blocks inside the VPC that can be used for new subnets.
- **EKS Recommendations**: Validates subnets against EKS best practices (AZ diversity, IP availability, required ELB tags).
- **Interactive HTML Visualizer**: AZ swim-lane CIDR map, IP utilization overlay, hover tooltips, VPC→AZ→Subnet dependency diagram, sortable details table, EKS readiness section, per-VPC zoom controls.
- **All-VPCs Report**: Analyze or visualize every VPC in a region in a single command.
- **Read-Only**: Only calls `Describe` APIs — no changes are made to your AWS account.

## Installation

```bash
git clone https://github.com/your-repo/subnets-tracker.git
cd subnets-tracker
uv sync
```

## Usage

Ensure AWS credentials are configured (e.g. `aws configure`, environment variables, or an IAM role).

### Analyze a single VPC (table output)

```bash
subnet-tracker --vpc-id vpc-0123456789abcdef0 --region us-east-1
```

### Analyze a single VPC (HTML visualization)

Opens an interactive HTML report in your default browser:

```bash
subnet-tracker --vpc-id vpc-0123456789abcdef0 --region us-east-1 --visual
```

### Analyze all VPCs in a region (table output)

Omit `--vpc-id` to loop over every VPC and print a table for each:

```bash
subnet-tracker --region us-east-1
```

### Analyze all VPCs in a region (HTML visualization)

Omit `--vpc-id` and add `--visual` to generate a single HTML file covering every VPC, with full subnet-type detection, EKS readiness, and unallocated-space sections per VPC:

```bash
subnet-tracker --region us-east-1 --visual
```

### Save the HTML file without opening a browser

```bash
subnet-tracker --region us-east-1 --visual --no-open --output-dir ./reports
```

### All options

| Flag | Default | Description |
|------|---------|-------------|
| `--vpc-id` | _(none)_ | VPC to analyze. Omit to process all VPCs in the region. |
| `--region` | `us-east-1` | AWS region. |
| `--visual` | off | Generate an interactive HTML visualization. |
| `--multi-vpc` | off | Quick raw HTML dump of all VPCs (no EKS/unallocated enrichment). |
| `--output-dir` | current dir | Directory to write the HTML file. |
| `--no-open` | off | Write the HTML file without opening it in a browser. |

## HTML Report

The interactive HTML report includes:

- **Stats cards** — subnet count, AZ count, total usable IPs, and VPC CIDR at a glance.
- **CIDR Map** — one swim lane per Availability Zone; subnet bars colored by type (green = Public, blue = Private) with a darker overlay showing used IPs. Gray bars for unallocated CIDR space. Click a bar to highlight the matching row in the details table.
- **Dependency Diagram** — VPC → AZ → Subnet tree with type badges and EKS tag labels.
- **Subnet Details** — sortable table with Name, ID, AZ, Type, CIDR, Total/Used/Available IPs, utilization bar, and EKS tags.
- **EKS Readiness** — per-VPC status badge (OK / Warning) with issues and proposals.
- **VPC Switcher** — click between VPCs when the report covers multiple VPCs.
- **Zoom controls** — zoom the CIDR map in/out per VPC.

## Development & Testing

```bash
uv sync --dev             # installs pytest, moto, etc.
uv run pytest             # run all tests
uv run pytest -v          # verbose
uv run pytest --cov=subnet_tracker  # with coverage (requires pytest-cov)
```

## License

MIT

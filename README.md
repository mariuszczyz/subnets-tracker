# AWS Subnet Tracker

A read-only command-line tool to discover and analyze AWS VPC subnets. It calculates IP usage, identifies unallocated VPC space, and provides EKS networking best practice recommendations.

## Features

- **Subnet Inventory**: Shows ID, Name, AZ, Type (Public/Private), CIDR, Total/Used/Available IPs, and EKS Tags.
- **Unallocated Space**: Lists available CIDR blocks in the VPC that can be used for new subnets.
- **EKS Recommendations**: Analyzes subnets against EKS best practices (AZ diversity, IP availability, and required ELB tags).
- **Interactive Visualizer**: CIDR map visualization with hover tooltips, click-to-expand, zoom controls, and multi-VPC support.
- **Read-Only**: Performs only `Describe` operations; no changes are made to your AWS account.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/subnets-tracker.git
   cd subnets-tracker
   ```

2. Install the package:
   ```bash
   pip install -e .
   ```

## Usage

Ensure you have your AWS credentials configured (e.g., via `aws configure` or environment variables).

### Table Output

Run the tool by providing a VPC ID:

```bash
subnet-tracker --vpc-id vpc-0123456789abcdef0 --region us-east-1
```

### Visual Output

Generate an interactive HTML visualization and open it in your browser:

```bash
subnet-tracker --vpc-id vpc-0123456789abcdef0 --region us-east-1 --visual
```

Visualize all VPCs in the region:

```bash
subnet-tracker --vpc-id vpc-0123456789abcdef0 --region us-east-1 --multi-vpc
```

### Options

- `--vpc-id`: (Required) The ID of the VPC to analyze.
- `--region`: (Optional) The AWS region. Defaults to `us-east-1`.
- `--visual`: (Optional) Generate an interactive HTML visualization.
- `--multi-vpc`: (Optional) Visualize all VPCs in the region.
- `--output-dir`: (Optional) Directory to write the visualization file.

## Development & Testing

Install development dependencies:
```bash
pip install pytest moto
```

Run tests:
```bash
pytest
```

## License

MIT

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AWS Subnet Tracker — a read-only CLI tool that discovers and analyzes AWS VPC subnets. It reports IP usage, identifies unallocated CIDR blocks, and evaluates subnets against EKS networking best practices.

## Architecture

The project is a small Python package built with setuptools and click.

```
pyproject.toml          # Build config, dependencies (boto3, click, rich)
src/subnet_tracker/
├── cli.py              # CLI entry point, click commands, rich table rendering
└── tracker.py          # Core logic: SubnetTracker class with all AWS operations
tests/
└── test_tracker.py     # pytest tests using moto to mock AWS
```

**`SubnetTracker`** (tracker.py) manages the data layer:
- `fetch_data()` — calls `describe_vpcs`, `describe_subnets`, `describe_route_tables`
- `is_public(subnet_id)` — checks if subnet's route table has an igw- route
- `get_subnet_details()` — returns enriched subnet info (IPs, type, EKS tags)
- `get_unallocated_space()` — calculates free CIDR blocks using `ipaddress.address_exclude`
- `get_eks_recommendations()` — validates AZ diversity, IP availability, and ELB tagging

**`cli.py`** is the presentation layer: three rich tables (Subnet Inventory, Unallocated Space, EKS Recommendations).

## Commands

```bash
# Install
pip install -e .

# Run against a VPC
subnet-tracker --vpc-id vpc-0123456789abcdef0 --region us-east-1

# Run tests
pytest

# Run tests with verbose output
pytest -v

# Run a single test file
pytest tests/test_tracker.py

# Run with coverage
pip install pytest-cov && pytest --cov=subnet_tracker
```

## Development Notes

- The tool is read-only — it only calls `Describe` APIs, never modifies AWS resources.
- AWS IP calculations follow AWS conventions: 5 IPs reserved per subnet.
- EKS best practices checked: ≥2 private subnets across different AZs, minimum IPs, proper ELB tags (`kubernetes.io/role/internal-elb`, `kubernetes.io/role/elb`).
- Tests use `moto` to mock AWS — no real credentials needed.
- Default region is `us-east-1`.

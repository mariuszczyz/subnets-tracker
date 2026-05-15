# All-VPCs CLI Report

**Date:** 2026-05-15
**Status:** Approved

## Summary

When `subnet-tracker` is invoked without `--vpc-id` (and without `--multi-vpc`), instead of erroring, the tool prints the full three-table CLI report for every VPC in the region, one after another.

## Motivation

The current error message when `--vpc-id` is omitted is unhelpful for users who want a quick overview of all VPCs in a region. The `--multi-vpc` flag exists but only generates an HTML file, not a terminal report.

## Behavior Change

### Before

```
$ subnet-tracker --region us-east-1
Error: --vpc-id is required unless --multi-vpc is specified.
```

### After

```
$ subnet-tracker --region us-east-1
────────────── VPC: vpc-0abc123  (10.0.0.0/16) ──────────────
[Subnet Inventory table]
[Unallocated VPC Space table]
[EKS Recommendations panel]

────────────── VPC: vpc-0def456  (172.31.0.0/16) ──────────────
[Subnet Inventory table]
...
```

## Design

### Entry point: `cli.py` — `main()`

Replace the current error block:

```python
if not vpc_id:
    console.print("[bold red]Error:[/bold red] --vpc-id is required ...")
    sys.exit(1)
```

With:

```python
if not vpc_id:
    _run_all_vpcs_report(region)
    return
```

The `--visual` flag without `--vpc-id` continues to be an error (handled before this block by short-circuiting `--multi-vpc`, but `--visual` alone still requires `--vpc-id`).

### New helper: `_run_all_vpcs_report(region)`

```
1. Create boto3 ec2 client for the region.
2. Call describe_vpcs() — no filter, returns all VPCs.
3. If empty, print "No VPCs found in region <region>." and return.
4. For each VPC:
   a. Print a rich Rule separator: "VPC: <vpc-id>  (<cidr>)"
   b. Create SubnetTracker(vpc_id=vpc['VpcId'], region=region)
   c. Call tracker.fetch_data()
   d. Call _print_tables(tracker)
   e. On any exception: print error and continue to next VPC.
```

### Unchanged

- `--multi-vpc` flag (HTML visualization) — no change.
- Single-VPC path (`--vpc-id` provided) — no change.
- `tracker.py`, `visualizer.py` — no change.

## Edge Cases

| Scenario | Behavior |
|---|---|
| No VPCs in account/region | Prints "No VPCs found in region `<region>`." |
| One VPC fails to fetch | Prints error for that VPC, continues with rest |
| `--visual` without `--vpc-id` | Falls through to `_run_all_vpcs_report`; `--visual` is ignored (CLI tables shown). Note: use `--multi-vpc --visual` for HTML. |
| `--output-dir` without `--vpc-id` | Ignored (only relevant for `--visual`/`--multi-vpc` HTML output) |

## Testing

Add one new test in `tests/test_tracker.py`:

- `test_all_vpcs_report_cli` — mock two VPCs, invoke `main()` with no `--vpc-id`, assert both VPC IDs appear in output and no error is raised.

## AWS Permissions Required

No new permissions. Existing `ec2:DescribeVpcs` already covers the unfiltered `describe_vpcs()` call used in `_run_all_vpcs_report`.

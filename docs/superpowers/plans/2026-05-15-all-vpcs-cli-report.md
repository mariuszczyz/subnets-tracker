# All-VPCs CLI Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `subnet-tracker` is invoked without `--vpc-id` (and without `--multi-vpc`), print the full three-table CLI report for every VPC in the region instead of erroring.

**Architecture:** Add a `_run_all_vpcs_report(region)` helper in `cli.py` that fetches all VPCs via `describe_vpcs()`, then loops over them calling the existing `_print_tables(tracker)` for each. Change the `if not vpc_id:` guard in `main()` to call this helper instead of exiting. No changes to `tracker.py`.

**Tech Stack:** Python, boto3, click, rich, moto (tests), pytest

---

### Task 1: Update the existing no-vpc-id test and add new all-VPCs CLI test

The existing test `test_cli_errors_without_vpc_id_and_without_multi_vpc` asserts that omitting `--vpc-id` exits non-zero. After this change the behavior is inverted — it must succeed. Replace that test and add a second one that verifies both VPC IDs appear in output when two VPCs exist.

**Files:**
- Modify: `tests/test_tracker.py:172-178`

- [ ] **Step 1: Replace the old no-vpc-id test and add a two-VPC output test**

Replace lines 172–178 in `tests/test_tracker.py` with:

```python
@mock_aws
def test_cli_all_vpcs_report_no_vpc_id():
    """No --vpc-id should print tables for all VPCs and exit zero."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    ec2.create_subnet(VpcId=vpc['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')

    runner = CliRunner()
    result = runner.invoke(main, ['--region', 'us-east-1'])
    assert result.exit_code == 0, result.output
    assert vpc['VpcId'] in result.output


@mock_aws
def test_cli_all_vpcs_report_shows_all_vpcs():
    """No --vpc-id must print a section for every VPC in the region."""
    ec2 = boto3.client('ec2', region_name='us-east-1')
    vpc1 = ec2.create_vpc(CidrBlock='10.0.0.0/16')['Vpc']
    vpc2 = ec2.create_vpc(CidrBlock='10.1.0.0/16')['Vpc']
    ec2.create_subnet(VpcId=vpc1['VpcId'], CidrBlock='10.0.1.0/24', AvailabilityZone='us-east-1a')
    ec2.create_subnet(VpcId=vpc2['VpcId'], CidrBlock='10.1.1.0/24', AvailabilityZone='us-east-1b')

    runner = CliRunner()
    result = runner.invoke(main, ['--region', 'us-east-1'])
    assert result.exit_code == 0, result.output
    assert vpc1['VpcId'] in result.output
    assert vpc2['VpcId'] in result.output
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pytest tests/test_tracker.py::test_cli_all_vpcs_report_no_vpc_id tests/test_tracker.py::test_cli_all_vpcs_report_shows_all_vpcs -v
```

Expected: both FAIL — `test_cli_all_vpcs_report_no_vpc_id` because exit code is currently 1, `test_cli_all_vpcs_report_shows_all_vpcs` for the same reason.

---

### Task 2: Implement `_run_all_vpcs_report` and update `main()`

**Files:**
- Modify: `src/subnet_tracker/cli.py`

- [ ] **Step 1: Add `_run_all_vpcs_report` helper**

Add the following function to `src/subnet_tracker/cli.py` immediately after `_run_multi_vpc` (after line 73):

```python
def _run_all_vpcs_report(region: str) -> None:
    ec2 = boto3.client('ec2', region_name=region)
    vpcs = ec2.describe_vpcs()['Vpcs']
    if not vpcs:
        console.print(f"[yellow]No VPCs found in region {region}.[/yellow]")
        return
    for vpc in vpcs:
        vpc_id = vpc['VpcId']
        cidr = vpc.get('CidrBlock', 'N/A')
        console.rule(f"VPC: {vpc_id}  ({cidr})")
        try:
            tracker = SubnetTracker(vpc_id, region)
            tracker.fetch_data()
            _print_tables(tracker)
        except Exception as e:
            console.print(f"[bold red]Error fetching VPC {vpc_id}:[/bold red] {e}")
```

- [ ] **Step 2: Replace the error block in `main()`**

In `src/subnet_tracker/cli.py`, replace:

```python
    if not vpc_id:
        console.print("[bold red]Error:[/bold red] --vpc-id is required unless --multi-vpc is specified.")
        sys.exit(1)
```

With:

```python
    if not vpc_id:
        _run_all_vpcs_report(region)
        return
```

- [ ] **Step 3: Run the new tests to verify they pass**

```bash
pytest tests/test_tracker.py::test_cli_all_vpcs_report_no_vpc_id tests/test_tracker.py::test_cli_all_vpcs_report_shows_all_vpcs -v
```

Expected: both PASS.

- [ ] **Step 4: Run the full test suite to check for regressions**

```bash
pytest tests/test_tracker.py -v
```

Expected: all tests PASS. Pay attention to `test_cli_multi_vpc_does_not_require_vpc_id` — it must still pass because `--multi-vpc` is handled before the `if not vpc_id` block.

- [ ] **Step 5: Commit**

```bash
git add src/subnet_tracker/cli.py tests/test_tracker.py
git commit -m "feat: show all-VPCs CLI report when --vpc-id is omitted"
```

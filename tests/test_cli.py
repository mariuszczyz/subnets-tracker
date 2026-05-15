"""Tests for the CLI entry point."""

from pathlib import Path

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from subnet_tracker.cli import main


@mock_aws
def test_visual_without_vpc_id_generates_html(tmp_path):
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    ec2.create_subnet(
        VpcId=vpc["VpcId"],
        CidrBlock="10.0.1.0/24",
        AvailabilityZone="us-east-1a",
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--region", "us-east-1", "--visual", "--no-open", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    html_files = list(tmp_path.glob("vpc-visualizer-multi.html"))
    assert len(html_files) == 1
    content = html_files[0].read_text()
    assert vpc["VpcId"] in content


@mock_aws
def test_visual_without_vpc_id_enriches_subnet_types(tmp_path):
    """Subnets in the all-VPCs visual report must show Public/Private (not all Private)."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]

    # Create an Internet Gateway and attach it so one subnet becomes Public
    igw = ec2.create_internet_gateway()["InternetGateway"]
    ec2.attach_internet_gateway(InternetGatewayId=igw["InternetGatewayId"], VpcId=vpc["VpcId"])
    subnet = ec2.create_subnet(
        VpcId=vpc["VpcId"], CidrBlock="10.0.1.0/24", AvailabilityZone="us-east-1a"
    )["Subnet"]
    ec2.create_tags(
        Resources=[subnet["SubnetId"]], Tags=[{"Key": "Name", "Value": "PublicSub"}]
    )
    rtb = ec2.describe_route_tables(
        Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}, {"Name": "association.main", "Values": ["true"]}]
    )["RouteTables"][0]
    ec2.create_route(
        RouteTableId=rtb["RouteTableId"],
        DestinationCidrBlock="0.0.0.0/0",
        GatewayId=igw["InternetGatewayId"],
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--region", "us-east-1", "--visual", "--no-open", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    content = (tmp_path / "vpc-visualizer-multi.html").read_text()
    assert 'data-type="Public"' in content



@mock_aws
def test_visual_with_vpc_id_unchanged(tmp_path):
    """Single-VPC --visual path must still produce a per-VPC file."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]
    ec2.create_subnet(
        VpcId=vpc["VpcId"], CidrBlock="10.0.1.0/24", AvailabilityZone="us-east-1a"
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--vpc-id", vpc["VpcId"],
            "--region", "us-east-1",
            "--visual",
            "--no-open",
            "--output-dir", str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    expected = tmp_path / f"vpc-visualizer-{vpc['VpcId']}.html"
    assert expected.exists()
